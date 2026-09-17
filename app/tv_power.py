"""Gemeinsame Ein-/Ausschalt-Logik, genutzt von morning_routine.py,
leave_routine.py UND der Fernbedienung (POST /api/remote/power).

Bewusst als eigenes Modul, damit "Fernseher an/aus" nur an einer Stelle
implementiert ist, egal ob per Zeitplan oder manuell vom Handy ausgeloest.
"""

from __future__ import annotations

import logging
import time

import requests

from app import kiosk_media, radio, tts
from app.config import Config
from app.dashboard import kiosk
from app.tv_control import get_controller

logger = logging.getLogger(__name__)

FAREWELL_TEXT = "Bis später! Ich schalte jetzt ab."


def _dashboard_url(cfg: Config, path: str) -> str:
    # Bewusst IMMER 127.0.0.1 statt cfg.dashboard.host: der Server kann auf
    # 0.0.0.0 lauschen (fuers Handy im selben WLAN), aber der lokale
    # Selbstaufruf von hier aus funktioniert nur ueber localhost.
    return f"http://127.0.0.1:{cfg.dashboard.port}{path}"


def _post_local(cfg: Config, path: str, json: dict | None = None) -> None:
    headers = {}
    if cfg.secrets.remote_control_secret:
        headers["X-Remote-Secret"] = cfg.secrets.remote_control_secret
    try:
        requests.post(_dashboard_url(cfg, path), json=json, headers=headers, timeout=3)
    except requests.RequestException as exc:
        logger.warning("Aufruf von %s fehlgeschlagen (%s)", path, exc)


def power_on(cfg: Config) -> None:
    tv = get_controller(cfg)
    logger.info("Schalte Fernseher ein ...")
    tv.turn_on()
    time.sleep(cfg.tv_control.boot_wait_seconds)
    kiosk.start(cfg)


def power_off(cfg: Config, farewell: bool = False) -> None:
    logger.info("Stoppe Radio ...")
    radio.stop()
    kiosk_media.stop_youtube(cfg)

    if farewell:
        logger.info("Verabschiedung ...")
        tts.speak(cfg, FAREWELL_TEXT)

    logger.info("Löse Ausschalt-Animation aus ...")
    _post_local(cfg, "/api/shutdown-animation")
    time.sleep(cfg.dashboard.shutdown_animation_seconds + 0.2)

    # Fernseher ZUERST ausschalten, danach erst den Kiosk beenden - sonst ist
    # kurz der Desktop dahinter sichtbar, waehrend der Fernseher noch an ist.
    tv = get_controller(cfg)
    logger.info("Schalte Fernseher aus ...")
    tv.turn_off()

    kiosk.stop()
