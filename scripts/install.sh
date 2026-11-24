#!/usr/bin/env bash
# RPi TV - Installation mit einem Befehl (Raspberry Pi OS mit Desktop, 64 Bit):
#
#   curl -fsSL https://raw.githubusercontent.com/t0n3y/tv-jarvis/main/scripts/install.sh | bash
#
# Als normaler Benutzer ausfuehren (nicht als root) - fuer die Systempakete
# fragt das Skript einmal nach dem sudo-Passwort. Erneut ausfuehren
# aktualisiert eine bestehende Installation; Einstellungen bleiben erhalten.
#
# Anpassen per Umgebungsvariablen, z.B. fuer einen eigenen Fork:
#   RPITV_REPO=https://github.com/<du>/tv-jarvis.git RPITV_DIR=~/mein-tv bash install.sh
#
# Alles in main(), damit bei abgebrochenem Download nichts halb ausgefuehrt wird.

set -euo pipefail

main() {
  local repo="${RPITV_REPO:-https://github.com/t0n3y/tv-jarvis.git}"
  local branch="${RPITV_BRANCH:-main}"
  local run_user install_dir script_dir

  if [[ $EUID -eq 0 ]]; then
    if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
      echo "Bitte ohne sudo starten - das Skript fragt selbst, wenn es Rechte braucht." >&2
    else
      echo "Bitte als normaler Benutzer (nicht root) ausführen." >&2
    fi
    exit 1
  fi
  run_user="$(id -un)"

  # Aus einem vorhandenen Checkout gestartet (./scripts/install.sh)?
  script_dir=""
  if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  fi
  if [[ -n "${RPITV_DIR:-}" ]]; then
    install_dir="${RPITV_DIR/#\~/$HOME}"
  elif [[ -n "$script_dir" && -d "$script_dir/app" ]]; then
    install_dir="$script_dir"
  elif [[ -d "$HOME/tv-jarvis/app" ]]; then
    install_dir="$HOME/tv-jarvis"   # aeltere Installationen
  else
    install_dir="$HOME/rpi-tv"
  fi

  step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

  step "RPi TV wird installiert"
  echo "Ordner:   $install_dir"
  echo "Benutzer: $run_user"
  sudo -v

  step "Systempakete"
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    git curl python3-venv python3-pip \
    chromium mpv ffmpeg alsa-utils cec-utils \
    poppler-utils 7zip qrencode >/dev/null
  # RAR-Comics (CBR): je nach Distribution ein eigenes Paket, optional
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq 7zip-rar >/dev/null 2>&1 || true

  step "Programm laden"
  if [[ -d "$install_dir/.git" ]]; then
    if [[ -n "$(git -C "$install_dir" status --porcelain --untracked-files=no)" ]]; then
      echo "Eigene Änderungen im Ordner gefunden - überspringe das Update (git pull)."
    else
      git -C "$install_dir" pull --ff-only --quiet || echo "Update fehlgeschlagen - mache mit der vorhandenen Version weiter."
    fi
  elif [[ -e "$install_dir" && -n "$(ls -A "$install_dir" 2>/dev/null)" ]]; then
    echo "$install_dir existiert schon und ist kein Git-Ordner - bitte RPITV_DIR setzen." >&2
    exit 1
  else
    git clone --quiet --branch "$branch" "$repo" "$install_dir"
  fi
  cd "$install_dir"

  step "Python-Umgebung"
  [[ -x .venv/bin/python ]] || python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements.txt
  # Apps mit eigenen Python-Paketen (apps/<id>/requirements.txt)
  for req in apps/*/requirements.txt; do
    [[ -f "$req" ]] && .venv/bin/pip install --quiet -r "$req" || true
  done

  step "Einstellungen"
  mkdir -p data
  if [[ ! -f .env ]]; then
    cp .env.example .env
    echo "Zugangsdaten-Datei .env angelegt (wird über die Fernbedienung gefüllt)."
  fi
  chmod 600 .env

  step "Stimme (Piper, Deutsch)"
  local voice="de_DE-thorsten-medium"
  local voice_dir="data/piper-voices"
  local voice_url="https://huggingface.co/rhasspy/piper-voices/resolve/main/de/de_DE/thorsten/medium"
  mkdir -p "$voice_dir"
  for file in "$voice.onnx" "$voice.onnx.json"; do
    if [[ ! -s "$voice_dir/$file" ]]; then
      curl -fsSL -o "$voice_dir/$file.part" "$voice_url/$file" && mv "$voice_dir/$file.part" "$voice_dir/$file" \
        || echo "Download von $file fehlgeschlagen - später erneut ausführen."
    fi
  done

  step "Geräte-Rechte (HDMI-CEC, Ton, DMX-Licht)"
  sudo usermod -aG video,audio,plugdev,dialout "$run_user"
  echo 'SUBSYSTEM=="usb", ATTRS{idVendor}=="16c0", ATTRS{idProduct}=="05dc", MODE="0660", GROUP="plugdev"' \
    | sudo tee /etc/udev/rules.d/50-udmx.rules >/dev/null
  sudo udevadm control --reload-rules || true

  step "Desktop: automatisch anmelden + Ton über HDMI"
  if command -v raspi-config >/dev/null; then
    # B4 = Desktop mit automatischer Anmeldung - der Kiosk braucht die Sitzung
    sudo raspi-config nonint do_boot_behaviour B4 || true
  fi
  local autostart_dir="$HOME/.config/labwc"
  local autostart_line="$install_dir/scripts/fix_audio_sink.sh >> $install_dir/data/autostart.log 2>&1 &"
  mkdir -p "$autostart_dir"
  if ! grep -qF "fix_audio_sink.sh" "$autostart_dir/autostart" 2>/dev/null; then
    echo "$autostart_line" >> "$autostart_dir/autostart"
  fi

  step "Dienst einrichten"
  sed -e "s#__INSTALL_DIR__#$install_dir#g" -e "s#__RUN_USER__#$run_user#g" \
    systemd/dashboard.service.template | sudo tee /etc/systemd/system/dashboard.service >/dev/null
  sudo systemctl daemon-reload
  sudo systemctl enable --quiet dashboard.service
  sudo systemctl restart dashboard.service

  local port url ip
  port="$(.venv/bin/python -c 'from app.config import load_config; print(load_config().dashboard.port)' 2>/dev/null || echo 8080)"
  ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
  url="http://${ip:-$(hostname).local}:$port/remote.html"

  step "Fertig"
  echo "Öffne die Fernbedienung auf deinem Handy (gleiches WLAN) und folge der Einrichtung:"
  echo
  echo "    $url"
  echo "    (oder http://$(hostname).local:$port/remote.html)"
  echo
  if command -v qrencode >/dev/null; then
    qrencode -t ANSIUTF8 -m 2 "$url" || true
  fi
  echo "Tipp: In Safari „Teilen → Zum Home-Bildschirm“ - dann ist es eine App."
  # id -nG ohne Namen = Gruppen dieser Sitzung (neue gelten erst nach Neuanmeldung)
  if ! id -nG | grep -qw plugdev || ! id -nG | grep -qw video; then
    echo "Neue Geräte-Rechte gelten nach einem Neustart: sudo reboot"
  fi
}

main "$@"
