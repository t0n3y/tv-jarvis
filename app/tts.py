"""Wrapper um Piper (offline TTS, laeuft performant auf dem Pi 4).

`pip install piper-tts` legt das `piper`-CLI-Binary im selben bin/-Verzeichnis
wie den Python-Interpreter ab (also im venv). Systemd-Services rufen die venv-
Python ueber ihren vollen Pfad auf, OHNE das venv zu aktivieren - das venv-
bin/-Verzeichnis steht dann NICHT im PATH. Deshalb wird piper hier relativ zu
`sys.executable` aufgeloest statt sich auf PATH zu verlassen.

Das Sprachmodell liegt unter `cfg.tts.model_dir/<voice>.onnx` (+ `.onnx.json`)
- siehe scripts/install.sh, das die deutsche Stimme automatisch herunterlaedt.

Ausgabe geht direkt (raw PCM, ohne Zwischendatei) an `aplay`, das auf dem Pi
per Default ueber HDMI an die TV-Lautsprecher ausgibt. Gesprochen wird ueber
die Python-API von Piper in einem eigenen Prozess (`python -m app.tts`), damit
zwischen Saetzen und Abschnitten echte Pausen eingefuegt werden koennen.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
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


# Pausen zwischen Saetzen (eine Zeile im Text) und Abschnitten (Leerzeile).
# Piper selbst macht zwischen Saetzen kaum eine Pause - bei Aufzaehlungen wie
# den ToDos klingt das sonst wie ein einziger Satz.
SENTENCE_PAUSE_SECONDS = 0.55
SECTION_PAUSE_SECONDS = 1.0


def split_text(text: str) -> list[list[str]]:
    """Abschnitte (durch Leerzeilen getrennt) -> Saetze (eine Zeile je Satz)."""
    sections = []
    for block in re.split(r"\n\s*\n", text.strip()):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if lines:
            sections.append(lines)
    return sections


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

    # Eigener Prozess: das Sprachmodell (onnxruntime) soll nicht dauerhaft im
    # Speicher des Dashboard-Dienstes bleiben
    job = {
        "model": str(model_path),
        "length_scale": length_scale,
        "sections": split_text(text),
    }
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.tts"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    aplay_args = ["aplay", "-q", "-r", str(sample_rate), "-f", "S16_LE", "-t", "raw"]
    if cfg.audio.alsa_device:
        aplay_args += ["-D", cfg.audio.alsa_device]
    aplay_args.append("-")

    aplay = subprocess.Popen(aplay_args, stdin=worker.stdout)

    assert worker.stdin is not None
    worker.stdin.write(json.dumps(job).encode("utf-8"))
    worker.stdin.close()
    if worker.stdout:
        worker.stdout.close()  # Worker bekommt SIGPIPE, sobald aplay fertig ist

    aplay.wait()
    worker.wait()

    if worker.returncode not in (0, None):
        logger.warning("Sprachausgabe wurde mit Returncode %s beendet", worker.returncode)


def _synthesize(job: dict) -> None:
    """Laeuft im Worker-Prozess: Saetze einzeln sprechen, dazwischen Stille."""
    from piper import PiperVoice, SynthesisConfig

    voice = PiperVoice.load(job["model"])
    syn_config = SynthesisConfig(length_scale=job["length_scale"])
    rate = voice.config.sample_rate
    out = sys.stdout.buffer

    def silence(seconds: float) -> None:
        out.write(b"\x00\x00" * int(rate * seconds))

    sections = job["sections"]
    for i, lines in enumerate(sections):
        for j, line in enumerate(lines):
            for chunk in voice.synthesize(line, syn_config=syn_config):
                out.write(chunk.audio_int16_bytes)
            if j < len(lines) - 1:
                silence(SENTENCE_PAUSE_SECONDS)
        if i < len(sections) - 1:
            silence(SECTION_PAUSE_SECONDS)
        out.flush()


if __name__ == "__main__":
    try:
        _synthesize(json.loads(sys.stdin.read()))
    except BrokenPipeError:
        pass
