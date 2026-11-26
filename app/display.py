"""Mehrere Fernseher an einem Pi: jeder Fernseher ist eine eigene "Instanz"
(eigener Dienst, Port, Daten, Fernbedienung), alle aus demselben Code.

Hauptfernseher:  Projektordner, Port 8080      (dashboard.service)
Weitere:         instances/<id>/, Port 8081 ... (rpitv-<id>.service)
Anlegen:         .venv/bin/python -m app.add_tv

Pro Instanz (config.yaml der Instanz, Abschnitt "display"):
  output        HDMI-Ausgang fuer Kiosk und TV-Browser (z.B. "HDMI-A-1")
  primary       nur der Hauptfernseher steuert das DMX-Licht und den
                Standard-Tonausgang
  browser_port  Port fuer die Steuerung des TV-Browsers (9223, 9224, ...)

Fenster auf den richtigen Bildschirm: labwc (der Desktop des Pi) liest
~/.config/labwc/rc.xml zusaetzlich zur System-Konfiguration (labwc -m).
Dort pflegt jede Instanz eine Regel "Fenster mit app_id rpitv-<id> ->
Ausgang". Chromium bekommt die app_id per --class.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import threading
from pathlib import Path

import yaml

from app.config import CODE_DIR, ROOT_DIR, Config

logger = logging.getLogger(__name__)

LABWC_RC = Path.home() / ".config" / "labwc" / "rc.xml"
INSTANCES_DIR = CODE_DIR / "instances"
BLOCK_START = "<!-- rpitv:start (von RPi TV verwaltet) -->"
BLOCK_END = "<!-- rpitv:end -->"
_lock = threading.Lock()


def instance_id() -> str:
    """"main" fuer den Hauptfernseher, sonst der Ordnername der Instanz."""
    return "main" if ROOT_DIR == CODE_DIR else ROOT_DIR.name


def window_class(kind: str = "tv") -> str:
    return f"rpitv-{instance_id()}-{kind}"


# ---------- Fenster -> HDMI-Ausgang (labwc) ----------

def _rule(cls: str, output: str) -> str:
    return (
        f'    <windowRule identifier="{cls}">\n'
        f'      <action name="MoveToOutput" output="{output}" />\n'
        f"    </windowRule>\n"
    )


def ensure_window_rules(cfg: Config) -> None:
    """Regeln fuer Kiosk und TV-Browser dieser Instanz eintragen (nur wenn
    sich etwas aendert, dann labwc neu laden)."""
    output = cfg.display.output
    if not output:
        return
    with _lock:
        text = LABWC_RC.read_text(encoding="utf-8") if LABWC_RC.exists() else ""
        if BLOCK_START not in text:
            text = (
                '<?xml version="1.0"?>\n<labwc_config>\n  <windowRules>\n'
                f"    {BLOCK_START}\n    {BLOCK_END}\n  </windowRules>\n</labwc_config>\n"
                if not text.strip()
                else text.replace("</labwc_config>", f"  <windowRules>\n    {BLOCK_START}\n    {BLOCK_END}\n  </windowRules>\n</labwc_config>")
            )
        start = text.index(BLOCK_START) + len(BLOCK_START)
        end = text.index(BLOCK_END)
        block = text[start:end]
        rules = {m.group(1): m.group(0) for m in re.finditer(r'    <windowRule identifier="([^"]+)">.*?</windowRule>\n', block, re.S)}
        for kind in ("tv", "browser"):
            rules[window_class(kind)] = _rule(window_class(kind), output)
        new_block = "\n" + "".join(rules[key] for key in sorted(rules)) + "    "
        if new_block == block:
            return
        LABWC_RC.parent.mkdir(parents=True, exist_ok=True)
        LABWC_RC.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
    _reload_labwc()
    logger.info("labwc: Fenster von %s -> %s", instance_id(), output)


def _reload_labwc() -> None:
    try:
        pid = subprocess.run(["pidof", "labwc"], capture_output=True, text=True, timeout=3).stdout.split()
        for value in pid:
            os.kill(int(value), 1)  # SIGHUP = Konfiguration neu laden
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        logger.warning("labwc nicht neu geladen: %s", exc)


# ---------- Tonausgang dieser Instanz ----------

def hdmi_index(cfg: Config) -> int | None:
    """plughw:CARD=vc4hdmi1,DEV=0 -> 1"""
    match = re.search(r"vc4hdmi(\d)", cfg.audio.alsa_device or "")
    return int(match.group(1)) if match else None


def output_for_index(index: int) -> str:
    return f"HDMI-A-{index + 1}"


# ---------- Alle Fernseher im Haus ----------

def _instance_info(root: Path, default_port: int, default_name: str) -> dict:
    raw: dict = {}
    for name in ("config.yaml",):
        path = root / name
        if path.exists():
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    dash = raw.get("dashboard") or {}
    title = dash.get("title")
    try:
        import json

        settings = json.loads((root / "data" / "settings.json").read_text(encoding="utf-8"))
        title = ((settings.get("config") or {}).get("dashboard") or {}).get("title") or title
    except (OSError, ValueError):
        pass
    return {"name": title or default_name, "port": int(dash.get("port") or default_port)}


def list_tvs() -> list[dict]:
    tvs = [{"id": "main", **_instance_info(CODE_DIR, 8080, "Fernseher")}]
    if INSTANCES_DIR.is_dir():
        for folder in sorted(INSTANCES_DIR.iterdir()):
            if (folder / "config.yaml").exists():
                tvs.append({"id": folder.name, **_instance_info(folder, 8081, folder.name)})
    current = instance_id()
    for tv in tvs:
        tv["current"] = tv["id"] == current
    return tvs
