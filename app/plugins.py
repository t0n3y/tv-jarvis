"""Eigene Apps: jeder Ordner in apps/ ist eine App fuer den App Store.

    apps/<id>/
      app.json      Pflicht: Name, Symbol, Farbe, Beschreibung, Felder, Anleitung
      remote.html   Ansicht in der Fernbedienung (optional)
      remote.js     Logik dazu - bekommt RPiTV.app() (optional)
      remote.css    Aussehen dazu (optional)
      tv.html       Seite fuer den Fernseher (optional, app.tv.open())
      server.py     eigene API unter /api/apps/<id>/... (optional)
      icon.svg      eigenes Symbol, 24x24, Linien (optional)
      _name.json    private Dateien (werden nie ausgeliefert, z.B. Antworten)

Anleitung fuer Entwickler: apps/README.md. Neue App anlegen:
    .venv/bin/python -m app.new_app "Mein App-Name"

In server.py:
    from fastapi import APIRouter
    from app.plugins import context

    ctx = context(__file__)     # Einstellungen, Speicher, Fernseher, Stimme
    router = APIRouter()        # wird unter /api/apps/<id> eingehaengt

    @router.get("/hallo")
    def hallo():
        return {"text": f"Hallo aus {ctx.name}"}

Optionale Haken in server.py (alle duerfen fehlen):
    public_router = APIRouter()   /api/apps/<id>/public/... OHNE Passwort
                                  (z.B. Mitspieler-Handys beim Quiz)
    def test() -> str             Knopf "Verbindung testen" im App Store
    def dashboard() -> dict|None  Kachel auf dem Fernseher-Dashboard
    def briefing() -> str|None    Satz fuer die Morgen-Ansage des Weckers
    async def background()        laeuft dauerhaft ab dem Start des Dienstes
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import re
import sys
import threading
from pathlib import Path

from app import settings_store
from app.config import CODE_DIR, ROOT_DIR, Config, get_config

logger = logging.getLogger(__name__)

APPS_DIR = CODE_DIR / "apps"
DATA_DIR = ROOT_DIR / "data" / "apps"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
SECRET_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,50}$")
FIELD_TYPES = {"text", "url", "password", "number", "lines"}
# Was der Server aus einem App-Ordner ausliefert (nie server.py o.ae.)
STATIC_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp3": "audio/mpeg",
    ".woff2": "font/woff2",
}
DEFAULT_CATEGORY = "Weitere Apps"
DEFAULT_COLOR = "142, 142, 147"

_modules: dict[str, object] = {}
_errors: dict[str, str] = {}


class PluginError(ValueError):
    pass


# ---------- Entdecken ----------

def _read_manifest(folder: Path) -> dict:
    app_id = folder.name
    if not ID_PATTERN.match(app_id):
        raise PluginError("Ordnername nur aus a-z, 0-9 und _ (beginnt mit Buchstabe)")
    try:
        raw = json.loads((folder / "app.json").read_text(encoding="utf-8"))
    except ValueError as exc:
        raise PluginError(f"app.json ist kein gültiges JSON: {exc}") from exc
    if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
        raise PluginError("app.json braucht mindestens \"name\"")

    fields = []
    for field in raw.get("fields") or []:
        ftype = field.get("type", "text")
        if ftype not in FIELD_TYPES:
            raise PluginError(f"Feldtyp {ftype!r} gibt es nicht ({', '.join(sorted(FIELD_TYPES))})")
        item = {k: field[k] for k in ("label", "placeholder", "generate") if k in field}
        item["type"] = ftype
        item.setdefault("label", field.get("key") or field.get("secret") or "")
        if field.get("secret"):
            name = str(field["secret"])
            if not SECRET_PATTERN.match(name) or name == "REMOTE_CONTROL_SECRET":
                raise PluginError(f"Ungültiger Name für ein Geheimnis: {name}")
            item["secret"] = name
        elif field.get("key") and re.match(r"^[a-z][a-z0-9_]{0,40}$", str(field["key"])):
            item["config"] = f"apps.{app_id}.{field['key']}"
        else:
            raise PluginError("Jedes Feld braucht \"key\" (a-z, 0-9, _) oder \"secret\" (GROSS_GESCHRIEBEN)")
        fields.append(item)

    icon = str(raw.get("icon") or "")
    icon_svg = ""
    if (folder / "icon.svg").exists():
        icon_svg = _svg_inner((folder / "icon.svg").read_text(encoding="utf-8"))
        icon = f"app-{app_id}"
    return {
        "id": app_id,
        "name": str(raw["name"]).strip()[:40],
        "icon": icon or "star",
        "icon_svg": icon_svg,
        "color": str(raw.get("color") or DEFAULT_COLOR),
        "category": str(raw.get("category") or DEFAULT_CATEGORY),
        "summary": str(raw.get("summary") or ""),
        "fields": fields,
        "guide": [str(step) for step in raw.get("guide") or []],
        "author": str(raw.get("author") or ""),
        "version": str(raw.get("version") or ""),
        "homepage": str(raw.get("homepage") or ""),
        "plugin": True,
        "view": (folder / "remote.html").exists() or (folder / "remote.js").exists(),
        "files": sorted(p.name for p in folder.iterdir() if p.suffix in STATIC_TYPES and p.is_file() and not p.name.startswith("_")),
        "has_server": (folder / "server.py").exists(),
    }


def _svg_inner(svg: str) -> str:
    """Nur den Inhalt des <svg> - er kommt als <symbol> in die Symbol-Sammlung."""
    match = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S)
    inner = match.group(1) if match else svg
    return re.sub(r"<script.*?</script>", "", inner, flags=re.S | re.I)


def discover() -> list[dict]:
    """Alle App-Ordner, alphabetisch. Kaputte Apps erscheinen mit Fehler im
    App Store, statt den ganzen Dienst lahmzulegen."""
    apps = []
    if not APPS_DIR.is_dir():
        return apps
    for folder in sorted(APPS_DIR.iterdir()):
        if not folder.is_dir() or folder.name.startswith((".", "_")) or not (folder / "app.json").exists():
            continue
        try:
            manifest = _read_manifest(folder)
        except (PluginError, OSError) as exc:
            logger.warning("App %s: %s", folder.name, exc)
            manifest = {
                "id": folder.name, "name": folder.name, "icon": "star", "icon_svg": "", "color": DEFAULT_COLOR,
                "category": DEFAULT_CATEGORY, "summary": "", "fields": [], "guide": [], "plugin": True,
                "view": False, "files": [], "has_server": False, "error": str(exc),
            }
        if folder.name in _errors:
            manifest["error"] = _errors[folder.name]
        for field in manifest["fields"]:
            if "secret" in field:
                settings_store.SECRET_KEYS.add(field["secret"])
        apps.append(manifest)
    return apps


def static_file(app_id: str, name: str) -> tuple[Path, str]:
    # "_name": private Dateien der App (z.B. Quiz-Antworten) - nie ausliefern
    if not ID_PATTERN.match(app_id) or "/" in name or "\\" in name or name.startswith((".", "_")):
        raise PluginError("Datei nicht gefunden")
    path = APPS_DIR / app_id / name
    mime = STATIC_TYPES.get(path.suffix.lower())
    if not mime or not path.is_file():
        raise PluginError("Datei nicht gefunden")
    return path, mime


# ---------- server.py laden ----------

def load_servers(include_router, include_public_router=None) -> None:
    """Beim Start: server.py jeder App laden, ihre Router einhaengen."""
    for manifest in discover():
        if not manifest.get("has_server") or manifest.get("error"):
            continue
        app_id = manifest["id"]
        try:
            module = _import(app_id)
            router = getattr(module, "router", None)
            if router is not None:
                include_router(router, app_id)
            public = getattr(module, "public_router", None)
            if public is not None and include_public_router is not None:
                include_public_router(public, app_id)
            _modules[app_id] = module
            logger.info("App %s geladen", app_id)
        except Exception as exc:  # noqa: BLE001 - eine kaputte App darf den Dienst nicht stoppen
            logger.exception("App %s: server.py ließ sich nicht laden", app_id)
            _errors[app_id] = f"server.py: {exc}"


def module(app_id: str):
    """server.py einer App - auch ausserhalb des Dienstes (Wecker-Testlauf)."""
    if app_id not in _modules and app_id not in _errors and (APPS_DIR / app_id / "server.py").exists():
        try:
            _modules[app_id] = _import(app_id)
        except Exception as exc:  # noqa: BLE001
            logger.exception("App %s: server.py ließ sich nicht laden", app_id)
            _errors[app_id] = f"server.py: {exc}"
    return _modules.get(app_id)


def enabled_ids() -> list[str]:
    from app import apps

    enabled = apps.enabled_map()
    return [m["id"] for m in discover() if enabled.get(m["id"]) and m.get("has_server")]


def _hook(name: str):
    for app_id in enabled_ids():
        fn = getattr(module(app_id), name, None)
        if callable(fn):
            yield app_id, fn


def dashboard_panels() -> list[dict]:
    """Kacheln fuer das Fernseher-Dashboard. Format eines Rueckgabewerts:
        {"title": "Abfahrten", "meta": "Vlotho", "empty": "Gerade nichts",
         "items": [{"time": "7:12", "text": "RE 78 → Bielefeld", "note": "+3", "strike": False}]}
    """
    manifests = {m["id"]: m for m in discover()}
    panels = []
    for app_id, fn in _hook("dashboard"):
        try:
            panel = fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("App %s: dashboard() fehlgeschlagen: %s", app_id, exc)
            panel = {"title": manifests[app_id]["name"], "items": [], "empty": "Gerade nicht erreichbar"}
        if not panel:
            continue
        items = [
            {k: str(item.get(k) or "") for k in ("time", "text", "note")} | {"strike": bool(item.get("strike"))}
            for item in (panel.get("items") or [])[:12]
            if isinstance(item, dict)
        ]
        panels.append({
            "id": app_id,
            "title": str(panel.get("title") or manifests[app_id]["name"]),
            "meta": str(panel.get("meta") or ""),
            "empty": str(panel.get("empty") or ""),
            "items": items,
            "color": manifests[app_id]["color"],
        })
    return panels


def briefing_texts() -> list[str]:
    texts = []
    for app_id, fn in _hook("briefing"):
        try:
            text = fn()
        except Exception as exc:  # noqa: BLE001
            logger.warning("App %s: briefing() fehlgeschlagen: %s", app_id, exc)
            continue
        if text and str(text).strip():
            texts.append(str(text).strip())
    return texts


def start_background_tasks() -> None:
    """Beim Start des Dienstes: background() jeder geladenen App starten.
    Die Funktion selbst prueft mit ctx.enabled(), ob sie arbeiten soll."""
    for app_id, module_ in list(_modules.items()):
        fn = getattr(module_, "background", None)
        if fn is None or not asyncio.iscoroutinefunction(fn):
            continue

        async def runner(app_id=app_id, fn=fn) -> None:
            while True:
                try:
                    await fn()
                    return
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001 - neu starten statt den Dienst zu stoppen
                    logger.exception("App %s: background() abgestuerzt - neuer Versuch in 60 s", app_id)
                    await asyncio.sleep(60)

        asyncio.get_running_loop().create_task(runner())


# Vom Server eingetragen (app/dashboard/server.py): Wiedergabe-Zustand und
# An/Aus, damit Apps nicht in die Interna greifen muessen.
HOST: dict = {}


def _import(app_id: str):
    path = APPS_DIR / app_id / "server.py"
    name = f"rpitv_apps.{app_id}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_function(app_id: str):
    module = _modules.get(app_id)
    return getattr(module, "test", None) if module else None


# ---------- Kontext fuer server.py ----------

class AppContext:
    """Alles, was eine App auf dem Server braucht."""

    def __init__(self, app_id: str) -> None:
        self.id = app_id
        self.dir = APPS_DIR / app_id
        self.data_dir = DATA_DIR / app_id
        self.log = logging.getLogger(f"apps.{app_id}")
        self._lock = threading.Lock()

    @property
    def name(self) -> str:
        try:
            return json.loads((self.dir / "app.json").read_text(encoding="utf-8")).get("name", self.id)
        except (OSError, ValueError):
            return self.id

    @property
    def config(self) -> Config:
        """Die gesamte Konfiguration (Name des Systems, Ort, ...)."""
        return get_config()

    def settings(self) -> dict:
        """Die Felder aus app.json (ohne Geheimnisse), wie im App Store eingetragen."""
        from app.config import _settings_overrides

        return dict((_settings_overrides().get("apps") or {}).get(self.id) or {})

    def secret(self, name: str) -> str | None:
        """Ein Geheimnis aus app.json ("secret": "NAME"), gespeichert in .env."""
        import os

        return os.environ.get(name) or None

    # ----- Speicher: data/apps/<id>/<name>.json -----

    def load(self, name: str = "data", default=None):
        try:
            return json.loads((self.data_dir / f"{name}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def save(self, data, name: str = "data") -> None:
        with self._lock:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            path = self.data_dir / f"{name}.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)

    # ----- Fernseher und Stimme -----

    async def show_on_tv(self, page: str = "tv.html") -> None:
        """Eine Seite der App (oder eine https-Adresse) im Vollbild auf dem Fernseher."""
        from app import radio, tv_browser

        url = page if page.startswith(("http://", "https://")) else f"http://127.0.0.1:{self.config.dashboard.port}/apps/{self.id}/{page}"
        await asyncio.to_thread(radio.stop)
        await tv_browser.browser.open(self.config, url)

    async def close_tv(self) -> None:
        """Seite schliessen - der Fernseher zeigt wieder das Dashboard."""
        from app import tv_browser

        await tv_browser.browser.close()

    def say(self, text: str) -> None:
        """Text mit der Stimme ueber den Fernseher sprechen (blockiert, bis fertig).
        In async-Funktionen: await asyncio.to_thread(ctx.say, text)."""
        from app import tts

        tts.speak(self.config, text)

    # ----- Zustand und Steuerung -----

    def enabled(self) -> bool:
        """Ist die App im App Store eingeschaltet?"""
        from app import apps

        return bool(apps.enabled_map().get(self.id))

    def tv_is_on(self) -> bool:
        from app.dashboard import kiosk

        return kiosk.is_running()

    def busy(self) -> bool:
        """Laeuft gerade etwas (Video, Radio, Platte, Stream, TV-Browser)?"""
        fn = HOST.get("busy")
        return bool(fn()) if fn else False

    async def power(self, on: bool) -> None:
        """Fernseher ein- oder ausschalten - wie der Knopf in der Fernbedienung
        (aus = Wiedergabe stoppen, Abschied-Animation, Fernseher aus)."""
        from app import tv_power

        await asyncio.to_thread(tv_power.power_on if on else tv_power.power_off, self.config)


_contexts: dict[str, AppContext] = {}


def context(file: str) -> AppContext:
    """In server.py: ctx = context(__file__)"""
    app_id = Path(file).resolve().parent.name
    if app_id not in _contexts:
        _contexts[app_id] = AppContext(app_id)
    return _contexts[app_id]
