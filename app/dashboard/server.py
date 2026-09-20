"""FastAPI-Backend fuers Dashboard und die Fernbedienung.

Laeuft dauerhaft (systemd/dashboard.service). Aufgaben:
1. Liefert den zuletzt von morning_routine.py geschriebenen Briefing-Stand
   (data/state.json) als JSON unter GET /api/state.
2. Nimmt ToDo-Updates von der iCloud-Shortcuts-Automation entgegen
   (POST /api/todos/webhook).
3. Broadcastet per WebSocket Events (Ausschalt-Animation, YouTube-Steuerung)
   an die im Chromium-Kiosk offene Seite.
4. Stellt die Fernbedienungs-API bereit (POST /api/remote/*), gedacht fuer
   die mobile Seite unter /remote.html (vom iPhone/iPad im selben WLAN).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app import audio_control, kiosk_media, radio, radio_stations, schedule_store, tv_power
from app.config import ROOT_DIR, get_config
from app.scheduler import Scheduler
from app.sources import todos_icloud_shortcut

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="TV-Jarvis Dashboard")

STATE_FILE = ROOT_DIR / "data" / "state.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> None:
        dead = []
        for ws in self.active:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


manager = ConnectionManager()

# Letzter bekannter YouTube-Stand, gemeldet vom Kiosk-Player per WebSocket
# (siehe dashboard/static/app.js). Lebt nur im Prozessspeicher - die
# Fernbedienung pollt ihn ueber GET /api/remote/now-playing fuer Titel/
# Fortschrittsbalken, da die YouTube IFrame API nur im Kiosk-Browser laeuft.
youtube_now_playing: dict = {
    "video_id": None,
    "title": None,
    "thumbnail_url": None,
    "current_time": 0,
    "duration": 0,
    "playing": False,
}


def _reset_youtube_state() -> None:
    youtube_now_playing.update(
        {
            "video_id": None,
            "title": None,
            "thumbnail_url": None,
            "current_time": 0,
            "duration": 0,
            "playing": False,
        }
    )


@app.on_event("startup")
async def _start_scheduler() -> None:
    Scheduler(get_config()).start()


@app.middleware("http")
async def _no_cache(request: Request, call_next):
    # Ohne das cachen mobile Browser (v.a. Safari/iOS) remote.html/css/js nach
    # einem Deploy teils ueber mehrere Seitenaufrufe hinweg, ohne den Server
    # ueberhaupt erneut zu fragen - "no-cache" erzwingt immer eine
    # Revalidierung (billiger 304 dank ETag/Last-Modified von StaticFiles),
    # verhindert aber, dass je eine veraltete Version angezeigt wird.
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-cache"
    return response


def require_remote_secret(
    x_remote_secret: str | None = Header(default=None),
    secret: str | None = Query(default=None),
) -> None:
    """Schuetzt die Fernbedienungs-Routen, FALLS REMOTE_CONTROL_SECRET in .env
    gesetzt ist. Ohne konfiguriertes Secret bleibt die Fernbedienung offen
    fuers eigene WLAN (siehe README - Empfehlung: Secret setzen)."""
    expected = get_config().secrets.remote_control_secret
    if not expected:
        return
    if (x_remote_secret or secret) != expected:
        raise HTTPException(status_code=401, detail="ungueltiges oder fehlendes Secret")


@app.get("/api/state")
def get_state() -> JSONResponse:
    if not STATE_FILE.exists():
        return JSONResponse({"error": "noch kein Briefing erzeugt"}, status_code=404)
    data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    data["radio_playing"] = radio.is_playing()
    return JSONResponse(data)


@app.post("/api/todos/webhook")
async def todos_webhook(
    request: Request,
    x_webhook_secret: str | None = Header(default=None),
) -> dict:
    cfg = get_config()
    expected = cfg.secrets.todos_webhook_secret
    if not expected or x_webhook_secret != expected:
        raise HTTPException(status_code=401, detail="ungueltiges oder fehlendes Secret")

    body = await request.json()
    raw_text = body.get("text", "")
    items = [line.strip() for line in raw_text.splitlines() if line.strip()]

    todos_icloud_shortcut.write_todos_cache(cfg.todos.cache_file, items)
    logger.info("ToDos aktualisiert (%d Eintraege)", len(items))
    return {"ok": True, "count": len(items)}


@app.post("/api/shutdown-animation", dependencies=[Depends(require_remote_secret)])
async def trigger_shutdown_animation() -> dict:
    await manager.broadcast({"type": "shutdown"})
    return {"ok": True}


def _apply_youtube_command_state(body: dict) -> None:
    # Zentraler Durchlaufpunkt fuer JEDEN YouTube-Befehl, egal ob von der
    # Fernbedienung (/api/remote/youtube) oder direkt aus tv_power.py beim
    # Ausschalten (kiosk_media.stop_youtube) ausgeloest - so bleibt der
    # now-playing-Stand fuer die Fernbedienung immer aktuell, unabhaengig vom
    # Ausloeser.
    msg_type = body.get("type")
    if msg_type == "youtube_play":
        video_id = body.get("video_id")
        youtube_now_playing.update(
            {
                "video_id": video_id,
                "title": None,
                "thumbnail_url": kiosk_media.thumbnail_url(video_id) if video_id else None,
                "current_time": 0,
                "duration": 0,
                "playing": True,
            }
        )
    elif msg_type == "youtube_pause":
        youtube_now_playing["playing"] = False
    elif msg_type == "youtube_resume":
        youtube_now_playing["playing"] = True
    elif msg_type == "youtube_stop":
        _reset_youtube_state()


@app.post("/api/youtube-command", dependencies=[Depends(require_remote_secret)])
async def youtube_command(request: Request) -> dict:
    body = await request.json()
    _apply_youtube_command_state(body)
    await manager.broadcast(body)
    return {"ok": True}


@app.post("/api/remote/power", dependencies=[Depends(require_remote_secret)])
async def remote_power(request: Request) -> dict:
    body = await request.json()
    state = body.get("state")
    cfg = get_config()
    if state == "on":
        await asyncio.to_thread(tv_power.power_on, cfg)
    elif state == "off":
        await asyncio.to_thread(tv_power.power_off, cfg, False)
    else:
        raise HTTPException(status_code=400, detail="state muss 'on' oder 'off' sein")
    return {"ok": True}


@app.post("/api/remote/volume", dependencies=[Depends(require_remote_secret)])
async def remote_volume(request: Request) -> dict:
    body = await request.json()
    delta = body.get("delta", 0)
    if delta > 0:
        await asyncio.to_thread(audio_control.volume_up)
    elif delta < 0:
        await asyncio.to_thread(audio_control.volume_down)
    else:
        await asyncio.to_thread(audio_control.mute_toggle)
    return {"ok": True}


@app.post("/api/remote/youtube", dependencies=[Depends(require_remote_secret)])
async def remote_youtube(request: Request) -> dict:
    body = await request.json()
    action = body.get("action")
    cfg = get_config()

    if action == "play":
        video_id = await asyncio.to_thread(kiosk_media.play_youtube, cfg, body.get("url", ""))
        if not video_id:
            raise HTTPException(status_code=400, detail="Konnte keine YouTube-Video-ID aus der URL lesen")
        return {"ok": True, "video_id": video_id}
    if action == "pause":
        await asyncio.to_thread(kiosk_media.pause_youtube, cfg)
    elif action == "resume":
        await asyncio.to_thread(kiosk_media.resume_youtube, cfg)
    elif action == "stop":
        await asyncio.to_thread(kiosk_media.stop_youtube, cfg)
    elif action == "seek":
        await asyncio.to_thread(kiosk_media.seek_youtube, cfg, int(body.get("seconds", 0)))
    elif action == "seek_to":
        await asyncio.to_thread(kiosk_media.seek_to_youtube, cfg, float(body.get("seconds", 0)))
    else:
        raise HTTPException(status_code=400, detail="unbekannte action")
    return {"ok": True}


@app.get("/api/remote/radio/stations", dependencies=[Depends(require_remote_secret)])
async def get_radio_stations() -> dict:
    return radio_stations.list_stations(get_config())


@app.post("/api/remote/radio/stations", dependencies=[Depends(require_remote_secret)])
async def add_radio_station(request: Request) -> dict:
    body = await request.json()
    name = (body.get("name") or "").strip()
    url = (body.get("url") or "").strip()
    if not name or not url:
        raise HTTPException(status_code=400, detail="name und url erforderlich")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url muss mit http:// oder https:// beginnen")
    return await asyncio.to_thread(radio_stations.add_station, get_config(), name, url)


@app.delete("/api/remote/radio/stations/{station_id}", dependencies=[Depends(require_remote_secret)])
async def delete_radio_station(station_id: str) -> dict:
    return await asyncio.to_thread(radio_stations.remove_station, get_config(), station_id)


@app.post("/api/remote/radio", dependencies=[Depends(require_remote_secret)])
async def remote_radio(request: Request) -> dict:
    body = await request.json()
    action = body.get("action")
    cfg = get_config()

    if action == "play":
        station_id = body.get("station_id")
        if station_id:
            try:
                await asyncio.to_thread(radio_stations.set_current, cfg, station_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        # Radio und YouTube-Ton teilen sich die TV-Lautsprecher - beim
        # (Um-)Schalten des Senders laeuft evtl. noch ein Video.
        await asyncio.to_thread(kiosk_media.stop_youtube, cfg)
        await asyncio.to_thread(radio.stop)
        await asyncio.to_thread(radio.start, cfg)
    elif action == "stop":
        await asyncio.to_thread(radio.stop)
    else:
        raise HTTPException(status_code=400, detail="unbekannte action")
    return {"ok": True, "playing": radio.is_playing()}


@app.get("/api/remote/now-playing", dependencies=[Depends(require_remote_secret)])
async def get_now_playing() -> dict:
    cfg = get_config()
    return {
        "youtube": youtube_now_playing,
        "radio": {"playing": radio.is_playing(), "station": radio_stations.current_station(cfg)},
    }


@app.get("/api/remote/schedule", dependencies=[Depends(require_remote_secret)])
async def get_schedule() -> dict:
    return schedule_store.load_schedule(get_config())


@app.post("/api/remote/schedule", dependencies=[Depends(require_remote_secret)])
async def set_schedule(request: Request) -> dict:
    body = await request.json()
    try:
        return await asyncio.to_thread(schedule_store.save_schedule, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if msg.get("type") == "youtube_progress":
                youtube_now_playing["current_time"] = msg.get("current_time", 0)
                youtube_now_playing["duration"] = msg.get("duration", 0)
                youtube_now_playing["playing"] = bool(msg.get("playing", False))
                title = msg.get("title")
                if title:
                    youtube_now_playing["title"] = title
    except WebSocketDisconnect:
        manager.disconnect(ws)


# Muss zuletzt gemountet werden, sonst faengt der Catch-All die API-Routen ab.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
