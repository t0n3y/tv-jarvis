"""Steuert die YouTube-Wiedergabe im Dashboard (Kiosk-Browser) per WebSocket.

Der eigentliche Player laeuft im Frontend (YouTube IFrame API, siehe
dashboard/static/app.js) - dieses Modul schickt nur die Steuerbefehle per
POST an den lokalen Dashboard-Server, der sie per WebSocket an die im
Kiosk offene Seite weiterreicht.
"""

from __future__ import annotations

import logging
import re

import requests

from app import radio
from app.config import Config

logger = logging.getLogger(__name__)

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


def _dashboard_url(cfg: Config, path: str) -> str:
    return f"http://127.0.0.1:{cfg.dashboard.port}{path}"


def _post_local(cfg: Config, path: str, json: dict | None = None) -> None:
    headers = {}
    if cfg.secrets.remote_control_secret:
        headers["X-Remote-Secret"] = cfg.secrets.remote_control_secret
    try:
        requests.post(_dashboard_url(cfg, path), json=json, headers=headers, timeout=3)
    except requests.RequestException as exc:
        logger.warning("Aufruf von %s fehlgeschlagen (%s)", path, exc)


def play_youtube(cfg: Config, url_or_id: str) -> str | None:
    video_id = extract_video_id(url_or_id)
    if not video_id:
        return None
    # Radio und YouTube-Ton gleichzeitig ueber dieselben TV-Lautsprecher waere
    # nur Laerm - Radio wird beim Videostart automatisch gestoppt.
    radio.stop()
    _post_local(cfg, "/api/youtube-command", {"type": "youtube_play", "video_id": video_id})
    return video_id


def pause_youtube(cfg: Config) -> None:
    _post_local(cfg, "/api/youtube-command", {"type": "youtube_pause"})


def resume_youtube(cfg: Config) -> None:
    _post_local(cfg, "/api/youtube-command", {"type": "youtube_resume"})


def stop_youtube(cfg: Config) -> None:
    _post_local(cfg, "/api/youtube-command", {"type": "youtube_stop"})
