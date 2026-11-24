# Eigene Apps bauen

Eine App ist ein **Ordner in `apps/`**. Sie erscheint automatisch im App Store
der Fernbedienung. Man kann sie dort ein- und ausschalten, sie bekommt eine
Kachel auf dem Homescreen und kann eigene Einstellungen, eine eigene API und
eine eigene Seite auf dem Fernseher haben. Am Kern musst du nichts ändern.

## In 1 Minute zur ersten App

Auf dem Pi im Projektordner:

```bash
.venv/bin/python -m app.new_app "Meine App"
sudo systemctl restart dashboard.service
```

Danach in der Fernbedienung **App Store → Meine App** einschalten. Die
neue App ist schon lauffähig: Du tippst eine Nachricht ein, und sie erscheint
groß auf dem Fernseher. Von dort aus baust du sie um. Die App
[`pinnwand/`](pinnwand) ist genau so entstanden und dient als Beispiel.

Tipp zum Entwickeln: HTML/JS/CSS ändern → Fernbedienung neu laden, fertig.
Nur nach Änderungen an `server.py` oder `app.json`-Feldern den Dienst neu
starten.

## Aufbau eines App-Ordners

```
apps/meine_app/
  app.json      Pflicht: Steckbrief für den App Store
  remote.html   Ansicht in der Fernbedienung          (optional)
  remote.js     Logik der Ansicht                     (optional)
  remote.css    Aussehen der Ansicht                  (optional)
  tv.html       Seite für den Fernseher               (optional)
  server.py     eigene API unter /api/apps/meine_app/  (optional)
  icon.svg      eigenes Symbol                        (optional)
```

Der Ordnername ist die **ID** der App: nur `a-z`, `0-9` und `_`, beginnend mit
einem Buchstaben. Ordner, die mit `_` oder `.` beginnen, werden ignoriert.
Eine App ohne `remote.html`/`remote.js` hat keine Kachel. Das passt etwa für
reine Hintergrund-Apps.

## app.json

```json
{
  "name": "Meine App",
  "icon": "star",
  "color": "255, 149, 0",
  "category": "Weitere Apps",
  "summary": "Ein Satz, was die App macht.",
  "author": "Dein Name",
  "version": "1.0",
  "homepage": "https://github.com/du/meine-app",
  "fields": [
    { "key": "stadt", "label": "Deine Stadt", "type": "text", "placeholder": "z. B. Berlin" },
    { "secret": "MEINE_APP_TOKEN", "label": "API-Schlüssel", "type": "password" }
  ],
  "guide": [
    "Schritt 1 der Anleitung – <b>fett</b> und <code>befehl</code> gehen.",
    "Schritt 2 …"
  ]
}
```

| Feld | Bedeutung |
| --- | --- |
| `name` | Pflicht. Name auf der Kachel und im App Store |
| `icon` | Eingebautes Symbol (Liste unten) – oder lege `icon.svg` in den Ordner |
| `color` | Farbe der Kachel als `"r, g, b"` |
| `category` | Überschrift im App Store, Standard „Weitere Apps“ |
| `fields` | Einstellungen im App Store. `key` = normaler Wert (landet in `data/settings.json`), `secret` = Zugangsdaten (landen in `.env`, werden nie an den Browser geschickt). `type`: `text`, `url`, `password`, `number`, `lines` (ein Wert pro Zeile). `"generate": true` zeigt einen Knopf, der ein zufälliges Geheimnis erzeugt |
| `guide` | Schritt-für-Schritt-Anleitung im App Store (etwas HTML erlaubt) |

**Eingebaute Symbole:** `star`, `tv`, `radio`, `vinyl`, `film`, `youtube`,
`twitch`, `jellyfin`, `sun`, `alarm`, `timer`, `calendar`, `school`, `book`,
`globe`, `mic`, `keyboard`, `person`, `folder`, `link`, `search`, `check`,
`speaker`, `play`, `sliders`, `bag`, `upload`.
Eigenes Symbol: `icon.svg` mit `viewBox="0 0 24 24"` und Linien
(`stroke="currentColor"`, kein `fill`), wie bei [`pinnwand/icon.svg`](pinnwand/icon.svg).

## remote.html + remote.js: die Ansicht in der Fernbedienung

`remote.html` ist nur der **Inhalt** der Ansicht. Kopfzeile und Zurück-Knopf
kommen automatisch dazu. Nutze die Bausteine der Fernbedienung, dann sieht
die App aus wie der Rest:

```html
<div class="card stack">            <!-- Fläche mit Abstand -->
  <div class="kicker">Überschrift</div>
  <label class="field"><input type="text" placeholder="…" /></label>
  <button class="btn btn-primary btn-block">Großer Knopf</button>
  <button class="btn btn-ghost btn-block">Zweiter Knopf</button>
</div>
<div class="section-label">Abschnitt</div>
<div class="group">                 <!-- Liste wie in den Einstellungen -->
  <div class="group-row"><span class="row-label">Zeile</span>…</div>
</div>
<p class="hint">Kleiner grauer Hinweis</p>
```

In `remote.js` holst du dir mit `RPiTV.app()` alles, was die App braucht:

```js
(() => {
  const app = RPiTV.app();

  app.el                        // die Ansicht (remote.html steckt schon drin)
  app.onOpen(async () => {})    // läuft bei jedem Öffnen der App
  await app.api.get("pfad")     // GET  /api/apps/<id>/pfad  (Passwort kommt automatisch mit)
  await app.api.post("pfad", { … })
  await app.api.del("pfad")
  await app.tv.open("tv.html")  // Seite der App im Vollbild auf dem Fernseher
  await app.tv.close()          // … und zurück zum Dashboard
  app.toast("Gespeichert")      // kurze Meldung; app.toast("Fehler", true)
  app.file("bild.png")          // Adresse einer Datei aus dem App-Ordner
  app.h("div", { class: "card" }, "Text")   // Element bauen
  app.icon("star")              // Symbol als <svg>
})();
```

Pack alles in `(() => { … })();`, damit sich deine Namen nicht mit anderen
Apps überschneiden. In `remote.css` jede Regel mit `#view-app-<id>` beginnen.
Die Akzentfarbe (`color` aus `app.json`) steht als `rgb(var(--tint))`
bereit.

## tv.html: die Seite auf dem Fernseher

Eine normale HTML-Seite. `app.tv.open()` aus der Fernbedienung (oder
`await ctx.show_on_tv()` im Server) zeigt sie im Vollbild auf dem
Fernseher. Ist der Fernseher aus, schaltet er sich dabei ein, und das Radio
stoppt. Die Seite läuft auf dem Pi selbst und darf deshalb
`/api/apps/<id>/…` **ohne Passwort** aufrufen. Ein Beispiel:

```js
const data = await fetch("/api/apps/meine_app/status").then((r) => r.json());
```

Gestaltung für den Fernseher: schwarzer Hintergrund, große Schrift in `vh`,
viel Rand. Von der Couch aus muss man alles lesen können.

## server.py: eigene API

```python
from fastapi import APIRouter, Request
from app.plugins import context

ctx = context(__file__)
router = APIRouter()          # erreichbar unter /api/apps/<id>/...


@router.get("/status")
def status() -> dict:
    stadt = ctx.settings().get("stadt", "")         # Feld aus app.json
    token = ctx.secret("MEINE_APP_TOKEN")           # Geheimnis aus app.json
    return {"stadt": stadt, "verbunden": bool(token)}


@router.post("/merken")
async def merken(request: Request) -> dict:
    daten = ctx.load("liste", [])                   # data/apps/<id>/liste.json
    daten.append((await request.json())["text"])
    ctx.save(daten, "liste")
    return {"ok": True}


def test() -> str:            # optional: Knopf „Verbindung testen“ im App Store
    return "Alles gut"
```

| `ctx.…` | |
| --- | --- |
| `settings()` | Werte der `key`-Felder aus dem App Store |
| `secret("NAME")` | Wert eines `secret`-Felds |
| `load(name, standard)` / `save(daten, name)` | JSON-Speicher in `data/apps/<id>/` |
| `await show_on_tv("tv.html")` / `await close_tv()` | Seite auf dem Fernseher öffnen/schließen (auch `https://…`) |
| `say("Text")` | Mit der Stimme über den Fernseher sprechen (blockiert; in `async`-Funktionen `await asyncio.to_thread(ctx.say, "…")`) |
| `config` | Gesamte Konfiguration, z. B. `ctx.config.dashboard.title`, `ctx.config.location.city` |
| `log` | Logger, zu lesen mit `journalctl -u dashboard.service` |
| `data_dir` / `dir` | Speicherordner / App-Ordner als `Path` |

Alle Routen sind geschützt: Die Fernbedienung braucht das Passwort, der
Fernseher (Anfragen vom Pi selbst) nicht. Langsame Dinge (Netz, Dateien)
gehören in normale `def`-Funktionen. FastAPI führt die automatisch im
Hintergrund aus. Hat `server.py` einen Fehler, läuft der Rest weiter. Die
App zeigt dann im App Store „Fehler“, Details stehen im Log.

## Weitergeben

Einfach den Ordner teilen, z. B. als eigenes Git-Repo. Andere legen ihn nach
`apps/`, starten den Dienst neu und schalten die App im App Store ein. Eine
gute App:

- hat eine `guide` mit allen Schritten, die man außerhalb erledigen muss
  (Konten, Schlüssel, Geräte),
- speichert Zugangsdaten nur über `secret`-Felder,
- hat einen `test()`, wenn sie sich mit etwas verbindet.

Apps, die ins Repo kommen, stehen wie das ganze Projekt unter der
PolyForm Noncommercial License.
