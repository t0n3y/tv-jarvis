"""Fallback-Implementierung ueber eine Alexa-kompatible Smart-Steckdose.

Noch als Stub, weil das genaue Modell noch nicht feststeht. Sobald ihr euch
entschieden habt, hier die passende lokale Steuerung eintragen, z.B.:

- TP-Link Tapo/Kasa: `python-kasa` (`pip install python-kasa`), lokale Steuerung
  ohne Cloud: `kasa --host <ip> on` / `off`, oder die `kasa.SmartPlug`-Klasse.
- Meross: `meross-iot`, laeuft ueber Merosss Cloud-API (Account noetig).
- Tuya/Smart Life (Govee o.ae.): `tinytuya`, braucht einmalig den lokalen
  "local_key" des Geraets (Anleitung in der tinytuya-Doku).

Wichtig fuers Konzept (siehe Plan): Steckdose AUS = Fernseher verliert komplett
Strom (spart Standby-Verbrauch). Steckdose AN = Fernseher bekommt wieder Strom
und faehrt je nach TV-Einstellung ("Automatisches Einschalten nach
Stromausfall") entweder direkt hoch oder bleibt im Standby - Letzteres in den
TV-Einstellungen aktivieren, falls verfuegbar, dann kann zusaetzlich per CEC
aus dem Standby geweckt werden.
"""

from __future__ import annotations

from app.config import Config
from app.tv_control.base import TVController


class SmartPlugController(TVController):
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def turn_on(self) -> None:
        raise NotImplementedError(
            "Smart-Plug-Backend ist noch nicht implementiert - Marke/Modell "
            "waehlen und hier die Steuerung ergaenzen (siehe Docstring oben)."
        )

    def turn_off(self) -> None:
        raise NotImplementedError(
            "Smart-Plug-Backend ist noch nicht implementiert - Marke/Modell "
            "waehlen und hier die Steuerung ergaenzen (siehe Docstring oben)."
        )

    def is_on(self) -> bool | None:
        return None
