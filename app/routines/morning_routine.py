"""Morgen-Routine: TV an -> Kiosk starten -> Briefing sammeln -> vorlesen -> Radio an.

Wird von systemd/morning-routine.timer taeglich zur konfigurierten Weckzeit
gestartet (siehe scripts/install.sh). Manueller Testlauf:

    python -m app.routines.morning_routine

Oder in der Fernbedienung: Einstellungen -> Wecker -> "Wecker jetzt testen".
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Callable

from app import kiosk_media, plugins, radio, tts, tv_power
from app.briefing import build_briefing
from app.config import ROOT_DIR, get_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATE_FILE = ROOT_DIR / "data" / "state.json"


def main(on_state_written: Callable[[], None] | None = None) -> None:
    cfg = get_config()

    # Laeuft noch Musik (z.B. das Radio von gestern Abend), soll die Stimme
    # nicht dagegen ansprechen
    radio.stop()
    kiosk_media.stop_all_media(cfg)

    tv_power.power_on(cfg)

    logger.info("Sammle Briefing-Daten ...")
    briefing = build_briefing(cfg)
    if briefing.errors:
        logger.warning("Briefing mit Einschraenkungen: %s", "; ".join(briefing.errors))

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(asdict(briefing), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if on_state_written:
        on_state_written()  # Kiosk zeigt die frischen Daten, waehrend vorgelesen wird

    # Eigene Apps (apps/<id>/server.py: briefing()) duerfen je einen Satz
    # beisteuern - vor dem Abschiedsgruss
    speech = briefing.speech_text
    extra = plugins.briefing_texts()
    if extra:
        closing = "Ich wünsche dir einen schönen Tag!"
        head, sep, tail = speech.rpartition(closing)
        block = "\n\n".join(extra)
        speech = f"{head}{block}\n\n{sep}{tail}" if sep else f"{speech}\n\n{block}"

    logger.info("Lese Briefing vor ...")
    tts.speak(cfg, speech)

    logger.info("Starte Radio ...")
    radio.start(cfg)

    logger.info("Morgen-Routine abgeschlossen.")


if __name__ == "__main__":
    main()
