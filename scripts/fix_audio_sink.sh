#!/usr/bin/env bash
# Setzt den PipeWire-Standard-Audio-Sink auf den HDMI-Ausgang zum Fernseher
# statt den Kopfhoereranschluss (bcm2835 Headphones), den PipeWire sonst oft
# als Default waehlt. Wird beim Desktop-Login per labwc-Autostart aufgerufen
# (siehe scripts/install.sh) - Sink-IDs koennen sich zwischen Boots aendern,
# deshalb wird jedes Mal per Namen ("HDMI") neu gesucht statt eine feste ID
# zu hinterlegen.
set -euo pipefail
export XDG_RUNTIME_DIR="/run/user/$(id -u)"

# Kurz warten, falls PipeWire/WirePlumber beim Login noch nicht ganz bereit ist.
for _ in $(seq 1 10); do
  if wpctl status >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

SINK_ID=$(wpctl status | sed -n '/Sinks:/,/Sources:/p' | grep "HDMI" | sed -E 's/^[^0-9]*([0-9]+)\..*/\1/' | head -1)

if [ -n "$SINK_ID" ]; then
  wpctl set-default "$SINK_ID"
  echo "Default-Audio-Sink auf HDMI (ID $SINK_ID) gesetzt."
else
  echo "Kein HDMI-Audio-Sink gefunden - nichts geaendert." >&2
fi
