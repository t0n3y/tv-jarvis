"""Weiteren Fernseher am selben Pi einrichten (zweiter HDMI-Anschluss, auch
ueber ein Funk-HDMI-Set):

    .venv/bin/python -m app.add_tv "Telefunken"

Legt instances/<id>/ an (Einstellungen, Zugangsdaten und Apps werden vom
Hauptfernseher uebernommen, Wecker aus), richtet den Dienst rpitv-<id> ein
(fragt einmal nach dem sudo-Passwort) und zeigt die Adresse der eigenen
Fernbedienung. Der Hauptfernseher behaelt seinen Anschluss, der neue bekommt
den anderen (Pi 4/5: HDMI 0 und HDMI 1).

Optionen: --hdmi 0|1  Anschluss erzwingen   --port 8081  eigener Port
          --plain     nichts vom Hauptfernseher uebernehmen (Einrichtung neu)
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from app.config import CODE_DIR, ROOT_DIR, get_config
from app.display import INSTANCES_DIR, hdmi_index, list_tvs, output_for_index
from app.new_app import slugify


def _deep_merge(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in extra.items():
        out[key] = _deep_merge(out[key], value) if isinstance(value, dict) and isinstance(out.get(key), dict) else value
    return out


def _main_index() -> int:
    cfg = get_config()
    index = hdmi_index(cfg)
    if index is not None:
        return index
    match = re.search(r"cec(\d)", cfg.tv_control.cec_adapter or "")
    if match:
        return int(match.group(1))
    for status in sorted(Path("/sys/class/drm").glob("card*-HDMI-A-*/status")):
        if status.read_text().strip() == "connected":
            return int(status.parent.name[-1]) - 1
    return 0


def main() -> None:
    if ROOT_DIR != CODE_DIR:
        raise SystemExit("Bitte vom Hauptfernseher aus starten (ohne RPITV_DATA_ROOT).")
    parser = argparse.ArgumentParser(description="Weiteren Fernseher einrichten")
    parser.add_argument("name", nargs="?", default="Fernseher 2")
    parser.add_argument("--hdmi", type=int, choices=(0, 1))
    parser.add_argument("--port", type=int)
    parser.add_argument("--plain", action="store_true")
    args = parser.parse_args()

    tvs = list_tvs()
    tv_id = slugify(args.name)
    folder = INSTANCES_DIR / tv_id
    if folder.exists():
        raise SystemExit(f"{folder} gibt es schon – anderer Name oder Ordner löschen.")
    main_index = _main_index()
    index = args.hdmi if args.hdmi is not None else 1 - main_index
    if index == main_index:
        raise SystemExit(f"HDMI {index} nutzt schon der Hauptfernseher.")
    port = args.port or max(tv["port"] for tv in tvs) + 1
    browser_port = 9223 + len(tvs)

    # Hauptfernseher fest auf seinen Anschluss legen (sonst landet sein
    # Fenster evtl. auf dem neuen Bildschirm)
    from app import settings_store

    settings_store.update(config={"display.output": output_for_index(main_index), "display.primary": True})

    # Einstellungen der neuen Instanz
    own = {
        "dashboard": {"port": port, "title": args.name},
        "tv_control": {"cec_adapter": f"/dev/cec{index}" if Path(f"/dev/cec{index}").exists() else ""},
        "audio": {"alsa_device": f"plughw:CARD=vc4hdmi{index},DEV=0"},
        "display": {"output": output_for_index(index), "primary": False, "browser_port": browser_port},
    }
    base = {} if args.plain or not (CODE_DIR / "config.yaml").exists() else yaml.safe_load((CODE_DIR / "config.yaml").read_text(encoding="utf-8")) or {}
    for key in ("display",):
        base.pop(key, None)
    (folder / "data").mkdir(parents=True)
    (folder / "config.yaml").write_text(
        "# Weiterer Fernseher - von app/add_tv.py angelegt. Werte hier ueberschreiben\n"
        "# config.example.yaml; die Fernbedienung (data/settings.json) wiederum diese.\n"
        + yaml.safe_dump(_deep_merge(base, own), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    main_settings = settings_store.load()
    if args.plain:
        settings = {"setup_done": False, "apps": {}, "config": {}}
    else:
        settings = copy.deepcopy(main_settings)
        settings["config"].pop("display", None)
        settings["config"].setdefault("dashboard", {})["title"] = args.name
    (folder / "data" / "settings.json").write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    cfg = get_config()
    schedule = {
        "enabled": False,
        "weekday": {"wake_time": cfg.schedule.weekday.wake_time, "leave_time": cfg.schedule.weekday.leave_time},
        "weekend": {"wake_time": cfg.schedule.weekend.wake_time, "leave_time": cfg.schedule.weekend.leave_time},
    }
    (folder / "data" / "schedule.json").write_text(json.dumps(schedule, indent=2), encoding="utf-8")
    env_file = folder / ".env"
    if not args.plain and (CODE_DIR / ".env").exists():
        shutil.copy2(CODE_DIR / ".env", env_file)  # gleiches Passwort, gleiche Zugaenge
    else:
        env_file.write_text("REMOTE_CONTROL_SECRET=\n", encoding="utf-8")
    os.chmod(env_file, 0o600)

    # Dienst einrichten
    unit = (CODE_DIR / "systemd" / "rpitv-tv.service.template").read_text(encoding="utf-8")
    for key, value in {"__NAME__": args.name, "__INSTALL_DIR__": str(CODE_DIR), "__DATA_ROOT__": str(folder), "__RUN_USER__": os.environ.get("USER") or "pi"}.items():
        unit = unit.replace(key, value)
    service = f"rpitv-{tv_id}.service"
    with tempfile.NamedTemporaryFile("w", suffix=".service", delete=False, encoding="utf-8") as tmp:
        tmp.write(unit)
    print(f"Richte den Dienst {service} ein (sudo-Passwort) …")
    for cmd in (
        ["sudo", "cp", tmp.name, f"/etc/systemd/system/{service}"],
        ["sudo", "systemctl", "daemon-reload"],
        ["sudo", "systemctl", "enable", "--now", service],
    ):
        if subprocess.run(cmd).returncode != 0:
            raise SystemExit(f"Fehlgeschlagen: {' '.join(cmd)}")
    os.unlink(tmp.name)

    ip = (subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split() or ["pi.local"])[0]
    print(f"""
Fertig: „{args.name}“ an HDMI {index} ({output_for_index(index)}), eigener Dienst {service}.

  Fernbedienung:  http://{ip}:{port}/remote.html
  Hauptfernseher: bleibt an {output_for_index(main_index)} – bitte einmal neu starten,
                  damit sein Fenster fest auf seinem Bildschirm bleibt:
                  sudo systemctl restart dashboard.service

Übernommen vom Hauptfernseher: Apps, Zugangsdaten, Passwort. Der Wecker ist aus.
Der Fernseher wird per HDMI-CEC geschaltet ({own['tv_control']['cec_adapter'] or 'kein CEC-Adapter gefunden'}).
In der Fernbedienung: Einstellungen → „Fernseher & Ton testen“.""")


if __name__ == "__main__":
    sys.exit(main())
