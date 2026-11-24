"""Baut die Live-Vorschau (statische Webseite) nach _site/.

    python scripts/build_demo.py            # Seite bauen (nur Standardbibliothek)
    python scripts/build_demo.py --data     # demo/data.json neu erzeugen (braucht
                                            # die Python-Pakete des Projekts)

Die Vorschau nutzt die ECHTEN Dateien von Fernbedienung und Fernseher
(app/dashboard/static, apps/*). Statt des Pi antwortet demo/server.js im
Browser - alles im Speicher, nach dem Neuladen ist alles wieder wie am Anfang.
Damit das unter einer Unteradresse (GitHub Pages: /tv-jarvis/) laeuft, werden
absolute Pfade ("/api/...", "/apps/...") relativ gemacht.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "dashboard" / "static"
OUT = ROOT / "_site"
# Nur was die Vorschau braucht (keine Seiten anderer, noch unfertiger Teile)
STATIC_FILES = [
    "index.html", "app.js", "style.css", "vinyl.css", "clock.css",
    "remote.html", "remote.js", "remote.css", "remote-vinyl.css", "remote-subs.js",
    "remote-browser.js", "remote-store.js", "remote-store.css", "apple-touch-icon.png",
]
APP_FILE_TYPES = {".html", ".js", ".css", ".svg", ".png", ".jpg", ".webp"}
SHIM = '<script src="{prefix}demo/shim.js"></script>'
PATH_RE = re.compile(r"""(["'`(])/(api|apps|ws)/""")


def relative_paths(text: str) -> str:
    text = PATH_RE.sub(r"\1\2/", text)
    return text.replace('"/comics.html"', '"comics.html"')


def inject_shim(html: str, prefix: str) -> str:
    # Vor allen anderen Skripten - fetch und WebSocket muessen schon ersetzt sein
    marker = "<script"
    index = html.find(marker)
    tag = SHIM.format(prefix=prefix) + "\n"
    return html[:index] + tag + html[index:] if index >= 0 else html.replace("</head>", tag + "</head>")


def copy_text(src: Path, dst: Path, shim_prefix: str | None = None) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = relative_paths(src.read_text(encoding="utf-8"))
    if shim_prefix is not None:
        text = inject_shim(text, shim_prefix)
    dst.write_text(text, encoding="utf-8")


def build() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    for name in STATIC_FILES:
        src = STATIC / name
        if src.suffix in {".html", ".js", ".css"}:
            copy_text(src, OUT / name, "" if name in {"index.html", "remote.html"} else None)
        else:
            shutil.copy2(src, OUT / name)
    for app_dir in sorted((ROOT / "apps").iterdir()):
        if not app_dir.is_dir() or app_dir.name.startswith((".", "_")):
            continue
        for src in app_dir.iterdir():
            if src.suffix not in APP_FILE_TYPES or src.name.startswith("_"):
                continue
            dst = OUT / "apps" / app_dir.name / src.name
            if src.suffix in {".html", ".js", ".css"}:
                copy_text(src, dst, "../../" if src.suffix == ".html" else None)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    # Startseite = Vorschau (demo/index.html), die Fernseher-Seite heisst tv.html
    shutil.move(str(OUT / "index.html"), OUT / "tv.html")
    shutil.copytree(ROOT / "demo", OUT / "demo")
    shutil.move(str(OUT / "demo" / "index.html"), OUT / "index.html")
    (OUT / ".nojekyll").write_text("", encoding="utf-8")
    print(f"Vorschau gebaut: {OUT}")


def build_data() -> None:
    """Steckbriefe aller Apps + Licht-Effekte fuer die Vorschau."""
    sys.path.insert(0, str(ROOT))
    from app import apps  # noqa: PLC0415
    from app.lighting import engine  # noqa: PLC0415

    data = {"apps": apps.public_list(), "effects": engine.effect_catalog()}
    for app in data["apps"]:
        for field in app["fields"]:
            field["is_set"] = False if "is_set" in field else field.get("is_set")
    (ROOT / "demo" / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("demo/data.json geschrieben")


if __name__ == "__main__":
    build_data() if "--data" in sys.argv else build()
