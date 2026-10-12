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
import time

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


_SINK_ID = re.compile(r"^[^0-9]*([0-9]+)\.")
HDMI_WAIT_SECONDS = 8


def _hdmi_sink_id() -> str | None:
    status = _wpctl("status") or ""
    audio = status.split("Video", 1)[0]
    sinks = audio.split("Sinks:", 1)[-1].split("Sources:", 1)[0]
    for line in sinks.splitlines():
        match = _SINK_ID.match(line)
        if match and "HDMI" in line:
            return match.group(1)
    return None


def ensure_hdmi_output() -> None:
    """Sorgt dafuer, dass Chromium (YouTube, Jellyfin, Twitch, Plattenspieler)
    ueber HDMI am Fernseher ausgibt.

    Startet der Pi, waehrend der Fernseher nicht per HDMI verbunden ist, legt
    WirePlumber den HDMI-Ausgang nur als "aus" an und spaeter nicht von selbst
    neu an - dann landet der Ton im leeren Kopfhoerer-Anschluss. Ein Neustart
    von WirePlumber (Benutzerdienst, kein sudo) erkennt die Geraete neu."""
    sink = _hdmi_sink_id()
    if sink is None:
        logger.warning("Kein HDMI-Audioausgang in PipeWire - lasse WirePlumber die Geraete neu erkennen")
        env = os.environ.copy()
        env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        try:
            subprocess.run(["systemctl", "--user", "restart", "wireplumber"], env=env, timeout=15, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError, subprocess.TimeoutExpired) as exc:
            logger.warning("WirePlumber-Neustart fehlgeschlagen: %s", exc)
            return
        for _ in range(HDMI_WAIT_SECONDS * 2):
            time.sleep(0.5)
            sink = _hdmi_sink_id()
            if sink:
                break
    if sink is None:
        logger.warning("Auch danach kein HDMI-Audioausgang gefunden")
        return
    if "hdmi" not in (_wpctl("inspect", SINK) or "").lower():
        _wpctl("set-default", sink)
        logger.info("Standard-Audioausgang auf HDMI gesetzt (ID %s)", sink)


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


def unmute() -> None:
    _wpctl("set-mute", SINK, "0")


def mute_toggle() -> None:
    _wpctl("set-mute", SINK, "toggle")


def get_volume() -> dict | None:
    """z.B. {"percent": 45, "muted": False} - aus "Volume: 0.45 [MUTED]"."""
    output = _wpctl("get-volume", SINK)
    match = re.search(r"Volume:\s*([0-9.]+)", output or "")
    if not match:
        return None
    return {"percent": round(float(match.group(1)) * 100), "muted": "MUTED" in output}
