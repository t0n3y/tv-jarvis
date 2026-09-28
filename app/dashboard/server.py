"""FastAPI-Backend fuers Dashboard und die Fernbedienung.

Laeuft dauerhaft (systemd/dashboard.service). Aufgaben:
1. Liefert den zuletzt von morning_routine.py geschriebenen Briefing-Stand
   (data/state.json) als JSON unter GET /api/state.
2. Nimmt ToDo-Updates von der iCloud-Shortcuts-Automation entgegen
   (POST /api/todos/webhook).
3. Broadcastet per WebSocket Events (Ausschalt-Animation, YouTube-/Jellyfin-
   Steuerung) an die im Chromium-Kiosk offene Seite.
4. Stellt die Fernbedienungs-API bereit (/api/remote/*), gedacht fuer die
   mobile Seite unter /remote.html (vom iPhone/iPad im selben WLAN).
5. Proxyt Jellyfin-Streams und -Bilder, damit der Jellyfin-API-Key (Admin-
   Rechte, Jellyfin ist oeffentlich erreichbar) nie einen Browser erreicht.
6. Plattenspieler: fuehrt die Warteschlange (Platte, Schrank, Zufallsmix)
   und schickt dem Kiosk Song fuer Song (versteckter YouTube-Player).
7. Loest ueber app/scheduler.py Morgen-/Verlassen-Routine zur Weckzeit aus.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import random
import re
import time
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.datastructures import MutableHeaders

from app import (
    audio_control,
    jellyfin_client,
    kiosk_media,
    media_upload,
    radio,
    radio_stations,
    schedule_store,
    school_settings,
    tv_power,
    vinyl_library,
)
from app.briefing import build_briefing
from app.config import ROOT_DIR, get_config
from app.dashboard import kiosk
from app.lighting import engine as lighting
from app.scheduler import Scheduler
from app.sources import todos_icloud_shortcut

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATE_FILE = ROOT_DIR / "data" / "state.json"
STATIC_DIR = Path(__file__).resolve().parent / "static"

# Der Kiosk laeuft auf dem Pi selbst; mit Dual-Stack-Socket (dashboard.host
# "::") kommen IPv4-Verbindungen als ::ffff:127.0.0.1 an.
LOCAL_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1"}
JELLYFIN_SYNC_INTERVAL_SECONDS = 15
IMAGE_TYPES = {"Primary", "Backdrop", "Thumb"}
STREAM_PASSTHROUGH_HEADERS = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "last-modified",
    "etag",
)


class NoCacheMiddleware:
    """Setzt Cache-Control: no-cache, wo eine Route nichts eigenes vorgibt.

    Ohne das cachen mobile Browser (v.a. Safari/iOS) remote.html/css/js nach
    einem Deploy teils ueber mehrere Seitenaufrufe hinweg, ohne den Server
    ueberhaupt erneut zu fragen. Reine ASGI-Middleware statt
    @app.middleware("http"): die BaseHTTPMiddleware-Variante leitet
    Streaming-Antworten (Jellyfin-Videos) ueber Zwischen-Queues."""

    def __init__(self, asgi_app) -> None:
        self.app = asgi_app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_cache_header(message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if "cache-control" not in headers:
                    headers["Cache-Control"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_with_cache_header)


app = FastAPI(title="TV-Jarvis Dashboard")
app.add_middleware(NoCacheMiddleware)


class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()
        # Letzter Abspiel-Befehl, der keinen Kiosk erreicht hat (Fernseher war
        # gerade erst eingeschaltet, Seite lud noch) - wird nachgeholt, sobald
        # sich der Kiosk verbindet.
        self.pending_play: dict | None = None

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)
        if self.pending_play is not None:
            message, self.pending_play = self.pending_play, None
            await ws.send_json(message)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, message: dict) -> bool:
        delivered = False
        for ws in list(self.active):
            try:
                await ws.send_json(message)
                delivered = True
            except Exception:  # noqa: BLE001
                self.disconnect(ws)
        return delivered


manager = ConnectionManager()

# Letzter bekannter Wiedergabe-Stand, gemeldet vom Kiosk per WebSocket (siehe
# dashboard/static/app.js). Lebt nur im Prozessspeicher - die Fernbedienung
# pollt ihn ueber GET /api/remote/now-playing, da die Player nur im
# Kiosk-Browser laufen.
youtube_now_playing: dict = {
    "video_id": None,
    "title": None,
    "thumbnail_url": None,
    "current_time": 0,
    "duration": 0,
    "playing": False,
}
jellyfin_now_playing: dict = {
    "item_id": None,
    "title": None,
    "subtitle": None,
    "poster": None,
    "backdrop": None,
    "current_time": 0,
    "duration": 0,
    "playing": False,
}
# Fortlaufende id, damit die Fernbedienung jeden Fehler genau einmal anzeigt
jellyfin_error: dict = {"id": 0, "message": None}

# Plattenspieler: die Warteschlange lebt hier (nicht im Kiosk), damit die
# Fernbedienung vor/zurueck schalten kann. Jeder Song bekommt ein neues token;
# Meldungen des Kiosks zu einem alten token werden ignoriert.
vinyl_now_playing: dict = {
    "token": 0,
    "queue": [],          # [(record_id, song_index), ...]
    "position": 0,
    "context": None,      # z.B. "Electronic & House" oder "Zufallsmix"
    "record": None,
    "song_index": 0,
    "title": None,
    "artist": None,
    "current_time": 0,
    "duration": 0,
    "playing": False,
}
vinyl_error: dict = {"id": 0, "message": None}
_vinyl_failures = 0
_jellyfin_last_sync = {"at": 0.0, "position": -1.0}
_background_tasks: set[asyncio.Task] = set()
_http_client: httpx.AsyncClient | None = None


def _http() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        # read=None: ein pausiertes Video liest minutenlang nichts - das ist
        # kein Fehler, der Stream soll dann einfach offen bleiben.
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))
    return _http_client


def _as_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _spawn(coro) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _reset_youtube_state() -> None:
    youtube_now_playing.update(
        video_id=None, title=None, thumbnail_url=None, current_time=0, duration=0, playing=False
    )


def _reset_jellyfin_state() -> None:
    jellyfin_now_playing.update(
        item_id=None,
        title=None,
        subtitle=None,
        poster=None,
        backdrop=None,
        current_time=0,
        duration=0,
        playing=False,
    )


def _reset_vinyl_state() -> None:
    vinyl_now_playing.update(
        queue=[], position=0, context=None, record=None, song_index=0,
        title=None, artist=None, current_time=0, duration=0, playing=False,
    )


def _save_jellyfin_progress(item_id: str, position: float, duration: float) -> None:
    try:
        jellyfin_client.save_progress(get_config(), item_id, position, duration)
    except jellyfin_client.JellyfinError as exc:
        logger.warning("Jellyfin-Position fuer %s nicht gespeichert: %s", item_id, exc)


def _schedule_jellyfin_save(position: float | None = None) -> None:
    item_id = jellyfin_now_playing["item_id"]
    if not item_id:
        return
    if position is None:
        position = jellyfin_now_playing["current_time"]
    duration = jellyfin_now_playing["duration"]
    _jellyfin_last_sync.update(at=time.monotonic(), position=position)
    _spawn(asyncio.to_thread(_save_jellyfin_progress, item_id, position, duration))


def _finish_jellyfin_session(position: float | None = None) -> None:
    if jellyfin_now_playing["item_id"]:
        _schedule_jellyfin_save(position)
        _reset_jellyfin_state()


@app.on_event("startup")
async def _start_scheduler() -> None:
    Scheduler(get_config()).start()
    lighting.get_engine().start()


@app.on_event("shutdown")
async def _close_http_client() -> None:
    if _http_client is not None:
        await _http_client.aclose()


def _is_local(host: str | None) -> bool:
    return host in LOCAL_HOSTS


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


def require_local(request: Request) -> None:
    if not _is_local(request.client.host if request.client else None):
        raise HTTPException(status_code=403, detail="nur fuer den Kiosk auf dem Pi selbst")


def require_local_or_remote_secret(
    request: Request,
    x_remote_secret: str | None = Header(default=None),
    secret: str | None = Query(default=None),
) -> None:
    # Bilder brauchen Kiosk (lokal, kennt kein Secret) UND Fernbedienung.
    if _is_local(request.client.host if request.client else None):
        return
    require_remote_secret(x_remote_secret, secret)


async def _ensure_tv_on() -> None:
    """Abspielen bei ausgeschaltetem Fernseher schaltet ihn erst ein. Der
    Abspiel-Befehl wartet dann als pending_play, bis der Kiosk verbunden ist."""
    if not kiosk.is_running():
        await asyncio.to_thread(tv_power.power_on, get_config())


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

    # Kurzbefehle schicken je nach Einrichtung JSON ({"text": ...}, auch mit
    # anderem Feldnamen), ein Formular oder reinen Text - alles annehmen.
    raw = await request.body()
    content_type = request.headers.get("content-type", "")
    body: dict = {}
    try:
        parsed = json.loads(raw) if raw else {}
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        body = parsed
    elif isinstance(parsed, str):
        body = {"text": parsed}
    elif "form" in content_type:
        body = dict((await request.form()).items())
    else:
        body = {"text": raw.decode("utf-8", errors="replace")}
    raw_text = body.get("text")
    if not isinstance(raw_text, str) or not raw_text.strip():
        raw_text = next((v for k, v in body.items() if k != "title" and isinstance(v, str) and v.strip()), "")
    if not raw_text.strip():
        # Nur die Form loggen, nicht den Inhalt
        logger.warning(
            "ToDo-Webhook ohne Text: Content-Type=%s, Felder=%s",
            content_type, {k: type(v).__name__ for k, v in body.items()},
        )
    # Aufzaehlungszeichen/Checklisten-Kaestchen aus der Notizen-App entfernen
    lines = [re.sub(r"^\s*(?:[-*•◦▪‣·]|☐|☑|✓|\[[ xX]?\])\s*", "", line).strip() for line in raw_text.splitlines()]
    items = [line for line in lines if line]
    # Kurzbefehl kann den Notiztitel mitschicken - der ist kein ToDo
    title = str(body.get("title") or "").strip()
    if title and items and items[0] == title:
        items = items[1:]

    todos_icloud_shortcut.write_todos_cache(cfg.todos.cache_file, items)
    logger.info("ToDos aktualisiert (%d Eintraege)", len(items))
    return {"ok": True, "count": len(items)}


@app.post("/api/shutdown-animation", dependencies=[Depends(require_remote_secret)])
async def trigger_shutdown_animation() -> dict:
    await manager.broadcast({"type": "shutdown"})
    return {"ok": True}


def _apply_command_state(body: dict) -> None:
    # Zentraler Durchlaufpunkt fuer JEDEN Medien-Befehl, egal ob von der
    # Fernbedienung oder direkt aus tv_power.py beim Ausschalten ausgeloest -
    # so bleibt der now-playing-Stand unabhaengig vom Ausloeser aktuell.
    msg_type = body.get("type")
    if msg_type in ("youtube_play", "jellyfin_play", "vinyl_play"):
        clock_screen["on"] = False
    if msg_type == "youtube_play":
        _finish_jellyfin_session()
        _reset_vinyl_state()
        video_id = body.get("video_id")
        youtube_now_playing.update(
            video_id=video_id,
            title=None,
            thumbnail_url=kiosk_media.thumbnail_url(video_id) if video_id else None,
            current_time=0,
            duration=0,
            playing=True,
        )
    elif msg_type == "youtube_pause":
        youtube_now_playing["playing"] = False
    elif msg_type == "youtube_resume":
        youtube_now_playing["playing"] = True
    elif msg_type == "youtube_stop":
        _reset_youtube_state()
    elif msg_type == "jellyfin_play":
        _finish_jellyfin_session()
        _reset_youtube_state()
        _reset_vinyl_state()
        jellyfin_now_playing.update(
            item_id=body.get("item_id"),
            title=body.get("title"),
            subtitle=body.get("subtitle"),
            poster=body.get("poster_url"),
            backdrop=body.get("backdrop_url"),
            current_time=_as_float(body.get("start_seconds")),
            duration=_as_float(body.get("duration")),
            playing=True,
        )
        _jellyfin_last_sync.update(at=time.monotonic(), position=jellyfin_now_playing["current_time"])
    elif msg_type == "jellyfin_pause":
        jellyfin_now_playing["playing"] = False
        _schedule_jellyfin_save()
    elif msg_type == "jellyfin_resume":
        jellyfin_now_playing["playing"] = True
    elif msg_type == "jellyfin_stop":
        _finish_jellyfin_session()
    elif msg_type == "vinyl_play":
        _finish_jellyfin_session()
        _reset_youtube_state()
    elif msg_type == "vinyl_pause":
        vinyl_now_playing["playing"] = False
    elif msg_type == "vinyl_resume":
        vinyl_now_playing["playing"] = True
    elif msg_type == "vinyl_stop":
        _reset_vinyl_state()


async def _send_to_kiosk(body: dict) -> bool:
    _apply_command_state(body)
    delivered = await manager.broadcast(body)
    msg_type = body.get("type") or ""
    if msg_type in ("youtube_play", "jellyfin_play", "vinyl_play"):
        manager.pending_play = None if delivered else body
    elif msg_type.endswith("_stop"):
        manager.pending_play = None
    return delivered


@app.post("/api/kiosk-command", dependencies=[Depends(require_remote_secret)])
async def kiosk_command(request: Request) -> dict:
    body = await request.json()
    return {"ok": True, "delivered": await _send_to_kiosk(body)}


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
    return {"ok": True, "volume": await asyncio.to_thread(audio_control.get_volume)}


@app.post("/api/remote/youtube", dependencies=[Depends(require_remote_secret)])
async def remote_youtube(request: Request) -> dict:
    body = await request.json()
    action = body.get("action")
    cfg = get_config()

    if action == "play":
        url = body.get("url", "")
        if not kiosk_media.extract_video_id(url):
            raise HTTPException(status_code=400, detail="Konnte keine YouTube-Video-ID aus dem Link lesen")
        await _ensure_tv_on()
        video_id = await asyncio.to_thread(kiosk_media.play_youtube, cfg, url)
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
        await asyncio.to_thread(kiosk_media.seek_to_youtube, cfg, _as_float(body.get("seconds")))
    else:
        raise HTTPException(status_code=400, detail="unbekannte action")
    return {"ok": True}


# ---------- Jellyfin ----------

async def _jellyfin(fn, *args):
    try:
        return await asyncio.to_thread(fn, get_config(), *args)
    except jellyfin_client.JellyfinError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _require_jellyfin_id(value: str | None, name: str = "item_id") -> None:
    if not jellyfin_client.valid_id(value):
        raise HTTPException(status_code=400, detail=f"ungueltige {name}")


@app.get("/api/remote/jellyfin/home", dependencies=[Depends(require_remote_secret)])
async def jellyfin_home() -> dict:
    libraries, resume = await asyncio.gather(
        _jellyfin(jellyfin_client.libraries), _jellyfin(jellyfin_client.resume)
    )
    return {"libraries": libraries, "resume": resume}


@app.get("/api/remote/jellyfin/items", dependencies=[Depends(require_remote_secret)])
async def jellyfin_items(parent_id: str | None = None, search: str | None = None) -> dict:
    search = (search or "").strip()[:100]
    if not search:
        _require_jellyfin_id(parent_id, "parent_id")
    return {"items": await _jellyfin(jellyfin_client.browse, parent_id, search or None)}


@app.get("/api/remote/jellyfin/item/{item_id}", dependencies=[Depends(require_remote_secret)])
async def jellyfin_item(item_id: str) -> dict:
    _require_jellyfin_id(item_id)
    return await _jellyfin(jellyfin_client.item, item_id)


@app.post("/api/remote/jellyfin", dependencies=[Depends(require_remote_secret)])
async def remote_jellyfin(request: Request) -> dict:
    body = await request.json()
    action = body.get("action")
    cfg = get_config()

    if action == "play":
        item_id = body.get("item_id")
        _require_jellyfin_id(item_id)
        item = await _jellyfin(jellyfin_client.item, item_id)
        if item["is_folder"]:
            raise HTTPException(status_code=400, detail="Das ist ein Ordner, kein Video")
        if item["playback_issue"]:
            raise HTTPException(status_code=409, detail=item["playback_issue"])
        start = 0 if body.get("from_start") else item["position_seconds"]
        await _ensure_tv_on()
        await asyncio.to_thread(kiosk_media.play_jellyfin, cfg, item, start)
        return {"ok": True}
    if action == "pause":
        await asyncio.to_thread(kiosk_media.pause_jellyfin, cfg)
    elif action == "resume":
        await asyncio.to_thread(kiosk_media.resume_jellyfin, cfg)
    elif action == "stop":
        await asyncio.to_thread(kiosk_media.stop_jellyfin, cfg)
    elif action == "seek":
        await asyncio.to_thread(kiosk_media.seek_jellyfin, cfg, int(body.get("seconds", 0)))
    elif action == "seek_to":
        await asyncio.to_thread(kiosk_media.seek_to_jellyfin, cfg, _as_float(body.get("seconds")))
    else:
        raise HTTPException(status_code=400, detail="unbekannte action")
    return {"ok": True}


@app.get("/api/jellyfin/image/{item_id}", dependencies=[Depends(require_local_or_remote_secret)])
async def jellyfin_image(
    item_id: str,
    image_type: str = Query("Primary", alias="type"),
    tag: str | None = None,
    max_width: int = 480,
) -> Response:
    _require_jellyfin_id(item_id)
    if image_type not in IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="ungueltiger Bildtyp")
    if tag is not None and not re.fullmatch(r"[0-9a-fA-F]{8,64}", tag):
        raise HTTPException(status_code=400, detail="ungueltiger Tag")
    cfg = get_config()
    if not jellyfin_client.is_configured(cfg):
        raise HTTPException(status_code=503, detail="Jellyfin ist nicht eingerichtet")
    url = jellyfin_client.image_url(cfg, item_id, image_type, tag, max(80, min(max_width, 1920)))
    try:
        resp = await _http().get(url, headers=jellyfin_client.auth_headers(cfg), timeout=10)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Jellyfin nicht erreichbar") from exc
    if resp.status_code != 200:
        raise HTTPException(status_code=404, detail="Bild nicht gefunden")
    # Der Tag in der URL aendert sich mit dem Bild - daher dauerhaft cachebar
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "image/jpeg"),
        headers={"Cache-Control": "public, max-age=604800, immutable"},
    )


@app.get("/api/kiosk/jellyfin/stream/{item_id}", dependencies=[Depends(require_local)])
async def jellyfin_stream(item_id: str, request: Request) -> StreamingResponse:
    _require_jellyfin_id(item_id)
    cfg = get_config()
    headers = jellyfin_client.auth_headers(cfg)
    # Range durchreichen - der Browser springt so beim Spulen direkt an die
    # passende Byte-Position statt die Datei von vorne zu laden.
    if "range" in request.headers:
        headers["Range"] = request.headers["range"]
    client = _http()
    try:
        upstream = await client.send(
            client.build_request("GET", jellyfin_client.stream_url(cfg, item_id), headers=headers),
            stream=True,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Jellyfin nicht erreichbar") from exc
    if upstream.status_code >= 400:
        await upstream.aclose()
        raise HTTPException(status_code=upstream.status_code, detail="Stream nicht verfuegbar")
    passthrough = {
        name: upstream.headers[name] for name in STREAM_PASSTHROUGH_HEADERS if name in upstream.headers
    }
    passthrough["Cache-Control"] = "no-store"
    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=passthrough,
        background=BackgroundTask(upstream.aclose),
    )


# ---------- Jellyfin: Upload auf die Platte ----------
# Chunks von der Fernbedienung (siehe app/media_upload.py) - Filme sind
# mehrere GB gross, ein einzelner Request waere weder robust noch
# fortsetzbar.

async def _upload(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except media_upload.UploadError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except jellyfin_client.JellyfinError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except OSError as exc:
        logger.warning("Upload: Dateifehler %s", exc)
        raise HTTPException(status_code=500, detail="Schreiben auf die Platte fehlgeschlagen – ist sie eingehängt?") from exc


@app.get("/api/remote/jellyfin/upload/targets", dependencies=[Depends(require_remote_secret)])
async def upload_targets() -> dict:
    cfg = get_config()
    found = await _upload(media_upload.targets, cfg)
    free = await _upload(media_upload.free_bytes, cfg)
    return {"targets": [{k: t[k] for k in ("id", "name", "kind")} for t in found], "free_bytes": free}


@app.post("/api/remote/jellyfin/upload", dependencies=[Depends(require_remote_secret)])
async def upload_start(request: Request) -> dict:
    return await _upload(media_upload.start, get_config(), await request.json())


@app.put("/api/remote/jellyfin/upload/{upload_id}", dependencies=[Depends(require_remote_secret)])
async def upload_chunk(upload_id: str, request: Request, offset: int = Query(ge=0)) -> dict:
    chunk = await request.body()
    return {"received": await _upload(media_upload.append, upload_id, offset, chunk)}


@app.post("/api/remote/jellyfin/upload/{upload_id}/finish", dependencies=[Depends(require_remote_secret)])
async def upload_finish(upload_id: str) -> dict:
    return await _upload(media_upload.finish, get_config(), upload_id)


@app.delete("/api/remote/jellyfin/upload/{upload_id}", dependencies=[Depends(require_remote_secret)])
async def upload_cancel(upload_id: str) -> dict:
    await _upload(media_upload.cancel, upload_id)
    return {"ok": True}


# ---------- Radio ----------

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
        # Radio und Video-Ton teilen sich die TV-Lautsprecher - beim
        # (Um-)Schalten des Senders laeuft evtl. noch ein Video.
        await asyncio.to_thread(kiosk_media.stop_all_media, cfg)
        await asyncio.to_thread(radio.stop)
        await asyncio.to_thread(radio.start, cfg)
    elif action == "stop":
        await asyncio.to_thread(radio.stop)
    else:
        raise HTTPException(status_code=400, detail="unbekannte action")
    return {"ok": True, "playing": radio.is_playing()}


# ---------- Plattenspieler ----------

VINYL_RESTART_THRESHOLD_SECONDS = 5
VINYL_MAX_FAILURES = 5


async def _vinyl(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except vinyl_library.VinylError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _vinyl_record_public(record: dict) -> dict:
    return {
        "id": record["id"],
        "album": record["album"],
        "artist": record["artist"],
        "year": record.get("year"),
        "cover": record.get("cover"),
        "color": record.get("color"),
        "songs": [s["title"] for s in record["songs"]],
    }


def _vinyl_queue(body: dict) -> tuple[list[tuple[str, int]], int, str]:
    """Baut die Warteschlange: eine Platte (ab einem Song), ein Schrank oder alles."""
    lib = vinyl_library.library()
    records = lib["records"]
    shuffle = bool(body.get("shuffle"))
    if body.get("record_id"):
        record = next((r for r in records if r["id"] == body["record_id"]), None)
        if record is None:
            raise HTTPException(status_code=404, detail="Diese Platte gibt es nicht mehr")
        queue = [(record["id"], i) for i in range(len(record["songs"]))]
        if shuffle:
            random.shuffle(queue)
            return queue, 0, record["album"]
        start = max(0, min(int(body.get("song_index") or 0), len(queue) - 1))
        return queue, start, record["album"]
    if body.get("genre_id"):
        genre = next((g for g in lib["genres"] if g["id"] == body["genre_id"]), None)
        if genre is None:
            raise HTTPException(status_code=404, detail="Diesen Schrank gibt es nicht mehr")
        records = [r for r in records if r["genre"] == genre["id"]]
        context = genre["name"]
    else:
        context = "Zufallsmix" if shuffle else "Alle Platten"
    queue = [(r["id"], i) for r in records for i in range(len(r["songs"]))]
    if shuffle:
        random.shuffle(queue)
    if not queue:
        raise HTTPException(status_code=400, detail="Hier stehen noch keine Platten")
    return queue, 0, context


async def _vinyl_play_position(position: int) -> bool:
    """Legt den Song an Stelle `position` auf. Songs ohne YouTube-Video
    (oder geloeschte Platten) werden uebersprungen. False = Ende erreicht."""
    queue = vinyl_now_playing["queue"]
    record = None
    while 0 <= position < len(queue):
        record_id, song_index = queue[position]
        record = vinyl_library.find_record(record_id)
        if record and song_index < len(record["songs"]) and record["songs"][song_index].get("youtube"):
            break
        position += 1
    else:
        return False

    song = record["songs"][song_index]
    upcoming = None
    for next_record_id, next_index in queue[position + 1:position + 2]:
        next_record = vinyl_library.find_record(next_record_id)
        if next_record and next_index < len(next_record["songs"]):
            upcoming = {"title": next_record["songs"][next_index]["title"], "artist": next_record["artist"]}
    vinyl_now_playing["token"] += 1
    vinyl_now_playing.update(
        position=position,
        record=_vinyl_record_public(record),
        song_index=song_index,
        title=song["title"],
        artist=song.get("artist") or record["artist"],
        current_time=0,
        duration=0,
        playing=True,
    )
    await _send_to_kiosk({
        "type": "vinyl_play",
        "token": vinyl_now_playing["token"],
        "video_id": song["youtube"],
        "start": song.get("start") or 0,
        "title": vinyl_now_playing["title"],
        "artist": vinyl_now_playing["artist"],
        "record": vinyl_now_playing["record"],
        "song_index": song_index,
        "position": position,
        "queue_length": len(queue),
        "context": vinyl_now_playing["context"],
        "next": upcoming,
    })
    return True


async def _vinyl_advance(step: int = 1) -> None:
    if not vinyl_now_playing["queue"]:
        return
    if not await _vinyl_play_position(vinyl_now_playing["position"] + step):
        await _send_to_kiosk({"type": "vinyl_stop"})


def _vinyl_public_state() -> dict:
    state = {k: v for k, v in vinyl_now_playing.items() if k != "queue"}
    state["queue_length"] = len(vinyl_now_playing["queue"])
    state["active"] = bool(vinyl_now_playing["queue"])
    return state


@app.get("/api/remote/vinyl/library", dependencies=[Depends(require_remote_secret)])
async def vinyl_get_library() -> dict:
    return await asyncio.to_thread(vinyl_library.library)


@app.post("/api/remote/vinyl/genres", dependencies=[Depends(require_remote_secret)])
async def vinyl_add_genre(request: Request) -> dict:
    body = await request.json()
    return await _vinyl(vinyl_library.add_genre, str(body.get("name") or ""))


@app.patch("/api/remote/vinyl/genres/{genre_id}", dependencies=[Depends(require_remote_secret)])
async def vinyl_rename_genre(genre_id: str, request: Request) -> dict:
    body = await request.json()
    await _vinyl(vinyl_library.rename_genre, genre_id, str(body.get("name") or ""))
    return {"ok": True}


@app.delete("/api/remote/vinyl/genres/{genre_id}", dependencies=[Depends(require_remote_secret)])
async def vinyl_delete_genre(genre_id: str) -> dict:
    await _vinyl(vinyl_library.delete_genre, genre_id)
    return {"ok": True}


@app.post("/api/remote/vinyl/records", dependencies=[Depends(require_remote_secret)])
async def vinyl_add_record(request: Request) -> dict:
    body = await request.json()
    return await _vinyl(vinyl_library.add_record, body)


@app.patch("/api/remote/vinyl/records/{record_id}", dependencies=[Depends(require_remote_secret)])
async def vinyl_update_record(record_id: str, request: Request) -> dict:
    body = await request.json()
    changes = {k: body[k] for k in ("genre", "remove_song") if k in body}
    return await _vinyl(vinyl_library.update_record, record_id, changes)


@app.delete("/api/remote/vinyl/records/{record_id}", dependencies=[Depends(require_remote_secret)])
async def vinyl_delete_record(record_id: str) -> dict:
    await _vinyl(vinyl_library.delete_record, record_id)
    return {"ok": True}


@app.get("/api/remote/vinyl/search", dependencies=[Depends(require_remote_secret)])
async def vinyl_search(q: str = "", kind: str = "album") -> dict:
    return {"results": await _vinyl(vinyl_library.search, q[:100], kind)}


@app.get("/api/remote/vinyl/album/{collection_id}", dependencies=[Depends(require_remote_secret)])
async def vinyl_album(collection_id: int) -> dict:
    return await _vinyl(vinyl_library.album_tracks, collection_id)


@app.post("/api/remote/vinyl", dependencies=[Depends(require_remote_secret)])
async def remote_vinyl(request: Request) -> dict:
    global _vinyl_failures
    body = await request.json()
    action = body.get("action")

    if action == "play":
        queue, start, context = await asyncio.to_thread(_vinyl_queue, body)
        await _ensure_tv_on()
        # Radio und Videos teilen sich die TV-Lautsprecher
        await asyncio.to_thread(radio.stop)
        _vinyl_failures = 0
        vinyl_now_playing.update(queue=queue, context=context)
        if not await _vinyl_play_position(start):
            _reset_vinyl_state()
            raise HTTPException(status_code=400, detail="Für diese Songs ist kein YouTube-Video hinterlegt")
    elif not vinyl_now_playing["queue"]:
        raise HTTPException(status_code=409, detail="Gerade liegt keine Platte auf")
    elif action == "pause":
        await _send_to_kiosk({"type": "vinyl_pause"})
    elif action == "resume":
        await _send_to_kiosk({"type": "vinyl_resume"})
    elif action == "next":
        await _vinyl_advance(1)
    elif action == "prev":
        # Wie am CD-Player: erst an den Songanfang, beim zweiten Druck davor
        if vinyl_now_playing["current_time"] > VINYL_RESTART_THRESHOLD_SECONDS or vinyl_now_playing["position"] == 0:
            await _send_to_kiosk({"type": "vinyl_seek_to", "seconds": 0})
        else:
            await _vinyl_play_position(vinyl_now_playing["position"] - 1)
    elif action == "seek_to":
        await _send_to_kiosk({"type": "vinyl_seek_to", "seconds": _as_float(body.get("seconds"))})
    elif action == "stop":
        await _send_to_kiosk({"type": "vinyl_stop"})
    else:
        raise HTTPException(status_code=400, detail="unbekannte action")
    return {"ok": True, "vinyl": _vinyl_public_state()}


# ---------- Licht (DMX) ----------

LIGHT_FIELDS = {"on", "brightness", "color", "effect", "bpm", "fixtures", "tap"}


@app.get("/api/remote/light", dependencies=[Depends(require_remote_secret)])
async def get_light() -> dict:
    return {**lighting.get_engine().state(), "effects": lighting.effect_catalog()}


@app.post("/api/remote/light", dependencies=[Depends(require_remote_secret)])
async def set_light(request: Request) -> dict:
    body = await request.json()
    changes = {k: v for k, v in body.items() if k in LIGHT_FIELDS}
    try:
        return lighting.get_engine().update(changes)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- Dashboard-Daten (Wetter, Kalender, ToDos, Vertretungsplan) ----------
# Frueher schrieb nur die Morgen-Routine data/state.json - ohne Wecker (oder
# bei einem Netzaussetzer genau zur Weckzeit) blieben die Panels tagelang alt
# oder leer. Jetzt aktualisiert der Dienst sie selbst.

DASHBOARD_REFRESH_SECONDS = 10 * 60
DASHBOARD_RETRY_SECONDS = 60


def _refresh_dashboard_state() -> bool:
    briefing = build_briefing(get_config())
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(dataclasses.asdict(briefing), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)
    # Wetter fehlt = meist kein Netz. Andere Einzelfehler (z.B. IServ) nicht
    # minuetlich wiederholen, sonst meldet sich der Pi dauernd neu an.
    return briefing.weather is not None


async def _dashboard_refresh_loop() -> None:
    while True:
        try:
            ok = await asyncio.to_thread(_refresh_dashboard_state)
        except Exception:  # noqa: BLE001 - der Loop darf nie sterben
            logger.exception("Dashboard-Daten konnten nicht aktualisiert werden")
            ok = False
        # Nach einem Fehler (z.B. WLAN noch nicht da) bald erneut versuchen
        await asyncio.sleep(DASHBOARD_REFRESH_SECONDS if ok else DASHBOARD_RETRY_SECONDS)


@app.on_event("startup")
async def _start_dashboard_refresh() -> None:
    _spawn(_dashboard_refresh_loop())


@app.get("/api/remote/school", dependencies=[Depends(require_remote_secret)])
async def get_school() -> dict:
    return await asyncio.to_thread(school_settings.load, get_config())


@app.post("/api/remote/school", dependencies=[Depends(require_remote_secret)])
async def set_school(request: Request) -> dict:
    body = await request.json()
    try:
        await asyncio.to_thread(school_settings.save_courses, body.get("kurse"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Vertretungsplan auf dem Fernseher gleich mit den neuen Kursen zeigen
    _spawn(asyncio.to_thread(_refresh_dashboard_state))
    return await asyncio.to_thread(school_settings.load, get_config())


# ---------- Uhr & Timer ----------
# Der Timer lebt hier (nicht im Kiosk), damit er auch bei ausgeschaltetem
# Fernseher weiterlaeuft. Beim Ablauf wird alles pausiert, der Kiosk zeigt
# den Alarm und spielt den Ton, bis die Fernbedienung geoeffnet wird ("ack").

TIMER_MAX_SECONDS = 24 * 3600

# state: idle | running | paused | ringing. id waechst bei jedem Start, damit
# ein alter Ablauf-Task einen neu gestellten Timer nicht ausloest.
timer_state: dict = {"id": 0, "state": "idle", "duration": 0, "ends_at": 0.0, "remaining": 0.0, "acknowledged": False}
clock_screen: dict = {"on": False}
_timer_task: asyncio.Task | None = None


def _timer_remaining() -> float:
    if timer_state["state"] == "running":
        return max(0.0, timer_state["ends_at"] - time.time())
    if timer_state["state"] == "paused":
        return timer_state["remaining"]
    return 0.0


def _timer_public() -> dict:
    return {
        "id": timer_state["id"],
        "state": timer_state["state"],
        "duration": timer_state["duration"],
        # Restzeit statt Endzeitpunkt: Handy- und Pi-Uhr muessen nicht synchron sein
        "remaining_ms": round(_timer_remaining() * 1000),
        "acknowledged": timer_state["acknowledged"],
        "clock_screen": clock_screen["on"],
    }


def _timer_message(show: bool = False) -> dict:
    return {"type": "timer_state", "show": show, **_timer_public()}


def _cancel_timer_task() -> None:
    global _timer_task
    if _timer_task is not None:
        _timer_task.cancel()
        _timer_task = None


def _schedule_timer() -> None:
    global _timer_task
    _cancel_timer_task()
    _timer_task = asyncio.create_task(_timer_wait(timer_state["id"]))


async def _timer_wait(timer_id: int) -> None:
    await asyncio.sleep(max(0.0, timer_state["ends_at"] - time.time()))
    if timer_state["id"] == timer_id and timer_state["state"] == "running":
        await _timer_ring()


async def _pause_all_media() -> None:
    if youtube_now_playing["video_id"] and youtube_now_playing["playing"]:
        await _send_to_kiosk({"type": "youtube_pause"})
    if jellyfin_now_playing["item_id"] and jellyfin_now_playing["playing"]:
        await _send_to_kiosk({"type": "jellyfin_pause"})
    if vinyl_now_playing["queue"] and vinyl_now_playing["playing"]:
        await _send_to_kiosk({"type": "vinyl_pause"})
    if radio.is_playing():
        # mpv-Radio kann nicht pausieren (Livestream) - dann eben stoppen
        await asyncio.to_thread(radio.stop)


async def _timer_ring() -> None:
    timer_state.update(state="ringing", acknowledged=False, remaining=0.0)
    logger.info("Timer abgelaufen")
    await _pause_all_media()
    # Stummgeschalteter Fernseher wuerde den Alarm verschlucken
    await asyncio.to_thread(audio_control.unmute)
    await _ensure_tv_on()
    await manager.broadcast(_timer_message())


async def _timer_start(seconds: float) -> None:
    timer_state.update(
        id=timer_state["id"] + 1,
        state="running",
        duration=seconds,
        ends_at=time.time() + seconds,
        remaining=seconds,
        acknowledged=False,
    )
    _schedule_timer()
    await _ensure_tv_on()
    await manager.broadcast(_timer_message(show=True))


@app.post("/api/remote/timer", dependencies=[Depends(require_remote_secret)])
async def remote_timer(request: Request) -> dict:
    body = await request.json()
    action = body.get("action")
    state = timer_state["state"]

    if action == "start":
        seconds = _as_float(body.get("seconds"))
        if not 1 <= seconds <= TIMER_MAX_SECONDS:
            raise HTTPException(status_code=400, detail="Der Timer muss zwischen 1 Sekunde und 24 Stunden liegen")
        await _timer_start(round(seconds))
        return {"ok": True, "timer": _timer_public()}
    if action == "restart":
        if not timer_state["duration"]:
            raise HTTPException(status_code=409, detail="Es gibt keinen Timer zum Neustarten")
        await _timer_start(timer_state["duration"])
        return {"ok": True, "timer": _timer_public()}

    if action == "pause" and state == "running":
        timer_state.update(state="paused", remaining=_timer_remaining())
        _cancel_timer_task()
    elif action == "resume" and state == "paused":
        timer_state.update(state="running", ends_at=time.time() + timer_state["remaining"])
        _schedule_timer()
    elif action == "add" and state in ("running", "paused"):
        seconds = max(0.0, min(_as_float(body.get("seconds")), TIMER_MAX_SECONDS))
        timer_state["duration"] += seconds
        if state == "running":
            timer_state["ends_at"] += seconds
            _schedule_timer()
        else:
            timer_state["remaining"] += seconds
    elif action == "ack" and state == "ringing":
        timer_state["acknowledged"] = True
    elif action in ("cancel", "dismiss"):
        _cancel_timer_task()
        timer_state.update(state="idle", remaining=0.0, acknowledged=False)
    elif action not in ("pause", "resume", "add", "ack"):
        raise HTTPException(status_code=400, detail="unbekannte action")
    await manager.broadcast(_timer_message())
    return {"ok": True, "timer": _timer_public()}


@app.post("/api/remote/clock", dependencies=[Depends(require_remote_secret)])
async def remote_clock(request: Request) -> dict:
    """Vollbild-Uhr auf dem Fernseher an/aus."""
    body = await request.json()
    show = bool(body.get("show"))
    clock_screen["on"] = show
    if show:
        # Ist der Fernseher aus, holt der Kiosk die Uhr beim Verbinden nach
        await _ensure_tv_on()
    await manager.broadcast({"type": "clock_show" if show else "clock_hide"})
    return {"ok": True, "timer": _timer_public()}


# ---------- Status / Einstellungen ----------

@app.get("/api/remote/now-playing", dependencies=[Depends(require_remote_secret)])
async def get_now_playing() -> dict:
    cfg = get_config()
    return {
        "tv_on": kiosk.is_running(),
        "youtube": youtube_now_playing,
        "jellyfin": jellyfin_now_playing,
        "jellyfin_error": jellyfin_error,
        "vinyl": _vinyl_public_state(),
        "timer": _timer_public(),
        "vinyl_error": vinyl_error,
        "radio": {"playing": radio.is_playing(), "station": radio_stations.current_station(cfg)},
        "light": lighting.get_engine().state(),
    }


@app.get("/api/remote/info", dependencies=[Depends(require_remote_secret)])
async def remote_info() -> dict:
    cfg = get_config()
    name = None
    if jellyfin_client.is_configured(cfg):
        try:
            name = await asyncio.to_thread(jellyfin_client.user_display_name, cfg)
        except jellyfin_client.JellyfinError:
            pass
    return {"name": name, "jellyfin": jellyfin_client.is_configured(cfg)}


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


# ---------- WebSocket zum Kiosk ----------

def _handle_vinyl_report(msg: dict) -> None:
    global _vinyl_failures
    if msg.get("token") != vinyl_now_playing["token"] or not vinyl_now_playing["queue"]:
        return  # Meldung zu einem inzwischen abgeloesten Song
    msg_type = msg.get("type")
    if msg_type == "vinyl_progress":
        vinyl_now_playing["current_time"] = _as_float(msg.get("current_time"))
        vinyl_now_playing["duration"] = _as_float(msg.get("duration"))
        vinyl_now_playing["playing"] = bool(msg.get("playing"))
        if vinyl_now_playing["playing"]:
            _vinyl_failures = 0
    elif msg_type == "vinyl_ended":
        _spawn(_vinyl_advance(1))
    elif msg_type == "vinyl_error":
        # Meist: Video darf nicht eingebettet werden (YouTube-Fehler 101/150)
        _vinyl_failures += 1
        title = vinyl_now_playing["title"]
        logger.warning("Plattenspieler: %s nicht abspielbar (YouTube-Fehler %s)", title, msg.get("code"))
        vinyl_error["id"] += 1
        if _vinyl_failures >= min(VINYL_MAX_FAILURES, len(vinyl_now_playing["queue"])):
            vinyl_error["message"] = "Die Songs lassen sich gerade nicht abspielen"
            _spawn(_send_to_kiosk({"type": "vinyl_stop"}))
        else:
            vinyl_error["message"] = f"„{title}“ ließ sich nicht abspielen – nächster Song"
            _spawn(_vinyl_advance(1))


def _handle_kiosk_report(msg: dict) -> None:
    msg_type = msg.get("type")
    if isinstance(msg_type, str) and msg_type.startswith("vinyl_"):
        _handle_vinyl_report(msg)
        return
    if msg_type == "youtube_progress":
        youtube_now_playing["current_time"] = _as_float(msg.get("current_time"))
        youtube_now_playing["duration"] = _as_float(msg.get("duration"))
        youtube_now_playing["playing"] = bool(msg.get("playing"))
        if isinstance(msg.get("title"), str) and msg["title"]:
            youtube_now_playing["title"] = msg["title"]
        return

    if msg.get("item_id") != jellyfin_now_playing["item_id"] or not jellyfin_now_playing["item_id"]:
        return  # Meldung zu einem inzwischen abgeloesten Video
    if msg_type == "jellyfin_progress":
        jellyfin_now_playing["current_time"] = _as_float(msg.get("current_time"))
        duration = _as_float(msg.get("duration"))
        if duration > 0:
            jellyfin_now_playing["duration"] = duration
        jellyfin_now_playing["playing"] = bool(msg.get("playing"))
        due = time.monotonic() - _jellyfin_last_sync["at"] >= JELLYFIN_SYNC_INTERVAL_SECONDS
        # Waehrend einer Pause meldet der Kiosk weiter jede Sekunde dieselbe
        # Position - die muss nicht alle 15 s erneut gespeichert werden.
        moved = abs(jellyfin_now_playing["current_time"] - _jellyfin_last_sync["position"]) >= 1
        if due and moved:
            _schedule_jellyfin_save()
    elif msg_type == "jellyfin_ended":
        _finish_jellyfin_session(position=jellyfin_now_playing["duration"])
    elif msg_type == "jellyfin_error":
        _reset_jellyfin_state()
        jellyfin_error["id"] += 1
        message = msg.get("message")
        jellyfin_error["message"] = message if isinstance(message, str) else "Wiedergabe fehlgeschlagen"


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    # Nur der Kiosk auf dem Pi selbst - seine Fortschrittsmeldungen schreiben
    # in Jellyfin, das soll niemand sonst im WLAN faelschen koennen.
    if not _is_local(ws.client.host if ws.client else None):
        await ws.close(code=1008)
        return
    await manager.connect(ws)
    # Frisch gestarteter Kiosk (z.B. Fernseher gerade fuer den Timer
    # eingeschaltet): laufenden Timer und Vollbild-Uhr sofort uebernehmen
    if timer_state["state"] != "idle":
        await ws.send_json(_timer_message(show=True))
    if clock_screen["on"]:
        await ws.send_json({"type": "clock_show"})
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(msg, dict):
                _handle_kiosk_report(msg)
    except WebSocketDisconnect:
        manager.disconnect(ws)


# Muss zuletzt gemountet werden, sonst faengt der Catch-All die API-Routen ab.
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
