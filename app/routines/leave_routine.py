"""Verlassen-Routine: Radio stoppen -> Ausschalt-Animation -> Kiosk beenden -> TV aus.

Wird von systemd/leave-routine.timer taeglich zur konfigurierten Verlasszeit
gestartet. Manueller Testlauf:

    python -m app.routines.leave_routine
"""

from __future__ import annotations

import logging
import time

import requests

from app import radio
from app.config import get_config
from app.dashboard import kiosk
from app.tv_control import get_controller

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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

    logger.info("Löse Ausschalt-Animation aus ...")
    _trigger_shutdown_animation(cfg)
    time.sleep(cfg.dashboard.shutdown_animation_seconds + 0.5)

    kiosk.stop()

    tv = get_controller(cfg)
    logger.info("Schalte Fernseher aus ...")
    tv.turn_off()

    logger.info("Verlassen-Routine abgeschlossen.")


if __name__ == "__main__":
    main()
