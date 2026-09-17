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

from app import audio_control, kiosk_media, radio, tv_power
from app.config import ROOT_DIR, get_config
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


@app.post("/api/youtube-command", dependencies=[Depends(require_remote_secret)])
async def youtube_command(request: Request) -> dict:
    body = await request.json()
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
    else:
        raise HTTPException(status_code=400, detail="unbekannte action")
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    await manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(ws)


# Muss zuletzt gemountet werden, sonst faengt der Catch-All die API-Routen ab.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
