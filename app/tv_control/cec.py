"""Steuert den Fernseher per HDMI-CEC ueber `cec-client` (Paket: cec-utils).

Der Pi 4 hat zwei micro-HDMI-Ports mit je einem eigenen CEC-Adapter
(/dev/cec0, /dev/cec1). Ohne explizite Adapter-Angabe waehlt cec-client
irgendeinen davon - haengt der Fernseher am jeweils anderen Port, schlaegt
jeder Befehl fehl ("power status: unknown"). Deshalb: per `cec-client -l`
bzw. `cat /sys/class/drm/*/status` pruefen, welcher Port tatsaechlich
verbunden ist, und den passenden Adapter in config.yaml
(`tv_control.cec_adapter`, z.B. "/dev/cec1") eintragen.

Am Samsung-TV muss zusaetzlich "Anynet+" UND "Auto Turn Off" aktiviert sein -
ohne "Auto Turn Off" ignoriert Samsung oft den Standby-Befehl (bekanntes
Community-Problem).
"""

from __future__ import annotations

import logging
import subprocess
import time

from app.config import Config
from app.tv_control.base import TVController

logger = logging.getLogger(__name__)

CEC_TIMEOUT_SECONDS = 15


class CECController(TVController):
    def __init__(self, cfg: Config):
        self.device = cfg.tv_control.cec_device
        self.adapter = cfg.tv_control.cec_adapter or None

    def _cec_command(self, command: str) -> str:
        args = ["cec-client"]
        if self.adapter:
            args.append(self.adapter)
        args += ["-s", "-d", "1"]

        result = subprocess.run(
            args,
            input=command + "\n",
            capture_output=True,
            text=True,
            timeout=CEC_TIMEOUT_SECONDS,
        )
        return result.stdout

    def turn_on(self) -> None:
        logger.info("CEC: Fernseher einschalten (Geraet %s, Adapter %s)", self.device, self.adapter or "auto")
        # "on" weckt den Fernseher nur aus dem Standby, wechselt aber nicht die
        # Eingangsquelle. "as" (Active Source) macht den Pi zur aktiven Quelle,
        # damit der Fernseher automatisch auf den richtigen HDMI-Eingang
        # umschaltet, statt bei der zuletzt genutzten Quelle zu bleiben. Zwei
        # getrennte Aufrufe mit kurzer Pause, damit der Fernseher Zeit hat,
        # aus dem Standby aufzuwachen, bevor die aktive Quelle beansprucht wird.
        self._cec_command(f"on {self.device}")
        time.sleep(2)
        self._cec_command("as")

    def turn_off(self) -> None:
        logger.info("CEC: Fernseher in Standby (Geraet %s, Adapter %s)", self.device, self.adapter or "auto")
        self._cec_command(f"standby {self.device}")

    def is_on(self) -> bool | None:
        output = self._cec_command(f"pow {self.device}")
        lowered = output.lower()
        if "power status: on" in lowered:
            return True
        if "power status: standby" in lowered:
            return False
        logger.warning("CEC: Power-Status nicht eindeutig ermittelbar:\n%s", output)
        return None
