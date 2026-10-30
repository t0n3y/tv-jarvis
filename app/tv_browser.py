"""TV-Browser: ein zweites Chromium-Fenster auf dem Fernseher, das die
Fernbedienung wie einen normalen Browser bedient (Seiten oeffnen, antippen,
scrollen, tippen) - und in dem Sprachschach auf chess.com laeuft.

Es liegt ueber dem Kiosk und hat ein eigenes Profil (data/tvbrowser-profile):
Logins wie chess.com bleiben dort erhalten. Gesteuert wird es ueber das
Chrome-DevTools-Protokoll (CDP) auf 127.0.0.1:9223 - nur vom Pi selbst
erreichbar. Schliesst man es, ist wieder der Kiosk zu sehen.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import signal
import subprocess
import time
from typing import Awaitable, Callable

import httpx
from websockets.asyncio.client import connect

from app.config import ROOT_DIR, Config
from app.dashboard import kiosk

logger = logging.getLogger(__name__)

PID_FILE = ROOT_DIR / "data" / "tvbrowser.pid"
PROFILE_DIR = ROOT_DIR / "data" / "tvbrowser-profile"
DEBUG_PORT = 9223
HOME_URL = "https://www.google.de/"
CONNECT_TIMEOUT_SECONDS = 25
SCREENCAST = {"format": "jpeg", "quality": 55, "maxWidth": 1280, "maxHeight": 720, "everyNthFrame": 1}
# Chromium schickt Bilder nur bei Aenderungen (und bei ausgeschaltetem
# Fernseher womoeglich gar nicht) - dann selbst ein Bildschirmfoto holen
SNAPSHOT_AFTER_SECONDS = 1.5

# Laeuft vor jeder Seite: Links und Popups im selben Fenster oeffnen (ein
# Kiosk-Fenster hat keine Tabs) und die Bruecke fuer Sprachschach bereitstellen.
PREAMBLE = r"""
(() => {
  if (window.__jarvisChess) return;
  document.addEventListener('click', (e) => {
    const a = e.target && e.target.closest && e.target.closest('a[target]');
    if (a && a.target !== '_self') a.target = '_self';
  }, true);
  window.open = (url) => { if (url) location.href = url; return null; };
  const send = (obj) => { try { window.jarvisBridge(JSON.stringify(obj)); } catch (e) {} };
  let n = 0;
  const wartet = {};
  window.__jarvisChess = {
    sprich(text, mal) {
      const id = ++n;
      return new Promise((resolve) => {
        wartet[id] = resolve;
        send({ type: 'sprich', id, text, mal: mal || 1 });
        // Falls Jarvis nicht antwortet: nicht ewig haengen bleiben
        setTimeout(() => { if (wartet[id]) { delete wartet[id]; resolve(); } }, 15000 * (mal || 1));
      });
    },
    fertig(id) { const r = wartet[id]; if (r) { delete wartet[id]; r(); } },
    verstummen() { send({ type: 'verstummen' }); },
    status(s) { send(Object.assign({ type: 'status' }, s)); },
  };
})();
"""

KEYS = {
    "Enter": (13, "Enter", "\r"),
    "Backspace": (8, "Backspace", ""),
    "Tab": (9, "Tab", ""),
    "Escape": (27, "Escape", ""),
    "ArrowUp": (38, "ArrowUp", ""),
    "ArrowDown": (40, "ArrowDown", ""),
    "ArrowLeft": (37, "ArrowLeft", ""),
    "ArrowRight": (39, "ArrowRight", ""),
}


class CDPError(RuntimeError):
    pass


def _pid() -> int:
    try:
        return int(PID_FILE.read_text().strip() or 0)
    except (OSError, ValueError):
        return 0


def is_running() -> bool:
    pid = _pid()
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill() -> None:
    """Fenster schliessen (synchron, auch aus anderen Threads/Prozessen)."""
    pid = _pid()
    if pid > 0:
        with contextlib.suppress(OSError):
            os.kill(pid, signal.SIGTERM)
            logger.info("TV-Browser geschlossen (PID %s)", pid)
    PID_FILE.unlink(missing_ok=True)


def _launch(cfg: Config, url: str) -> None:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (PROFILE_DIR / name).unlink(missing_ok=True)
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")
    proc = subprocess.Popen(
        [
            kiosk._chromium_binary(),
            "--kiosk",
            "--ozone-platform=wayland",
            f"--user-data-dir={PROFILE_DIR}",
            f"--remote-debugging-port={DEBUG_PORT}",
            "--remote-debugging-address=127.0.0.1",
            "--password-store=basic",
            "--noerrdialogs",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            "--disable-features=Translate",
            "--no-first-run",
            "--no-default-browser-check",
            "--lang=de-DE",
            "--autoplay-policy=no-user-gesture-required",
            "--check-for-update-interval=31536000",
            url,
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    PID_FILE.write_text(str(proc.pid))
    logger.info("TV-Browser gestartet (PID %s) -> %s", proc.pid, url)


Handler = Callable[[dict], Awaitable[None] | None]


class Browser:
    """Eine CDP-Verbindung zur (einzigen) Seite des TV-Browsers."""

    def __init__(self) -> None:
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._connect_lock = asyncio.Lock()
        self._handlers: dict[str, list[Handler]] = {}
        self._on_connect: list[Callable[[], Awaitable[None]]] = []
        self._viewers: set[asyncio.Queue] = set()
        self._screencasting = False
        self._last_frame = 0.0
        self._snapshot_task: asyncio.Task | None = None
        self.meta: dict = {}
        self.url = ""
        self.title = ""

    # ---------- Ereignisse ----------

    def on(self, method: str, handler: Handler) -> None:
        self._handlers.setdefault(method, []).append(handler)

    def on_connect(self, hook: Callable[[], Awaitable[None]]) -> None:
        self._on_connect.append(hook)

    @property
    def connected(self) -> bool:
        return self._ws is not None

    # ---------- Starten / Verbinden ----------

    async def open(self, cfg: Config, url: str | None = None) -> None:
        """Fenster oeffnen (oder vorhandenes nehmen) und verbinden."""
        async with self._connect_lock:
            if not is_running():
                self._ws = None
                if not kiosk.is_running():
                    # Fernseher ist aus: erst einschalten, dann liegt der
                    # Browser ueber dem frisch gestarteten Kiosk
                    from app import tv_power

                    await asyncio.to_thread(tv_power.power_on, cfg)
                await asyncio.to_thread(_launch, cfg, url or HOME_URL)
                url = None
            if self._ws is None:
                await self._connect()
        if url:
            await self.navigate(url)

    async def _connect(self) -> None:
        deadline = time.monotonic() + CONNECT_TIMEOUT_SECONDS
        target = None
        async with httpx.AsyncClient(timeout=3) as client:
            while time.monotonic() < deadline:
                with contextlib.suppress(httpx.HTTPError, ValueError):
                    targets = (await client.get(f"http://127.0.0.1:{DEBUG_PORT}/json/list")).json()
                    target = next((t for t in targets if t.get("type") == "page"), None)
                    if target:
                        break
                await asyncio.sleep(0.5)
        if not target:
            raise CDPError("Der TV-Browser antwortet nicht")
        self._ws = await connect(target["webSocketDebuggerUrl"], max_size=None, ping_interval=None)
        self._reader = asyncio.create_task(self._read_loop(self._ws))
        self.url = target.get("url", "")
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("Runtime.addBinding", {"name": "jarvisBridge"})
        await self.send("Page.addScriptToEvaluateOnNewDocument", {"source": PREAMBLE})
        await self.evaluate(PREAMBLE)
        if self._viewers:
            await self._start_screencast()
        for hook in self._on_connect:
            with contextlib.suppress(Exception):
                await hook()
        logger.info("TV-Browser verbunden: %s", self.url)

    async def close(self) -> None:
        ws, self._ws = self._ws, None
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()
        await asyncio.to_thread(kill)

    async def _read_loop(self, ws) -> None:
        try:
            async for raw in ws:
                msg = json.loads(raw)
                if "id" in msg:
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(CDPError(msg["error"].get("message", "CDP-Fehler")))
                        else:
                            fut.set_result(msg.get("result", {}))
                    continue
                method = msg.get("method")
                params = msg.get("params", {})
                if method == "Page.screencastFrame":
                    self._frame(params)
                    continue
                if method == "Page.frameNavigated" and not params.get("frame", {}).get("parentId"):
                    self.url = params["frame"].get("url", self.url)
                for handler in self._handlers.get(method, []):
                    result = handler(params)
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
        except Exception:  # noqa: BLE001 - Verbindung weg (Fenster geschlossen)
            pass
        finally:
            if self._ws is ws:
                self._ws = None
                self._screencasting = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(CDPError("TV-Browser getrennt"))
            self._pending.clear()

    async def send(self, method: str, params: dict | None = None, timeout: float = 15) -> dict:
        if self._ws is None:
            raise CDPError("TV-Browser ist nicht offen")
        self._next_id += 1
        msg_id = self._next_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        await self._ws.send(json.dumps({"id": msg_id, "method": method, "params": params or {}}))
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(msg_id, None)

    async def evaluate(self, expression: str, await_promise: bool = False, timeout: float = 15):
        result = await self.send(
            "Runtime.evaluate",
            {"expression": expression, "awaitPromise": await_promise, "returnByValue": True},
            timeout=timeout,
        )
        if result.get("exceptionDetails"):
            details = result["exceptionDetails"]
            text = (details.get("exception") or {}).get("description") or details.get("text") or "Skriptfehler"
            raise CDPError(text.splitlines()[0])
        return (result.get("result") or {}).get("value")

    # ---------- Navigation ----------

    async def navigate(self, url: str) -> None:
        await self.send("Page.navigate", {"url": url})

    async def history(self, step: int) -> None:
        await self.evaluate(f"history.go({int(step)})")

    async def reload(self) -> None:
        await self.send("Page.reload")

    async def page_info(self) -> dict:
        with contextlib.suppress(Exception):
            info = await self.evaluate("({url: location.href, title: document.title})", timeout=3)
            self.url, self.title = info["url"], info["title"]
        return {"url": self.url, "title": self.title}

    # ---------- Bild fuer die Fernbedienung ----------

    async def add_viewer(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=2)
        self._viewers.add(queue)
        if self.connected and not self._screencasting:
            await self._start_screencast()
        if self._snapshot_task is None or self._snapshot_task.done():
            self._last_frame = 0.0
            self._snapshot_task = asyncio.create_task(self._snapshot_loop())
        return queue

    async def remove_viewer(self, queue: asyncio.Queue) -> None:
        self._viewers.discard(queue)
        if not self._viewers and self._screencasting and self.connected:
            self._screencasting = False
            with contextlib.suppress(Exception):
                await self.send("Page.stopScreencast")

    async def _start_screencast(self) -> None:
        self._screencasting = True
        await self.send("Page.startScreencast", SCREENCAST)

    async def _snapshot_loop(self) -> None:
        while self._viewers:
            await asyncio.sleep(0.5)
            if not self.connected or time.monotonic() - self._last_frame < SNAPSHOT_AFTER_SECONDS:
                continue
            with contextlib.suppress(Exception):
                metrics = await self.send("Page.getLayoutMetrics", timeout=5)
                viewport = metrics.get("cssVisualViewport") or metrics.get("cssLayoutViewport") or {}
                width = viewport.get("clientWidth") or 1920
                height = viewport.get("clientHeight") or 1080
                scale = min(1.0, 1280 / width)
                shot = await self.send(
                    "Page.captureScreenshot",
                    {"format": "jpeg", "quality": 55, "clip": {"x": viewport.get("pageX", 0), "y": viewport.get("pageY", 0), "width": width, "height": height, "scale": scale}},
                    timeout=10,
                )
                self.meta = {**self.meta, "deviceWidth": width, "deviceHeight": height}
                self._publish({"data": shot["data"], "w": width, "h": height})

    def _frame(self, params: dict) -> None:
        self.meta = params.get("metadata", {})
        asyncio.create_task(self._ack(params.get("sessionId")))
        self._publish({"data": params.get("data"), "w": self.meta.get("deviceWidth"), "h": self.meta.get("deviceHeight")})

    def _publish(self, frame: dict) -> None:
        self._last_frame = time.monotonic()
        for queue in list(self._viewers):
            if queue.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
            queue.put_nowait(frame)

    async def _ack(self, session_id) -> None:
        with contextlib.suppress(Exception):
            await self.send("Page.screencastFrameAck", {"sessionId": session_id}, timeout=5)

    # ---------- Eingaben ----------

    def _point(self, nx: float, ny: float) -> tuple[float, float]:
        width = self.meta.get("deviceWidth") or 1920
        height = self.meta.get("deviceHeight") or 1080
        return max(0.0, min(1.0, nx)) * width, max(0.0, min(1.0, ny)) * height

    async def tap(self, nx: float, ny: float) -> None:
        x, y = self._point(nx, ny)
        await self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            await self.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    async def scroll(self, nx: float, ny: float, dx: float, dy: float) -> None:
        x, y = self._point(nx, ny)
        await self.send("Input.dispatchMouseEvent", {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy})

    async def insert_text(self, text: str) -> None:
        await self.send("Input.insertText", {"text": text})

    async def key(self, name: str) -> None:
        if name not in KEYS:
            raise CDPError(f"Unbekannte Taste {name}")
        code, key, text = KEYS[name]
        base = {"key": key, "code": key, "windowsVirtualKeyCode": code, "nativeVirtualKeyCode": code}
        await self.send("Input.dispatchKeyEvent", {**base, "type": "rawKeyDown"})
        if text:
            await self.send("Input.dispatchKeyEvent", {**base, "type": "char", "text": text})
        await self.send("Input.dispatchKeyEvent", {**base, "type": "keyUp"})


browser = Browser()


def normalize_url(raw: str) -> str:
    """Adresszeile: "chess.com" -> https://chess.com, Suchbegriffe -> Google."""
    text = (raw or "").strip()
    if not text:
        return HOME_URL
    if "://" in text:
        return text
    if " " not in text and "." in text:
        return "https://" + text
    from urllib.parse import quote_plus

    return f"https://www.google.de/search?q={quote_plus(text)}"
