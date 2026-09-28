"""ToDos aus einer iCloud-Notiz, angeliefert per iOS/Mac-Shortcuts-Automation.

Apple bietet keine offizielle API fuer Notizen. Der zuverlaessigste Weg ohne
inoffizielle/instabile Libraries: eine Shortcuts-Automation auf iPhone/Mac liest
die Notiz (offizieller On-Device-Zugriff) und schickt den Text per HTTP POST an
den kleinen Webhook-Endpunkt, den dashboard/server.py bereitstellt
(POST /api/todos/webhook, siehe README fuer die Shortcuts-Einrichtung).

Dieses Modul kuemmert sich nur um die Ablage/den Abruf der zuletzt empfangenen
Liste (data/todos_cache.json). Eine Zeile in der Notiz = ein ToDo.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.config import Config


def write_todos_cache(cache_file: Path, items: list) -> None:
    """items: Texte oder {"text", "done"} (aus parse_note). "items" im Cache
    bleiben die offenen Punkte (Sprachausgabe), "entries" alle mit Haken-Status
    in Notiz-Reihenfolge (Dashboard)."""
    entries = [i if isinstance(i, dict) else {"text": str(i), "done": False} for i in items]
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "items": [e["text"] for e in entries if not e["done"]],
        "entries": entries,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def get_todos(cfg: Config) -> list[str]:
    if not cfg.todos.cache_file.exists():
        return []
    try:
        data = json.loads(cfg.todos.cache_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return [str(item).strip() for item in data.get("items", []) if str(item).strip()]


def get_entries(cfg: Config) -> list[dict]:
    """Alle Punkte der Notiz, auch abgehakte: [{"text": ..., "done": bool}]."""
    if not cfg.todos.cache_file.exists():
        return []
    try:
        data = json.loads(cfg.todos.cache_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if "entries" in data:
        return [{"text": str(e.get("text", "")).strip(), "done": bool(e.get("done"))} for e in data["entries"] if str(e.get("text", "")).strip()]
    return [{"text": t, "done": False} for t in get_todos(cfg)]


# Aufzaehlungen/Checklisten, wie sie der Kurzbefehl aus der Notizen-App liefert
# ("- [ ] Layout", "• Milch", "☐ Muell"). Erledigte Punkte ("[x]", "☑")
# werden mit done=True mitgeliefert (Dashboard zeigt sie durchgestrichen).
_MARKER = re.compile(r"^\s*(?:[-*•◦▪‣·]|☐|☑|✓|✔|\[[  xX✓]?\])\s*")
_DONE = re.compile(r"^\s*(?:[-*•]\s*)?(?:☑|✓|✔|\[[xX✓]\])")


def parse_note(text: str, title: str = "") -> list[dict]:
    lines: list[tuple[str, bool, bool]] = []  # (Text, hatte Aufzaehlungszeichen, abgehakt)
    for line in text.splitlines():
        if not line.strip():
            continue
        done = bool(_DONE.match(line))
        clean = line
        while True:
            stripped = _MARKER.sub("", clean, count=1)
            if stripped == clean:
                break
            clean = stripped
        clean = clean.strip()
        if clean:
            lines.append((clean, clean != line.strip(), done))
    # Die erste Zeile einer Notiz ist ihr Titel ("Zu tun Jarvis") - erkennbar
    # am mitgeschickten Titel oder daran, dass nur sie kein Kaestchen hat.
    if lines:
        first, first_marked, _ = lines[0]
        if (title and first == title.strip()) or (not first_marked and any(m for _, m, _ in lines[1:])):
            lines = lines[1:]
    return [{"text": text, "done": done} for text, _, done in lines]
