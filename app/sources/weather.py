"""Wetter ueber Open-Meteo (kostenlos, kein API-Key noetig)."""

from __future__ import annotations

from dataclasses import dataclass

import requests

from app.config import Config

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes -> (deutsche Beschreibung, Emoji fuers Dashboard)
WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("Klarer Himmel", "☀️"),
    1: ("Überwiegend klar", "🌤️"),
    2: ("Teilweise bewölkt", "⛅"),
    3: ("Bedeckt", "☁️"),
    45: ("Nebel", "🌫️"),
    48: ("Reifnebel", "🌫️"),
    51: ("Leichter Nieselregen", "🌦️"),
    53: ("Mäßiger Nieselregen", "🌦️"),
    55: ("Starker Nieselregen", "🌧️"),
    56: ("Leichter gefrierender Nieselregen", "🌧️"),
    57: ("Starker gefrierender Nieselregen", "🌧️"),
    61: ("Leichter Regen", "🌧️"),
    63: ("Mäßiger Regen", "🌧️"),
    65: ("Starker Regen", "🌧️"),
    66: ("Leichter gefrierender Regen", "🌧️"),
    67: ("Starker gefrierender Regen", "🌧️"),
    71: ("Leichter Schneefall", "🌨️"),
    73: ("Mäßiger Schneefall", "🌨️"),
    75: ("Starker Schneefall", "❄️"),
    77: ("Schneekörner", "❄️"),
    80: ("Leichte Regenschauer", "🌦️"),
    81: ("Mäßige Regenschauer", "🌧️"),
    82: ("Heftige Regenschauer", "⛈️"),
    85: ("Leichte Schneeschauer", "🌨️"),
    86: ("Starke Schneeschauer", "❄️"),
    95: ("Gewitter", "⛈️"),
    96: ("Gewitter mit leichtem Hagel", "⛈️"),
    99: ("Gewitter mit starkem Hagel", "⛈️"),
}


@dataclass
class WeatherData:
    description: str
    icon: str
    temp_current: float
    temp_min: float
    temp_max: float
    precipitation_probability: int


def _describe(code: int) -> tuple[str, str]:
    return WEATHER_CODES.get(code, ("Unbekannt", "❓"))


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
            "current": "temperature_2m,weather_code,precipitation_probability",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto",
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    current = data["current"]
    daily = data["daily"]
    description, icon = _describe(current["weather_code"])

    return WeatherData(
        description=description,
        icon=icon,
        temp_current=current["temperature_2m"],
        temp_min=daily["temperature_2m_min"][0],
        temp_max=daily["temperature_2m_max"][0],
        precipitation_probability=daily["precipitation_probability_max"][0],
    )
