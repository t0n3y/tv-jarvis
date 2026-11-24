"""Abfahrten der eigenen Haltestelle ueber Transitous (MOTIS, europaweit,
kostenlos: https://transitous.org). Haltestelle wird in der App gesucht und
in data/apps/abfahrten/stop.json gemerkt."""

import re
import threading
import time
from datetime import datetime

import requests
from fastapi import APIRouter, HTTPException, Request

from app import speech_de
from app.plugins import context

ctx = context(__file__)
router = APIRouter()

API = "https://api.transitous.org/api/v1"
HEADERS = {"User-Agent": "RPi-TV/1.0 (+https://github.com/t0n3y/tv-jarvis)"}
CACHE_SECONDS = 60
MODES = {
    "BUS": "Bus", "TRAM": "Tram", "SUBWAY": "U-Bahn", "METRO": "S-Bahn", "REGIONAL_RAIL": "Zug",
    "REGIONAL_FAST_RAIL": "Zug", "LONG_DISTANCE": "Zug", "HIGHSPEED_RAIL": "Zug", "NIGHT_RAIL": "Zug",
    "FERRY": "Fähre", "COACH": "Fernbus", "RAIL": "Zug",
}
_cache: dict = {"at": 0.0, "stop": None, "data": []}
_lock = threading.Lock()


def _get(path: str, **params) -> dict | list:
    resp = requests.get(f"{API}/{path}", params=params, headers=HEADERS, timeout=12)
    resp.raise_for_status()
    return resp.json()


def _stop() -> dict | None:
    return ctx.load("stop")


def _local(iso: str | None) -> datetime | None:
    if not iso:
        return None
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone()


def _fetch(stop: dict) -> list[dict]:
    try:
        data = _get("stoptimes", stopId=stop["id"], n=30)
    except requests.HTTPError:
        # IDs aendern sich mit neuen Fahrplandaten: per Name neu suchen
        found = search(stop["name"])
        if not found:
            raise
        stop = {**stop, "id": found[0]["id"]}
        ctx.save(stop, "stop")
        data = _get("stoptimes", stopId=stop["id"], n=30)
    departures = []
    for item in data.get("stopTimes", []):
        place = item.get("place") or {}
        when = _local(place.get("departure"))
        planned = _local(place.get("scheduledDeparture")) or when
        if when is None:
            continue
        delay = round((when - planned).total_seconds() / 60) if item.get("realTime") and planned else 0
        departures.append({
            "line": (item.get("displayName") or item.get("routeShortName") or "").strip(),
            "direction": (item.get("headsign") or "").strip(),
            "mode": MODES.get(item.get("mode") or "", ""),
            "when": when.isoformat(),
            "time": planned.strftime("%H:%M"),
            "delay": delay,
            "track": place.get("track") or "",
            "cancelled": bool(item.get("cancelled") or item.get("tripCancelled")),
            "realtime": bool(item.get("realTime")),
        })
    return departures


def _compact(line: str) -> str:
    return re.sub(r"\s+", "", line).lower()


def departures() -> list[dict]:
    stop = _stop()
    if not stop:
        return []
    with _lock:
        if _cache["stop"] != stop["id"] or time.time() - _cache["at"] > CACHE_SECONDS:
            _cache.update(data=_fetch(stop), at=time.time(), stop=stop["id"])
        data = list(_cache["data"])
    settings = ctx.settings()
    wanted = {_compact(line) for line in settings.get("lines") or [] if line.strip()}
    walk = float(settings.get("walk_minutes") or 0)
    now = time.time()
    result = []
    for dep in data:
        if wanted and _compact(dep["line"]) not in wanted:
            continue
        dep = {**dep, "reachable": datetime.fromisoformat(dep["when"]).timestamp() >= now + walk * 60}
        if datetime.fromisoformat(dep["when"]).timestamp() < now - 30:
            continue
        result.append(dep)
    return result


def search(query: str) -> list[dict]:
    results = _get("geocode", text=query, language="de")
    return [
        {"id": r["id"], "name": r.get("name") or "", "area": ", ".join(a.get("name", "") for a in (r.get("areas") or [])[:2] if a.get("name"))}
        for r in results
        if r.get("type") == "STOP"
    ][:10]


# ---------- API fuer die Fernbedienung ----------

@router.get("/search")
def api_search(q: str = "") -> dict:
    if len(q.strip()) < 2:
        return {"stops": []}
    try:
        return {"stops": search(q.strip())}
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Die Fahrplanauskunft antwortet gerade nicht") from exc


@router.post("/stop")
async def api_set_stop(request: Request) -> dict:
    body = await request.json()
    if not body.get("id") or not body.get("name"):
        raise HTTPException(status_code=400, detail="Haltestelle fehlt")
    ctx.save({"id": str(body["id"]), "name": str(body["name"])[:80]}, "stop")
    _cache["at"] = 0
    return {"ok": True}


@router.get("/departures")
def api_departures() -> dict:
    try:
        return {"stop": _stop(), "departures": departures()[:20]}
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail="Die Fahrplanauskunft antwortet gerade nicht") from exc


# ---------- Haken fuer Dashboard, Wecker, App Store ----------

def _label(dep: dict) -> str:
    return f"{dep['line']} → {dep['direction']}" if dep["direction"] else dep["line"]


def dashboard() -> dict | None:
    stop = _stop()
    if not stop:
        return {"title": "Abfahrten", "items": [], "empty": "Haltestelle in der App wählen"}
    items = []
    for dep in [d for d in departures() if d["reachable"]][:6]:
        note = "fällt aus" if dep["cancelled"] else " · ".join(filter(None, [f"+{dep['delay']}" if dep["delay"] > 0 else "", f"Gl. {dep['track']}" if dep["track"] else ""]))
        items.append({"time": dep["time"], "text": _label(dep), "note": note, "strike": dep["cancelled"]})
    return {"title": "Abfahrten", "meta": stop["name"], "items": items, "empty": "Gerade keine Abfahrten"}


def briefing() -> str | None:
    stop = _stop()
    if not stop:
        return None
    upcoming = [d for d in departures() if d["reachable"] and not d["cancelled"]]
    if not upcoming:
        return None
    dep = upcoming[0]
    vehicle = dep["mode"] or "Verbindung"
    direction = f" Richtung {dep['direction']}" if dep["direction"] else ""
    text = f"Die nächste Verbindung ab {stop['name']}: {vehicle} {dep['line']}{direction} um {speech_de.spoken_time(dep['time'])}"
    if dep["delay"] >= 2:
        text += f", heute {dep['delay']} Minuten später"
    return text + "."


def test() -> str:
    stop = _stop()
    if not stop:
        return "Noch keine Haltestelle gewählt – App öffnen und suchen"
    deps = departures()
    return f"{stop['name']}: {len(deps)} Abfahrten gefunden"
