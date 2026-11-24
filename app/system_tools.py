"""System-Werkzeuge fuer die Fernbedienung: Neustart (mit Wiederherstellen
von Fernseher und Radio), Updates, Backup und Apps per Link installieren.

Neustart: Der Dienst beendet sich mit Fehlercode, systemd (Restart=on-failure)
startet ihn neu. Dabei endet alles in seiner cgroup - auch Kiosk und Radio.
Deshalb merkt sich restart() vorher, ob der Fernseher an war und welches
Radio lief, und der neue Prozess stellt das wieder her (restore_after_restart).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

from app.config import ROOT_DIR, get_config

logger = logging.getLogger(__name__)

RESTORE_FILE = ROOT_DIR / "data" / "restore-after-restart.json"
INSTALLED_FILE = ROOT_DIR / "data" / "apps" / "_installed.json"
TMP_DIR = ROOT_DIR / "data" / "tmp"
GIT_TIMEOUT = 90
PIP_TIMEOUT = 900
RESTART_EXIT_CODE = 3


class SystemError_(RuntimeError):
    pass


def _run(args: list[str], timeout: float, cwd: Path = ROOT_DIR) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    try:
        result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        raise SystemError_(f"{args[0]} hat zu lange gebraucht") from exc
    except FileNotFoundError as exc:
        raise SystemError_(f"{args[0]} ist nicht installiert") from exc
    if result.returncode != 0:
        message = (result.stderr or result.stdout).strip().splitlines()
        raise SystemError_(message[-1] if message else f"{args[0]} ist fehlgeschlagen")
    return result.stdout


def _rmtree(path: Path) -> None:
    """Ordner loeschen - auch schreibgeschuetzte Dateien (z.B. aus .git)."""
    import stat

    def retry(func, target, *_):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if path.exists():
        shutil.rmtree(path, onerror=retry)


# ---------- Neustart ----------

def restart(delay: float = 1.0) -> None:
    """Dienst neu starten - Fernseher und Radio kommen danach wieder."""
    from app import radio
    from app.dashboard import kiosk

    # radio.start() spielt danach den zuletzt gewaehlten Sender
    state = {"tv_on": kiosk.is_running(), "radio": False, "at": time.time()}
    try:
        state["radio"] = radio.is_playing()
    except Exception:  # noqa: BLE001
        pass
    RESTORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RESTORE_FILE.write_text(json.dumps(state), encoding="utf-8")
    logger.info("Neustart angefordert (%s)", state)
    # Kurz warten, damit die Antwort noch beim Handy ankommt
    threading.Timer(delay, lambda: os._exit(RESTART_EXIT_CODE)).start()


def restore_after_restart() -> None:
    """Im neuen Prozess (blockierend, im Thread aufrufen)."""
    try:
        state = json.loads(RESTORE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    RESTORE_FILE.unlink(missing_ok=True)
    if time.time() - float(state.get("at") or 0) > 600:
        return  # alter Rest, z.B. nach einem Stromausfall
    from app import radio, tv_power

    cfg = get_config()
    if state.get("tv_on"):
        logger.info("Nach dem Neustart: Fernseher wieder an")
        tv_power.power_on(cfg)
    if state.get("radio"):
        logger.info("Nach dem Neustart: Radio wieder an")
        radio.start(cfg)


# ---------- Updates (git) ----------

update_state: dict = {"running": False, "step": "", "error": None, "done": False}


def check_update() -> dict:
    if not (ROOT_DIR / ".git").exists():
        return {"available": False, "possible": False, "reason": "Kein Git-Ordner – neu installieren mit dem Installationsbefehl."}
    try:
        upstream = _run(["git", "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], 10).strip()
        _run(["git", "fetch", "--quiet"], GIT_TIMEOUT)
        count = int(_run(["git", "rev-list", "--count", f"HEAD..{upstream}"], 10).strip() or 0)
        changes = _run(["git", "log", "--format=%s", "-n", "8", f"HEAD..{upstream}"], 10).strip().splitlines() if count else []
        version = _run(["git", "log", "-1", "--format=%h · %cd", "--date=format:%d.%m.%Y"], 10).strip()
        dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"], 10).strip()
    except SystemError_ as exc:
        return {"available": False, "possible": False, "reason": str(exc)}
    result = {"available": count > 0, "count": count, "changes": changes, "version": version, "possible": True, "reason": ""}
    if dirty:
        result["possible"] = False
        result["reason"] = f"Im Ordner wurden {len(dirty.splitlines())} Dateien von Hand geändert – dann aktualisiere ich nicht automatisch."
    return result


def requirement_files() -> list[Path]:
    files = [ROOT_DIR / "requirements.txt"]
    files += sorted((ROOT_DIR / "apps").glob("*/requirements.txt"))
    return [f for f in files if f.exists()]


def _pip_install(files: list[Path]) -> None:
    for file in files:
        _run([sys.executable, "-m", "pip", "install", "--quiet", "-r", str(file)], PIP_TIMEOUT)


def start_update() -> None:
    if update_state["running"]:
        raise SystemError_("Das Update läuft schon")
    check = check_update()
    if not check["possible"]:
        raise SystemError_(check["reason"])
    if not check["available"]:
        raise SystemError_("Schon auf dem neuesten Stand")
    update_state.update(running=True, step="Lade neue Version …", error=None, done=False)

    def work() -> None:
        try:
            _run(["git", "pull", "--ff-only", "--quiet"], GIT_TIMEOUT)
            update_state["step"] = "Installiere Python-Pakete …"
            _pip_install(requirement_files())
            update_state.update(step="Starte neu …", done=True)
            restart(delay=0.5)
        except SystemError_ as exc:
            update_state.update(error=str(exc), running=False)

    threading.Thread(target=work, daemon=True).start()


# ---------- Backup ----------

def _backup_files(include_secrets: bool) -> list[Path]:
    data = ROOT_DIR / "data"
    files = [p for p in data.glob("*.json") if p.name not in {"state.json", RESTORE_FILE.name}]
    files += [p for p in (data / "apps").rglob("*") if p.is_file() and p.suffix in {".json", ".txt"}]
    for extra in ("config.yaml",) + ((".env",) if include_secrets else ()):
        if (ROOT_DIR / extra).exists():
            files.append(ROOT_DIR / extra)
    return files


def export_backup(include_secrets: bool) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in _backup_files(include_secrets):
            archive.write(path, path.relative_to(ROOT_DIR).as_posix())
        archive.writestr("rpitv-backup.json", json.dumps({"created": time.strftime("%Y-%m-%d %H:%M"), "name": get_config().dashboard.title}))
    return buffer.getvalue()


def _allowed_backup_path(name: str) -> bool:
    if name in {"config.yaml", ".env"}:
        return True
    parts = name.split("/")
    if ".." in parts or name.startswith("/") or "\\" in name:
        return False
    if len(parts) == 2 and parts[0] == "data" and name.endswith(".json"):
        return True
    return len(parts) >= 3 and parts[:2] == ["data", "apps"] and Path(name).suffix in {".json", ".txt"}


def import_backup(content: bytes) -> int:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise SystemError_("Das ist keine Backup-Datei") from exc
    names = archive.namelist()
    if "rpitv-backup.json" not in names:
        raise SystemError_("Das ist kein Backup von RPi TV")
    count = 0
    for name in names:
        if name == "rpitv-backup.json" or name.endswith("/"):
            continue
        if not _allowed_backup_path(name):
            logger.warning("Backup: %s uebersprungen", name)
            continue
        target = ROOT_DIR / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read(name))
        if name == ".env":
            os.chmod(target, 0o600)
        count += 1
    return count


# ---------- Apps per Link installieren ----------

URL_PATTERN = re.compile(r"^https://[A-Za-z0-9.-]+(:\d+)?/[A-Za-z0-9._~/-]+$")


def _installed() -> dict:
    try:
        return json.loads(INSTALLED_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def installed_ids() -> set[str]:
    return set(_installed())


def install_app(url: str) -> dict:
    from app import new_app, plugins

    url = url.strip()
    if url.endswith(".git"):
        url = url[:-4]
    if not URL_PATTERN.match(url):
        raise SystemError_("Bitte die https-Adresse eines Git-Repos angeben, z. B. https://github.com/name/meine-app")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    work = TMP_DIR / f"install-{int(time.time() * 1000)}"
    try:
        _run(["git", "clone", "--depth", "1", "--quiet", "--", url, str(work)], GIT_TIMEOUT, cwd=TMP_DIR)
        manifest_path = work / "app.json"
        if not manifest_path.exists():
            raise SystemError_("Im Repo liegt keine app.json – ist das eine App für RPi TV?")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            raise SystemError_("app.json ist kaputt") from exc
        app_id = str(manifest.get("id") or new_app.slugify(url.rstrip("/").rsplit("/", 1)[-1]))
        if not plugins.ID_PATTERN.match(app_id):
            raise SystemError_(f"Ungültige App-ID {app_id!r}")
        from app import apps

        target = plugins.APPS_DIR / app_id
        if app_id in apps.BUILTIN_IDS or target.exists():
            raise SystemError_(f"Eine App „{app_id}“ gibt es schon")
        _rmtree(work / ".git")
        shutil.move(str(work), str(target))
        try:
            plugins._read_manifest(target)
        except plugins.PluginError as exc:
            _rmtree(target)
            raise SystemError_(f"Die App ist fehlerhaft: {exc}") from exc
        if (target / "requirements.txt").exists():
            _pip_install([target / "requirements.txt"])
        registry = _installed()
        registry[app_id] = {"url": url, "installed": time.strftime("%Y-%m-%d %H:%M")}
        INSTALLED_FILE.parent.mkdir(parents=True, exist_ok=True)
        INSTALLED_FILE.write_text(json.dumps(registry, indent=2), encoding="utf-8")
        logger.info("App %s von %s installiert", app_id, url)
        return {"id": app_id, "needs_restart": (target / "server.py").exists()}
    finally:
        _rmtree(work)


def remove_app(app_id: str) -> None:
    from app import plugins

    registry = _installed()
    if app_id not in registry or not plugins.ID_PATTERN.match(app_id):
        raise SystemError_("Nur per Link installierte Apps lassen sich entfernen – andere einfach ausschalten")
    target = plugins.APPS_DIR / app_id
    if target.resolve().parent != plugins.APPS_DIR.resolve():
        raise SystemError_("Ungültiger Ordner")
    _rmtree(target)
    del registry[app_id]
    INSTALLED_FILE.write_text(json.dumps(registry, indent=2), encoding="utf-8")
