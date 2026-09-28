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

import dataclasses
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from app import school_settings
from app.config import Config


@dataclass
class SubstitutionEntry:
    lesson: str
    subject: str
    room: str
    note: str
    day: str = ""       # z.B. "Heute" / "Morgen" / "Montag" (Untis-Plaene)
    kind: str = ""      # Untis-"Art": Vertretung, Entfall, Raum-Vertretung, ...
    date: str = ""      # Tag des Plans (ISO), aus dem Untis-Titel


class IServError(RuntimeError):
    pass


_META_REFRESH_URL = re.compile(r"url=(.+)$", re.IGNORECASE)
MAX_META_REDIRECTS = 5


def _follow_meta_refresh(session: requests.Session, resp: requests.Response) -> requests.Response:
    """IServ leitet nach der Anmeldung und beim ersten Aufruf jeder App ueber
    eine Zwischenseite mit <meta http-equiv="refresh"> weiter (OpenID-Code
    abholen). requests folgt nur HTTP-Weiterleitungen - diese hier von Hand."""
    for _ in range(MAX_META_REDIRECTS):
        meta = BeautifulSoup(resp.text, "html.parser").find(
            "meta", attrs={"http-equiv": lambda v: v and v.lower() == "refresh"}
        )
        match = _META_REFRESH_URL.search(meta.get("content", "")) if meta else None
        if not match:
            return resp
        resp = session.get(urljoin(resp.url, match.group(1).strip("'\" ")), timeout=15)
        resp.raise_for_status()
    return resp


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

    # Neuere IServ-Versionen leiten /iserv/app/login auf die zentrale
    # Anmeldung (/iserv/auth/login?_target_path=...) um - das Formular hat
    # kein action-Attribut, gehoert also an genau diese Adresse. Danach
    # laufen die Weiterleitungen (OpenID) von selbst zurueck in die App.
    post_resp = session.post(get_resp.url, data=payload, timeout=15)
    post_resp.raise_for_status()
    post_resp = _follow_meta_refresh(session, post_resp)

    still_on_login = BeautifulSoup(post_resp.text, "html.parser").find("input", {"name": "_password"})
    if still_on_login is not None:
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


# ---------- Untis-Vertretungsplan ueber den IServ-Infobildschirm ----------
# Die Schule veroeffentlicht den Untis-Export (subst_001.htm, ganze Schule)
# als Infobildschirm "V Heute"/"V Morgen". Spalten laut Kopfzeile:
# Klasse(n) | Stunde | Schuelergr. | (Lehrer) | (Fach) | (Raum) | Art | Text.
# Geaenderte Werte stehen als "<s>ALT</s>?NEU" (der Pfeil kommt als "?" an).

_UNTIS_COLUMNS = {
    "klasse": "klasse", "stunde": "lesson", "schülergr": "group", "lehrer": "teacher",
    "fach": "subject", "raum": "room", "art": "kind", "text": "text",
}
_GRADE_RE = re.compile(r"^(\d+)([a-z]*)$", re.IGNORECASE)


def _cell(td) -> tuple[str, str]:
    """(neuer Wert, alter Wert) einer Untis-Zelle."""
    old = " ".join(s.get_text(" ", strip=True) for s in td.find_all("s"))
    for s_tag in td.find_all("s"):
        s_tag.decompose()
    new = td.get_text(" ", strip=True).lstrip("?").strip()
    if new in ("---", "-"):
        new = ""
    return new, old


def _matches_class(cell: str, klasse: str) -> bool:
    if not klasse:
        return True
    want = _GRADE_RE.match(klasse)
    for token in re.split(r"[\s?,]+", cell):
        if token.lower() == klasse.lower():
            return True
        # "05abcd" gilt auch fuer "05b"
        got = _GRADE_RE.match(token)
        if want and got and want.group(2) and int(got.group(1)) == int(want.group(1)) and want.group(2).lower() in got.group(2).lower():
            return True
    return False


def _matches_course(row: dict, kurse: list[str]) -> bool:
    if not kurse:
        return True
    group = (row.get("group") or "").replace(" ", "").lower()
    subject = (row.get("subject") or "").replace(" ", "").lower()
    if not group and not subject:
        return True  # Veranstaltung fuer die ganze Stufe (z.B. Stufenfahrt)
    for kurs in kurse:
        k = kurs.replace(" ", "").lower()
        if k and (group.startswith(k) or subject == k or subject.startswith(k)):
            return True
    return False


_CANCEL_KINDS = ("entfall", "eigenverantwortlich")


def _is_cancelled(row: dict, old: dict, kind: str) -> bool:
    """Entfall ist im Plan dieser Schule so gekennzeichnet:
    - Art "Entfall" oder "eigenverantwortliches Arbeiten" (EVA)
    - Lehrer durchgestrichen ohne neuen Lehrer (oft auch Fach/Raum)
    - Klasse/Stufe durchgestrichen (Klassenfahrt, Exkursion ...)"""
    lk = kind.lower()
    if any(word in lk for word in _CANCEL_KINDS) or lk == "eva":
        return True
    if old.get("teacher") and not row.get("teacher"):
        return True
    return bool(old.get("klasse")) and not row.get("klasse")


def _untis_entry(row: dict, old: dict, kind: str, day_label: str) -> SubstitutionEntry:
    subject = re.sub(r"\s+", " ", row.get("subject") or old.get("subject") or row.get("group", ""))
    lesson = row.get("lesson", "").replace(" ", "")
    lk = kind.lower()
    if _is_cancelled(row, old, kind):
        # Anlass mitnehmen, wenn es nicht nur "Entfall"/"EVA" heisst (z.B. "Stufenfahrt Q2 Prag")
        reason = kind if kind and not any(w in lk for w in _CANCEL_KINDS) and lk != "eva" else ""
        note = " · ".join(filter(None, [reason, row.get("text", "")]))
        return SubstitutionEntry(lesson=lesson, subject=subject, room="", note=note, day=day_label, kind="Entfall")
    details = []
    if old.get("teacher") and row.get("teacher"):
        details.append(f"{row['teacher']} statt {old['teacher']}")
    if old.get("room"):
        details.append(f"Raum {row['room']} statt {old['room']}" if row.get("room") else f"statt Raum {old['room']}")
    if row.get("text"):
        details.append(row["text"])
    return SubstitutionEntry(
        lesson=lesson,
        subject=subject,
        room=row.get("room", "") if not old.get("room") else "",
        note=" · ".join(details),
        day=day_label,
        kind=kind,
    )


def _parse_untis(html: str, cfg: Config, day_label: str) -> list[SubstitutionEntry]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="mon_list")
    if table is None:
        raise IServError("Untis-Vertretungsplan hat kein erwartetes Tabellenformat (mon_list)")
    header = [th.get_text(" ", strip=True) for th in table.find_all("th")]
    keys = []
    for name in header:
        clean = name.strip("()").lower().replace(".", "").replace("(n)", "")
        keys.append(next((v for k, v in _UNTIS_COLUMNS.items() if clean.startswith(k)), clean))

    # Kurse aus Einstellungen -> Schule (data/school.json), sonst config.yaml
    kurse = school_settings.courses(cfg)
    entries: list[SubstitutionEntry] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) != len(keys):
            continue  # Kopfzeile oder Zwischenueberschrift (nur Klassenname)
        cells = [_cell(td) for td in tds]
        row = {k: new for k, (new, _) in zip(keys, cells)}
        old = {k: old for k, (_, old) in zip(keys, cells)}
        if not _matches_class(row.get("klasse", "") + " " + old.get("klasse", ""), cfg.iserv.klasse):
            continue
        if not _matches_course(row, kurse):
            continue
        kind = row.get("kind", "")
        entries.append(_untis_entry(row, old, kind, day_label))
    # Zeilen fuer Klassenverbuende ("05abcd") stehen unter jeder Klasse erneut
    unique = {tuple(dataclasses.astuple(e)): e for e in entries}
    return list(unique.values())


_UNTIS_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _untis_date(html: str) -> date | None:
    """Datum aus dem Untis-Titel, z.B. "28.9.2026 Montag, Woche A"."""
    title = BeautifulSoup(html, "html.parser").select_one(".mon_title")
    match = _UNTIS_DATE.search(title.get_text(" ", strip=True)) if title else None
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _day_label(plan_day: date, today: date) -> str:
    if plan_day == today:
        return "Heute"
    if plan_day == today + timedelta(days=1):
        return "Morgen"
    return _WEEKDAYS[plan_day.weekday()]


def _untis_page(session: requests.Session, cfg: Config, path: str) -> str:
    """Infobildschirm-Seite -> eingebettete Untis-Datei (iframe) laden."""
    base = cfg.iserv.base_url.rstrip("/")
    page = _follow_meta_refresh(session, session.get(base + path, timeout=15))
    frame = BeautifulSoup(page.text, "html.parser").find("iframe", src=True)
    if frame is None:
        raise IServError(f"Auf {path} ist kein Vertretungsplan eingebettet")
    resp = session.get(urljoin(page.url, frame["src"]), timeout=15)
    resp.raise_for_status()
    # Untis exportiert je nach Version ISO-8859-1 oder UTF-8
    resp.encoding = resp.apparent_encoding or resp.encoding
    return resp.text


def get_vertretungsplan(cfg: Config) -> list[SubstitutionEntry]:
    if not cfg.iserv.enabled:
        return []

    session = requests.Session()
    _login(session, cfg)

    if cfg.iserv.plan_pages:
        # "V Heute"/"V Morgen" tauscht die Schule erst morgens aus - nachts
        # zeigt "V Heute" also noch den Vortag. Deshalb jeden Plan nach
        # seinem eigenen Datum einordnen und Vergangenes weglassen.
        today = date.today()
        entries: list[SubstitutionEntry] = []
        for page in cfg.iserv.plan_pages:
            html = _untis_page(session, cfg, page["path"])
            plan_day = _untis_date(html)
            if plan_day is not None and plan_day < today:
                continue
            label = _day_label(plan_day, today) if plan_day else page.get("label", "")
            for entry in _parse_untis(html, cfg, label):
                entry.date = plan_day.isoformat() if plan_day else ""
                entries.append(entry)
        return sorted(entries, key=lambda e: e.date)

    plan_url = cfg.iserv.base_url.rstrip("/") + cfg.iserv.vertretungsplan_path
    resp = session.get(plan_url, timeout=15)
    resp.raise_for_status()
    resp = _follow_meta_refresh(session, resp)

    return _parse_plan(resp.text, cfg.iserv.selectors)
