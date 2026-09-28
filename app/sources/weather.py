"""Wetter ueber Open-Meteo (kostenlos, kein API-Key noetig).

Liefert neben dem aktuellen Wetter auch die naechsten Stunden und Tage fuers
Dashboard. Symbole kommen als Schluessel ("sun", "rain", ...) statt als Emoji:
der Kiosk-Chromium auf dem Pi hat keine Emoji-Schrift, das Dashboard zeichnet
die Symbole selbst (SVG).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from functools import lru_cache

import requests

from app.config import Config

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_SLOTS = 6
HOURLY_STEP = 2       # alle 2 Stunden -> deckt die naechsten 12 h ab
FORECAST_DAYS = 4     # heute + 3 Tage

# WMO Weather interpretation codes -> (deutsche Beschreibung, Symbol)
WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("Klarer Himmel", "sun"),
    1: ("Überwiegend klar", "sun-cloud"),
    2: ("Teilweise bewölkt", "sun-cloud"),
    3: ("Bedeckt", "cloud"),
    45: ("Nebel", "fog"),
    48: ("Reifnebel", "fog"),
    51: ("Leichter Nieselregen", "drizzle"),
    53: ("Mäßiger Nieselregen", "drizzle"),
    55: ("Starker Nieselregen", "drizzle"),
    56: ("Leichter gefrierender Nieselregen", "sleet"),
    57: ("Starker gefrierender Nieselregen", "sleet"),
    61: ("Leichter Regen", "rain"),
    63: ("Mäßiger Regen", "rain"),
    65: ("Starker Regen", "rain"),
    66: ("Leichter gefrierender Regen", "sleet"),
    67: ("Starker gefrierender Regen", "sleet"),
    71: ("Leichter Schneefall", "snow"),
    73: ("Mäßiger Schneefall", "snow"),
    75: ("Starker Schneefall", "snow"),
    77: ("Schneekörner", "snow"),
    80: ("Leichte Regenschauer", "showers"),
    81: ("Mäßige Regenschauer", "showers"),
    82: ("Heftige Regenschauer", "showers"),
    85: ("Leichte Schneeschauer", "snow"),
    86: ("Starke Schneeschauer", "snow"),
    95: ("Gewitter", "thunder"),
    96: ("Gewitter mit leichtem Hagel", "thunder"),
    99: ("Gewitter mit starkem Hagel", "thunder"),
}
WEEKDAYS_SHORT = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


@dataclass
class WeatherData:
    description: str
    icon: str
    is_day: bool
    temp_current: float
    temp_feels: float
    temp_min: float
    temp_max: float
    precipitation_probability: int
    wind_kmh: float
    city: str | None
    sunrise: str
    sunset: str
    hourly: list[dict] = field(default_factory=list)
    daily: list[dict] = field(default_factory=list)


def _describe(code: int) -> tuple[str, str]:
    return WEATHER_CODES.get(code, ("Unbekannt", "cloud"))


@lru_cache(maxsize=8)
def _geocode(city: str) -> tuple[float, float]:
    resp = requests.get(
        GEOCODING_URL,
        params={"name": city, "count": 1, "language": "de"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json().get("results")
    if not results:
        raise ValueError(f"Ort '{city}' nicht gefunden (Open-Meteo Geocoding)")
    return results[0]["latitude"], results[0]["longitude"]


def get_weather(cfg: Config) -> WeatherData:
    lat, lon = cfg.location.lat, cfg.location.lon
    if lat is None or lon is None:
        if not cfg.location.city:
            raise ValueError("Weder lat/lon noch city in config.yaml gesetzt")
        lat, lon = _geocode(cfg.location.city)

    resp = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m",
            "hourly": "temperature_2m,weather_code,precipitation_probability,is_day",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
            "timezone": "auto",
            "forecast_days": FORECAST_DAYS,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    current = data["current"]
    daily = data["daily"]
    hourly = data["hourly"]
    description, icon = _describe(current["weather_code"])

    # Stundenwerte ab der naechsten vollen Stunde
    now = datetime.fromisoformat(current["time"])
    upcoming = [i for i, t in enumerate(hourly["time"]) if datetime.fromisoformat(t) > now]
    hours = []
    for i in upcoming[: HOURLY_SLOTS * HOURLY_STEP : HOURLY_STEP]:
        hours.append({
            "time": hourly["time"][i][11:16],
            "icon": _describe(hourly["weather_code"][i])[1],
            "is_day": bool(hourly["is_day"][i]),
            "temp": hourly["temperature_2m"][i],
            "rain": hourly["precipitation_probability"][i] or 0,
        })

    days = []
    for i, day in enumerate(daily["time"][1:FORECAST_DAYS], start=1):
        days.append({
            "day": WEEKDAYS_SHORT[datetime.fromisoformat(day).weekday()],
            "icon": _describe(daily["weather_code"][i])[1],
            "min": daily["temperature_2m_min"][i],
            "max": daily["temperature_2m_max"][i],
            "rain": daily["precipitation_probability_max"][i] or 0,
        })

    return WeatherData(
        description=description,
        icon=icon,
        is_day=bool(current["is_day"]),
        temp_current=current["temperature_2m"],
        temp_feels=current["apparent_temperature"],
        temp_min=daily["temperature_2m_min"][0],
        temp_max=daily["temperature_2m_max"][0],
        precipitation_probability=daily["precipitation_probability_max"][0] or 0,
        wind_kmh=current["wind_speed_10m"],
        city=cfg.location.city,
        sunrise=daily["sunrise"][0][11:16],
        sunset=daily["sunset"][0][11:16],
        hourly=hours,
        daily=days,
    )
