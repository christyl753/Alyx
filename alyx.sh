#!/bin/bash
# Script de lancement pour Linux (Fedora/Nobara)
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
RUNDIR="$DIR/run"
LOGDIR="$DIR/logs"

mkdir -p "$RUNDIR"
mkdir -p "$LOGDIR"

echo "=========================================="
echo "    Demarrage d'Alyx (Linux)"
echo "=========================================="

echo "[Alyx] Demarrage du Backend API..."
nohup "$DIR/.venv/bin/python" "$DIR/api.py" > "$LOGDIR/api.log" 2>&1 &
API_PID=$!
echo $API_PID > "$RUNDIR/api.pid"
echo "Backend API demarre (PID: $API_PID)"

echo "[Alyx] Demarrage du Frontend UI (C#)..."
cd "$DIR/AlyxDesktop"
nohup dotnet run > "$LOGDIR/ui.log" 2>&1 &
UI_PID=$!
echo $UI_PID > "$RUNDIR/ui.pid"
echo "Frontend UI demarre (PID: $UI_PID)"

echo "Tous les processus sont lances en arriere-plan."
echo "Pour les arreter, executez ./stop.sh"
