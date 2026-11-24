# RPi TV

Ein Raspberry Pi macht aus jedem Fernseher mit HDMI ein kleines Zuhause-System:
morgens geht der Fernseher von selbst an, zeigt Wetter, Termine, ToDos und den
Vertretungsplan und liest alles vor. Danach läuft Radio. Gesteuert wird alles
mit dem Handy über eine Fernbedienungs-Web-App im Apple-Stil, inklusive
Jellyfin, YouTube, Twitch, Plattenschrank, Licht, Comics und Sprachschach.

Name, Apps und Zugangsdaten stellst du in der Fernbedienung ein. Den Namen
„RPi TV“ kannst du durch deinen eigenen ersetzen: Er erscheint dann auf dem
Fernseher, in der App und in der Sprachausgabe.

## Installation: ein Befehl

Du brauchst:

- einen **Raspberry Pi 4 oder 5** mit **Raspberry Pi OS (64 Bit, mit Desktop)**
  und Internet (am besten per LAN-Kabel),
- einen **Fernseher mit HDMI-CEC**, damit der Pi ihn ein- und ausschalten
  kann. Je nach Marke heißt das *Anynet+* (Samsung), *Bravia Sync* (Sony),
  *SimpLink* (LG) oder *EasyLink* (Philips). Bei Samsung zusätzlich
  „Automatisches Ausschalten“ aktivieren.

Auf dem Pi ein Terminal öffnen (oder per SSH) und eingeben:

```bash
curl -fsSL https://raw.githubusercontent.com/t0n3y/tv-jarvis/main/scripts/install.sh | bash
```

Das Skript fragt einmal nach deinem Passwort (für `sudo`). Danach erledigt es
alles: Systempakete, Python-Umgebung, deutsche Stimme (Piper), Geräte-Rechte,
automatische Desktop-Anmeldung und den Systemdienst. Zum Schluss zeigt es
eine Adresse und einen **QR-Code** an.

## Einrichtung: in der Fernbedienung

QR-Code mit dem Handy scannen (gleiches WLAN) oder
`http://<name-des-pi>.local:8080/remote.html` öffnen. Ein Assistent führt in
vier Schritten durch die Einrichtung:

1. **Name** des Systems, dein Vorname und dein Ort fürs Wetter
2. **Fernseher**: Der Pi sucht den HDMI-Anschluss selbst. Mit „Fernseher
   testen“ geht der Fernseher an und sagt Hallo.
3. **Apps** auswählen
4. **Passwort** für die Fernbedienung (wird vorgeschlagen)

Tipp fürs iPhone: In Safari *Teilen → Zum Home-Bildschirm* tippen, dann liegt
die Fernbedienung wie eine normale App auf dem Home-Bildschirm.

## App Store

Im **App Store** in der Fernbedienung schaltest du Apps ein und aus. Jede App
hat eine Schritt-für-Schritt-Anleitung. Bei Apps mit Zugangsdaten gibt es
außerdem „Verbindung testen“.

| App | Was sie macht | Was du brauchst |
| --- | --- | --- |
| **Jellyfin** | Filme und Serien vom eigenen Mediaserver, Weiterschauen, Upload vom Handy | Jellyfin-Server + API-Schlüssel |
| **YouTube** | Links vom Handy abspielen, neueste Videos deiner Abos | für Abos: einmal im TV-Browser anmelden |
| **Twitch** | Lieblings-Streamer: wer ist live, Stream im Vollbild ohne Chat | nichts |
| **Plattenschrank** | Plattenspieler auf dem Fernseher, Schränke pro Genre | nichts |
| **Licht** | DMX-Scheinwerfer, Farben und Effekte im Takt | uDMX-USB-Adapter |
| **Sprachschach** | chess.com gegen Bots oder online, Züge per Sprache | chess.com-Konto |
| **Comics** | Reader mit Doppelseiten und Blätteranimation (CBZ/CBR/PDF) | nichts |
| **IServ-Vertretungsplan** | Vertretungen für deine Kurse auf dem Dashboard und im Wecker | IServ-Zugang |
| **Google / iCloud Kalender** | Termine auf dem Dashboard und im Wecker | iCal-Adresse bzw. App-Passwort |
| **ToDos aus Notizen** | Checkliste aus der Notizen-App | iPhone-Kurzbefehl |
| **Fernzugriff** | Fernbedienung von unterwegs mit https | Cloudflare-Konto + Domain |

Apps, die aus sind, verschwinden vom Homescreen der Fernbedienung und vom
Dashboard auf dem Fernseher.

## Anpassen

Das ganze Projekt ist offen: Du darfst es für dich umbauen (Lizenz siehe
unten).

- **Name**: *Einstellungen → Allgemein*. Ersetzt „RPi TV“ überall.
- **Eigene App**: einen Eintrag in `app/apps.py` anlegen (Name, Symbol, Farbe,
  Felder, Anleitung). Die Felder speichert der App Store automatisch, normale
  Werte in `data/settings.json`, Zugangsdaten in `.env`. Hat die App eine
  eigene Ansicht, kommt eine Kachel mit `data-open="<id>"` in
  `app/dashboard/static/remote.html`.
- **Einstellungen als Datei**: Alle Standardwerte stehen in
  `config.example.yaml`. Wer lieber Dateien bearbeitet, kopiert sie nach
  `config.yaml`. Es gilt die Reihenfolge
  `config.example.yaml` → `config.yaml` → `data/settings.json`
  (Fernbedienung), also überschreibt jede Ebene die vorige.
- **Eigener Fork**: Mit dem Installer kannst du auch deinen eigenen Fork
  installieren:
  `curl -fsSL …/install.sh | RPITV_REPO=https://github.com/<du>/tv-jarvis.git bash`

## Aktualisieren

Den Installationsbefehl einfach noch einmal ausführen. Er lädt die neue
Version und behält alle Einstellungen. Hast du selbst Dateien geändert,
überspringt er das Update.

## Fehlersuche

```bash
systemctl status dashboard.service        # läuft der Dienst?
journalctl -u dashboard.service -e        # Log
sudo systemctl restart dashboard.service  # neu starten
./scripts/quick_test.sh 120               # Weckvorgang sofort testen
```

- **Fernseher geht nicht an**: HDMI-CEC am Fernseher prüfen, dann
  *Einstellungen → Fernseher & Ton testen*. Der Pi 4 hat zwei HDMI-Ports mit
  je eigenem CEC-Adapter (`/dev/cec0`, `/dev/cec1`). Der Test erkennt den
  richtigen Port neu.
- **Kein Ton**: ebenfalls *Fernseher & Ton testen*. Es setzt die
  HDMI-Tonausgabe (`plughw:CARD=vc4hdmi0|1,DEV=0`) passend zum Port.
- **Vertretungsplan leer**: Jede Schule baut IServ etwas anders. Die Pfade
  „Vertretung heute/morgen“ im App Store prüfen. Klassischer IServ-Plan statt
  Untis: Selektoren unter `iserv.selectors` in `config.yaml` anpassen.
- **Stimme fehlt**: Den Installer erneut ausführen. Er lädt
  `de_DE-thorsten-medium` von
  [huggingface.co/rhasspy/piper-voices](https://huggingface.co/rhasspy/piper-voices)
  nach `data/piper-voices/`.
- **Songs/Videos laden nicht mehr**: YouTube ändert sich oft. Dann hilft
  `.venv/bin/pip install -U "yt-dlp[default]"`.

## Lizenz

[PolyForm Noncommercial 1.0.0](LICENSE.md). Du darfst den Code frei nutzen,
verändern und weitergeben, aber **nicht kommerziell**: kein Verkauf, kein
Einsatz in einem bezahlten Produkt oder einer bezahlten Dienstleistung. Private
Nutzung, Schulen, Vereine und Forschung sind ausdrücklich erlaubt.

Weil kommerzielle Nutzung ausgeschlossen ist, ist das „source available“ und
keine Open-Source-Lizenz im Sinne der OSI.

## Fernbedienung (iPhone/iPad)

Der Dashboard-Server hostet unter `/remote.html` eine mobile Fernbedienung im
Tablet-Look. Im selben WLAN wie der Pi im Browser öffnen und am besten über
"Teilen → Zum Home-Bildschirm" als App ablegen (eigenes Icon, Vollbild):

```
http://pi.local:8080/remote.html
```

`pi.local` statt einer festen IP-Adresse: die ändert der Router gelegentlich,
der Name bleibt. Dafür muss `dashboard.host: "::"` gesetzt sein (Standard) -
dann lauscht der Server per IPv4 **und** IPv6.

Aufbau wie ein Tablet-Homescreen:

- **Homescreen**: Uhr + Begrüßung, "Jetzt läuft"-Karte (tippen öffnet die
  passende App), Fernseher an/aus, App-Icons für Jellyfin, YouTube, Radio,
  Platten, Licht und Einstellungen.
- **Jellyfin-App**: eigene Bibliothek mit Postern durchsuchen (Filme, Serien -
  Serien/Staffeln lassen sich aufklappen), Suche, "Weiterschauen"-Leiste.
  Antippen öffnet eine Detailansicht mit Beschreibung und "Abspielen" bzw.
  "Fortsetzen ab …"/"Von vorne". Das Video läuft in einem eigenen Player im
  Kiosk; die Position wird alle 15 s und beim Pausieren/Stoppen in Jellyfin
  gespeichert (Weiterschauen funktioniert also auch in den anderen
  Jellyfin-Apps). Ab ~92 % gilt ein Film als gesehen.
  **Hochladen** (Knopf oben rechts in der Jellyfin-App): Filme oder
  Serienfolgen vom Handy/iPad/PC direkt auf die Jellyfin-Platte, ohne sie
  abzuziehen. Titel/Jahr bzw. Serie/Staffel werden aus dem Dateinamen
  vorgeschlagen; abgelegt wird als `Filme/Titel (Jahr).ext` bzw.
  `Serien/Serie/Staffel NN/<Datei>`. Übertragen wird in 8-MB-Stücken –
  bricht es ab, dieselbe Datei erneut wählen, dann geht es an der Stelle
  weiter. Danach liest Jellyfin die Bibliothek neu ein; Formate, die der
  Fernseher nicht direkt kann (z. B. HEVC), werden angemerkt.
- **YouTube-App**: Link einfügen und abspielen (Stopp-Knopf als "×" im
  Eingabefeld), Now-Playing-Karte mit Thumbnail, Titel und scrubbarem
  Fortschrittsbalken, 10s zurück/vor sowie ein Pause/Weiter-Knopf.
- **Radio-App**: zwischen den konfigurierten Sendern wechseln (Standard:
  Sunshine Live, 1LIVE) sowie Stopp.
- **Platten-App (Plattenschrank)**: eigene Retro-Optik (angelehnt an
  wgv-sv.de/platten) mit einem Holzschrank pro Genre. Platte antippen →
  "Platte auflegen", "Mischen" oder einen einzelnen Song; pro Schrank
  abspielen/mischen, oben "Zufallsmix" über alles. Solange etwas läuft,
  zeigt ein Hi-Fi-Deck Titel, Fortschritt und Tasten (zurück, Pause, weiter,
  Stopp). **Neue Musik:** "Platte dazu" → Album oder einzelnen Song suchen
  (Cover + Tracklist über die iTunes-Suche, ohne Account) → Lieblingssongs
  antippen → Schrank wählen. Das passende YouTube-Video je Song sucht der Pi
  selbst ("<Künstler> <Song> topic", yt-dlp als Rückfallebene). Auf dem
  Fernseher läuft ein Plattenspieler-Bildschirm (drehende Platte mit Cover als
  Etikett, Tonarm folgt dem Songfortschritt, Tracklist); der YouTube-Player
  spielt unsichtbar dahinter. Sammlung: `data/vinyl.json` (beim ersten Start
  aus `app/vinyl_seed.json` befüllt).
- **Uhr-App**: Uhr mit Sekunden, auf Wunsch im Vollbild auf dem Fernseher.
  Timer über Vorlagen (1 Min – 1 Std) oder eigene Zeit; er zählt auf dem
  Fernseher im Vollbild mit Fortschrittsring herunter. Läuft gerade
  Plattenspieler, YouTube oder Jellyfin, zeigt eine kleine Notch oben die
  Restzeit. Beim Ablauf wird alles pausiert (Radio gestoppt), der Fernseher
  (falls aus) eingeschaltet und ein Alarmton gespielt, bis die Fernbedienung
  geöffnet wird; dort dann groß „Beenden“ oder „Neu starten“. Der Timer läuft
  im Dashboard-Dienst, also auch bei ausgeschaltetem Fernseher.
- **Licht-App**: DMX-Scheinwerfer über den uDMX-Adapter – Farbe, Helligkeit,
  Effekte (Soft/Hard/Ramp) im BPM-Takt mit Fader und Tap-Sync.
- **Einstellungen-App**: Wecker an/aus + Weck-/Verlasszeiten für Wochentag und
  Wochenende (wirkt sofort, siehe oben), Radiosender hinzufügen/entfernen.
- **Control-Dock**: am unteren Rand fest sichtbar, egal welche App gerade
  offen ist - Home, Lautstärke -/+ (zeigt den neuen Pegel an), Stumm und ein
  Pause/Weiter-Knopf, der automatisch das steuert, was gerade läuft.

Abspielen bei ausgeschaltetem Fernseher schaltet ihn automatisch ein und
startet das Video, sobald der Kiosk bereit ist. Es läuft immer nur eine Quelle
(Jellyfin, YouTube, Plattenspieler oder Radio) - jede neue stoppt die
vorherige. YouTube-Untertitel und YouTubes eigenes Pause-Overlay sind
unterdrückt. Der Kiosk lädt die Seite bewusst über `localhost` (nicht
127.0.0.1): bei einer IP als Herkunft verweigert YouTube eingebettete
Musikvideos mit Fehler 150.

**Jellyfin-App einrichten:** In Jellyfin unter Dashboard → API-Schlüssel einen
Schlüssel anlegen, in `.env` als `JELLYFIN_API_KEY` eintragen und in
`config.yaml` unter `jellyfin.username` den Jellyfin-Benutzer angeben. Der Key
hat Admin-Rechte und bleibt deshalb serverseitig: Streams und Poster laufen
über den Dashboard-Server (der Stream-Proxy antwortet nur dem Kiosk auf dem Pi
selbst). Abgespielt wird per Direct Play ohne Transcoding - Formate, die der
Kiosk-Browser nicht kann (z. B. HEVC/H.265, DTS-Ton), lehnt die App vor dem
Start mit einer klaren Meldung ab.

**Absicherung:** Ohne `REMOTE_CONTROL_SECRET` in `.env` ist die Fernbedienung
ohne Passwort nutzbar (ok fürs eigene, vertrauenswürdige WLAN). Zum Absichern
in `.env` einen Wert eintragen - die Seite fragt dann beim ersten Laden
einmalig danach und merkt sich das Passwort im Browser.

## Architektur (Kurzüberblick)

```
app/
  config.py            Einstellungen laden (Standardwerte -> config.yaml -> data/settings.json)
  settings_store.py     Speichert, was in der Fernbedienung eingestellt wird (+ .env)
  apps.py               App Store: Apps, Felder, Anleitungen, Verbindungstests
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
  kiosk_media.py                YouTube-/Jellyfin-Steuerung (WebSocket-Broadcast)
  jellyfin_client.py             Jellyfin-REST-API (Bibliothek, Details, Position)
  vinyl_library.py               Plattenschrank: Sammlung + Suche (iTunes, YouTube)
  lighting/                      uDMX-Treiber + Licht-Engine (BPM-Effekte)
  audio_control.py               Lautstaerke ueber PipeWire/wpctl
  sources/                        Wetter, Google-ICS, iCloud-CalDAV, IServ, ToDos
  tv_control/                      CEC- und Steckdosen-Backend (austauschbar)
  dashboard/                        FastAPI-Server + Frontend (static/:
                                     index.html/app.js fuers Kiosk-Fenster,
                                     remote.html/css/js fuers Handy)
  routines/                          morning_routine.py / leave_routine.py
systemd/                              dashboard.service-Vorlage (von install.sh
                                       gerendert - der einzige systemd-Dienst,
                                       der Zeitplan laeuft in-Prozess mit)
scripts/install.sh                     Installation mit einem Befehl (curl | bash)
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
