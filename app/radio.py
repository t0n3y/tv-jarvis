"""Startet/stoppt Sunshine Live per mpv (nur Audio, kein Video-Fenster).

Der laufende Prozess wird ueber eine PID-Datei nachverfolgt, damit
leave_routine.py (ein eigener Prozessaufruf) ihn zuverlaessig wiederfindet und
beenden kann.
"""

from __future__ import annotations

import logging
import signal
import subprocess
from pathlib import Path

from app.config import Config, ROOT_DIR

logger = logging.getLogger(__name__)

PID_FILE = ROOT_DIR / "data" / "radio.pid"


def is_playing() -> bool:
    if not PID_FILE.exists():
        return False
    pid = int(PID_FILE.read_text().strip() or 0)
    if pid <= 0:
        return False
    try:
        # Signal 0 = nur pruefen ob der Prozess existiert, nichts senden
        import os
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def start(cfg: Config) -> None:
    if not cfg.radio.enabled or not cfg.radio.stream_url:
        return
    if is_playing():
        return

    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    args = ["mpv", "--no-video", f"--volume={cfg.radio.volume}", "--really-quiet"]
    if cfg.audio.alsa_device:
        args.append(f"--audio-device=alsa/{cfg.audio.alsa_device}")
    args.append(cfg.radio.stream_url)

    proc = subprocess.Popen(
        args,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    PID_FILE.write_text(str(proc.pid))
    logger.info("Radio gestartet (PID %s)", proc.pid)


def stop() -> None:
    if not PID_FILE.exists():
        return
    pid = int(PID_FILE.read_text().strip() or 0)
    if pid > 0:
        try:
            import os
            os.kill(pid, signal.SIGTERM)
            logger.info("Radio gestoppt (PID %s)", pid)
        except OSError:
            pass
    PID_FILE.unlink(missing_ok=True)
