"""Steuert die Medienwiedergabe (YouTube, Jellyfin) im Kiosk-Browser per WebSocket.

Die eigentlichen Player laufen im Frontend (YouTube IFrame API bzw. ein
<video>-Element fuer Jellyfin, siehe dashboard/static/app.js) - dieses Modul
schickt nur die Steuerbefehle per POST an den lokalen Dashboard-Server, der sie
per WebSocket an die im Kiosk offene Seite weiterreicht.

Nur ein Medium laeuft gleichzeitig: jedes *_play stoppt das Radio, und der
Kiosk stoppt beim Wechsel des Bildschirms das jeweils andere Video selbst.
"""

from __future__ import annotations

import logging
import re

import requests

from app import radio
from app.config import Config

logger = logging.getLogger(__name__)

KIOSK_COMMAND_PATH = "/api/kiosk-command"

# Deckt die gaengigen YouTube-URL-Formen ab: watch?v=, youtu.be/, shorts/, embed/
_VIDEO_ID_PATTERNS = [
    re.compile(r"(?:v=|/embed/|/shorts/|youtu\.be/)([A-Za-z0-9_-]{11})"),
]


def extract_video_id(url_or_id: str) -> str | None:
    url_or_id = url_or_id.strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", url_or_id):
        return url_or_id
    for pattern in _VIDEO_ID_PATTERNS:
        match = pattern.search(url_or_id)
        if match:
            return match.group(1)
    return None


def thumbnail_url(video_id: str) -> str:
    return f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg"


def _send(cfg: Config, message: dict) -> None:
    headers = {}
    if cfg.secrets.remote_control_secret:
        headers["X-Remote-Secret"] = cfg.secrets.remote_control_secret
    try:
        requests.post(
            f"http://127.0.0.1:{cfg.dashboard.port}{KIOSK_COMMAND_PATH}",
            json=message,
            headers=headers,
            timeout=3,
        )
    except requests.RequestException as exc:
        logger.warning("Kiosk-Befehl %s fehlgeschlagen (%s)", message.get("type"), exc)


# ---------- YouTube ----------

def play_youtube(cfg: Config, url_or_id: str) -> str | None:
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return None
    radio.stop()
    _send(cfg, {"type": "youtube_play", "video_id": video_id})
    return video_id


def pause_youtube(cfg: Config) -> None:
    _send(cfg, {"type": "youtube_pause"})


def resume_youtube(cfg: Config) -> None:
    _send(cfg, {"type": "youtube_resume"})


def stop_youtube(cfg: Config) -> None:
    _send(cfg, {"type": "youtube_stop"})


def seek_youtube(cfg: Config, seconds: int) -> None:
    _send(cfg, {"type": "youtube_seek", "seconds": seconds})


def seek_to_youtube(cfg: Config, seconds: float) -> None:
    _send(cfg, {"type": "youtube_seek_to", "seconds": seconds})


# ---------- Jellyfin ----------

def play_jellyfin(cfg: Config, item: dict, start_seconds: float) -> None:
    radio.stop()
    _send(
        cfg,
        {
            "type": "jellyfin_play",
            "item_id": item["id"],
            "title": item["name"],
            "subtitle": item["subtitle"],
            "poster_url": item["poster"],
            "backdrop_url": item["backdrop"],
            "duration": item["runtime_seconds"],
            "start_seconds": start_seconds,
            # Proxy-Route im Dashboard-Server - der Jellyfin-Key bleibt serverseitig
            "stream_url": f"/api/kiosk/jellyfin/stream/{item['id']}",
        },
    )


def pause_jellyfin(cfg: Config) -> None:
    _send(cfg, {"type": "jellyfin_pause"})


def resume_jellyfin(cfg: Config) -> None:
    _send(cfg, {"type": "jellyfin_resume"})


def stop_jellyfin(cfg: Config) -> None:
    _send(cfg, {"type": "jellyfin_stop"})


def seek_jellyfin(cfg: Config, seconds: int) -> None:
    _send(cfg, {"type": "jellyfin_seek", "seconds": seconds})


def seek_to_jellyfin(cfg: Config, seconds: float) -> None:
    _send(cfg, {"type": "jellyfin_seek_to", "seconds": seconds})


def stop_all_media(cfg: Config) -> None:
    stop_youtube(cfg)
    stop_jellyfin(cfg)
