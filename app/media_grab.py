"""Videos von Webseiten auf die Jellyfin-Platte laden (wie die Browser-
Erweiterung "Video DownloadHelper", aber ueber das schnelle LAN des Pi).

1. find:     Seite pruefen. Kennt yt-dlp die Seite, reicht das. Sonst wird sie
             in einem unsichtbaren Chromium geoeffnet, der Player angeklickt
             (viele Player laden erst nach einem Klick) und mitgeschnitten,
             welche Videodaten die Seite laedt (HLS, DASH, MP4).
2. download: das gewaehlte Video mit yt-dlp in eine versteckte Datei im
             Zielordner laden, umbenennen wie beim Upload (media_upload) und
             Jellyfin neu einlesen lassen.

Nur fuer Videos, die man speichern darf - kopiergeschuetzte Streams (DRM)
lassen sich so ohnehin nicht laden.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

import httpx
from websockets.asyncio.client import connect

from app import jellyfin_client, media_upload
from app.config import ROOT_DIR, Config
from app.dashboard import kiosk

logger = logging.getLogger(__name__)

PROFILE_DIR = ROOT_DIR / "data" / "grab-profile"
DEBUG_PORT = 9225
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/152.0.0.0 Safari/537.36"
)
SEARCH_SECONDS = 50
CLICK_ATTEMPTS = 6
YTDLP_PROBE_SECONDS = 45
MAX_JOBS = 30

_HLS = re.compile(r"\.m3u8(\?|$)", re.I)
_DASH = re.compile(r"\.mpd(\?|$)", re.I)
_FILE = re.compile(r"\.(mp4|m4v|webm|mkv|mov)(\?|$)", re.I)
_SEGMENT = re.compile(r"(seg|frag|chunk|init)[-_]?\d|\.m4s(\?|$)|\.ts(\?|$)|range=", re.I)
_PROGRESS = re.compile(r"^jarvis:(?P<pct>[\d.]+|NA)\|(?P<done>\d+|NA)\|(?P<total>[\d.]+|NA)\|(?P<speed>[\d.]+|NA)\|(?P<eta>\d+|NA)")

jobs: dict[str, dict] = {}
_search_lock = asyncio.Lock()
_download_lock = asyncio.Lock()
_processes: dict[str, subprocess.Popen] = {}


class GrabError(RuntimeError):
    pass


def _ytdlp() -> str:
    local = Path(sys.executable).parent / "yt-dlp"
    return str(local) if local.exists() else (shutil.which("yt-dlp") or "yt-dlp")


def public_jobs() -> list[dict]:
    keys = ("id", "url", "status", "title", "candidates", "progress", "result", "error", "created")
    return sorted(({k: j.get(k) for k in keys} for j in jobs.values()), key=lambda j: j["created"], reverse=True)


# ---------- 1. Suchen ----------

def _probe_ytdlp(url: str) -> dict | None:
    """Kennt yt-dlp die Seite (oder steht dort ein normales <video>)?"""
    try:
        result = subprocess.run(
            [_ytdlp(), "-J", "--no-playlist", "--no-warnings", url],
            capture_output=True, text=True, timeout=YTDLP_PROBE_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0:
        return None
    try:
        info = json.loads(result.stdout)
    except ValueError:
        return None
    if info.get("_type") == "playlist" or not (info.get("formats") or info.get("url")):
        return None
    heights = [f.get("height") or 0 for f in info.get("formats") or []]
    return {
        "title": info.get("title") or "",
        "generic": info.get("extractor_key") == "Generic",
        "candidate": {
            "kind": "seite",
            "url": url,
            "headers": {},
            "height": max(heights) if heights else info.get("height"),
            "size": info.get("filesize") or info.get("filesize_approx"),
            "duration": info.get("duration"),
        },
    }


def _classify(url: str, mime: str) -> str | None:
    mime = (mime or "").lower()
    if "mpegurl" in mime or _HLS.search(url):
        return "hls"
    if "dash+xml" in mime or _DASH.search(url):
        return "dash"
    if _SEGMENT.search(url):
        return None
    if mime.startswith("video/") or _FILE.search(url):
        return "datei"
    return None


def _launch_headless() -> subprocess.Popen:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (PROFILE_DIR / name).unlink(missing_ok=True)
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return subprocess.Popen(
        [
            kiosk._chromium_binary(),
            "--headless=new",
            f"--user-data-dir={PROFILE_DIR}",
            f"--remote-debugging-port={DEBUG_PORT}",
            "--remote-debugging-address=127.0.0.1",
            "--password-store=basic",
            "--no-first-run",
            "--mute-audio",
            "--autoplay-policy=no-user-gesture-required",
            "--window-size=1280,720",
            f"--user-agent={USER_AGENT}",
            "about:blank",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


_LARGEST_PLAYER = """
(() => {
  const els = [...document.querySelectorAll('video, iframe, object, embed, [class*=player], [id*=player]')];
  let best = null, area = 0;
  for (const el of els) {
    const r = el.getBoundingClientRect();
    const a = Math.max(0, Math.min(r.right, innerWidth) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, innerHeight) - Math.max(r.top, 0));
    if (a > area && r.width > 160 && r.height > 90) { area = a; best = r; }
  }
  if (!best) return null;
  return { x: best.left + best.width / 2, y: best.top + best.height / 2, top: best.top };
})()
"""


async def _sniff(url: str) -> dict:
    """Seite unsichtbar oeffnen, Player anklicken, Videodaten mitschneiden."""
    found: dict[str, dict] = {}
    request_headers: dict[str, dict] = {}
    proc = await asyncio.to_thread(_launch_headless)
    try:
        version = None
        async with httpx.AsyncClient(timeout=3) as client:
            for _ in range(40):
                with contextlib.suppress(httpx.HTTPError, ValueError):
                    version = (await client.get(f"http://127.0.0.1:{DEBUG_PORT}/json/version")).json()
                    break
                await asyncio.sleep(0.25)
        if not version:
            raise GrabError("Der unsichtbare Browser startet nicht")

        async with connect(version["webSocketDebuggerUrl"], max_size=None) as ws:
            counter = 0
            pending: dict[int, asyncio.Future] = {}
            page_session = None
            main_url = url
            popups: list[str] = []

            async def call(method: str, params: dict | None = None, session: str | None = None, timeout: float = 15) -> dict:
                nonlocal counter
                counter += 1
                msg = {"id": counter, "method": method, "params": params or {}}
                if session:
                    msg["sessionId"] = session
                fut = asyncio.get_running_loop().create_future()
                pending[counter] = fut
                await ws.send(json.dumps(msg))
                return await asyncio.wait_for(fut, timeout)

            async def prepare(session: str) -> None:
                # Jede Ebene (auch der Player im iframe) wird mitgeschnitten
                with contextlib.suppress(Exception):
                    await call("Network.enable", {}, session)
                    await call("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True}, session)

            async def reader() -> None:
                async for raw in ws:
                    msg = json.loads(raw)
                    if "id" in msg:
                        fut = pending.pop(msg["id"], None)
                        if fut and not fut.done():
                            fut.set_result(msg.get("result", {}))
                        continue
                    method = msg.get("method")
                    params = msg.get("params", {})
                    if method == "Target.attachedToTarget":
                        asyncio.create_task(prepare(params["sessionId"]))
                    elif method == "Target.targetCreated":
                        info = params.get("targetInfo", {})
                        # Werbe-Popups: neue Seiten, die die Seite selbst oeffnet
                        if info.get("type") == "page" and info.get("openerId"):
                            popups.append(info["targetId"])
                    elif method == "Network.requestWillBeSent":
                        req = params.get("request", {})
                        request_headers[req.get("url", "")] = req.get("headers", {})
                    elif method == "Network.responseReceived":
                        resp = params.get("response", {})
                        media_url = resp.get("url", "")
                        kind = _classify(media_url, resp.get("mimeType", ""))
                        if kind and media_url.startswith("http") and media_url not in found:
                            size = (resp.get("headers") or {}).get("content-length") or (resp.get("headers") or {}).get("Content-Length")
                            found[media_url] = {
                                "kind": kind,
                                "url": media_url,
                                "headers": request_headers.get(media_url, {}),
                                "size": int(size) if str(size or "").isdigit() else None,
                                "order": len(found),
                            }

            read_task = asyncio.create_task(reader())
            try:
                await call("Target.setDiscoverTargets", {"discover": True})
                target = (await call("Target.createTarget", {"url": "about:blank"}))["targetId"]
                page_session = (await call("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
                await call("Page.enable", {}, page_session)
                await prepare(page_session)
                await call("Network.setUserAgentOverride", {"userAgent": USER_AGENT, "acceptLanguage": "de-DE,de"}, page_session)
                await call("Page.navigate", {"url": url}, page_session)

                deadline = time.monotonic() + SEARCH_SECONDS
                await asyncio.sleep(6)
                title = ""
                attempts = 0
                while time.monotonic() < deadline:
                    for popup in popups:
                        with contextlib.suppress(Exception):
                            await call("Target.closeTarget", {"targetId": popup})
                    popups.clear()
                    state = {"u": main_url, "t": ""}
                    with contextlib.suppress(Exception):
                        state = (await call("Runtime.evaluate", {"expression": "({u: location.href, t: document.title})", "returnByValue": True}, page_session))["result"]["value"]
                        title = title or state["t"]
                    # Erst bei einem Stream aufhoeren: einzelne MP4s sind oft
                    # Werbung, die vor dem eigentlichen Video laeuft
                    if any(c["kind"] in ("hls", "dash") for c in found.values()):
                        await asyncio.sleep(2)
                        break
                    # Ein Klick hat auf eine Werbeseite gefuehrt: zurueck
                    if urlparse(state["u"]).netloc != urlparse(main_url).netloc:
                        with contextlib.suppress(Exception):
                            await call("Page.navigate", {"url": main_url}, page_session)
                        await asyncio.sleep(5)
                        continue
                    if attempts < CLICK_ATTEMPTS:
                        attempts += 1
                        with contextlib.suppress(Exception):
                            spot = (await call("Runtime.evaluate", {"expression": _LARGEST_PLAYER, "returnByValue": True}, page_session))["result"].get("value")
                            if spot and (spot["top"] < 0 or spot["top"] > 600):
                                await call("Runtime.evaluate", {"expression": f"window.scrollBy(0, {int(spot['top']) - 80})"}, page_session)
                                await asyncio.sleep(0.6)
                                spot = (await call("Runtime.evaluate", {"expression": _LARGEST_PLAYER, "returnByValue": True}, page_session))["result"].get("value")
                            if spot:
                                for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
                                    await call("Input.dispatchMouseEvent", {"type": kind, "x": spot["x"], "y": spot["y"], "button": "left", "clickCount": 1}, page_session)
                    await asyncio.sleep(4)
            finally:
                read_task.cancel()
    finally:
        proc.terminate()
        with contextlib.suppress(subprocess.TimeoutExpired):
            await asyncio.to_thread(proc.wait, 10)

    # Beste zuerst: Streams vor Einzeldateien. Bei Streams der zuerst
    # geladene (die Uebersicht mit allen Qualitaeten, yt-dlp nimmt daraus die
    # beste), bei Dateien die groesste.
    rank = {"hls": 0, "dash": 1, "datei": 2}
    candidates = sorted(
        found.values(),
        key=lambda c: (rank[c["kind"]], c["order"] if c["kind"] != "datei" else -(c["size"] or 0)),
    )
    return {"title": title, "candidates": candidates[:8]}


async def _search(job: dict) -> None:
    async with _search_lock:
        try:
            probe = await asyncio.to_thread(_probe_ytdlp, job["url"])
            # Bekannte Seite oder direkter Link auf eine Videodatei: fertig
            if probe and (not probe["generic"] or _FILE.search(urlparse(job["url"]).path)):
                job.update(title=probe["title"], candidates=[probe["candidate"]], status="auswahl")
                return
            result = await _sniff(job["url"])
            candidates = result["candidates"]
            if probe:
                # yt-dlp hat auf der unbekannten Seite irgendein Video gefunden -
                # als weitere Wahl, der Mitschnitt kommt zuerst
                candidates = candidates + [probe["candidate"]]
            if not candidates:
                raise GrabError("Auf der Seite lief kein Video an – evtl. ist es kopiergeschützt")
            job.update(title=result["title"] or (probe or {}).get("title", ""), candidates=candidates, status="auswahl")
        except GrabError as exc:
            job.update(status="fehler", error=str(exc))
        except Exception as exc:  # noqa: BLE001
            logger.exception("Videosuche fehlgeschlagen")
            job.update(status="fehler", error=f"Suche fehlgeschlagen ({exc.__class__.__name__})")


def add(url: str) -> dict:
    url = (url or "").strip()
    if not re.match(r"^https?://", url):
        raise GrabError("Bitte einen Link mit http(s):// einfügen")
    for old in sorted(jobs.values(), key=lambda j: j["created"])[: max(0, len(jobs) - MAX_JOBS + 1)]:
        if old["status"] in ("fertig", "fehler", "abgebrochen"):
            jobs.pop(old["id"], None)
    job = {"id": uuid.uuid4().hex[:12], "url": url, "status": "suche", "title": "", "candidates": [], "progress": None, "result": None, "error": None, "created": time.time()}
    jobs[job["id"]] = job
    asyncio.create_task(_search(job))
    return job


# ---------- 2. Laden ----------

def _target_path(cfg: Config, body: dict) -> tuple[dict, Path]:
    target = next((t for t in media_upload.targets(cfg) if t["id"] == body.get("target")), None)
    if target is None:
        raise GrabError("Bitte „Film“ oder „Serie“ wählen")
    if target["kind"] == "tvshows":
        series = media_upload._clean(body.get("series"))
        season = int(body.get("season") or 1)
        episode = int(body.get("episode") or 1)
        filename = f"{series} S{season:02d}E{episode:02d}.mp4"
    else:
        filename = "video.mp4"
    try:
        final = media_upload._final_path(target, body, filename)
    except media_upload.UploadError as exc:
        raise GrabError(str(exc)) from exc
    return target, final


def _run_download(job: dict, candidate: dict, part_base: Path) -> Path:
    headers = {k.lower(): v for k, v in (candidate.get("headers") or {}).items()}
    args = [
        _ytdlp(),
        "--newline", "--no-playlist", "--no-warnings",
        "--concurrent-fragments", "4",
        "--merge-output-format", "mp4",
        "--progress-template", "download:jarvis:%(progress._percent)s|%(progress.downloaded_bytes)s|%(progress.total_bytes_estimate)s|%(progress.speed)s|%(progress.eta)s",
        "-o", f"{part_base}.%(ext)s",
        "--user-agent", headers.get("user-agent", USER_AGENT),
    ]
    if headers.get("referer"):
        args += ["--referer", headers["referer"]]
    if headers.get("origin"):
        args += ["--add-header", f"Origin:{headers['origin']}"]
    args.append(candidate["url"])
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    _processes[job["id"]] = proc
    tail: list[str] = []
    assert proc.stdout is not None
    for line in proc.stdout:
        match = _PROGRESS.match(line.strip())
        if match:
            num = lambda k: float(match[k]) if match[k] not in ("NA", None) else None  # noqa: E731
            job["progress"] = {"percent": num("pct"), "bytes": num("done"), "total": num("total"), "speed": num("speed"), "eta": num("eta")}
        else:
            tail = (tail + [line.strip()])[-5:]
    proc.wait()
    _processes.pop(job["id"], None)
    if job["status"] == "abgebrochen":
        raise GrabError("Abgebrochen")
    if proc.returncode != 0:
        logger.warning("yt-dlp: %s", " | ".join(tail))
        raise GrabError("Das Video ließ sich nicht laden – der Link ist evtl. abgelaufen, bitte neu suchen")
    # Zwischendateien von yt-dlp (.part, .ytdl, .f137.mp4 vor dem Zusammenfuegen) auslassen
    done = [
        p for p in part_base.parent.glob(part_base.name + ".*")
        if not p.name.endswith((".part", ".ytdl")) and not re.search(r"\.f\d+\.", p.name)
    ]
    if not done:
        raise GrabError("Download fertig, aber keine Datei gefunden")
    return max(done, key=lambda p: p.stat().st_size)


def _cleanup(part_base: Path) -> None:
    for leftover in part_base.parent.glob(part_base.name + "*"):
        with contextlib.suppress(OSError):
            leftover.unlink()


async def download(cfg: Config, job_id: str, body: dict) -> dict:
    job = jobs.get(job_id)
    if not job or job["status"] not in ("auswahl", "fehler"):
        raise GrabError("Dieser Eintrag kann gerade nicht geladen werden")
    index = int(body.get("candidate") or 0)
    if not 0 <= index < len(job["candidates"]):
        raise GrabError("Bitte ein Video auswählen")
    target, final = await asyncio.to_thread(_target_path, cfg, body)
    if final.exists():
        raise GrabError(f"„{final.name}“ gibt es in {target['name']} schon")
    job.update(status="wartet", error=None, progress=None)
    asyncio.create_task(_download(cfg, job, job["candidates"][index], target, final))
    return job


async def _download(cfg: Config, job: dict, candidate: dict, target: dict, final: Path) -> None:
    async with _download_lock:
        if job["status"] == "abgebrochen":
            return
        job["status"] = "laedt"
        final.parent.mkdir(parents=True, exist_ok=True)
        # versteckt: Jellyfin ignoriert die halbe Datei beim Scannen
        part_base = final.parent / f".jarvis-grab-{job['id']}"
        try:
            path = await asyncio.to_thread(_run_download, job, candidate, part_base)
            final = final.with_suffix(path.suffix)
            if final.exists():
                raise GrabError(f"„{final.name}“ gibt es schon")
            path.rename(final)
            _cleanup(part_base)
            with contextlib.suppress(jellyfin_client.JellyfinError):
                await asyncio.to_thread(jellyfin_client._request, cfg, "POST", f"/Items/{target['id']}/Refresh", params={"Recursive": "true"})
            warning = await asyncio.to_thread(media_upload._probe, final)
            job.update(status="fertig", result={"name": final.name, "warning": warning})
            logger.info("Video geladen: %s", final)
        except GrabError as exc:
            _cleanup(part_base)
            if job["status"] != "abgebrochen":
                job.update(status="fehler", error=str(exc))
        except OSError as exc:
            _cleanup(part_base)
            logger.warning("Video-Download: Dateifehler %s", exc)
            job.update(status="fehler", error="Schreiben auf die Platte fehlgeschlagen – ist sie eingehängt?")


def remove(job_id: str) -> None:
    job = jobs.get(job_id)
    if not job:
        return
    if job["status"] in ("laedt", "wartet"):
        job["status"] = "abgebrochen"
        proc = _processes.get(job_id)
        if proc and proc.poll() is None:
            proc.terminate()
    else:
        jobs.pop(job_id, None)
