"""Verwaltet die Liste der Radiosender (Presets + ueber die Einstellungen-App
hinzugefuegte) und welcher Sender gerade ausgewaehlt ist.

Wie schedule_store.py laufzeit-veraenderbar und getrennt von config.yaml, das
nur den ehemals einzigen Stream als Startwert liefert.
"""

from __future__ import annotations

import json
import re

from app.config import Config, ROOT_DIR

STATIONS_FILE = ROOT_DIR / "data" / "radio_stations.json"

DEFAULT_STATIONS = [
    {
        "id": "sunshine-live",
        "name": "Sunshine Live",
        "url": "https://stream.sunshine-live.de/live/mp3-192/stream.sunshine-live.de",
    },
    {
        "id": "1live",
        "name": "1LIVE",
        "url": "https://wdr-1live-live.icecastssl.wdr.de/wdr/1live/live/mp3/128/stream.mp3",
    },
]


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
    return slug or "sender"


def _load(cfg: Config) -> dict:
    if STATIONS_FILE.exists():
        try:
            return json.loads(STATIONS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    stations = [dict(s) for s in DEFAULT_STATIONS]
    known_urls = {s["url"] for s in stations}
    if cfg.radio.stream_url and cfg.radio.stream_url not in known_urls:
        stations.insert(0, {"id": "standard", "name": "Standard", "url": cfg.radio.stream_url})
    data = {"stations": stations, "current_id": stations[0]["id"] if stations else None}
    _save(data)
    return data


def _save(data: dict) -> None:
    STATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def list_stations(cfg: Config) -> dict:
    return _load(cfg)


def add_station(cfg: Config, name: str, url: str) -> dict:
    data = _load(cfg)
    base_id = _slugify(name)
    existing_ids = {s["id"] for s in data["stations"]}
    station_id = base_id
    counter = 2
    while station_id in existing_ids:
        station_id = f"{base_id}-{counter}"
        counter += 1
    data["stations"].append({"id": station_id, "name": name.strip(), "url": url.strip()})
    _save(data)
    return data


def remove_station(cfg: Config, station_id: str) -> dict:
    data = _load(cfg)
    data["stations"] = [s for s in data["stations"] if s["id"] != station_id]
    if data.get("current_id") == station_id:
        data["current_id"] = data["stations"][0]["id"] if data["stations"] else None
    _save(data)
    return data


def set_current(cfg: Config, station_id: str) -> dict:
    data = _load(cfg)
    if not any(s["id"] == station_id for s in data["stations"]):
        raise ValueError(f"unbekannter Sender: {station_id!r}")
    data["current_id"] = station_id
    _save(data)
    return data


def current_station(cfg: Config) -> dict | None:
    data = _load(cfg)
    return next((s for s in data["stations"] if s["id"] == data.get("current_id")), None)
