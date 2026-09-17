"""Verlassen-Routine: Radio/YouTube stoppen -> Verabschiedung -> TV aus.

Wird von systemd/leave-routine.timer taeglich zur konfigurierten Verlasszeit
gestartet. Manueller Testlauf:

    python -m app.routines.leave_routine
"""

from __future__ import annotations

import logging

from app import tv_power
from app.config import get_config

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main() -> None:
    cfg = get_config()
    tv_power.power_off(cfg, farewell=True)
    logger.info("Verlassen-Routine abgeschlossen.")


if __name__ == "__main__":
    main()
