"""Gemeinsame Typen fuer die Kalenderquellen (Google-ICS, iCloud-CalDAV)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class CalendarEvent:
    title: str
    start: datetime | date
    end: datetime | date
    all_day: bool
    source: str  # "google" oder "icloud", fuers Dashboard/Debugging

    @property
    def time_label(self) -> str:
        if self.all_day:
            return "ganztägig"
        return self.start.strftime("%H:%M")

    def sort_key(self):
        if self.all_day:
            # Ganztaegige Termine zuerst anzeigen
            start = self.start if isinstance(self.start, date) else self.start.date()
            return (0, datetime.combine(start, datetime.min.time()))
        return (1, self.start)


def dedupe_and_sort(events: list[CalendarEvent]) -> list[CalendarEvent]:
    seen: set[tuple] = set()
    unique: list[CalendarEvent] = []
    for ev in events:
        key = (ev.title, str(ev.start), str(ev.end))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ev)
    return sorted(unique, key=lambda e: e.sort_key())
