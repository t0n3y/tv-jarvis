"""Laedt config.yaml + .env und stellt sie als typisierte Objekte bereit.

Aufruf ueberall im Projekt: `from app.config import get_config; cfg = get_config()`
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent


def resolve_path(relative: str) -> Path:
    """Relative Pfade aus der Config sind immer relativ zum Projekt-Root gemeint."""
    p = Path(relative)
    return p if p.is_absolute() else ROOT_DIR / p


@dataclass
class LocationConfig:
    city: str | None
    lat: float | None
    lon: float | None


@dataclass
class ScheduleWindow:
    wake_time: str
    leave_time: str


@dataclass
class ScheduleConfig:
    weekday: ScheduleWindow
    weekend: ScheduleWindow

    def for_weekday(self, iso_weekday: int) -> ScheduleWindow:
        """iso_weekday: 1=Montag ... 7=Sonntag"""
        return self.weekend if iso_weekday >= 6 else self.weekday

    def is_school_day(self, iso_weekday: int) -> bool:
        return iso_weekday < 6


@dataclass
class TVControlConfig:
    backend: str
    cec_device: str
    cec_adapter: str
    boot_wait_seconds: float


@dataclass
class GoogleCalendarConfig:
    enabled: bool
    ics_urls: list[str] = field(default_factory=list)


@dataclass
class ICloudCalendarConfig:
    enabled: bool
    calendar_names: list[str] = field(default_factory=list)


@dataclass
class CalendarsConfig:
    google: GoogleCalendarConfig
    icloud: ICloudCalendarConfig


@dataclass
class IServConfig:
    enabled: bool
    base_url: str
    vertretungsplan_path: str
    login_path: str
    selectors: dict[str, str]


@dataclass
class TodosConfig:
    provider: str
    cache_file: Path
    notion_database_id: str


@dataclass
class AudioConfig:
    # ALSA-Geraetename fuer den HDMI-Port, an dem der Fernseher haengt, z.B.
    # "plughw:CARD=vc4hdmi1,DEV=0" (siehe README, Abschnitt CEC/Audio-Port
    # ermitteln - der Pi 4 hat zwei HDMI-Audio-Karten, "default" trifft nicht
    # zuverlaessig den richtigen Port). Leer = ALSA-Standardgeraet.
    alsa_device: str


@dataclass
class RadioConfig:
    enabled: bool
    stream_url: str
    volume: int


@dataclass
class JellyfinConfig:
    # Vom Pi aus gesehen - Dashboard-Server und Jellyfin laufen auf demselben
    # Geraet, daher bewusst localhost statt der oeffentlichen Tunnel-Adresse.
    url: str
    # Wessen Bibliothek/"Weiterschauen"-Stand die Fernbedienung nutzt.
    username: str


@dataclass
class TTSConfig:
    voice: str
    model_dir: Path
    speed: float


@dataclass
class DashboardConfig:
    host: str
    port: int
    title: str
    boot_animation_seconds: float
    shutdown_animation_seconds: float


@dataclass
class Secrets:
    iserv_username: str | None
    iserv_password: str | None
    icloud_apple_id: str | None
    icloud_app_specific_password: str | None
    notion_token: str | None
    todos_webhook_secret: str | None
    remote_control_secret: str | None
    jellyfin_api_key: str | None


@dataclass
class Config:
    location: LocationConfig
    schedule: ScheduleConfig
    tv_control: TVControlConfig
    calendars: CalendarsConfig
    iserv: IServConfig
    todos: TodosConfig
    audio: AudioConfig
    radio: RadioConfig
    jellyfin: JellyfinConfig
    tts: TTSConfig
    dashboard: DashboardConfig
    secrets: Secrets


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(
            f"{path} nicht gefunden. Kopiere config.example.yaml nach config.yaml "
            "und passe es an."
        )
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_config(config_path: Path | None = None, env_path: Path | None = None) -> Config:
    load_dotenv(env_path or (ROOT_DIR / ".env"))
    raw = _load_yaml(config_path or (ROOT_DIR / "config.yaml"))

    loc = raw.get("location", {})
    sched = raw.get("schedule", {})
    tvc = raw.get("tv_control", {})
    cals = raw.get("calendars", {})
    isv = raw.get("iserv", {})
    todos = raw.get("todos", {})
    audio = raw.get("audio", {})
    radio = raw.get("radio", {})
    jellyfin = raw.get("jellyfin", {})
    tts = raw.get("tts", {})
    dash = raw.get("dashboard", {})

    return Config(
        location=LocationConfig(
            city=loc.get("city"),
            lat=loc.get("lat"),
            lon=loc.get("lon"),
        ),
        schedule=ScheduleConfig(
            weekday=ScheduleWindow(**sched.get("weekday", {})),
            weekend=ScheduleWindow(**sched.get("weekend", {})),
        ),
        tv_control=TVControlConfig(
            backend=tvc.get("backend", "cec"),
            cec_device=str(tvc.get("cec_device", "0")),
            cec_adapter=tvc.get("cec_adapter", ""),
            boot_wait_seconds=float(tvc.get("boot_wait_seconds", 3)),
        ),
        calendars=CalendarsConfig(
            google=GoogleCalendarConfig(**cals.get("google", {"enabled": False})),
            icloud=ICloudCalendarConfig(**cals.get("icloud", {"enabled": False})),
        ),
        iserv=IServConfig(
            enabled=isv.get("enabled", False),
            base_url=isv.get("base_url", ""),
            vertretungsplan_path=isv.get("vertretungsplan_path", ""),
            login_path=isv.get("login_path", ""),
            selectors=isv.get("selectors", {}),
        ),
        todos=TodosConfig(
            provider=todos.get("provider", "icloud_shortcut"),
            cache_file=resolve_path(
                todos.get("icloud_shortcut", {}).get("cache_file", "data/todos_cache.json")
            ),
            notion_database_id=todos.get("notion", {}).get("database_id", ""),
        ),
        audio=AudioConfig(
            alsa_device=audio.get("alsa_device", ""),
        ),
        radio=RadioConfig(
            enabled=radio.get("enabled", True),
            stream_url=radio.get("stream_url", ""),
            volume=int(radio.get("volume", 25)),
        ),
        jellyfin=JellyfinConfig(
            url=str(jellyfin.get("url", "http://127.0.0.1:8096")).rstrip("/"),
            username=jellyfin.get("username", ""),
        ),
        tts=TTSConfig(
            voice=tts.get("voice", "de_DE-thorsten-medium"),
            model_dir=resolve_path(tts.get("model_dir", "data/piper-voices")),
            speed=float(tts.get("speed", 1.0)),
        ),
        dashboard=DashboardConfig(
            host=dash.get("host", "127.0.0.1"),
            port=int(dash.get("port", 8080)),
            title=dash.get("title", "JARVIS"),
            boot_animation_seconds=float(dash.get("boot_animation_seconds", 4)),
            shutdown_animation_seconds=float(dash.get("shutdown_animation_seconds", 1.5)),
        ),
        secrets=Secrets(
            iserv_username=os.environ.get("ISERV_USERNAME") or None,
            iserv_password=os.environ.get("ISERV_PASSWORD") or None,
            icloud_apple_id=os.environ.get("ICLOUD_APPLE_ID") or None,
            icloud_app_specific_password=os.environ.get("ICLOUD_APP_SPECIFIC_PASSWORD") or None,
            notion_token=os.environ.get("NOTION_TOKEN") or None,
            todos_webhook_secret=os.environ.get("TODOS_WEBHOOK_SECRET") or None,
            remote_control_secret=os.environ.get("REMOTE_CONTROL_SECRET") or None,
            jellyfin_api_key=os.environ.get("JELLYFIN_API_KEY") or None,
        ),
    )


@lru_cache(maxsize=1)
def get_config() -> Config:
    return load_config()
