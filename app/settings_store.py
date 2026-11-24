"""Einstellungen, die man in der Fernbedienung aendert (Einrichtung, App Store).

Schichten, jede ueberschreibt die vorige:
  1. config.example.yaml  - mitgelieferte Standardwerte
  2. config.yaml          - optional, fuer alle, die lieber Dateien bearbeiten
  3. data/settings.json   - was in der Fernbedienung eingestellt wurde
Zugangsdaten (Passwoerter, API-Schluessel) stehen nie in settings.json,
sondern in .env (nur fuer den eigenen Benutzer lesbar).

data/settings.json:
  {"setup_done": true, "apps": {"iserv": true, ...}, "config": {...}}
"""

from __future__ import annotations

import copy
import json
import os
import re
import secrets
import threading
from pathlib import Path

from app.config import ROOT_DIR, get_config

SETTINGS_FILE = ROOT_DIR / "data" / "settings.json"
ENV_FILE = ROOT_DIR / ".env"
DEFAULT_NAME = "RPi TV"
SECRET_KEYS = {
    "ISERV_USERNAME",
    "ISERV_PASSWORD",
    "ICLOUD_APPLE_ID",
    "ICLOUD_APP_SPECIFIC_PASSWORD",
    "NOTION_TOKEN",
    "TODOS_WEBHOOK_SECRET",
    "REMOTE_CONTROL_SECRET",
    "JELLYFIN_API_KEY",
}
_lock = threading.Lock()


def _legacy_install() -> bool:
    """Bestehende Installation von vor der Einrichtung per Fernbedienung:
    config.yaml von Hand gepflegt -> nichts neu abfragen, alle Apps an."""
    return (ROOT_DIR / "config.yaml").exists()


def load() -> dict:
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"setup_done": _legacy_install(), "apps": None, "config": {}}
    data.setdefault("config", {})
    data.setdefault("apps", None)
    data.setdefault("setup_done", False)
    return data


def _save(data: dict) -> None:
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)
    get_config.cache_clear()


def deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def get_path(data: dict, path: str, default=None):
    node = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _set_path(data: dict, path: str, value) -> None:
    parts = path.split(".")
    node = data
    for part in parts[:-1]:
        node = node.setdefault(part, {})
    node[parts[-1]] = value


def update(config: dict | None = None, apps: dict | None = None, setup_done: bool | None = None) -> dict:
    """config: {"pfad.zum.wert": wert}; apps: {"id": an/aus}."""
    with _lock:
        data = load()
        for path, value in (config or {}).items():
            _set_path(data["config"], path, value)
        if apps:
            current = data["apps"] if isinstance(data["apps"], dict) else {}
            current.update({k: bool(v) for k, v in apps.items()})
            data["apps"] = current
        if setup_done is not None:
            data["setup_done"] = bool(setup_done)
        _save(data)
        return data


def name() -> str:
    return get_config().dashboard.title or DEFAULT_NAME


# ---------- Zugangsdaten in .env ----------

def secret_is_set(key: str) -> bool:
    return bool(os.environ.get(key))


def set_secrets(values: dict) -> None:
    """Schreibt Zugangsdaten in .env (leerer Wert = loeschen) und uebernimmt
    sie sofort in den laufenden Prozess."""
    with _lock:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
        for key, value in values.items():
            if key not in SECRET_KEYS:
                raise ValueError(f"Unbekannter Schlüssel {key}")
            value = str(value or "").strip()
            if "\n" in value or "\r" in value:
                raise ValueError("Zeilenumbrüche sind nicht erlaubt")
            entry = f"{key}={value}"
            pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
            for i, line in enumerate(lines):
                if pattern.match(line):
                    lines[i] = entry
                    break
            else:
                lines.append(entry)
            if value:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)
        tmp = ENV_FILE.with_suffix(".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(ENV_FILE)
        get_config.cache_clear()


def new_password() -> str:
    """Vorschlag fuer das Passwort der Fernbedienung: gut tippbar, sicher."""
    alphabet = "abcdefghjkmnpqrstuvwxyz23456789"
    return "-".join("".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(4))
