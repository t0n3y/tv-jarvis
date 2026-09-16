"""Wrapper um Piper (offline TTS, laeuft performant auf dem Pi 4).

`pip install piper-tts` legt das `piper`-CLI-Binary im selben bin/-Verzeichnis
wie den Python-Interpreter ab (also im venv). Systemd-Services rufen die venv-
Python ueber ihren vollen Pfad auf, OHNE das venv zu aktivieren - das venv-
bin/-Verzeichnis steht dann NICHT im PATH. Deshalb wird piper hier relativ zu
`sys.executable` aufgeloest statt sich auf PATH zu verlassen.

Das Sprachmodell liegt unter `cfg.tts.model_dir/<voice>.onnx` (+ `.onnx.json`)
- siehe scripts/install.sh, das die deutsche Stimme automatisch herunterlaedt.

Ausgabe geht direkt (raw PCM, ohne Zwischendatei) an `aplay`, das auf dem Pi
per Default ueber HDMI an die TV-Lautsprecher ausgibt.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

from app.config import Config

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_RATE = 22050


def _piper_binary() -> str:
    # sys.prefix zeigt zuverlaessig auf das venv-Verzeichnis, selbst wenn
    # .venv/bin/python ein Symlink auf den System-Python ist (sys.executable
    # per .resolve() wuerde dann faelschlich zum System-bin/ fuehren, wo kein
    # piper liegt).
    venv_piper = Path(sys.prefix) / "bin" / "piper"
    if venv_piper.exists():
        return str(venv_piper)
    return "piper"  # Fallback: system-weite Installation im PATH


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
            _piper_binary(),
            "--model", str(model_path),
            "--output-raw",
            "--length_scale", str(length_scale),
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    aplay_args = ["aplay", "-q", "-r", str(sample_rate), "-f", "S16_LE", "-t", "raw"]
    if cfg.audio.alsa_device:
        aplay_args += ["-D", cfg.audio.alsa_device]
    aplay_args.append("-")

    aplay = subprocess.Popen(aplay_args, stdin=piper.stdout)

    assert piper.stdin is not None
    piper.stdin.write(text.encode("utf-8"))
    piper.stdin.close()
    if piper.stdout:
        piper.stdout.close()  # piper bekommt SIGPIPE, sobald aplay fertig ist

    aplay.wait()
    piper.wait()

    if piper.returncode not in (0, None) and piper.returncode < 0:
        logger.warning("piper wurde mit Returncode %s beendet", piper.returncode)
