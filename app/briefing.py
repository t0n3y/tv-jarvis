"""Sammelt alle Datenquellen und baut daraus Sprechtext + strukturierte Daten
fuers Dashboard. Ein Ausfall einer einzelnen Quelle darf das ganze Briefing
nicht blockieren - Fehler werden pro Quelle abgefangen und geloggt.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from app.config import Config
from app.sources import calendar_google, calendar_icloud, iserv, todos, weather
from app.sources.calendar_common import CalendarEvent, dedupe_and_sort

logger = logging.getLogger(__name__)

SOURCE_TIMEOUT_SECONDS = 20

WEEKDAY_NAMES_DE = [
    "Montag", "Dienstag", "Mittwoch", "Donnerstag",
    "Freitag", "Samstag", "Sonntag",
]


@dataclass
class BriefingData:
    generated_at: str
    weekday: str
    date_label: str
    is_school_day: bool
    weather: dict[str, Any] | None
    events: list[dict[str, Any]]
    substitution_plan: list[dict[str, Any]]
    todos: list[str]
    errors: list[str] = field(default_factory=list)
    speech_text: str = ""


def _run_sources_parallel(
    jobs: dict[str, Callable[[], Any]], errors: list[str]
) -> dict[str, Any]:
    """Fuehrt alle Quellen-Abfragen gleichzeitig aus (ein Thread pro Quelle),
    statt sie nacheinander abzuwarten - eine langsame Quelle bremst die anderen
    nicht aus."""
    results: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=max(len(jobs), 1)) as executor:
        futures = {name: executor.submit(fn) for name, fn in jobs.items()}
        for name, future in futures.items():
            try:
                results[name] = future.result(timeout=SOURCE_TIMEOUT_SECONDS)
            except FutureTimeoutError:
                msg = f"{name}: Zeitüberschreitung nach {SOURCE_TIMEOUT_SECONDS}s"
                logger.warning(msg)
                errors.append(msg)
                results[name] = None
            except Exception as exc:  # noqa: BLE001 - eine Quelle darf nicht alles blockieren
                msg = f"{name}: {exc}"
                logger.warning(msg, exc_info=True)
                errors.append(msg)
                results[name] = None
    return results


def _format_event(ev: CalendarEvent) -> dict[str, Any]:
    return {
        "title": ev.title,
        "time_label": ev.time_label,
        "all_day": ev.all_day,
        "source": ev.source,
    }


def _speech_for_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return "Heute stehen keine Termine in deinem Kalender."
    parts = [f"{e['title']} um {e['time_label']}" if not e["all_day"] else e["title"] for e in events]
    return "Deine Termine heute: " + "; ".join(parts) + "."


def _speech_for_weather(w: dict[str, Any] | None) -> str:
    if not w:
        return "Für das Wetter liegen gerade keine Daten vor."
    return (
        f"Das Wetter: {w['description']}, aktuell {w['temp_current']:.0f} Grad, "
        f"heute zwischen {w['temp_min']:.0f} und {w['temp_max']:.0f} Grad, "
        f"Regenwahrscheinlichkeit {w['precipitation_probability']} Prozent."
    )


def _speech_for_plan(plan: list[dict[str, Any]], is_school_day: bool) -> str:
    if not is_school_day:
        return ""
    if not plan:
        return "Im Vertretungsplan gibt es heute keine Änderungen."
    parts = [
        f"{p['lesson']}: {p['subject']}" + (f" in {p['room']}" if p["room"] else "") +
        (f", {p['note']}" if p["note"] else "")
        for p in plan
    ]
    return "Vertretungsplan: " + "; ".join(parts) + "."


def _speech_for_todos(items: list[str]) -> str:
    if not items:
        return "Für heute sind keine ToDos eingetragen."
    return "Deine ToDos heute: " + "; ".join(items) + "."


def build_briefing(cfg: Config, today: date | None = None) -> BriefingData:
    today = today or date.today()
    iso_weekday = today.isoweekday()
    is_school_day = cfg.schedule.is_school_day(iso_weekday)
    errors: list[str] = []

    jobs: dict[str, Callable[[], Any]] = {
        "Wetter": lambda: weather.get_weather(cfg),
        "Google-Kalender": lambda: calendar_google.get_todays_events(cfg, today),
        "iCloud-Kalender": lambda: calendar_icloud.get_todays_events(cfg, today),
        "ToDos": lambda: todos.get_todos(cfg),
    }
    if is_school_day:
        jobs["IServ-Vertretungsplan"] = lambda: iserv.get_vertretungsplan(cfg)

    results = _run_sources_parallel(jobs, errors)

    weather_data = results.get("Wetter")
    google_events = results.get("Google-Kalender") or []
    icloud_events = results.get("iCloud-Kalender") or []
    all_events = dedupe_and_sort([*google_events, *icloud_events])
    substitution_plan: list[Any] = results.get("IServ-Vertretungsplan") or []
    todo_items = results.get("ToDos") or []

    weather_dict = asdict(weather_data) if weather_data else None
    events_list = [_format_event(e) for e in all_events]
    plan_list = [asdict(p) for p in substitution_plan]

    greeting = "Guten Morgen!" if iso_weekday < 6 else "Schönen guten Morgen!"
    speech = " ".join(
        filter(
            None,
            [
                f"{greeting} Heute ist {WEEKDAY_NAMES_DE[iso_weekday - 1]}, der {today.strftime('%d.%m.%Y')}.",
                _speech_for_weather(weather_dict),
                _speech_for_events(events_list),
                _speech_for_plan(plan_list, is_school_day),
                _speech_for_todos(todo_items),
            ],
        )
    )

    return BriefingData(
        generated_at=datetime.now().isoformat(),
        weekday=WEEKDAY_NAMES_DE[iso_weekday - 1],
        date_label=today.strftime("%d.%m.%Y"),
        is_school_day=is_school_day,
        weather=weather_dict,
        events=events_list,
        substitution_plan=plan_list,
        todos=todo_items,
        errors=errors,
        speech_text=speech,
    )
