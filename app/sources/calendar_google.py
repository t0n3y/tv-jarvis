"""Google-Kalender ueber die 'Geheime Adresse im iCal-Format' (kein OAuth noetig).

Diese URL findest du in den Google-Kalender-Einstellungen des jeweiligen Kalenders
unter 'Kalender integrieren' -> 'Geheime Adresse im iCal-Format'.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import recurring_ical_events
import requests
from icalendar import Calendar

from app.config import Config
from app.sources.calendar_common import CalendarEvent, dedupe_and_sort


def _fetch_events_for_day(ics_url: str, day: date) -> list[CalendarEvent]:
    resp = requests.get(ics_url, timeout=15)
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.content)

    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    occurrences = recurring_ical_events.of(cal).between(start, end)

    events: list[CalendarEvent] = []
    for comp in occurrences:
        dtstart = comp.get("dtstart").dt
        dtend = comp.get("dtend").dt if comp.get("dtend") else dtstart
        all_day = not isinstance(dtstart, datetime)
        events.append(
            CalendarEvent(
                title=str(comp.get("summary", "(ohne Titel)")),
                start=dtstart,
                end=dtend,
                all_day=all_day,
                source="google",
            )
        )
    return events


def get_todays_events(cfg: Config, day: date | None = None) -> list[CalendarEvent]:
    if not cfg.calendars.google.enabled:
        return []
    day = day or date.today()

    all_events: list[CalendarEvent] = []
    for url in cfg.calendars.google.ics_urls:
        all_events.extend(_fetch_events_for_day(url, day))
    return dedupe_and_sort(all_events)
