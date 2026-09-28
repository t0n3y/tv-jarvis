"""Sammelt alle Datenquellen und baut daraus Sprechtext + strukturierte Daten
fuers Dashboard. Ein Ausfall einer einzelnen Quelle darf das ganze Briefing
nicht blockieren - Fehler werden pro Quelle abgefangen und geloggt.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable

from app import school_settings, speech_de as sp
from app.config import Config
from app.sources import calendar_google, calendar_icloud, iserv, todos, weather
from app.sources.calendar_common import CalendarEvent, dedupe_and_sort

logger = logging.getLogger(__name__)

SOURCE_TIMEOUT_SECONDS = 20
# Ab dann auch die Termine von morgen holen (Dashboard wechselt um 20 Uhr)
TOMORROW_FROM_HOUR = 19

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
    # Quellen ohne Zugangsdaten/Adresse: kein Fehler, sondern "noch nicht
    # eingerichtet" (Dashboard zeigt dann einen Hinweis im Panel)
    not_configured: list[str] = field(default_factory=list)
    # Alle ToDos inkl. abgehakter ({"text", "done"}) fuers Dashboard
    todo_entries: list[dict[str, Any]] = field(default_factory=list)
    # Termine des Folgetags - das Dashboard zeigt sie ab 20 Uhr statt "Heute"
    events_tomorrow: list[dict[str, Any]] = field(default_factory=list)


def _is_placeholder(value: str | None) -> bool:
    return not value or "DEINE" in value.upper() or "BEISPIEL" in value.upper()


def _not_configured(cfg: Config) -> set[str]:
    missing = set()
    google = cfg.calendars.google
    if not google.enabled or all(_is_placeholder(url) for url in google.ics_urls):
        missing.add("Google-Kalender")
    if not cfg.calendars.icloud.enabled or not (cfg.secrets.icloud_apple_id and cfg.secrets.icloud_app_specific_password):
        missing.add("iCloud-Kalender")
    if not cfg.iserv.enabled or _is_placeholder(cfg.iserv.base_url) or not (cfg.secrets.iserv_username and cfg.secrets.iserv_password):
        missing.add("IServ-Vertretungsplan")
    # Untis-Plan der ganzen Schule ohne Klassenfilter waeren 100+ Zeilen
    if cfg.iserv.plan_pages and not cfg.iserv.klasse:
        missing.add("IServ-Vertretungsplan")
    if cfg.todos.provider == "notion" and not cfg.secrets.notion_token:
        missing.add("ToDos")
    if cfg.todos.provider == "icloud_shortcut" and not cfg.todos.cache_file.exists():
        missing.add("ToDos")
    return missing


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
        # Fuers Dashboard: laufende Termine hervorheben, vergangene abblenden
        "start": None if ev.all_day else ev.start.isoformat(),
        "end": None if ev.all_day else ev.end.isoformat(),
    }


# Sprechtext: ein Satz pro Zeile, Leerzeile zwischen Abschnitten - app/tts.py
# macht daraus kurze bzw. laengere Pausen.


def _speech_for_events(events: list[dict[str, Any]]) -> str:
    if not events:
        return "Heute stehen keine Termine in deinem Kalender."
    lines = [sp.sentence(f"Du hast heute {sp.count_word(len(events))} {'Termin' if len(events) == 1 else 'Termine'}")]
    for e in events:
        title = sp.times_in_text(e["title"])
        if e["all_day"]:
            lines.append(sp.sentence(f"Den ganzen Tag: {title}"))
        else:
            lines.append(sp.sentence(f"Um {sp.spoken_time(e['time_label'])}: {title}"))
    return "\n".join(lines)


def _speech_for_weather(w: dict[str, Any] | None) -> str:
    if not w:
        return "Für das Wetter liegen gerade keine Daten vor."
    rain = int(w["precipitation_probability"] or 0)
    lines = [
        sp.sentence(f"Das Wetter: {w['description']}, aktuell {w['temp_current']:.0f} Grad"),
        sp.sentence(f"Heute werden es zwischen {w['temp_min']:.0f} und {w['temp_max']:.0f} Grad"),
    ]
    if rain >= 60:
        lines.append(f"Die Regenwahrscheinlichkeit liegt bei {rain} Prozent, nimm besser einen Schirm mit.")
    elif rain >= 25:
        lines.append(f"Die Regenwahrscheinlichkeit liegt bei {rain} Prozent.")
    else:
        lines.append("Regen ist nicht zu erwarten.")
    return "\n".join(lines)


def _plan_sentence(p: dict[str, Any]) -> str:
    subject = p.get("subject_name") or p.get("subject") or "ein Kurs"
    when = sp.lesson_phrase(p.get("lesson", ""))
    kind = (p.get("kind") or "").strip()
    lk = kind.lower()
    room = p.get("room") or ""
    lead = when[0].upper() + when[1:] if when else "Heute"
    if lk == "entfall":
        text = f"{lead} fällt {subject} aus"
        if p.get("note"):
            text += f", {p['note']}"
    elif "raum" in lk:
        text = f"{lead} ist {subject} in Raum {room}" if room else f"{lead} ist {subject} in einem anderen Raum"
    elif "verleg" in lk or "tausch" in lk:
        text = f"{lead} wird {subject} verlegt"
    elif "vertretung" in lk or not lk:
        text = f"{lead} wird {subject} vertreten" + (f", in Raum {room}" if room else "")
    else:
        text = f"{lead}, {subject}: {kind}"
    return sp.sentence(sp.times_in_text(text))


def _speech_for_plan(plan: list[dict[str, Any]], is_school_day: bool, today: date) -> str:
    if not is_school_day:
        return ""
    # Nur der Plan fuer heute - morgens liegt oft schon der fuer morgen vor
    todays = [p for p in plan if (p.get("date") == today.isoformat() if p.get("date") else p.get("day") in ("", "Heute"))]
    if not todays:
        return "Im Vertretungsplan gibt es für dich heute keine Änderungen."
    head = "Im Vertretungsplan gibt es heute eine Änderung für dich." if len(todays) == 1 else \
        f"Im Vertretungsplan gibt es heute {sp.count_word(len(todays))} Änderungen für dich."
    return "\n".join([head, *(_plan_sentence(p) for p in todays)])


def _speech_for_todos(items: list[str]) -> str:
    if not items:
        return "Auf deiner Liste steht heute nichts."
    head = "Auf deiner Liste steht eine Aufgabe." if len(items) == 1 else \
        f"Auf deiner Liste stehen {sp.count_word(len(items))} Aufgaben."
    return "\n".join([head, *(sp.sentence(sp.times_in_text(i)) for i in items)])


def build_briefing(cfg: Config, today: date | None = None) -> BriefingData:
    today = today or date.today()
    iso_weekday = today.isoweekday()
    is_school_day = cfg.schedule.is_school_day(iso_weekday)
    errors: list[str] = []

    jobs: dict[str, Callable[[], Any]] = {
        "Wetter": lambda: weather.get_weather(cfg),
        "Google-Kalender": lambda: calendar_google.get_todays_events(cfg, today),
        "iCloud-Kalender": lambda: calendar_icloud.get_todays_events(cfg, today),
        "ToDos": lambda: todos.get_entries(cfg),
    }
    # Auch am Wochenende holen: sonntags ab 16 Uhr zeigt das Dashboard den
    # Plan fuer Montag
    jobs["IServ-Vertretungsplan"] = lambda: iserv.get_vertretungsplan(cfg)
    tomorrow = today + timedelta(days=1)
    if datetime.now().hour >= TOMORROW_FROM_HOUR:
        jobs["Google-Kalender (morgen)"] = lambda: calendar_google.get_todays_events(cfg, tomorrow)
        jobs["iCloud-Kalender (morgen)"] = lambda: calendar_icloud.get_todays_events(cfg, tomorrow)
    not_configured = _not_configured(cfg)
    jobs = {name: fn for name, fn in jobs.items() if name.split(" (")[0] not in not_configured}

    results = _run_sources_parallel(jobs, errors)

    weather_data = results.get("Wetter")
    google_events = results.get("Google-Kalender") or []
    icloud_events = results.get("iCloud-Kalender") or []
    all_events = dedupe_and_sort([*google_events, *icloud_events])
    substitution_plan: list[Any] = results.get("IServ-Vertretungsplan") or []
    todo_entries = results.get("ToDos") or []
    todo_items = [e["text"] for e in todo_entries if not e["done"]]
    events_tomorrow = dedupe_and_sort([
        *(results.get("Google-Kalender (morgen)") or []),
        *(results.get("iCloud-Kalender (morgen)") or []),
    ])

    weather_dict = asdict(weather_data) if weather_data else None
    events_list = [_format_event(e) for e in all_events]
    plan_list = [asdict(p) for p in substitution_plan]
    names = school_settings.subject_names(cfg)
    for p in plan_list:
        p["subject_name"] = school_settings.subject_name(names, p["subject"])

    greeting = "Guten Morgen!" if iso_weekday < 6 else "Schönen guten Morgen!"
    speech = "\n\n".join(
        filter(
            None,
            [
                f"{greeting}\nHeute ist {WEEKDAY_NAMES_DE[iso_weekday - 1]}, der {sp.spoken_date(today.day, today.month)}.",
                _speech_for_weather(weather_dict),
                _speech_for_events(events_list),
                _speech_for_plan(plan_list, is_school_day, today),
                _speech_for_todos(todo_items),
                "Ich wünsche dir einen schönen Tag!",
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
        not_configured=sorted(not_configured),
        todo_entries=todo_entries,
        events_tomorrow=[_format_event(e) for e in events_tomorrow],
    )
