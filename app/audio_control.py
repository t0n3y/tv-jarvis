"""Lautstaerke-Steuerung ueber PipeWire (wpctl) fuer die Fernbedienung.

Wirkt auf den Standard-Audio-Sink (siehe README/scripts/fix_audio_sink.sh,
das sicherstellt, dass das der HDMI-Ausgang zum Fernseher ist, nicht der
Kopfhoereranschluss). Betrifft die Kiosk-Wiedergabe (YouTube/Jellyfin); Radio
(mpv) laeuft bewusst direkt ueber ALSA und hat seine eigene, feste Lautstaerke
(siehe config.yaml: radio.volume).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess

logger = logging.getLogger(__name__)

VOLUME_STEP_PERCENT = 10
SINK = "@DEFAULT_AUDIO_SINK@"


def _wpctl(*args: str) -> str | None:
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        result = subprocess.run(
            ["wpctl", *args], env=env, timeout=5, check=True, capture_output=True, text=True
        )
    except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("wpctl %s fehlgeschlagen: %s", " ".join(args), exc)
        return None
    return result.stdout


def volume_up() -> None:
    # Wie bei jeder TV-Fernbedienung hebt Lauter/Leiser die Stummschaltung auf -
    # sonst drueckt man bei stummem Ton "+" ins Leere (so landete der Pegel mal
    # unbemerkt bei 170 %).
    _wpctl("set-mute", SINK, "0")
    # -l 1.0: nicht ueber 100 % hinaus verstaerken (sonst uebersteuert der Ton)
    _wpctl("set-volume", "-l", "1.0", SINK, f"{VOLUME_STEP_PERCENT}%+")


def volume_down() -> None:
    _wpctl("set-mute", SINK, "0")
    _wpctl("set-volume", SINK, f"{VOLUME_STEP_PERCENT}%-")


def mute_toggle() -> None:
    _wpctl("set-mute", SINK, "toggle")


def get_volume() -> dict | None:
    """z.B. {"percent": 45, "muted": False} - aus "Volume: 0.45 [MUTED]"."""
    output = _wpctl("get-volume", SINK)
    match = re.search(r"Volume:\s*([0-9.]+)", output or "")
    if not match:
        return None
    return {"percent": round(float(match.group(1)) * 100), "muted": "MUTED" in output}
