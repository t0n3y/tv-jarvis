"""IServ-Login + Vertretungsplan-Scraping.

WICHTIG: Jede Schule konfiguriert IServ anders (natives Plan-Modul, oder ein
eingebundenes Untis/DAVINCI/Stundenplan24-Fenster). Dieses Modul ist ein
generisches Grundgeruest:

1. Login per Formular (CSRF-Token holen, dann POST mit Zugangsdaten)
2. Abruf der in config.yaml hinterlegten Vertretungsplan-Seite
3. Parsing der HTML-Tabelle anhand der konfigurierbaren CSS-Selektoren

Nach dem ersten Deploy MUSS das an die echte Seite eurer Schule angepasst werden
(siehe README, Abschnitt "IServ-Feinschliff"). Bis dahin gibt get_vertretungsplan()
ggf. eine leere Liste zurueck, statt das ganze Briefing zu blockieren.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from app.config import Config


@dataclass
class SubstitutionEntry:
    lesson: str
    subject: str
    room: str
    note: str


class IServError(RuntimeError):
    pass


def _login(session: requests.Session, cfg: Config) -> None:
    username = cfg.secrets.iserv_username
    password = cfg.secrets.iserv_password
    if not username or not password:
        raise IServError("ISERV_USERNAME / ISERV_PASSWORD fehlen in .env")

    login_url = cfg.iserv.base_url.rstrip("/") + cfg.iserv.login_path

    # Erstmal die Login-Seite holen, um ein evtl. CSRF-Token zu extrahieren.
    get_resp = session.get(login_url, timeout=15)
    get_resp.raise_for_status()
    soup = BeautifulSoup(get_resp.text, "html.parser")

    payload = {"_username": username, "_password": password}
    csrf_input = soup.find("input", {"name": "_csrf_token"})
    if csrf_input and csrf_input.get("value"):
        payload["_csrf_token"] = csrf_input["value"]

    post_resp = session.post(login_url, data=payload, timeout=15)
    post_resp.raise_for_status()

    if "login" in post_resp.url and "logout" not in post_resp.url:
        raise IServError(
            "IServ-Login vermutlich fehlgeschlagen (wieder auf der Login-Seite "
            "gelandet) - Zugangsdaten oder login_path/CSRF-Handling in "
            "config.yaml pruefen."
        )


def _parse_plan(html: str, selectors: dict[str, str]) -> list[SubstitutionEntry]:
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select(selectors.get("row", "table.plan tbody tr"))

    entries: list[SubstitutionEntry] = []
    for row in rows:
        def text_of(key: str) -> str:
            sel = selectors.get(key)
            if not sel:
                return ""
            el = row.select_one(sel)
            return el.get_text(strip=True) if el else ""

        entry = SubstitutionEntry(
            lesson=text_of("lesson"),
            subject=text_of("subject"),
            room=text_of("room"),
            note=text_of("note"),
        )
        if any([entry.lesson, entry.subject, entry.room, entry.note]):
            entries.append(entry)

    return entries


def get_vertretungsplan(cfg: Config) -> list[SubstitutionEntry]:
    if not cfg.iserv.enabled:
        return []

    session = requests.Session()
    _login(session, cfg)

    plan_url = cfg.iserv.base_url.rstrip("/") + cfg.iserv.vertretungsplan_path
    resp = session.get(plan_url, timeout=15)
    resp.raise_for_status()

    return _parse_plan(resp.text, cfg.iserv.selectors)
