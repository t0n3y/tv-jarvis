"""Startet/stoppt Chromium im Kiosk-Modus gegen das lokale Dashboard.

Analog zu app/radio.py: PID wird in einer Datei gemerkt, damit leave_routine.py
(ein eigener Prozessaufruf) den Browser zuverlaessig wieder schliessen kann.

Nutzt ein eigenes --user-data-dir statt Chromiums Standardprofil: wird der
Kiosk-Prozess einmal hart beendet (z.B. durch einen Stromausfall oder einen
vorherigen Bug, siehe git-Historie), bleibt sonst eine SingletonLock-Datei im
Profil zurueck, die JEDEN weiteren Start mit "Profil wird bereits verwendet"
blockiert. Vor jedem Start wird deshalb geprueft, ob der alte Prozess wirklich
noch laeuft - falls nicht, werden die Sperr-Dateien vorsorglich entfernt.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from pathlib import Path

from app.config import Config, ROOT_DIR

logger = logging.getLogger(__name__)

PID_FILE = ROOT_DIR / "data" / "kiosk.pid"
PROFILE_DIR = ROOT_DIR / "data" / "chromium-profile"

CHROMIUM_CANDIDATES = ["chromium-browser", "chromium"]

# Direkt nach einem Reboot ist der Wayland-Compositor (labwc) manchmal noch
# nicht bereit, wenn morning-routine.service schon anlaufen will. Ohne
# Wartezeit scheitert Chromium dann mit "Missing X server or $DISPLAY" bzw.
# findet den Wayland-Socket nicht. Deshalb kurz pollen statt sofort starten.
WAYLAND_WAIT_TIMEOUT_SECONDS = 45


def _wait_for_wayland_socket(display: str = "wayland-0") -> bool:
    socket_path = Path(f"/run/user/{os.getuid()}") / display
    deadline = time.monotonic() + WAYLAND_WAIT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if socket_path.exists():
            return True
        time.sleep(1)
    return False


def _chromium_binary() -> str:
    for name in CHROMIUM_CANDIDATES:
        from shutil import which
        if which(name):
            return name
    # Fallback: erstes Kandidat, schlaegt dann mit klarer FileNotFoundError fehl
    return CHROMIUM_CANDIDATES[0]


def is_running() -> bool:
    if not PID_FILE.exists():
        return False
    pid = int(PID_FILE.read_text().strip() or 0)
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _clear_stale_profile_lock() -> None:
    """Entfernt Singleton*-Sperrdateien, falls kein Kiosk-Prozess mehr laeuft.

    Ohne das blockiert ein hart beendeter Chromium-Prozess (SIGKILL, Absturz,
    Stromausfall) jeden folgenden Start mit "Profil wird bereits verwendet"."""
    if not PROFILE_DIR.exists():
        return
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        (PROFILE_DIR / name).unlink(missing_ok=True)


def start(cfg: Config) -> None:
    if is_running():
        return
    if not _wait_for_wayland_socket():
        logger.warning(
            "Wayland-Socket nach %ss nicht gefunden - versuche trotzdem zu starten.",
            WAYLAND_WAIT_TIMEOUT_SECONDS,
        )
    _clear_stale_profile_lock()

    url = f"http://{cfg.dashboard.host}:{cfg.dashboard.port}/"
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)

    # Raspberry Pi OS (Bookworm/Trixie) laeuft standardmaessig auf Wayland
    # (Compositor "labwc"), nicht X11 - ohne --ozone-platform=wayland +
    # WAYLAND_DISPLAY versucht Chromium X11 zu nutzen und scheitert mit
    # "Missing X server or $DISPLAY". Der Wayland-Socket liegt unter
    # $XDG_RUNTIME_DIR/wayland-0 fuer den eingeloggten Desktop-Benutzer.
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    env.setdefault("WAYLAND_DISPLAY", "wayland-0")

    proc = subprocess.Popen(
        [
            _chromium_binary(),
            "--kiosk",
            "--ozone-platform=wayland",
            f"--user-data-dir={PROFILE_DIR}",
            # Ohne dies versucht Chromium beim Start den System-Keyring fuer
            # Cookie-/Passwortspeicherung zu entsperren - ein "Unlock
            # Keyring"-Dialog blockiert dann den Kiosk mit weissem Bildschirm,
            # weil im Kiosk-Modus keine Fenster bedient werden koennen. Fuer
            # ein Kiosk-Geraet ohne gespeicherte Logins ist das unnoetig.
            "--password-store=basic",
            "--noerrdialogs",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            "--no-first-run",
            # Ohne dies blockiert Chromiums Autoplay-Schutz das automatische
            # Abspielen des YouTube-Players, weil der Start per WebSocket
            # (Fernbedienung) kommt statt per echtem Klick im Browser.
            "--autoplay-policy=no-user-gesture-required",
            "--check-for-update-interval=31536000",
            f"--app={url}",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    PID_FILE.write_text(str(proc.pid))
    logger.info("Kiosk-Browser gestartet (PID %s) -> %s", proc.pid, url)


def stop() -> None:
    if not PID_FILE.exists():
        return
    pid = int(PID_FILE.read_text().strip() or 0)
    if pid > 0:
        try:
            os.kill(pid, signal.SIGTERM)
            logger.info("Kiosk-Browser gestoppt (PID %s)", pid)
        except OSError:
            pass
    PID_FILE.unlink(missing_ok=True)
