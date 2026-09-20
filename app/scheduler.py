"""In-Prozess-Zeitplan: laeuft als Hintergrund-Task im Dashboard-Dienst und
loest morning_routine/leave_routine zur konfigurierten Zeit aus.

Ersetzt die frueheren systemd-Timer (morning-routine.timer/leave-routine.timer):
dashboard.service laeuft ohnehin dauerhaft, und so kann die Einstellungen-App
auf der Fernbedienung Zeiten aendern (app/schedule_store.py), ohne dass der
laufende Dienst systemd-Units neu schreiben oder sudo aufrufen muesste.
"""

from __future__ import annotations

import asyncio
import datetime
import logging

from app import schedule_store
from app.config import Config

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 20


class Scheduler:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._last_wake_date: datetime.date | None = None
        self._last_leave_date: datetime.date | None = None
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        while True:
            try:
                await self._check_once()
            except Exception:  # noqa: BLE001
                logger.exception("Fehler im Zeitplan-Check")
            await asyncio.sleep(CHECK_INTERVAL_SECONDS)

    async def _check_once(self) -> None:
        schedule = schedule_store.load_schedule(self.cfg)
        if not schedule.get("enabled", True):
            return

        now = datetime.datetime.now()
        today = now.date()
        hhmm = now.strftime("%H:%M")
        group = "weekend" if now.isoweekday() >= 6 else "weekday"
        window = schedule[group]

        if hhmm == window["wake_time"] and self._last_wake_date != today:
            self._last_wake_date = today
            logger.info("Zeitplan: Weckzeit erreicht, starte Morgen-Routine")
            await asyncio.to_thread(self._run_morning)

        if hhmm == window["leave_time"] and self._last_leave_date != today:
            self._last_leave_date = today
            logger.info("Zeitplan: Verlasszeit erreicht, starte Verlassen-Routine")
            await asyncio.to_thread(self._run_leave)

    @staticmethod
    def _run_morning() -> None:
        from app.routines import morning_routine

        morning_routine.main()

    @staticmethod
    def _run_leave() -> None:
        from app.routines import leave_routine

        leave_routine.main()
