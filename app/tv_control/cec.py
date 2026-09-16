"""Steuert den Fernseher per HDMI-CEC ueber `cec-client` (Paket: cec-utils).

Voraussetzungen auf dem Pi 4 (siehe README):
- Fernseher haengt am HDMI-Port NEBEN dem USB-C-Port (nur dieser unterstuetzt CEC)
- Am Samsung-TV ist "Anynet+" UND "Auto Turn Off" aktiviert - ohne "Auto Turn
  Off" ignoriert Samsung oft den Standby-Befehl (bekanntes Community-Problem)
"""

from __future__ import annotations

import logging
import subprocess

from app.config import Config
from app.tv_control.base import TVController

logger = logging.getLogger(__name__)

CEC_TIMEOUT_SECONDS = 15


def _cec_command(command: str) -> str:
    result = subprocess.run(
        ["cec-client", "-s", "-d", "1"],
        input=command + "\n",
        capture_output=True,
        text=True,
        timeout=CEC_TIMEOUT_SECONDS,
    )
    return result.stdout


class CECController(TVController):
    def __init__(self, cfg: Config):
        self.device = cfg.tv_control.cec_device

    def turn_on(self) -> None:
        logger.info("CEC: Fernseher einschalten (Geraet %s)", self.device)
        _cec_command(f"on {self.device}")

    def turn_off(self) -> None:
        logger.info("CEC: Fernseher in Standby (Geraet %s)", self.device)
        _cec_command(f"standby {self.device}")

    def is_on(self) -> bool | None:
        output = _cec_command(f"pow {self.device}")
        lowered = output.lower()
        if "power status: on" in lowered:
            return True
        if "power status: standby" in lowered:
            return False
        logger.warning("CEC: Power-Status nicht eindeutig ermittelbar:\n%s", output)
        return None
