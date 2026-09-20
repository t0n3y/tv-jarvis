#!/usr/bin/env bash
# Loest die komplette Routine sofort aus, unabhaengig vom Zeitplan
# (data/schedule.json, siehe Einstellungen-App) - fuer schnelle Tests ohne den
# Zeitplan anzufassen.
#
# Ablauf: TV an + Briefing + Radio -> N Sekunden warten -> Radio aus + TV aus.
#
# Aufruf:
#   ./scripts/quick_test.sh            # Standard: 120 Sekunden
#   ./scripts/quick_test.sh 60         # eigene Dauer in Sekunden
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DURATION="${1:-120}"

echo "== Morgen-Routine (TV an, Briefing, Radio) =="
"$INSTALL_DIR/.venv/bin/python" -m app.routines.morning_routine

echo "== Warte ${DURATION}s =="
sleep "$DURATION"

echo "== Verlassen-Routine (Radio aus, TV aus) =="
"$INSTALL_DIR/.venv/bin/python" -m app.routines.leave_routine

echo "== Fertig =="
