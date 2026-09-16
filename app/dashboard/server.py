"""FastAPI-Backend fuers Dashboard.

Laeuft dauerhaft (systemd/dashboard.service) und macht drei Dinge:
1. Liefert den zuletzt von morning_routine.py geschriebenen Briefing-Stand
   (data/state.json) als JSON unter GET /api/state.
2. Nimmt ToDo-Updates von der iCloud-Shortcuts-Automation entgegen
   (POST /api/todos/webhook).
3. Broadcastet per WebSocket ein "shutdown"-Event, damit die im
   Chromium-Kiosk offene Seite die Ausschalt-Animation abspielen kann, bevor
   leave_routine.py den Fernseher wirklich per CEC ausschaltet.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import ROOT_DIR, get_config
from app.sources import todos_icloud_shortcut
from app import radio

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


@app.post("/api/shutdown-animation")
async def trigger_shutdown_animation() -> dict:
    await manager.broadcast({"type": "shutdown"})
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
