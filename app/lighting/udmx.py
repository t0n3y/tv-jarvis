"""Treiber fuer den uDMX-USB-Adapter (anyma.ch, USB-ID 16c0:05dc).

Der uDMX ist kein serieller Adapter (kein /dev/ttyUSB), sondern wird per
USB-Control-Transfer angesprochen: ein Vendor-Request setzt einen Bereich von
DMX-Kanaelen, die Firmware sendet das zuletzt gesetzte Universum danach
selbststaendig und dauerhaft weiter. Ein eigener Refresh-Loop ist also nicht
noetig - geschrieben wird nur, wenn sich etwas aendert.

Zugriff ohne root braucht eine udev-Regel (siehe README, Abschnitt Licht).

Testen auf dem Pi:
    .venv/bin/python -m app.lighting.udmx 1 255 255 0 0     # ab Kanal 1: 255,255,0,0
    .venv/bin/python -m app.lighting.udmx off               # alle Kanaele auf 0
"""

from __future__ import annotations

import sys

import usb.core

VENDOR_ID = 0x16C0
PRODUCT_ID = 0x05DC
UNIVERSE_SIZE = 512

# Vendor | Device | Host->Geraet
_REQUEST_TYPE_OUT = 0x40
_CMD_SET_CHANNEL_RANGE = 2
_TIMEOUT_MS = 1000
_EOVERFLOW = 75


class UDMXError(RuntimeError):
    pass


class UDMX:
    def __init__(self) -> None:
        self._device = None

    def _open(self):
        if self._device is None:
            device = usb.core.find(idVendor=VENDOR_ID, idProduct=PRODUCT_ID)
            if device is None:
                raise UDMXError("uDMX-Adapter nicht gefunden - ist er eingesteckt?")
            self._device = device
        return self._device

    def send(self, start_channel: int, values: list[int]) -> None:
        """Setzt Kanaele ab start_channel (1-basiert, wie am Scheinwerfer)."""
        if not 1 <= start_channel <= UNIVERSE_SIZE:
            raise ValueError(f"Kanal {start_channel} ausserhalb 1-{UNIVERSE_SIZE}")
        if start_channel - 1 + len(values) > UNIVERSE_SIZE:
            raise ValueError("Zu viele Werte fuer das DMX-Universum")
        data = bytes(max(0, min(255, int(v))) for v in values)
        try:
            self._open().ctrl_transfer(
                _REQUEST_TYPE_OUT, _CMD_SET_CHANNEL_RANGE,
                len(data), start_channel - 1, data, _TIMEOUT_MS,
            )
        except usb.core.USBError as exc:
            # Nachbauten (Seriennummer "ilLUTZminator") quittieren den Transfer
            # mit EOVERFLOW, uebernehmen die Werte aber korrekt (am Geraet geprueft).
            if exc.errno == _EOVERFLOW:
                return
            # Adapter abgezogen/neu verbunden: beim naechsten Mal neu suchen
            self._device = None
            if exc.errno == 13:
                raise UDMXError("Keine Berechtigung fuer den uDMX-Adapter (udev-Regel fehlt)") from exc
            raise UDMXError(f"uDMX-Uebertragung fehlgeschlagen: {exc}") from exc

    def blackout(self) -> None:
        self.send(1, [0] * UNIVERSE_SIZE)


def _main(args: list[str]) -> None:
    dmx = UDMX()
    if args == ["off"]:
        dmx.blackout()
        return
    if len(args) < 2:
        raise SystemExit(__doc__)
    dmx.send(int(args[0]), [int(v) for v in args[1:]])


if __name__ == "__main__":
    _main(sys.argv[1:])
