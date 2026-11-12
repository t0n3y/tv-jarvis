"""YouTube-Abos: die neuesten Videos der abonnierten Kanaele fuer die
Fernbedienung.

Angemeldet wird nicht hier, sondern im TV-Browser (App "Browser" in der
Fernbedienung): yt-dlp liest dessen Cookies direkt aus dem Profil
(data/tvbrowser-profile). Ein Fenster auf dem Fernseher braucht es dafuer
nicht.

Ist man dort nur bei Google, aber (noch) nicht bei YouTube angemeldet, holt
refresh_login() die YouTube-Anmeldung nach - in einem unsichtbaren
Hintergrund-Tab des TV-Browsers bzw. in einem kurz gestarteten
Headless-Chromium. Ein Passwort wird dabei nie eingegeben.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
from websockets.asyncio.client import connect

from app import tv_browser
from app.dashboard import kiosk

logger = logging.getLogger(__name__)

FEED_URL = "https://www.youtube.com/feed/subscriptions"
YOUTUBE_LOGIN_URL = (
    "https://accounts.google.com/ServiceLogin?service=youtube&passive=true&hl=de"
    "&continue=https%3A%2F%2Fwww.youtube.com%2Fsignin%3Faction_handle_signin%3Dtrue%26app%3Ddesktop%26hl%3Dde%26next%3D%252F"
)
LIMIT = 50
CACHE_SECONDS = 5 * 60
YTDLP_TIMEOUT_SECONDS = 90
# So lange braucht Chromium, bis neue Cookies auf der Platte stehen
COOKIE_FLUSH_SECONDS = 35

_cache: dict = {"at": 0.0, "videos": []}
_lock = asyncio.Lock()


class SubscriptionError(RuntimeError):
    pass


def _ytdlp() -> str:
    local = Path(sys.executable).parent / "yt-dlp"
    return str(local) if local.exists() else (shutil.which("yt-dlp") or "yt-dlp")


def _fetch() -> list[dict]:
    try:
        result = subprocess.run(
            [
                _ytdlp(),
                "--cookies-from-browser", f"chromium:{tv_browser.PROFILE_DIR}",
                "--flat-playlist",
                "--playlist-items", f"1-{LIMIT}",
                "-J",
                FEED_URL,
            ],
            capture_output=True,
            text=True,
            timeout=YTDLP_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise SubscriptionError("YouTube antwortet gerade nicht") from exc
    if result.returncode != 0:
        logger.warning("yt-dlp Abos fehlgeschlagen: %s", result.stderr[-400:])
        raise SubscriptionError("Die Abos ließen sich nicht laden")
    try:
        entries = json.loads(result.stdout).get("entries") or []
    except ValueError as exc:
        raise SubscriptionError("Unerwartete Antwort von YouTube") from exc
    videos = []
    for e in entries:
        video_id = e.get("id")
        if not video_id or len(video_id) != 11:
            continue
        videos.append({
            "id": video_id,
            "title": e.get("title") or "",
            "channel": e.get("channel") or e.get("uploader") or "",
            "duration": e.get("duration"),
            "timestamp": e.get("timestamp"),
            "live": e.get("live_status") in ("is_live", "is_upcoming"),
            "thumbnail": f"https://i.ytimg.com/vi/{video_id}/mqdefault.jpg",
        })
    return videos


# ---------- YouTube-Anmeldung aus dem Google-Konto nachholen ----------

async def _login_in_background_tab() -> None:
    """TV-Browser laeuft: YouTube-Anmeldung in einem Hintergrund-Tab, der
    nicht sichtbar wird und danach wieder zugeht."""
    async with httpx.AsyncClient(timeout=5) as client:
        version = (await client.get(f"http://127.0.0.1:{tv_browser.DEBUG_PORT}/json/version")).json()
    async with connect(version["webSocketDebuggerUrl"], max_size=None) as ws:
        counter = 0

        async def call(method: str, params: dict | None = None) -> dict:
            nonlocal counter
            counter += 1
            my_id = counter
            await ws.send(json.dumps({"id": my_id, "method": method, "params": params or {}}))
            while True:
                msg = json.loads(await asyncio.wait_for(ws.recv(), 20))
                if msg.get("id") == my_id:
                    return msg.get("result", {})

        target = (await call("Target.createTarget", {"url": YOUTUBE_LOGIN_URL, "background": True}))["targetId"]
        try:
            await asyncio.sleep(15)
        finally:
            await call("Target.closeTarget", {"targetId": target})


def _login_headless() -> None:
    """TV-Browser ist zu: kurz unsichtbar mit demselben Profil anmelden.
    Beim Beenden schreibt Chromium die Cookies sofort auf die Platte."""
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (tv_browser.PROFILE_DIR / name).unlink(missing_ok=True)
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    proc = subprocess.Popen(
        [
            kiosk._chromium_binary(),
            "--headless=new",
            f"--user-data-dir={tv_browser.PROFILE_DIR}",
            "--password-store=basic",
            "--no-first-run",
            "--disable-gpu",
            YOUTUBE_LOGIN_URL,
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(20)
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=10)


async def refresh_login() -> None:
    if tv_browser.is_running():
        await _login_in_background_tab()
        await asyncio.sleep(COOKIE_FLUSH_SECONDS)
    else:
        await asyncio.to_thread(_login_headless)


# ---------- Oeffentlich ----------

async def videos(force: bool = False) -> list[dict]:
    async with _lock:
        if not force and _cache["videos"] and time.monotonic() - _cache["at"] < CACHE_SECONDS:
            return _cache["videos"]
        result = await asyncio.to_thread(_fetch)
        if not result:
            # Bei Google angemeldet, aber nicht bei YouTube: einmal nachholen
            logger.info("Abo-Feed leer - hole die YouTube-Anmeldung nach")
            with contextlib.suppress(Exception):
                await refresh_login()
            result = await asyncio.to_thread(_fetch)
        if not result:
            raise SubscriptionError("Keine Abo-Videos – ist im Browser der Fernbedienung ein Google-Konto angemeldet?")
        _cache.update(at=time.monotonic(), videos=result)
        return result
