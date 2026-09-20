# TV-Jarvis

Morgen-Briefing (Kalender, Stundenplan/Vertretungsplan, Wetter, ToDos) auf dem
Fernseher, vorgelesen und als Jarvis-artiges Dashboard angezeigt. Fernseher
geht automatisch an (Weckzeit) und wieder aus (Verlasszeit), am Wochenende mit
eigenen Zeiten und ohne Stundenplan. Läuft auf einem Raspberry Pi 4B.

## Voraussetzungen

- Raspberry Pi 4B mit Raspberry Pi OS **Desktop** (Bookworm/Trixie oder neuer,
  mit Autologin auf den Desktop – siehe unten), per HDMI an den Fernseher
  angeschlossen. Der Pi 4 hat zwei micro-HDMI-Ports mit je einem eigenen
  CEC-Adapter (`/dev/cec0`, `/dev/cec1`) – **egal an welchem der Fernseher
  hängt**, es muss nur der passende Adapter in `config.yaml`
  (`tv_control.cec_adapter`) eingetragen werden (siehe Schritt 3).
- Am Samsung-Fernseher: Einstellungen → Allgemein → Externe Geräteverwaltung
  → **Anynet+ (HDMI-CEC)** aktivieren, dort zusätzlich **Automatisches
  Ausschalten** aktivieren (ohne das ignoriert Samsung oft den
  CEC-Standby-Befehl).
- Autologin auf den Desktop einrichten (`sudo raspi-config` → System Options →
  Boot / Auto Login → Desktop Autologin), damit nach dem Hochfahren des Pi
  eine grafische Session für den Chromium-Kiosk existiert.
- Internetzugang für den Pi (Wetter, Kalender, IServ, ToDos).

## 1. Code auf den Pi bringen

Dieses Projekt wurde auf einem Windows-Rechner entwickelt. Auf den Pi
übertragen, z. B. per `git` (empfohlen: eigenes privates Repo, `.env` und
`config.yaml` sind über `.gitignore` ausgeschlossen) oder per `scp`:

```bash
scp -r tv-jarvis pi@<pi-ip>:/home/pi/tv-jarvis
```

## 2. Installation

```bash
cd /home/pi/tv-jarvis
sudo ./scripts/install.sh
```

Das Skript installiert Systempakete (cec-utils, mpv, chromium-browser,
alsa-utils), legt ein Python-Virtualenv an, installiert die
Python-Abhängigkeiten, kopiert `config.example.yaml` → `config.yaml` und
`.env.example` → `.env` (falls noch nicht vorhanden), lädt die deutsche
Piper-Stimme herunter und richtet die systemd-Dienste/Timer ein.

Falls der automatische Download der Piper-Stimme fehlschlägt (Netzwerk/URL
hat sich geändert): manuell von
[huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)
(`de/de_DE/thorsten/medium/`) die Dateien `de_DE-thorsten-medium.onnx` und
`.onnx.json` nach `data/piper-voices/` legen. Das `piper`-Binary selbst: von
den [Piper-Releases](https://github.com/rhasspy/piper/releases) die
`aarch64`-Variante laden und z. B. nach `/usr/local/bin` entpacken.

## 3. config.yaml anpassen

- **location**: Stadt für die Wetterabfrage (oder direkt `lat`/`lon`).
- **schedule**: Weck-/Verlasszeiten für Wochentage und Wochenende - dient nur
  als **Startwert** beim allerersten Lauf. Danach lebt der Zeitplan in
  `data/schedule.json` und lässt sich jederzeit live über die
  **Einstellungen-App** auf der Fernbedienung ändern (inkl. Wecker an/aus),
  ohne `config.yaml` anzufassen oder den Dienst neu zu starten.
- **tv_control**: `cec_device` bleibt meist `0`. `cec_adapter` ermitteln mit
  `for f in /sys/class/drm/*/status; do echo "$f: $(cat $f)"; done` (welcher
  HDMI-Port zeigt `connected`?) und `cec-client -l` (welcher `/dev/cecX`
  gehört dazu) - ohne diese Angabe kann `cec-client` den falschen der beiden
  Adapter wählen und jeder Befehl schlägt mit `power status: unknown` fehl.
- **audio.alsa_device**: Gleiches Thema wie beim CEC-Adapter - der Pi 4 hat
  zwei HDMI-Audio-Karten. Mit `aplay -l` den Kartennamen (z. B. `vc4hdmi1`)
  ermitteln, der zum verbundenen Port passt, und als
  `"plughw:CARD=vc4hdmi1,DEV=0"` eintragen (reines `hw:` ohne `plug`
  funktioniert oft nicht, da das Format sonst nicht passt).
- **calendars.google.ics_urls**: In Google Kalender → Einstellungen des
  jeweiligen Kalenders → "Kalender integrieren" → **"Geheime Adresse im
  iCal-Format"** kopieren.
- **calendars.icloud**: `calendar_names` leer lassen für alle Kalender, sonst
  genau wie in der iCloud-Kalender-App benannt.
- **iserv**: `base_url` eurer Schule eintragen. Die Selektoren (`selectors`)
  müssen an die echte Seite angepasst werden, siehe Abschnitt "IServ-
  Feinschliff" unten.
- **radio.stream_url**: nur noch der Fallback, falls `data/radio_stations.json`
  fehlt - die eigentliche Senderliste (Standard: Sunshine Live + 1LIVE) lässt
  sich über die Radio- bzw. Einstellungen-App auf der Fernbedienung verwalten.
  Stream-URLs vorher im Browser/VLC testen (Sender ändern ihre
  Streaming-Infrastruktur gelegentlich).

## 4. .env ausfüllen

```
ISERV_USERNAME=...
ISERV_PASSWORD=...
ICLOUD_APPLE_ID=...
ICLOUD_APP_SPECIFIC_PASSWORD=...
TODOS_WEBHOOK_SECRET=irgendein-langes-zufälliges-secret
```

**App-spezifisches Passwort für iCloud:** appleid.apple.com → Anmelden und
Sicherheit → App-spezifische Passwörter → neues erzeugen. **Nicht** das
normale Apple-ID-Passwort verwenden.

## 5. ToDos aus iCloud-Notizen (Shortcuts-Automation)

Da Apple keine offizielle API für Notizen anbietet, übernimmt das eine kleine
Automation in der **Kurzbefehle**-App (iPhone oder Mac):

1. Neuer Kurzbefehl: Aktion **"Notiz abrufen"** (die gewünschte ToDo-Notiz
   auswählen) → Aktion **"Inhalte von URL abrufen"**.
2. URL: `http://<pi-ip>:8080/api/todos/webhook`, Methode `POST`.
3. Header hinzufügen: `X-Webhook-Secret` = der Wert aus `TODOS_WEBHOOK_SECRET`
   in eurer `.env`.
4. Anfragetext (JSON): `{"text": "Text der Notiz"}` (Text der Notiz aus
   Schritt 1 einsetzen/verketten - jede Zeile der Notiz wird ein ToDo).
5. Automation: Unter "Automation" → neue persönliche Automation → "Zeitplan"
   (z. B. jeden Morgen kurz vor der Weckzeit) oder "App" (wenn Notizen
   geschlossen wird) → obigen Kurzbefehl ausführen, ohne vorher zu fragen.

Alternative: `todos.provider: notion` in `config.yaml` setzen und
`NOTION_TOKEN` + `notion.database_id` eintragen (offizielle REST-API, robuster
als der iCloud-Weg, falls die Shortcuts-Automation zu unzuverlässig ist).

## 6. IServ-Feinschliff

Jede Schule stellt den Vertretungsplan in IServ anders dar. Der mitgelieferte
Scraper (`app/sources/iserv.py`) ist ein Grundgerüst mit konfigurierbaren
CSS-Selektoren. Nach der ersten Installation:

1. Testlauf: `.venv/bin/python -m app.routines.morning_routine` und
   `data/state.json` → Feld `substitution_plan` prüfen.
2. Ist die Liste leer/falsch: HTML-Quelltext der eingeloggten
   Vertretungsplan-Seite besorgen (z. B. im Browser einloggen, Seite
   speichern) und die Selektoren in `config.yaml` (`iserv.selectors`)
   entsprechend anpassen.

## 7. Testen

```bash
sudo systemctl status dashboard.service
sudo -u pi /home/pi/tv-jarvis/.venv/bin/python -m app.routines.morning_routine
sudo -u pi /home/pi/tv-jarvis/.venv/bin/python -m app.routines.leave_routine
```

Nützliche Befehle:

```bash
sudo systemctl restart dashboard.service
journalctl -u dashboard.service -e
```

Der Zeitplan (Weckzeiten, Wecker an/aus) wird von `dashboard.service` selbst
im Hintergrund überwacht (kein separater Timer mehr, siehe
[Architektur](#architektur-kurzüberblick)) und lässt sich jederzeit über die
Einstellungen-App auf `/remote.html` ändern - Änderungen wirken sofort, ganz
ohne Neustart.

**Schnelltest ohne den Zeitplan anzufassen:** `./scripts/quick_test.sh [Sekunden]`
löst die komplette Routine sofort aus (TV an, Briefing, Radio), wartet die
angegebene Zeit (Standard 120s) und fährt dann wieder runter (Radio aus, TV
aus) - ohne `config.yaml` oder die systemd-Timer zu verändern.

## Fernbedienung (iPhone/iPad)

Der Dashboard-Server hostet unter `/remote.html` eine mobile Fernbedienung im
Tablet-Look, solange `dashboard.host: "0.0.0.0"` in `config.yaml` gesetzt ist
(Standard). Im selben WLAN wie der Pi im Browser öffnen (am besten "Zum
Home-Bildschirm" hinzufügen für App-artigen Vollbild-Zugriff):

```
http://<pi-ip>:8080/remote.html
```

Aufbau wie ein Tablet-Homescreen:

- **Homescreen**: Fernseher an/aus, darunter App-Icons für YouTube, Radio und
  Einstellungen.
- **YouTube-App**: Link einfügen und abspielen (Stopp-Knopf als "×" im
  Eingabefeld), Now-Playing-Karte mit Thumbnail, Titel und scrubbarem
  Fortschrittsbalken (an eine beliebige Stelle springen durch Ziehen), 10s
  zurück/vor sowie ein Pause/Weiter-Knopf, der seine Beschriftung automatisch
  umschaltet.
- **Radio-App**: zwischen den konfigurierten Sendern wechseln (Standard:
  Sunshine Live, 1LIVE) sowie Stopp.
- **Einstellungen-App**: Wecker an/aus + Weck-/Verlasszeiten für Wochentag und
  Wochenende (wirkt sofort, siehe oben), Radiosender hinzufügen/entfernen.
- **Control-Dock**: am unteren Rand fest sichtbar, egal welche App gerade
  offen ist - Home, Lautstärke -/+, Stumm und ein Pause/Weiter-Knopf, der
  automatisch YouTube oder Radio steuert (je nachdem, was gerade läuft).

YouTube läuft direkt im Kiosk-Fenster (YouTube IFrame API, Untertitel und das
eigene Pause-Overlay von YouTube sind unterdrückt); beim Abspielen wird das
Radio automatisch gestoppt und umgekehrt.

**Absicherung:** Ohne `REMOTE_CONTROL_SECRET` in `.env` ist die Fernbedienung
ohne Passwort nutzbar (ok fürs eigene, vertrauenswürdige WLAN). Zum Absichern
in `.env` einen Wert eintragen - die Seite fragt dann beim ersten Laden
einmalig danach und merkt sich das Passwort im Browser.

## Architektur (Kurzüberblick)

```
app/
  config.py            Config-/Secrets-Loader
  briefing.py           Sammelt alle Quellen parallel, baut Text + JSON
  tts.py                 Piper-Wrapper
  radio.py                mpv-Steuerung, spielt den aktuell gewaehlten Sender
  radio_stations.py        Sender-Liste + aktueller Sender (data/radio_stations.json)
  schedule_store.py         Laufzeit-Zeitplan, per Einstellungen-App editierbar
                             (data/schedule.json)
  scheduler.py               In-Prozess-Scheduler in dashboard.service - loest
                              morning_routine/leave_routine zur konfigurierten
                              Zeit aus (ersetzt die frueheren systemd-Timer)
  tv_power.py                 Gemeinsames An/Aus (Routinen + Fernbedienung)
  kiosk_media.py                YouTube-Steuerung (WebSocket-Broadcast)
  audio_control.py               Lautstaerke ueber PipeWire/wpctl
  sources/                        Wetter, Google-ICS, iCloud-CalDAV, IServ, ToDos
  tv_control/                      CEC- und Steckdosen-Backend (austauschbar)
  dashboard/                        FastAPI-Server + Jarvis-Frontend (static/:
                                     index.html/app.js fuers Kiosk-Fenster,
                                     remote.html/css/js fuers Handy)
  routines/                          morning_routine.py / leave_routine.py
systemd/                              dashboard.service-Vorlage (von install.sh
                                       gerendert - der einzige systemd-Dienst,
                                       der Zeitplan laeuft in-Prozess mit)
scripts/install.sh                     Komplette Einrichtung auf dem Pi
scripts/fix_audio_sink.sh               Setzt HDMI als PipeWire-Standardausgabe
                                         (per labwc-Autostart bei jedem Login)
```

Mehr Details/Hintergrund zu den Design-Entscheidungen: siehe Plan-Historie in
diesem Projekt (Config-Kommentare in `config.example.yaml` sind meist
selbsterklärend).

## Smart-Plug-Fallback

Aktuell ist CEC (Samsung Anynet+) die primäre Steuerung. Falls das in der
Praxis nicht zuverlässig funktioniert: `tv_control.backend: smart_plug` in
`config.yaml` setzen und `app/tv_control/smart_plug.py` mit der passenden
Bibliothek für eure Steckdosenmarke füllen (Kommentare in der Datei enthalten
konkrete Empfehlungen je nach Marke).
