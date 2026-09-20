"""Laufzeit-veraenderbarer Zeitplan (Wecker an/aus + Uhrzeiten).

Getrennt von config.yaml: config.yaml liefert nur den Startwert beim ersten
Lauf, danach lebt der Zeitplan hier und ist ueber die Einstellungen-App auf
der Fernbedienung (POST /api/remote/schedule) veraenderbar, ohne dass
systemd-Units neu geschrieben werden muessen (siehe app/scheduler.py).
"""

from __future__ import annotations

import json
import re

from app.config import Config, ROOT_DIR

SCHEDULE_FILE = ROOT_DIR / "data" / "schedule.json"

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _default_schedule(cfg: Config) -> dict:
    return {
        "enabled": True,
        "weekday": {
            "wake_time": cfg.schedule.weekday.wake_time,
            "leave_time": cfg.schedule.weekday.leave_time,
        },
        "weekend": {
            "wake_time": cfg.schedule.weekend.wake_time,
            "leave_time": cfg.schedule.weekend.leave_time,
        },
    }


def load_schedule(cfg: Config) -> dict:
    if SCHEDULE_FILE.exists():
        try:
            return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    data = _default_schedule(cfg)
    save_schedule(data)
    return data


def _validate_window(window: dict, group: str) -> dict:
    result = {}
    for key in ("wake_time", "leave_time"):
        value = str(window.get(key, ""))
        if not _TIME_RE.match(value):
            raise ValueError(f"ungueltige Uhrzeit fuer {group}.{key}: {value!r}")
        result[key] = value
    return result


def save_schedule(data: dict) -> dict:
    normalized = {
        "enabled": bool(data.get("enabled", True)),
        "weekday": _validate_window(data.get("weekday", {}), "weekday"),
        "weekend": _validate_window(data.get("weekend", {}), "weekend"),
    }
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    SCHEDULE_FILE.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized
