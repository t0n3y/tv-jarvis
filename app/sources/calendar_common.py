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


def event_for_day(title: str, start: datetime | date, end: datetime | date, day: date, source: str) -> CalendarEvent:
    """Baut den Termin so, wie er an `day` angezeigt werden soll:
    - Zeiten in UTC ("...Z", z.B. aus Google) in die Ortszeit des Pi umrechnen,
      sonst steht ein 8-Uhr-Termin als "06:00" auf dem Dashboard.
    - Mehrtaegige Termine (z.B. Urlaub) an den Folgetagen als ganztaegig
      zeigen statt jeden Tag mit der Uhrzeit vom ersten Tag.
    """
    if isinstance(start, datetime) and start.tzinfo is not None:
        start = start.astimezone()
    if isinstance(end, datetime) and end.tzinfo is not None:
        end = end.astimezone()
    all_day = not isinstance(start, datetime) or start.date() < day
    return CalendarEvent(title=title, start=start, end=end, all_day=all_day, source=source)
