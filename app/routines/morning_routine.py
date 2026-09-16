"""Morgen-Routine: TV an -> Kiosk starten -> Briefing sammeln -> vorlesen -> Radio an.

Wird von systemd/morning-routine.timer taeglich zur konfigurierten Weckzeit
gestartet (siehe scripts/install.sh). Manueller Testlauf:

    python -m app.routines.morning_routine
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict

from app import radio, tts
from app.briefing import build_briefing
from app.config import ROOT_DIR, get_config
from app.dashboard import kiosk
from app.tv_control import get_controller

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STATE_FILE = ROOT_DIR / "data" / "state.json"


def main() -> None:
    cfg = get_config()

    tv = get_controller(cfg)
    logger.info("Schalte Fernseher ein ...")
    tv.turn_on()
    time.sleep(cfg.tv_control.boot_wait_seconds)

    kiosk.start(cfg)

    logger.info("Sammle Briefing-Daten ...")
    briefing = build_briefing(cfg)
    if briefing.errors:
        logger.warning("Briefing mit Einschraenkungen: %s", "; ".join(briefing.errors))

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(asdict(briefing), ensure_ascii=False, indent=2), encoding="utf-8"
    )

    logger.info("Lese Briefing vor ...")
    tts.speak(cfg, briefing.speech_text)

    logger.info("Starte Radio ...")
    radio.start(cfg)

    logger.info("Morgen-Routine abgeschlossen.")


if __name__ == "__main__":
    main()
