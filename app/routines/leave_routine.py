"""Verlassen-Routine: Radio stoppen -> Verabschiedung -> Ausschalt-Animation
-> TV aus -> Kiosk beenden.

Wird von systemd/leave-routine.timer taeglich zur konfigurierten Verlasszeit
gestartet. Manueller Testlauf:

    python -m app.routines.leave_routine
"""

from __future__ import annotations

import logging
import time

import requests

from app import radio, tts
from app.config import get_config
from app.dashboard import kiosk
from app.tv_control import get_controller

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FAREWELL_TEXT = "Bis später! Ich schalte jetzt ab."


def _trigger_shutdown_animation(cfg) -> None:
    url = f"http://{cfg.dashboard.host}:{cfg.dashboard.port}/api/shutdown-animation"
    try:
        requests.post(url, timeout=3)
    except requests.RequestException as exc:
        logger.warning("Konnte Ausschalt-Animation nicht auslösen (%s) - fahre trotzdem fort.", exc)


def main() -> None:
    cfg = get_config()

    logger.info("Stoppe Radio ...")
    radio.stop()

    logger.info("Verabschiedung ...")
    tts.speak(cfg, FAREWELL_TEXT)

    logger.info("Löse Ausschalt-Animation aus ...")
    _trigger_shutdown_animation(cfg)
    time.sleep(cfg.dashboard.shutdown_animation_seconds + 0.2)

    # Fernseher ZUERST ausschalten, danach erst den Kiosk beenden - sonst ist
    # kurz der Desktop dahinter sichtbar, waehrend der Fernseher noch an ist.
    tv = get_controller(cfg)
    logger.info("Schalte Fernseher aus ...")
    tv.turn_off()

    kiosk.stop()

    logger.info("Verlassen-Routine abgeschlossen.")


if __name__ == "__main__":
    main()
