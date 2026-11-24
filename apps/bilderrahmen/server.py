"""Bilderrahmen: Diashow aus einem Foto-Ordner im TV-Browser. Startet auf
Wunsch von selbst, wenn der Fernseher an ist und nichts abgespielt wird."""

import asyncio
import random
import threading
import time
from datetime import date, datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.plugins import context

ctx = context(__file__)
router = APIRouter()

EXTENSIONS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
MAX_PHOTOS = 20000
RESCAN_SECONDS = 600
CHECK_SECONDS = 30
_scan: dict = {"folder": None, "at": 0.0, "photos": [], "day": None}
_lock = threading.Lock()
state = {"showing": False}


def _folder() -> Path | None:
    raw = str(ctx.settings().get("folder") or "").strip()
    return Path(raw) if raw else None


def photos() -> list[Path]:
    """Alle Fotos, pro Tag einmal gemischt (gleiche Reihenfolge fuer alle Abrufe)."""
    folder = _folder()
    with _lock:
        stale = time.time() - _scan["at"] > RESCAN_SECONDS or _scan["day"] != date.today()
        if folder != _scan["folder"] or stale:
            found: list[Path] = []
            if folder and folder.is_dir():
                for path in folder.rglob("*"):
                    if path.suffix.lower() in EXTENSIONS and not path.name.startswith("."):
                        found.append(path)
                        if len(found) >= MAX_PHOTOS:
                            break
            found.sort()
            random.Random(date.today().toordinal()).shuffle(found)
            _scan.update(folder=folder, at=time.time(), photos=found, day=date.today())
        return list(_scan["photos"])


def _seconds() -> int:
    try:
        return max(4, min(120, int(float(ctx.settings().get("seconds") or 12))))
    except ValueError:
        return 12


@router.get("/info")
def info() -> dict:
    folder = _folder()
    return {
        "folder": str(folder) if folder else "",
        "folder_ok": bool(folder and folder.is_dir()),
        "count": len(photos()),
        "seconds": _seconds(),
        "showing": state["showing"] and ctx.busy(),
    }


@router.get("/photo/{index}")
def photo(index: int) -> FileResponse:
    items = photos()
    if not items:
        raise HTTPException(status_code=404, detail="Keine Fotos gefunden")
    path = items[index % len(items)]
    return FileResponse(path, media_type=EXTENSIONS[path.suffix.lower()], headers={"Cache-Control": "private, max-age=86400"})


@router.post("/start")
async def start() -> dict:
    if not photos():
        raise HTTPException(status_code=400, detail="Keine Fotos – Ordner im App Store eintragen")
    await ctx.show_on_tv("tv.html")
    state["showing"] = True
    return {"ok": True}


@router.post("/stop")
async def stop() -> dict:
    state["showing"] = False
    await ctx.close_tv()
    return {"ok": True}


def _in_hours() -> bool:
    raw = str(ctx.settings().get("hours") or "").strip()
    if not raw:
        return True
    try:
        start_s, end_s = [part.strip() for part in raw.split("-", 1)]
        now = datetime.now().strftime("%H:%M")
        start_s, end_s = start_s.zfill(5), end_s.zfill(5)
        return start_s <= now <= end_s if start_s <= end_s else now >= start_s or now <= end_s
    except ValueError:
        return True


async def background() -> None:
    """Von selbst starten: Fernseher an, nichts laeuft, lange genug ruhig."""
    idle_since = None
    while True:
        await asyncio.sleep(CHECK_SECONDS)
        try:
            minutes = float(ctx.settings().get("idle_minutes") or 15)
        except ValueError:
            minutes = 15
        if not ctx.enabled() or minutes <= 0 or not ctx.tv_is_on() or ctx.busy():
            idle_since = None
            if not ctx.busy():
                state["showing"] = False
            continue
        idle_since = idle_since or time.time()
        if time.time() - idle_since >= minutes * 60 and _in_hours() and await asyncio.to_thread(photos):
            ctx.log.info("Bilderrahmen startet von selbst")
            try:
                await ctx.show_on_tv("tv.html")
                state["showing"] = True
            except Exception as exc:  # noqa: BLE001
                ctx.log.warning("Diashow ließ sich nicht starten: %s", exc)
            idle_since = None


def test() -> str:
    folder = _folder()
    if not folder:
        return "Noch kein Ordner eingetragen"
    if not folder.is_dir():
        return f"{folder} gibt es nicht (Platte angeschlossen?)"
    return f"{len(photos())} Fotos gefunden"
