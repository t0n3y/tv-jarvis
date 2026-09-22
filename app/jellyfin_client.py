"""Duenner Client fuer die Jellyfin-REST-API: Bibliothek durchsuchen,
Details/Fortsetzen-Position lesen und die Wiedergabeposition zurueckschreiben.

Authentifiziert ausschliesslich per Authorization-Header. Jellyfin 12 lehnt
die alte api_key-URL-Variante ohnehin ab, und der Key darf nie im Browser
landen (Jellyfin ist per Cloudflare Tunnel oeffentlich erreichbar, der Key hat
Admin-Rechte) - Streams und Bilder laufen deshalb ueber Proxy-Routen im
Dashboard-Server (siehe dashboard/server.py).
"""

from __future__ import annotations

import datetime
import logging
import re
from urllib.parse import urlencode

import requests

from app.config import Config

logger = logging.getLogger(__name__)

TICKS_PER_SECOND = 10_000_000
REQUEST_TIMEOUT_SECONDS = 8
# Ab diesem Anteil gilt ein Film als gesehen (der Abspann laeuft meist noch).
WATCHED_THRESHOLD = 0.92
# Wer nur kurz reinschaut, soll nicht in "Weiterschauen" landen.
MIN_RESUME_SECONDS = 60

# Was der Chromium-Kiosk ohne Transcoding abspielen kann (Direct Play only,
# siehe README). Alles andere wird vor dem Start mit klarer Meldung abgelehnt,
# statt mit schwarzem Bild oder ohne Ton zu "laufen".
PLAYABLE_VIDEO_CODECS = {"h264", "vp8", "vp9", "av1"}
PLAYABLE_AUDIO_CODECS = {"aac", "mp3", "opus", "vorbis", "flac"}

LIST_FIELDS = "PrimaryImageAspectRatio,ProductionYear,ChildCount"
HIDDEN_TYPES = {"Photo", "PhotoAlbum", "Audio", "MusicAlbum", "MusicArtist"}
IMAGE_PROXY_PATH = "/api/jellyfin/image"

# Jellyfin-IDs sind GUIDs (meist ohne Bindestriche). Strikt pruefen, weil die
# IDs in URL-Pfade mit Admin-Key eingesetzt werden.
_ID_RE = re.compile(r"[0-9a-fA-F]{32}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")

_user_cache: dict[str, dict] = {}


class JellyfinError(Exception):
    """Fehler mit fuer die Fernbedienung lesbarer Meldung."""


def is_configured(cfg: Config) -> bool:
    return bool(cfg.secrets.jellyfin_api_key and cfg.jellyfin.username)


def valid_id(value: str | None) -> bool:
    return bool(value and _ID_RE.fullmatch(value))


def auth_headers(cfg: Config) -> dict[str, str]:
    token = cfg.secrets.jellyfin_api_key or ""
    return {
        "Authorization": (
            'MediaBrowser Client="TV-Jarvis", Device="Raspberry Pi", '
            f'DeviceId="tv-jarvis-pi", Version="1.0", Token="{token}"'
        )
    }


def stream_url(cfg: Config, item_id: str) -> str:
    # static=true: Originaldatei ohne Transcoding (Direct Play)
    return f"{cfg.jellyfin.url}/Videos/{item_id}/stream?static=true"


def image_url(cfg: Config, item_id: str, image_type: str, tag: str | None, max_width: int) -> str:
    params: dict[str, str | int] = {"maxWidth": max_width, "quality": 85}
    if tag:
        params["tag"] = tag
    return f"{cfg.jellyfin.url}/Items/{item_id}/Images/{image_type}?{urlencode(params)}"


def _request(cfg: Config, method: str, path: str, **kwargs) -> requests.Response:
    if not is_configured(cfg):
        raise JellyfinError("Jellyfin ist nicht eingerichtet (API-Key oder Benutzer fehlt)")
    try:
        resp = requests.request(
            method,
            f"{cfg.jellyfin.url}{path}",
            headers=auth_headers(cfg),
            timeout=REQUEST_TIMEOUT_SECONDS,
            **kwargs,
        )
    except requests.RequestException as exc:
        raise JellyfinError("Jellyfin ist gerade nicht erreichbar") from exc
    if resp.status_code == 401:
        raise JellyfinError("Jellyfin lehnt den API-Key ab")
    if resp.status_code >= 400:
        raise JellyfinError(f"Jellyfin-Fehler ({resp.status_code})")
    return resp


def _user(cfg: Config) -> dict:
    key = cfg.jellyfin.username.lower()
    if key not in _user_cache:
        users = _request(cfg, "GET", "/Users").json()
        match = next((u for u in users if u.get("Name", "").lower() == key), None)
        if match is None:
            raise JellyfinError(f"Jellyfin-Benutzer '{cfg.jellyfin.username}' nicht gefunden")
        _user_cache[key] = {"id": match["Id"], "name": match["Name"]}
    return _user_cache[key]


def user_id(cfg: Config) -> str:
    return _user(cfg)["id"]


def user_display_name(cfg: Config) -> str:
    return _user(cfg)["name"]


def _seconds(ticks: int | None) -> float:
    return round((ticks or 0) / TICKS_PER_SECOND, 1)


def _image_path(item_id: str, image_type: str, tag: str, max_width: int) -> str:
    query = urlencode({"type": image_type, "tag": tag, "max_width": max_width})
    return f"{IMAGE_PROXY_PATH}/{item_id}?{query}"


def _primary_image(raw: dict) -> tuple[str, str] | None:
    tag = (raw.get("ImageTags") or {}).get("Primary")
    if tag:
        return raw["Id"], tag
    if raw.get("SeriesPrimaryImageTag") and raw.get("SeriesId"):
        return raw["SeriesId"], raw["SeriesPrimaryImageTag"]
    return None


def _backdrop_image(raw: dict) -> tuple[str, str] | None:
    tags = raw.get("BackdropImageTags") or []
    if tags:
        return raw["Id"], tags[0]
    parent_tags = raw.get("ParentBackdropImageTags") or []
    if parent_tags and raw.get("ParentBackdropItemId"):
        return raw["ParentBackdropItemId"], parent_tags[0]
    return None


def _subtitle(item: dict) -> str:
    if item["type"] == "Episode":
        code = ""
        if item["season_number"] is not None and item["episode_number"] is not None:
            code = f"S{item['season_number']:02d} E{item['episode_number']:02d}"
        return " · ".join(part for part in (item["series_name"], code) if part)
    return str(item["year"]) if item["year"] else ""


def _normalize(raw: dict) -> dict:
    user_data = raw.get("UserData") or {}
    primary = _primary_image(raw)
    backdrop = _backdrop_image(raw)
    aspect = raw.get("PrimaryImageAspectRatio")
    item = {
        "id": raw["Id"],
        "name": raw.get("Name") or "",
        "type": raw.get("Type") or "",
        "is_folder": bool(raw.get("IsFolder")),
        "year": raw.get("ProductionYear"),
        "runtime_seconds": _seconds(raw.get("RunTimeTicks")),
        "position_seconds": _seconds(user_data.get("PlaybackPositionTicks")),
        "played": bool(user_data.get("Played")),
        "series_name": raw.get("SeriesName"),
        "season_number": raw.get("ParentIndexNumber"),
        "episode_number": raw.get("IndexNumber"),
        "child_count": raw.get("ChildCount"),
        "wide": bool(aspect and aspect > 1.2),
        "poster": _image_path(primary[0], "Primary", primary[1], 480) if primary else None,
        "backdrop": _image_path(backdrop[0], "Backdrop", backdrop[1], 1280) if backdrop else None,
    }
    item["subtitle"] = _subtitle(item)
    return item


def _playback_issue(raw: dict) -> str | None:
    sources = raw.get("MediaSources") or []
    streams = (sources[0].get("MediaStreams") if sources else None) or raw.get("MediaStreams") or []
    video = next((s for s in streams if s.get("Type") == "Video"), None)
    audio_streams = [s for s in streams if s.get("Type") == "Audio"]
    audio = next((s for s in audio_streams if s.get("IsDefault")), audio_streams[0] if audio_streams else None)
    if video and (video.get("Codec") or "").lower() not in PLAYABLE_VIDEO_CODECS:
        codec = (video.get("Codec") or "unbekannt").upper()
        return f"Das Videoformat {codec} kann der Fernseher nicht direkt abspielen."
    if audio and (audio.get("Codec") or "").lower() not in PLAYABLE_AUDIO_CODECS:
        codec = (audio.get("Codec") or "unbekannt").upper()
        return f"Das Tonformat {codec} kann der Fernseher nicht direkt abspielen."
    return None


def libraries(cfg: Config) -> list[dict]:
    data = _request(cfg, "GET", "/UserViews", params={"userId": user_id(cfg)}).json()
    return [
        {"id": view["Id"], "name": view.get("Name", ""), "collection_type": view.get("CollectionType")}
        for view in data.get("Items", [])
    ]


def browse(cfg: Config, parent_id: str | None, search: str | None) -> list[dict]:
    params: dict[str, str | int] = {
        "userId": user_id(cfg),
        "fields": LIST_FIELDS,
        "enableImageTypes": "Primary,Backdrop,Thumb",
        "imageTypeLimit": 1,
        "limit": 300,
    }
    if search:
        params.update(searchTerm=search, recursive="true", includeItemTypes="Movie,Series,Episode,Video")
    else:
        # Staffeln/Folgen nach Nummer, alles andere (Filme) alphabetisch
        params.update(parentId=parent_id or "", sortBy="ParentIndexNumber,IndexNumber,SortName", sortOrder="Ascending")
    data = _request(cfg, "GET", "/Items", params=params).json()
    return [_normalize(raw) for raw in data.get("Items", []) if raw.get("Type") not in HIDDEN_TYPES]


def resume(cfg: Config) -> list[dict]:
    data = _request(
        cfg,
        "GET",
        "/UserItems/Resume",
        params={
            "userId": user_id(cfg),
            "fields": LIST_FIELDS,
            "mediaTypes": "Video",
            "enableImageTypes": "Primary,Backdrop,Thumb",
            "imageTypeLimit": 1,
            "limit": 12,
        },
    ).json()
    return [_normalize(raw) for raw in data.get("Items", [])]


def item(cfg: Config, item_id: str) -> dict:
    raw = _request(cfg, "GET", f"/Items/{item_id}", params={"userId": user_id(cfg)}).json()
    result = _normalize(raw)
    result.update(
        overview=raw.get("Overview") or "",
        genres=(raw.get("Genres") or [])[:3],
        official_rating=raw.get("OfficialRating"),
        community_rating=raw.get("CommunityRating"),
        playback_issue=None if result["is_folder"] else _playback_issue(raw),
    )
    return result


def save_progress(cfg: Config, item_id: str, position_seconds: float, duration_seconds: float) -> None:
    uid = user_id(cfg)
    finished = duration_seconds > 0 and position_seconds >= duration_seconds * WATCHED_THRESHOLD
    if finished:
        _request(cfg, "POST", f"/UserPlayedItems/{item_id}", params={"userId": uid})
    resume_at = 0 if finished or position_seconds < MIN_RESUME_SECONDS else position_seconds
    body = {
        "PlaybackPositionTicks": int(resume_at * TICKS_PER_SECOND),
        "LastPlayedDate": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }
    _request(cfg, "POST", f"/UserItems/{item_id}/UserData", params={"userId": uid}, json=body)
    logger.info("Jellyfin-Position gespeichert: %s bei %.0fs (gesehen: %s)", item_id, resume_at, finished)
