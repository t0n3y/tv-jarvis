"""WLAN-Lampen (Tuya/Smart Life/LSC) ueber tinytuya - lokal im WLAN.

Einmalig holt "Lampen suchen" ueber die Tuya-Cloud die Schluessel (local_key)
der Lampen und sucht sie im Netz. Danach geht alles direkt an die Lampen.
Gespeichert in data/apps/wlan_lampen/devices.json (nur fuer den Pi-Benutzer
lesbar - die Schluessel sind wie Passwoerter)."""

import os
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, HTTPException, Request

from app.plugins import context

ctx = context(__file__)
router = APIRouter()

SCAN_SECONDS = 18
_lock = threading.Lock()
SCENES = {
    "hell": {"on": True, "brightness": 100, "white": 50},
    "gemuetlich": {"on": True, "brightness": 35, "white": 0},
    "kino": {"on": True, "brightness": 8, "white": 0},
    "konzentration": {"on": True, "brightness": 90, "white": 100},
    "aus": {"on": False},
}


def _tinytuya():
    try:
        import tinytuya
    except ImportError as exc:
        raise HTTPException(status_code=500, detail="Paket tinytuya fehlt: .venv/bin/pip install tinytuya") from exc
    return tinytuya


def _devices() -> list[dict]:
    return ctx.load("devices", [])


def _save_devices(devices: list[dict]) -> None:
    ctx.save(devices, "devices")
    path = ctx.data_dir / "devices.json"
    if path.exists():
        os.chmod(path, 0o600)


def _public(device: dict) -> dict:
    return {k: device.get(k) for k in ("id", "name", "ip", "found")}


# ---------- Suchen ----------

@router.post("/discover")
def discover() -> dict:
    tinytuya = _tinytuya()
    access_id = ctx.secret("TUYA_ACCESS_ID")
    access_secret = ctx.secret("TUYA_ACCESS_SECRET")
    if not access_id or not access_secret:
        raise HTTPException(status_code=400, detail="Erst Access ID und Secret im App Store eintragen")
    settings = ctx.settings()
    cloud = tinytuya.Cloud(
        apiRegion=str(settings.get("region") or "eu").strip() or "eu",
        apiKey=access_id,
        apiSecret=access_secret,
        apiDeviceID=str(settings.get("device_id") or "").strip() or None,
    )
    found = cloud.getdevices(verbose=False)
    if isinstance(found, dict):
        raise HTTPException(status_code=400, detail=f"Tuya-Cloud: {found.get('Payload') or found.get('Error') or found}")
    lamps = [d for d in found if d.get("key")]
    if not lamps:
        raise HTTPException(status_code=404, detail="Keine Geräte im verknüpften Smart-Life-Konto gefunden")
    # Im WLAN suchen: IP und Protokollversion jeder Lampe
    scanned = tinytuya.deviceScan(verbose=False, maxretry=SCAN_SECONDS)
    by_id = {info.get("gwId") or info.get("id"): info for info in scanned.values()}
    devices = []
    for lamp in lamps:
        net = by_id.get(lamp["id"], {})
        devices.append({
            "id": lamp["id"],
            "name": lamp.get("name") or lamp["id"],
            "key": lamp["key"],
            "ip": net.get("ip") or lamp.get("ip") or "",
            "version": float(net.get("version") or 3.3),
            "found": bool(net.get("ip")),
        })
    with _lock:
        _save_devices(devices)
    ctx.log.info("WLAN-Lampen: %s Geräte, %s im WLAN gefunden", len(devices), sum(d["found"] for d in devices))
    return {"devices": [_public(d) for d in devices]}


# ---------- Schalten ----------

def _bulb(device: dict):
    tinytuya = _tinytuya()
    bulb = tinytuya.BulbDevice(device["id"], device["ip"] or "Auto", device["key"], version=device.get("version", 3.3))
    bulb.set_socketTimeout(3)
    bulb.set_socketRetryLimit(1)
    return bulb


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) != 6:
        raise HTTPException(status_code=400, detail="Farbe als #rrggbb")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def _apply(device: dict, change: dict) -> dict:
    bulb = _bulb(device)
    if change.get("on") is False:
        bulb.turn_off()
        return {"id": device["id"], "ok": True}
    bulb.turn_on()
    if change.get("color"):
        bulb.set_colour(*_hex_to_rgb(str(change["color"])))
        if change.get("brightness") is not None:
            bulb.set_brightness_percentage(int(change["brightness"]))
    elif change.get("white") is not None:
        bulb.set_white_percentage(int(change.get("brightness") if change.get("brightness") is not None else 100), int(change["white"]))
    elif change.get("brightness") is not None:
        bulb.set_brightness_percentage(int(change["brightness"]))
    return {"id": device["id"], "ok": True}


def _apply_safe(device: dict, change: dict) -> dict:
    try:
        return _apply(device, change)
    except Exception as exc:  # noqa: BLE001 - eine Lampe offline darf die anderen nicht stoppen
        ctx.log.warning("Lampe %s: %s", device.get("name"), exc)
        return {"id": device["id"], "ok": False, "error": str(exc)}


@router.get("/devices")
def devices() -> dict:
    return {"devices": [_public(d) for d in _devices()], "scenes": list(SCENES)}


@router.get("/status")
def status() -> dict:
    """An/aus je Lampe (parallel, damit eine offline Lampe nicht bremst)."""

    def one(device: dict) -> dict:
        try:
            data = _bulb(device).status()
            dps = data.get("dps") or {}
            on = dps.get("20", dps.get("1"))
            return {"id": device["id"], "on": bool(on), "online": "Error" not in data}
        except Exception:  # noqa: BLE001
            return {"id": device["id"], "on": False, "online": False}

    items = _devices()
    with ThreadPoolExecutor(max_workers=max(1, len(items))) as pool:
        return {"status": list(pool.map(one, items))}


@router.post("/set")
async def set_lamps(request: Request) -> dict:
    body = await request.json()
    ids = body.get("ids")
    change = SCENES.get(str(body.get("scene"))) or {k: body[k] for k in ("on", "brightness", "white", "color") if k in body}
    targets = [d for d in _devices() if not ids or d["id"] in ids]
    if not targets:
        raise HTTPException(status_code=400, detail="Keine Lampen – erst „Lampen suchen“")

    def run() -> list[dict]:
        with ThreadPoolExecutor(max_workers=len(targets)) as pool:
            return list(pool.map(lambda d: _apply_safe(d, change), targets))

    import asyncio

    results = await asyncio.to_thread(run)
    failed = [r for r in results if not r["ok"]]
    if failed and len(failed) == len(results):
        raise HTTPException(status_code=502, detail=f"Keine Lampe erreichbar ({failed[0].get('error')})")
    return {"results": results}


def test() -> str:
    items = _devices()
    if not items:
        return "Noch keine Lampen – in der App „Lampen suchen“"
    online = sum(1 for s in status()["status"] if s["online"])
    return f"{online} von {len(items)} Lampen erreichbar"
