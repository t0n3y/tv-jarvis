"""Lautstaerke-Steuerung ueber PipeWire (wpctl) fuer die Fernbedienung.

Wirkt auf den Standard-Audio-Sink (siehe README/scripts/fix_audio_sink.sh,
das sicherstellt, dass das der HDMI-Ausgang zum Fernseher ist, nicht der
Kopfhoereranschluss). Betrifft die Kiosk-/YouTube-Wiedergabe; Radio (mpv)
laeuft bewusst direkt ueber ALSA und hat seine eigene, feste Lautstaerke
(siehe config.yaml: radio.volume).
"""

from __future__ import annotations

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

VOLUME_STEP_PERCENT = 5


def _wpctl(*args: str) -> None:
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        subprocess.run(["wpctl", *args], env=env, timeout=5, check=True, capture_output=True)
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("wpctl %s fehlgeschlagen: %s", " ".join(args), exc)


def volume_up() -> None:
    _wpctl("set-volume", "@DEFAULT_AUDIO_SINK@", f"{VOLUME_STEP_PERCENT}%+")


def volume_down() -> None:
    _wpctl("set-volume", "@DEFAULT_AUDIO_SINK@", f"{VOLUME_STEP_PERCENT}%-")


def mute_toggle() -> None:
    _wpctl("set-mute", "@DEFAULT_AUDIO_SINK@", "toggle")
