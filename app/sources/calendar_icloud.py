"""iCloud-Kalender ueber CalDAV.

Braucht ein App-spezifisches Passwort (appleid.apple.com -> Anmelden und Sicherheit
-> App-spezifische Passwoerter), NICHT das normale Apple-ID-Passwort.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import caldav

from app.config import Config
from app.sources.calendar_common import CalendarEvent, dedupe_and_sort, event_for_day

ICLOUD_CALDAV_URL = "https://caldav.icloud.com"


def get_todays_events(cfg: Config, day: date | None = None) -> list[CalendarEvent]:
    if not cfg.calendars.icloud.enabled:
        return []

    apple_id = cfg.secrets.icloud_apple_id
    app_password = cfg.secrets.icloud_app_specific_password
    if not apple_id or not app_password:
        raise ValueError(
            "ICLOUD_APPLE_ID / ICLOUD_APP_SPECIFIC_PASSWORD fehlen in .env"
        )

    day = day or date.today()
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)

    client = caldav.DAVClient(url=ICLOUD_CALDAV_URL, username=apple_id, password=app_password)
    principal = client.principal()

    name_filter = set(cfg.calendars.icloud.calendar_names)
    events: list[CalendarEvent] = []

    for cal in principal.calendars():
        if name_filter and cal.name not in name_filter:
            continue
        results = cal.search(start=start, end=end, event=True, expand=True)
        for result in results:
            comp = result.icalendar_component
            dtstart = comp["dtstart"].dt
            dtend = comp["dtend"].dt if "dtend" in comp else dtstart
            title = str(comp.get("summary", "(ohne Titel)")).strip()
            events.append(event_for_day(title, dtstart, dtend, day, "icloud"))

    return dedupe_and_sort(events)
