"""Schul-Einstellungen, die man in der Fernbedienung aendert (Einstellungen ->
Schule): die eigenen Kurse fuer den Vertretungsplan und welches Fach dahinter
steckt ("PA G1" -> "Pädagogik"), damit das Briefing das Fach beim Namen nennt.

Gespeichert in data/school.json. Ohne Datei gelten die Kurse aus config.yaml
(iserv.kurse). Kurse im Format wie auf dem Plan (Spalte "Fach"), z.B.
"BI G1", "D G2", "PPLP1" - Leerzeichen und Gross/klein sind egal.
"""

from __future__ import annotations

import json
import re
import threading

from app.config import ROOT_DIR, Config

SETTINGS_FILE = ROOT_DIR / "data" / "school.json"
MAX_COURSES = 30
_COURSE_RE = re.compile(r"^[A-Za-z0-9ÄÖÜäöü][A-Za-z0-9ÄÖÜäöü _./-]{0,15}$")
MAX_SUBJECT_LENGTH = 40
_lock = threading.Lock()


def _normalize(course: str) -> str:
    return re.sub(r"\s+", " ", str(course)).strip().upper()


def _key(course: str) -> str:
    return re.sub(r"\s+", "", str(course)).upper()


def load(cfg: Config) -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        courses = [_normalize(c) for c in data.get("kurse", []) if str(c).strip()]
        names = {_normalize(k): str(v).strip() for k, v in (data.get("faecher") or {}).items() if str(v).strip()}
    except (OSError, ValueError):
        courses = [_normalize(c) for c in cfg.iserv.kurse]
        names = {}
    return {"klasse": cfg.iserv.klasse, "kurse": courses, "faecher": names}


def subject_names(cfg: Config) -> dict[str, str]:
    """Kurs (ohne Leerzeichen, gross) -> Fachname."""
    return {_key(k): v for k, v in load(cfg)["faecher"].items()}


def subject_name(names: dict[str, str], subject: str) -> str:
    """Fachname zu einem Eintrag aus der Spalte "Fach" - "" wenn unbekannt."""
    return names.get(_key(subject), "")


def courses(cfg: Config) -> list[str]:
    return load(cfg)["kurse"]


def save_courses(raw: list, raw_names: dict | None = None) -> list[str]:
    if not isinstance(raw, list):
        raise ValueError("kurse muss eine Liste sein")
    result: list[str] = []
    for item in raw[:MAX_COURSES]:
        course = _normalize(item)
        if not course:
            continue
        if not _COURSE_RE.match(course):
            raise ValueError(f"„{course}“ sieht nicht wie ein Kurs aus (z. B. BI G1)")
        if course not in result:
            result.append(course)
    names: dict[str, str] = {}
    for course, name in (raw_names or {}).items() if isinstance(raw_names, dict) else []:
        course, name = _normalize(course), re.sub(r"\s+", " ", str(name)).strip()
        if course in result and name:
            names[course] = name[:MAX_SUBJECT_LENGTH]
    with _lock:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kurse": result, "faecher": names}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
    return result
