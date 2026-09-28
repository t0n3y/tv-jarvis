"""Schul-Einstellungen, die man in der Fernbedienung aendert (Einstellungen ->
Schule): die eigenen Kurse fuer den Vertretungsplan.

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
_lock = threading.Lock()


def _normalize(course: str) -> str:
    return re.sub(r"\s+", " ", str(course)).strip().upper()


def load(cfg: Config) -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
        courses = [_normalize(c) for c in data.get("kurse", []) if str(c).strip()]
    except (OSError, ValueError):
        courses = [_normalize(c) for c in cfg.iserv.kurse]
    return {"klasse": cfg.iserv.klasse, "kurse": courses}


def courses(cfg: Config) -> list[str]:
    return load(cfg)["kurse"]


def save_courses(raw: list) -> list[str]:
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
    with _lock:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps({"kurse": result}, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
    return result
