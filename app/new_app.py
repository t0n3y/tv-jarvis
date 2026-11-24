"""Neue App anlegen:  .venv/bin/python -m app.new_app "Mein App-Name"

Legt apps/<id>/ mit einer kleinen, sofort lauffaehigen App an: eine Ansicht
in der Fernbedienung, eine Seite fuer den Fernseher und eine eigene API.
Danach den Dienst neu starten (wegen server.py) und die App im App Store
einschalten. Anleitung: apps/README.md
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata

from app.plugins import APPS_DIR, ID_PATTERN

APP_JSON = {
    "name": "",
    "icon": "star",
    "color": "255, 149, 0",
    "category": "Weitere Apps",
    "summary": "Schickt eine Nachricht vom Handy groß auf den Fernseher.",
    "author": "",
    "version": "1.0",
    "fields": [
        {"key": "signature", "label": "Unterschrift unter jeder Nachricht", "type": "text", "placeholder": "z. B. Mama"},
    ],
    "guide": [
        "In der App eine Nachricht eintippen und <b>Auf den Fernseher</b> drücken.",
        "Mit <b>Schließen</b> zeigt der Fernseher wieder das Dashboard.",
    ],
}

REMOTE_HTML = """<!-- Ansicht in der Fernbedienung. Die Klassen (card, field, btn, hint ...)
     kommen aus remote.css - so sieht die App aus wie der Rest. -->
<div class="card stack">
  <div class="kicker">Nachricht</div>
  <label class="field"><input data-ref="text" type="text" placeholder="Was soll auf dem Fernseher stehen?" /></label>
  <button class="btn btn-primary btn-block" data-ref="show" type="button">Auf den Fernseher</button>
  <button class="btn btn-ghost btn-block" data-ref="close" type="button">Schließen</button>
</div>
<p class="hint" data-ref="last"></p>
"""

REMOTE_JS = """"use strict";

// Laeuft in der Fernbedienung. RPiTV.app() liefert alles, was die App braucht
// (siehe apps/README.md). Alles in eine Funktion packen, damit sich Namen
// nicht mit anderen Apps ueberschneiden.
(() => {
  const app = RPiTV.app();
  const ref = (name) => app.el.querySelector(`[data-ref="${name}"]`);

  async function refresh() {
    const data = await app.api.get("message");
    ref("last").textContent = data.text ? `Zuletzt: „${data.text}“` : "";
  }

  ref("show").addEventListener("click", async () => {
    try {
      await app.api.post("message", { text: ref("text").value });
      await app.tv.open("tv.html");
      app.toast("Läuft auf dem Fernseher");
      refresh();
    } catch (err) {
      app.toast(err.message, true);
    }
  });

  ref("close").addEventListener("click", () => app.tv.close().catch((err) => app.toast(err.message, true)));

  // Bei jedem Oeffnen der App
  app.onOpen(refresh);
})();
"""

REMOTE_CSS = """/* Nur fuer diese App. Immer mit #view-app-__ID__ beginnen, dann bleibt der
   Rest der Fernbedienung unberuehrt. */
#view-app-__ID__ .hint:empty { display: none; }
"""

TV_HTML = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8" />
<title>__NAME__</title>
<style>
  html, body { margin: 0; height: 100%; background: #000; color: #fff; cursor: none;
    font-family: -apple-system, "Inter", "Helvetica Neue", system-ui, sans-serif; }
  main { height: 100%; display: grid; place-content: center; gap: 4vh; padding: 8vw; text-align: center; }
  #text { font-size: 9vh; font-weight: 700; line-height: 1.15; letter-spacing: -0.02em; }
  #signature { font-size: 3.4vh; color: rgba(235, 235, 245, 0.6); }
</style>
</head>
<body>
<main>
  <div id="text"></div>
  <div id="signature"></div>
</main>
<script>
  // Laeuft auf dem Fernseher (TV-Browser auf dem Pi) - darf die API der App
  // ohne Passwort aufrufen, weil die Anfrage vom Pi selbst kommt.
  async function update() {
    const data = await fetch("/api/apps/__ID__/message").then((r) => r.json());
    document.getElementById("text").textContent = data.text || "";
    document.getElementById("signature").textContent = data.signature ? `– ${data.signature}` : "";
  }
  update();
  setInterval(update, 2000);
</script>
</body>
</html>
"""

SERVER_PY = '''"""Server-Teil der App: alles unter /api/apps/__ID__/...

ctx (siehe app/plugins.py) bietet:
  ctx.settings()            Felder aus app.json, wie im App Store eingetragen
  ctx.secret("NAME")        Geheimnis aus app.json ("secret": "NAME")
  ctx.load(name) / ctx.save(daten, name)   JSON-Speicher in data/apps/__ID__/
  await ctx.show_on_tv("tv.html") / await ctx.close_tv()
  ctx.say("Text")           mit der Stimme ueber den Fernseher sprechen
  ctx.config                gesamte Konfiguration (Name, Ort, ...)
  ctx.log                   Logger (journalctl -u dashboard.service)
"""

from fastapi import APIRouter, HTTPException, Request

from app.plugins import context

ctx = context(__file__)
router = APIRouter()


@router.get("/message")
def get_message() -> dict:
    data = ctx.load("message", {"text": ""})
    return {"text": data["text"], "signature": ctx.settings().get("signature", "")}


@router.post("/message")
async def set_message(request: Request) -> dict:
    body = await request.json()
    text = str(body.get("text") or "").strip()[:200]
    if not text:
        raise HTTPException(status_code=400, detail="Bitte eine Nachricht eintippen")
    ctx.save({"text": text}, "message")
    ctx.log.info("Neue Nachricht: %s", text)
    return {"ok": True}


def test() -> str:
    """Knopf "Verbindung testen" im App Store (optional)."""
    return f"Läuft - letzte Nachricht: {ctx.load('message', {'text': '–'})['text']}"
'''


def slugify(name: str) -> str:
    text = name.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if not text or not text[0].isalpha():
        text = f"app_{text}"
    return text[:30]


def create(name: str) -> str:
    app_id = slugify(name)
    if not ID_PATTERN.match(app_id):
        raise SystemExit(f"Aus „{name}“ wird kein gültiger Ordnername ({app_id})")
    folder = APPS_DIR / app_id
    if folder.exists():
        raise SystemExit(f"{folder} gibt es schon")
    folder.mkdir(parents=True)
    manifest = {**APP_JSON, "name": name}
    files = {
        "app.json": json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        "remote.html": REMOTE_HTML,
        "remote.js": REMOTE_JS,
        "remote.css": REMOTE_CSS,
        "tv.html": TV_HTML,
        "server.py": SERVER_PY,
    }
    for file_name, content in files.items():
        content = content.replace("__ID__", app_id).replace("__NAME__", name)
        (folder / file_name).write_text(content, encoding="utf-8", newline="\n")
    return app_id


def main() -> None:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        raise SystemExit('Aufruf: .venv/bin/python -m app.new_app "Mein App-Name"')
    name = sys.argv[1].strip()
    app_id = create(name)
    print(f"""Fertig: apps/{app_id}/

  app.json     Name, Symbol, Farbe, Felder, Anleitung im App Store
  remote.html  Ansicht in der Fernbedienung
  remote.js    Logik dazu (RPiTV.app())
  remote.css   Aussehen dazu
  tv.html      Seite für den Fernseher
  server.py    eigene API unter /api/apps/{app_id}/

Nächste Schritte:
  1. sudo systemctl restart dashboard.service   (lädt server.py)
  2. Fernbedienung -> App Store -> "{name}" einschalten
  3. Loslegen: Dateien ändern, Seite neu laden. Nur nach Änderungen an
     server.py muss der Dienst neu starten.

Anleitung: apps/README.md""")


if __name__ == "__main__":
    main()
