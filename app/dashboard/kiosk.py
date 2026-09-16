"""Startet/stoppt Chromium im Kiosk-Modus gegen das lokale Dashboard.

Analog zu app/radio.py: PID wird in einer Datei gemerkt, damit leave_routine.py
(ein eigener Prozessaufruf) den Browser zuverlaessig wieder schliessen kann.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess

from app.config import Config, ROOT_DIR

logger = logging.getLogger(__name__)

PID_FILE = ROOT_DIR / "data" / "kiosk.pid"

CHROMIUM_CANDIDATES = ["chromium-browser", "chromium"]


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


def start(cfg: Config) -> None:
    if is_running():
        return

    url = f"http://{cfg.dashboard.host}:{cfg.dashboard.port}/"
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)

    proc = subprocess.Popen(
        [
            _chromium_binary(),
            "--kiosk",
            "--noerrdialogs",
            "--disable-infobars",
            "--disable-session-crashed-bubble",
            "--check-for-update-interval=31536000",
            f"--app={url}",
        ],
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
