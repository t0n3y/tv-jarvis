"""Wrapper um Piper (offline TTS, laeuft performant auf dem Pi 4).

Erwartet, dass das Binary `piper` im PATH liegt und das Sprachmodell unter
`cfg.tts.model_dir/<voice>.onnx` (+ `.onnx.json`) abgelegt ist - siehe
scripts/install.sh, das die deutsche Stimme automatisch herunterlaedt.

Ausgabe geht direkt (raw PCM, ohne Zwischendatei) an `aplay`, das auf dem Pi
per Default ueber HDMI an die TV-Lautsprecher ausgibt.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from app.config import Config

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 22050


def _sample_rate(config_path: Path) -> int:
    if not config_path.exists():
        return DEFAULT_SAMPLE_RATE
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        return int(data.get("audio", {}).get("sample_rate", DEFAULT_SAMPLE_RATE))
    except (json.JSONDecodeError, KeyError, ValueError):
        return DEFAULT_SAMPLE_RATE


def speak(cfg: Config, text: str) -> None:
    if not text.strip():
        return

    model_path = cfg.tts.model_dir / f"{cfg.tts.voice}.onnx"
    config_path = cfg.tts.model_dir / f"{cfg.tts.voice}.onnx.json"
    if not model_path.exists():
        raise FileNotFoundError(
            f"Piper-Modell nicht gefunden: {model_path}. "
            "scripts/install.sh ausfuehren oder Modell manuell nach data/piper-voices legen."
        )

    length_scale = 1.0 / cfg.tts.speed if cfg.tts.speed else 1.0
    sample_rate = _sample_rate(config_path)

    piper = subprocess.Popen(
        [
            "piper",
            "--model", str(model_path),
            "--output-raw",
            "--length_scale", str(length_scale),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    aplay = subprocess.Popen(
        ["aplay", "-q", "-r", str(sample_rate), "-f", "S16_LE", "-t", "raw", "-"],
        stdin=piper.stdout,
    )

    assert piper.stdin is not None
    piper.stdin.write(text.encode("utf-8"))
    piper.stdin.close()
    if piper.stdout:
        piper.stdout.close()  # piper bekommt SIGPIPE, sobald aplay fertig ist

    aplay.wait()
    piper.wait()

    if piper.returncode not in (0, None) and piper.returncode < 0:
        logger.warning("piper wurde mit Returncode %s beendet", piper.returncode)
