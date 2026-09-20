#!/usr/bin/env bash
# Installiert TV-Jarvis auf einem Raspberry Pi (Raspberry Pi OS, Bookworm oder neuer).
# Ausführen mit: sudo ./scripts/install.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Bitte mit sudo ausführen: sudo ./scripts/install.sh" >&2
  exit 1
fi

RUN_USER="${SUDO_USER:-$(whoami)}"
INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "== TV-Jarvis Installation =="
echo "Installationsverzeichnis: $INSTALL_DIR"
echo "Systembenutzer für die Dienste: $RUN_USER"

echo "\n-- Systempakete installieren --"
apt-get update
apt-get install -y \
  python3-venv python3-pip \
  cec-utils \
  mpv \
  alsa-utils \
  chromium-browser \
  curl

echo "\n-- Python-Virtualenv einrichten --"
sudo -u "$RUN_USER" python3 -m venv "$INSTALL_DIR/.venv"
sudo -u "$RUN_USER" "$INSTALL_DIR/.venv/bin/pip" install --upgrade pip
sudo -u "$RUN_USER" "$INSTALL_DIR/.venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"

echo "\n-- Konfigurationsdateien --"
if [[ ! -f "$INSTALL_DIR/config.yaml" ]]; then
  sudo -u "$RUN_USER" cp "$INSTALL_DIR/config.example.yaml" "$INSTALL_DIR/config.yaml"
  echo "config.yaml angelegt - bitte anpassen (Ort, Zeiten, Kalender-URLs, ...)!"
fi
if [[ ! -f "$INSTALL_DIR/.env" ]]; then
  sudo -u "$RUN_USER" cp "$INSTALL_DIR/.env.example" "$INSTALL_DIR/.env"
  chmod 600 "$INSTALL_DIR/.env"
  echo ".env angelegt - bitte Zugangsdaten eintragen!"
fi

echo "\n-- Piper TTS (deutsche Stimme) --"
VOICE_DIR="$INSTALL_DIR/data/piper-voices"
mkdir -p "$VOICE_DIR"
chown -R "$RUN_USER" "$INSTALL_DIR/data"

# Das piper-Binary kommt ueber requirements.txt (Paket "piper-tts") mit ins
# venv (.venv/bin/piper) - app/tts.py findet es relativ zum venv-Python,
# unabhaengig vom PATH des systemd-Diensts.
if [[ -x "$INSTALL_DIR/.venv/bin/piper" ]]; then
  echo "piper-Binary im venv gefunden: $INSTALL_DIR/.venv/bin/piper"
else
  echo "WARNUNG: piper-Binary fehlt im venv - 'pip install -r requirements.txt' pruefen."
fi

VOICE_BASENAME="de_DE-thorsten-medium"
if [[ ! -f "$VOICE_DIR/$VOICE_BASENAME.onnx" ]]; then
  echo "Lade Stimme $VOICE_BASENAME von Hugging Face ..."
  BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium"
  curl -L -o "$VOICE_DIR/$VOICE_BASENAME.onnx" "$BASE_URL/$VOICE_BASENAME.onnx" || \
    echo "Download fehlgeschlagen - Stimme manuell von $BASE_URL herunterladen."
  curl -L -o "$VOICE_DIR/$VOICE_BASENAME.onnx.json" "$BASE_URL/$VOICE_BASENAME.onnx.json" || \
    echo "Download der Modell-Config fehlgeschlagen."
  chown -R "$RUN_USER" "$VOICE_DIR"
fi

echo "\n-- Audio-Sink-Fix im Desktop-Autostart --"
# PipeWire waehlt sonst oft den Kopfhoereranschluss statt HDMI als Standard.
AUTOSTART_DIR="/home/$RUN_USER/.config/labwc"
AUTOSTART_FILE="$AUTOSTART_DIR/autostart"
AUTOSTART_LINE="$INSTALL_DIR/scripts/fix_audio_sink.sh >> $INSTALL_DIR/data/autostart.log 2>&1 &"
sudo -u "$RUN_USER" mkdir -p "$AUTOSTART_DIR"
if ! grep -qF "fix_audio_sink.sh" "$AUTOSTART_FILE" 2>/dev/null; then
  sudo -u "$RUN_USER" bash -c "echo '$AUTOSTART_LINE' >> '$AUTOSTART_FILE'"
  echo "Autostart-Eintrag hinzugefuegt: $AUTOSTART_FILE"
else
  echo "Autostart-Eintrag bereits vorhanden."
fi

echo "\n-- Alte Zeitplan-Timer entfernen (fruehere Version, jetzt durch den --"
echo "-- in-Prozess-Scheduler in dashboard.service ersetzt) --"
systemctl disable --now morning-routine.timer leave-routine.timer >/dev/null 2>&1 || true
rm -f /etc/systemd/system/morning-routine.timer /etc/systemd/system/morning-routine.service
rm -f /etc/systemd/system/leave-routine.timer /etc/systemd/system/leave-routine.service

echo "\n-- systemd-Unit generieren --"
TMP_DIR="$(mktemp -d)"
sed \
  -e "s#__INSTALL_DIR__#$INSTALL_DIR#g" \
  -e "s#__RUN_USER__#$RUN_USER#g" \
  "$INSTALL_DIR/systemd/dashboard.service.template" > "$TMP_DIR/dashboard.service"
cp "$TMP_DIR/dashboard.service" "/etc/systemd/system/dashboard.service"
rm -rf "$TMP_DIR"

systemctl daemon-reload
systemctl enable --now dashboard.service
systemctl restart dashboard.service

echo "\n== Fertig =="
echo "Dashboard laeuft unter http://localhost:$("$INSTALL_DIR/.venv/bin/python" -c "from app.config import load_config; print(load_config().dashboard.port)" 2>/dev/null || echo 8080)/"
echo "Weckzeiten werden jetzt von dashboard.service selbst ueberwacht (kein"
echo "separater Timer mehr) und lassen sich in der Einstellungen-App unter"
echo "/remote.html live aendern - config.yaml liefert nur den Startwert."
echo "Naechste Schritte: config.yaml und .env pruefen/anpassen, dann testen mit:"
echo "  sudo systemctl status dashboard.service"
echo "  sudo -u $RUN_USER $INSTALL_DIR/.venv/bin/python -m app.routines.morning_routine"
echo "Siehe README.md fuer CEC-Einrichtung, IServ-Feinschliff und die Shortcuts-Automation."
