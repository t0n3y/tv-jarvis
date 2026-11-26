"""App Store: eingebaute Apps (BUILTIN_APPS) und eigene Apps aus dem Ordner
apps/ (siehe app/plugins.py und apps/README.md).

Neue App? Am einfachsten als Ordner in apps/:
    .venv/bin/python -m app.new_app "Mein App-Name"

Felder eingebauter Apps:
  {"config": "pfad.in.der.config", ...}  -> data/settings.json
  {"secret": "ENV_NAME", ...}            -> .env (wird nie ausgeliefert)
  type: text | url | password | number | lines (eine Angabe pro Zeile)
Ist "enables" gesetzt, schaltet der App-Schalter diesen Config-Wert mit
(z.B. iserv.enabled), damit Dashboard und Wecker die Quelle nutzen.
"""

from __future__ import annotations

from typing import Callable

from app import plugins, settings_store
from app.config import Config, get_config

BUILTIN_APPS: list[dict] = [
    {
        "id": "jellyfin",
        "name": "Jellyfin",
        "icon": "jellyfin",
        "color": "94, 92, 230",
        "category": "Filme & Serien",
        "summary": "Deine Filme und Serien vom eigenen Mediaserver – auf dem Fernseher abspielen, Weiterschauen, vom Handy hochladen.",
        "fields": [
            {"config": "jellyfin.url", "label": "Adresse des Jellyfin-Servers", "type": "url", "placeholder": "http://127.0.0.1:8096"},
            {"config": "jellyfin.username", "label": "Dein Jellyfin-Benutzername", "type": "text"},
            {"secret": "JELLYFIN_API_KEY", "label": "API-Schlüssel", "type": "password"},
        ],
        "guide": [
            "Noch kein Jellyfin? Auf dem Pi installieren: <code>curl -fsSL https://repo.jellyfin.org/install-debuntu.sh | sudo bash</code>",
            "Im Browser <b>http://&lt;Pi&gt;:8096</b> öffnen, den Einrichtungsassistenten durchgehen und deine Film- und Serienordner als Bibliotheken anlegen (Typ „Filme“ bzw. „Serien“).",
            "In Jellyfin: <b>Dashboard → API-Schlüssel → +</b>, Name z.&nbsp;B. „RPi TV“. Den Schlüssel kopieren und hier einfügen.",
            "Deinen Jellyfin-Benutzernamen eintragen – davon kommen „Weiterschauen“ und gesehene Folgen.",
        ],
    },
    {
        "id": "youtube",
        "name": "YouTube",
        "icon": "youtube",
        "color": "255, 59, 48",
        "category": "Filme & Serien",
        "summary": "Links vom Handy auf dem Fernseher abspielen und die neuesten Videos deiner Abos.",
        "fields": [],
        "guide": [
            "Video auf dem Fernseher: in der YouTube-App <b>Teilen → Link kopieren</b> und in der App hier einfügen.",
            "Für deine Abos: App <b>Browser</b> öffnen, <b>youtube.com</b> aufrufen und dich mit deinem Google-Konto anmelden. Danach erscheinen die neuesten Abo-Videos in der YouTube-App.",
            "Der Pi spielt YouTube in H.264 mit höchstens 30 Bildern pro Sekunde ab – so ruckelt es nicht.",
        ],
    },
    {
        "id": "twitch",
        "name": "Twitch",
        "icon": "twitch",
        "color": "145, 70, 255",
        "category": "Filme & Serien",
        "summary": "Wer von deinen Lieblings-Streamern live ist – mit einem Tipp im Vollbild ohne Chat.",
        "fields": [],
        "guide": [
            "In der Twitch-App unten Streamer per Name oder twitch.tv-Link hinzufügen.",
            "Wer live ist, steht oben mit Vorschau. Antippen startet den Stream auf dem Fernseher.",
            "Kein Konto nötig.",
        ],
    },
    {
        "id": "vinyl",
        "name": "Plattenschrank",
        "icon": "vinyl",
        "color": "166, 102, 60",
        "category": "Musik",
        "summary": "Ein Plattenspieler auf dem Fernseher mit Schränken pro Genre – ganze Alben am Stück hören.",
        "fields": [],
        "guide": [
            "Platten hinzufügen: in der App <b>Platte dazu</b> antippen, Album suchen, Songs auswählen.",
            "Eigene Schränke (Genres) legst du unten mit <b>Neuen Schrank bauen</b> an.",
            "Die Musik kommt von YouTube; der Player läuft unsichtbar hinter dem Plattenspieler.",
        ],
    },
    {
        "id": "light",
        "name": "Licht",
        "icon": "sun",
        "color": "255, 204, 0",
        "category": "Zuhause",
        "summary": "DMX-Scheinwerfer steuern: Farben, Dimmer und Effekte im Takt der Musik mit Tap-Tempo.",
        "fields": [],
        "guide": [
            "Du brauchst einen <b>uDMX-USB-Adapter</b> (z.&nbsp;B. „Anyma uDMX“) und DMX-Scheinwerfer mit 8-Kanal-Modus (z.&nbsp;B. UKING RGB-Par).",
            "Adapter an den Pi stecken, Scheinwerfer per DMX-Kabel verbinden.",
            "Am ersten Scheinwerfer Adresse <b>d001</b> und 8-Kanal-Modus einstellen, am zweiten <b>d009</b>, dann d017 … (immer +8).",
            "In der App Licht unten die Anzahl der Lampen einstellen.",
        ],
    },
    {
        "id": "comics",
        "name": "Comics",
        "icon": "book",
        "color": "255, 149, 0",
        "category": "Lesen",
        "summary": "Comics und PDFs mit Doppelseiten und Blätteranimation – auch in Jellyfin.",
        "fields": [],
        "guide": [
            "Den Reader öffnest du mit der Kachel Comics oder unter <b>/comics.html</b>.",
            "Hefte (CBZ, CBR, CB7, PDF) mit dem <b>+</b> im Reader hochladen – oder direkt in den Ordner <b>Comics</b> neben deinen Jellyfin-Ordnern legen, ein Unterordner pro Reihe.",
            "Eigene Adresse wie comics.deine-domain.de: im Cloudflare-Tunnel einen Public Hostname auf <b>localhost:8080</b> anlegen (siehe App „Fernzugriff“).",
        ],
    },
    {
        "id": "iserv",
        "name": "IServ-Vertretungsplan",
        "icon": "school",
        "color": "0, 122, 255",
        "category": "Schule",
        "summary": "Deine Vertretungen auf dem Dashboard und im Wecker – nur für deine Kurse, ab 16 Uhr schon für morgen.",
        "enables": "iserv.enabled",
        "fields": [
            {"config": "iserv.base_url", "label": "IServ-Adresse deiner Schule", "type": "url", "placeholder": "https://deine-schule.de"},
            {"secret": "ISERV_USERNAME", "label": "IServ-Benutzername", "type": "text"},
            {"secret": "ISERV_PASSWORD", "label": "IServ-Passwort", "type": "password"},
            {"config": "iserv.klasse", "label": "Klasse oder Stufe (wie im Plan, z. B. 07b, EF, Q1)", "type": "text"},
            {"config": "iserv.plan_pages.0.path", "label": "Pfad „Vertretung heute“", "type": "text", "placeholder": "/iserv/infodisplay/show/28"},
            {"config": "iserv.plan_pages.1.path", "label": "Pfad „Vertretung morgen“", "type": "text", "placeholder": "/iserv/infodisplay/show/29"},
        ],
        "guide": [
            "IServ-Adresse, Benutzername und Passwort eintragen (wie beim Login im Browser).",
            "In IServ den Vertretungsplan öffnen (oft unter Schnellzugriff „V Heute“). Die Adresse endet z.&nbsp;B. auf <b>/iserv/infodisplay/show/28</b> – diesen Teil ab <b>/iserv</b> eintragen, genauso für „morgen“.",
            "Klasse bzw. Stufe genau so schreiben, wie sie im Plan steht.",
            "Oberstufe: deine Kurse und Fächer trägst du danach unter <b>Einstellungen → Schule</b> ein.",
            "Mit <b>Verbindung testen</b> prüfst du, ob der Plan gelesen wird.",
        ],
    },
    {
        "id": "calendar_google",
        "name": "Google Kalender",
        "icon": "calendar",
        "color": "52, 168, 83",
        "category": "Kalender",
        "summary": "Termine von heute (ab 20 Uhr von morgen) auf dem Dashboard und im Wecker.",
        "enables": "calendars.google.enabled",
        "fields": [
            {"config": "calendars.google.ics_urls", "label": "Privatadresse im iCal-Format (eine pro Kalender)", "type": "lines"},
        ],
        "guide": [
            "Am PC <b>calendar.google.com</b> öffnen → Zahnrad → <b>Einstellungen</b>.",
            "Links unter „Einstellungen für meine Kalender“ deinen Kalender wählen.",
            "Ganz unten bei <b>Privatadresse im iCal-Format</b> den Link kopieren (endet auf <b>basic.ics</b>) und hier einfügen. Mehrere Kalender: eine Adresse pro Zeile.",
            "Diese Adresse ist wie ein Passwort – nicht weitergeben.",
        ],
    },
    {
        "id": "calendar_icloud",
        "name": "iCloud Kalender",
        "icon": "calendar",
        "color": "255, 59, 48",
        "category": "Kalender",
        "summary": "Termine aus deinem iPhone-Kalender auf dem Dashboard und im Wecker.",
        "enables": "calendars.icloud.enabled",
        "fields": [
            {"secret": "ICLOUD_APPLE_ID", "label": "Apple-ID (E-Mail)", "type": "text"},
            {"secret": "ICLOUD_APP_SPECIFIC_PASSWORD", "label": "App-spezifisches Passwort", "type": "password"},
            {"config": "calendars.icloud.calendar_names", "label": "Nur diese Kalender (leer = alle, einer pro Zeile)", "type": "lines"},
        ],
        "guide": [
            "<b>account.apple.com</b> öffnen und anmelden → <b>Anmelden und Sicherheit → App-spezifische Passwörter</b>.",
            "Ein neues Passwort anlegen, Name z.&nbsp;B. „RPi TV“. Es sieht so aus: xxxx-xxxx-xxxx-xxxx.",
            "Hier deine Apple-ID und dieses Passwort eintragen – nicht dein normales Apple-Passwort.",
        ],
    },
    {
        "id": "todos",
        "name": "ToDos aus Notizen",
        "icon": "check",
        "color": "255, 214, 10",
        "category": "Kalender",
        "summary": "Eine Checkliste aus der Notizen-App erscheint auf dem Dashboard – abgehakte durchgestrichen.",
        "fields": [
            {"secret": "TODOS_WEBHOOK_SECRET", "label": "Geheimwort für den Kurzbefehl", "type": "password", "generate": True},
        ],
        "guide": [
            "Auf dem iPhone in <b>Kurzbefehle</b> einen neuen Kurzbefehl anlegen.",
            "Aktion <b>Notizen suchen</b> (deine ToDo-Notiz), dann <b>Inhalte von URL abrufen</b>: Methode POST, URL <b>https://&lt;deine Adresse&gt;/api/todos/webhook</b>.",
            "Bei Header <b>X-Webhook-Secret</b> mit dem Geheimwort von hier eintragen, als Text den Notizinhalt senden.",
            "Unter <b>Automation</b> z.&nbsp;B. „Beim Schließen der Notizen-App“ den Kurzbefehl ausführen lassen.",
        ],
    },
    {
        "id": "remote_access",
        "name": "Fernzugriff",
        "icon": "globe",
        "color": "142, 142, 147",
        "category": "System",
        "summary": "Die Fernbedienung von unterwegs und mit https nutzen – nötig z. B. für die Spracheingabe am iPhone.",
        "fields": [],
        "guide": [
            "Kostenloses Konto bei <b>Cloudflare</b> anlegen und deine Domain dort hinzufügen.",
            "<b>Zero Trust → Networks → Tunnels → Create a tunnel</b> (Cloudflared). Den angezeigten Installationsbefehl für <b>Debian, arm64</b> auf dem Pi ausführen.",
            "Im Tunnel einen <b>Public Hostname</b> anlegen: z.&nbsp;B. <b>tv.deine-domain.de</b>, Typ HTTP, URL <b>localhost:8080</b>. Für den Comic-Reader genauso <b>comics.deine-domain.de</b>.",
            "Empfohlen: unter <b>Zero Trust → Access</b> eine Application für diese Adressen anlegen (Login per E-Mail-Code). Dazu immer ein Passwort für die Fernbedienung (Einstellungen).",
        ],
    },
]

BUILTIN_IDS = {app["id"] for app in BUILTIN_APPS}


def all_apps() -> list[dict]:
    """Eingebaute Apps + Ordner aus apps/ (eine eigene App kann keine
    eingebaute ueberschreiben)."""
    extra = [app for app in plugins.discover() if app["id"] not in BUILTIN_IDS]
    return BUILTIN_APPS + extra


def by_id(app_id: str) -> dict | None:
    return next((app for app in all_apps() if app["id"] == app_id), None)


def enabled_map() -> dict[str, bool]:
    data = settings_store.load()
    saved = data["apps"]
    apps = all_apps()
    if not isinstance(saved, dict):
        # Bestehende Installation ohne App-Auswahl: alles sichtbar
        return {a["id"]: settings_store._legacy_install() and not a.get("error") for a in apps}
    return {a["id"]: bool(saved.get(a["id"], False)) and not a.get("error") for a in apps}


def _raw_config() -> dict:
    """Aktuelle Werte (alle Schichten) als dict - fuer die Formulare."""
    from app.config import CODE_DIR, ROOT_DIR, _load_yaml, _merge, _settings_overrides

    raw = _load_yaml(CODE_DIR / "config.example.yaml")
    raw = _merge(raw, _load_yaml(ROOT_DIR / "config.yaml"))
    return _merge(raw, _settings_overrides())


def _list_index_path(raw: dict, path: str):
    """iserv.plan_pages.0.path -> Wert aus der Liste."""
    parts = path.split(".")
    node = raw
    for part in parts:
        if isinstance(node, list):
            index = int(part)
            node = node[index] if index < len(node) else None
        elif isinstance(node, dict):
            node = node.get(part)
        else:
            return None
    return node


def public_list() -> list[dict]:
    from app import system_tools

    enabled = enabled_map()
    raw = _raw_config()
    removable = system_tools.installed_ids()
    result = []
    for app in all_apps():
        fields = []
        for field in app["fields"]:
            item = {k: field[k] for k in ("label", "type", "placeholder", "generate") if k in field}
            item["key"] = field.get("config") or f"secret:{field['secret']}"
            if "secret" in field:
                item["is_set"] = settings_store.secret_is_set(field["secret"])
                item["value"] = ""
            else:
                value = _list_index_path(raw, field["config"])
                item["value"] = "\n".join(value) if isinstance(value, list) else ("" if value is None else str(value))
            fields.append(item)
        result.append({
            **{k: app[k] for k in ("id", "name", "icon", "color", "category", "summary", "guide")},
            **{k: app[k] for k in ("icon_svg", "author", "version", "homepage", "view", "files", "error") if app.get(k)},
            "plugin": bool(app.get("plugin")),
            "removable": app["id"] in removable,
            "enabled": enabled[app["id"]],
            "fields": fields,
            "testable": app["id"] in TESTS or plugins.test_function(app["id"]) is not None,
            "configured": _configured(app, raw),
        })
    return result


def _configured(app: dict, raw: dict) -> bool:
    for field in app["fields"]:
        if field.get("generate"):
            continue
        if "secret" in field:
            if not settings_store.secret_is_set(field["secret"]):
                return False
        elif not _list_index_path(raw, field["config"]) and "placeholder" not in field and field["type"] != "lines":
            return False
    return True


def save(app_id: str, enabled: bool | None, values: dict) -> None:
    app = by_id(app_id)
    if not app:
        raise ValueError("Unbekannte App")
    if enabled and app.get("error"):
        raise ValueError(f"Die App hat einen Fehler: {app['error']}")
    config_updates: dict = {}
    secrets_updates: dict = {}
    raw = _raw_config()
    for field in app["fields"]:
        key = field.get("config") or f"secret:{field['secret']}"
        if key not in values:
            continue
        value = values[key]
        if "secret" in field:
            if value:  # leeres Feld = unveraendert lassen
                secrets_updates[field["secret"]] = str(value)
            continue
        if field["type"] == "lines":
            value = [line.strip() for line in str(value or "").splitlines() if line.strip()]
        elif field["type"] == "number":
            value = float(value) if str(value).strip() else None
        else:
            value = str(value or "").strip()
            if field["type"] == "url":
                value = value.rstrip("/")
        path = field["config"]
        if ".plan_pages." in path:
            # Listen-Eintrag: ganze Liste neu schreiben
            pages = list(raw.get("iserv", {}).get("plan_pages") or [])
            index = int(path.split(".")[2])
            while len(pages) <= index:
                pages.append({"label": ["Heute", "Morgen"][len(pages)] if len(pages) < 2 else "", "path": ""})
            pages[index] = {**pages[index], "path": value}
            config_updates["iserv.plan_pages"] = [p for p in pages if p.get("path")]
            raw.setdefault("iserv", {})["plan_pages"] = pages
        else:
            config_updates[path] = value
    if enabled is not None and app.get("enables"):
        config_updates[app["enables"]] = bool(enabled)
    if secrets_updates:
        settings_store.set_secrets(secrets_updates)
    # Ganze Auswahl mitschreiben: bei bestehenden Installationen (noch keine
    # Auswahl gespeichert = alles an) sollen die anderen Apps an bleiben.
    apps = {**enabled_map(), app_id: enabled} if enabled is not None else None
    settings_store.update(config=config_updates, apps=apps)


# ---------- Verbindung testen ----------

def _test_jellyfin(cfg: Config) -> str:
    from app import jellyfin_client

    name = jellyfin_client.user_display_name(cfg)
    return f"Verbunden – angemeldet als {name}" if name else "Server erreichbar"


def _test_iserv(cfg: Config) -> str:
    from app.sources import iserv

    entries = iserv.get_vertretungsplan(cfg)
    return f"Plan gelesen – {len(entries)} Einträge für dich"


def _test_google(cfg: Config) -> str:
    from datetime import date

    from app.sources import calendar_google

    events = calendar_google.get_todays_events(cfg, date.today())
    return f"Kalender gelesen – {len(events)} Termine heute"


def _test_icloud(cfg: Config) -> str:
    from datetime import date

    from app.sources import calendar_icloud

    events = calendar_icloud.get_todays_events(cfg, date.today())
    return f"Kalender gelesen – {len(events)} Termine heute"


TESTS: dict[str, Callable[[Config], str]] = {
    "jellyfin": _test_jellyfin,
    "iserv": _test_iserv,
    "calendar_google": _test_google,
    "calendar_icloud": _test_icloud,
}


def test(app_id: str) -> str:
    if app_id in TESTS:
        return TESTS[app_id](get_config())
    plugin_test = plugins.test_function(app_id)
    if plugin_test is None:
        raise ValueError("Für diese App gibt es keinen Test")
    return str(plugin_test())
