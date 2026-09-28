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

from app import kiosk_media, radio, tts, tv_power
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

    logger.info("Lese Briefing vor ...")
    tts.speak(cfg, briefing.speech_text)

    logger.info("Starte Radio ...")
    radio.start(cfg)

    logger.info("Morgen-Routine abgeschlossen.")


if __name__ == "__main__":
    main()
