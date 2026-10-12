"""Twitch: Lieblings-Streamer, wer gerade live ist, und der Stream fuer den
Kiosk.

Ohne Twitch-Konto und ohne API-Schluessel: Status und Abspiel-Token kommen
ueber die GraphQL-Schnittstelle, die auch die Twitch-Webseite nutzt (mit deren
oeffentlicher Client-ID - so machen es auch streamlink und yt-dlp). Der Kiosk
spielt den HLS-Stream selbst mit hls.js ab, ganz ohne Chat und Overlays.

Die Uebersicht (master.m3u8) holt der Server ueber /api/twitch/playlist, weil
usher.ttvnw.net keine CORS-Header schickt. Die einzelnen Qualitaeten und
Videostuecke darf der Kiosk-Browser dann direkt laden.
"""

from __future__ import annotations

import json
import random
import re
import threading
import time

import requests

from app.config import ROOT_DIR

CHANNELS_FILE = ROOT_DIR / "data" / "twitch.json"
GQL_URL = "https://gql.twitch.tv/gql"
# Oeffentliche Client-ID der Twitch-Webseite
CLIENT_ID = "kimne78kx3ncx6brgo4mv6wki5h1ko"
PLAYBACK_TOKEN_HASH = "0828119ded1c13477966434e15800ff57ddacf13ba1911c129dc2200705b0712"
USHER_URL = "https://usher.ttvnw.net/api/channel/hls/{login}.m3u8"
STATUS_CACHE_SECONDS = 30
MAX_CHANNELS = 50
TIMEOUT = 10

_LOGIN_RE = re.compile(r"^[a-z0-9_]{2,25}$")
_lock = threading.Lock()
_cache: dict = {"at": 0.0, "logins": (), "data": []}

_STATUS_QUERY = """
query($logins: [String!]) {
  users(logins: $logins) {
    login
    displayName
    profileImageURL(width: 150)
    stream {
      title
      viewersCount
      createdAt
      game { displayName }
      previewImageURL(width: 640, height: 360)
    }
  }
}
"""


class TwitchError(RuntimeError):
    pass


def normalize_login(raw: str) -> str:
    """"twitch.tv/Papaplatte", "@papaplatte", "Papaplatte" -> "papaplatte"."""
    text = str(raw or "").strip()
    match = re.search(r"twitch\.tv/([A-Za-z0-9_]+)", text)
    if match:
        text = match.group(1)
    return text.lstrip("@").strip().lower()


def load_channels() -> list[str]:
    try:
        data = json.loads(CHANNELS_FILE.read_text(encoding="utf-8"))
        return [c for c in data.get("channels", []) if isinstance(c, str)]
    except (OSError, ValueError):
        return []


def _save_channels(channels: list[str]) -> None:
    CHANNELS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CHANNELS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps({"channels": channels}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CHANNELS_FILE)
    _cache["at"] = 0.0


def _gql(payload: dict) -> dict:
    try:
        resp = requests.post(GQL_URL, json=payload, headers={"Client-ID": CLIENT_ID}, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as exc:
        raise TwitchError("Twitch ist gerade nicht erreichbar") from exc
    if data.get("errors"):
        raise TwitchError("Twitch hat die Anfrage abgelehnt")
    return data.get("data") or {}


def _fetch_users(logins: list[str]) -> list[dict]:
    users: list[dict] = []
    # Twitch nimmt hoechstens 100 Namen pro Anfrage
    for start in range(0, len(logins), 100):
        data = _gql({"query": _STATUS_QUERY, "variables": {"logins": logins[start:start + 100]}})
        users.extend(u for u in data.get("users") or [] if u)
    return users


def _public(user: dict) -> dict:
    stream = user.get("stream")
    return {
        "login": user["login"],
        "display_name": user.get("displayName") or user["login"],
        "avatar": user.get("profileImageURL"),
        "live": bool(stream),
        "title": (stream or {}).get("title") or "",
        "game": ((stream or {}).get("game") or {}).get("displayName") or "",
        "viewers": (stream or {}).get("viewersCount") or 0,
        "started_at": (stream or {}).get("createdAt"),
        # Vorschaubild aendert sich laufend - Zeitstempel gegen den Browser-Cache
        "thumbnail": f"{stream['previewImageURL']}?t={int(time.time() // 60)}" if stream and stream.get("previewImageURL") else None,
    }


def channel_status(force: bool = False) -> list[dict]:
    """Alle gespeicherten Kanaele mit Live-Status, live zuerst (nach Zuschauern)."""
    channels = load_channels()
    if not channels:
        return []
    with _lock:
        fresh = time.monotonic() - _cache["at"] < STATUS_CACHE_SECONDS
        if not force and fresh and _cache["logins"] == tuple(channels):
            return _cache["data"]
        found = {u["login"]: _public(u) for u in _fetch_users(channels)}
        result = []
        for login in channels:
            # Umbenannte/gesperrte Kanaele trotzdem zeigen, damit man sie loeschen kann
            result.append(found.get(login) or {
                "login": login, "display_name": login, "avatar": None, "live": False,
                "title": "", "game": "", "viewers": 0, "started_at": None, "thumbnail": None,
            })
        result.sort(key=lambda c: (not c["live"], -c["viewers"]))
        _cache.update(at=time.monotonic(), logins=tuple(channels), data=result)
        return result


def add_channel(raw: str) -> str:
    login = normalize_login(raw)
    if not _LOGIN_RE.match(login):
        raise ValueError("Das sieht nicht wie ein Twitch-Name aus")
    with _lock:
        channels = load_channels()
        if login in channels:
            return login
        if len(channels) >= MAX_CHANNELS:
            raise ValueError(f"Mehr als {MAX_CHANNELS} Streamer gehen nicht")
    users = _fetch_users([login])
    if not users:
        raise ValueError(f"„{login}“ gibt es auf Twitch nicht")
    with _lock:
        channels = load_channels()
        if login not in channels:
            channels.append(login)
            _save_channels(channels)
    return login


def remove_channel(login: str) -> None:
    login = normalize_login(login)
    with _lock:
        channels = load_channels()
        if login in channels:
            channels.remove(login)
            _save_channels(channels)


def master_playlist(login: str) -> str:
    """HLS-Uebersicht aller Qualitaeten eines laufenden Streams."""
    login = normalize_login(login)
    if not _LOGIN_RE.match(login):
        raise TwitchError("Ungueltiger Kanal")
    data = _gql({
        "operationName": "PlaybackAccessToken",
        "extensions": {"persistedQuery": {"version": 1, "sha256Hash": PLAYBACK_TOKEN_HASH}},
        "variables": {"isLive": True, "login": login, "isVod": False, "vodID": "", "playerType": "embed"},
    })
    token = data.get("streamPlaybackAccessToken")
    if not token:
        raise TwitchError(f"{login} ist gerade nicht live")
    try:
        resp = requests.get(
            USHER_URL.format(login=login),
            params={
                "sig": token["signature"],
                "token": token["value"],
                "allow_source": "true",
                "fast_bread": "true",
                "p": str(random.randint(100000, 999999)),
                "player_backend": "mediaplayer",
                "playlist_include_framerate": "true",
                "supported_codecs": "avc1",
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise TwitchError("Twitch ist gerade nicht erreichbar") from exc
    if resp.status_code == 404:
        raise TwitchError(f"{login} ist gerade nicht live")
    if resp.status_code != 200 or "#EXTM3U" not in resp.text:
        raise TwitchError("Der Stream ließ sich nicht laden")
    return resp.text
