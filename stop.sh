#!/bin/bash
# Script d'arrêt pour Linux (Fedora/Nobara)

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
RUNDIR="$DIR/run"

API_PID_FILE="$RUNDIR/api.pid"
UI_PID_FILE="$RUNDIR/ui.pid"

echo "=========================================="
echo "    Arret des processus Alyx (Linux)"
echo "=========================================="

if [ -f "$API_PID_FILE" ]; then
    API_PID=$(cat "$API_PID_FILE")
    echo "[Alyx] Tentative d'arret du Backend API (PID: $API_PID)..."
    if kill -9 $API_PID 2>/dev/null; then
        echo "[OK] Backend API arrete."
    else
        echo "[!] Impossible d'arreter le Backend (peut-etre deja arrete)."
    fi
    rm -f "$API_PID_FILE"
else
    echo "[Info] Aucun fichier PID trouve pour l'API."
fi

if [ -f "$UI_PID_FILE" ]; then
    UI_PID=$(cat "$UI_PID_FILE")
    echo "[Alyx] Tentative d'arret du Frontend UI (PID: $UI_PID)..."
    if kill -9 $UI_PID 2>/dev/null; then
        echo "[OK] Frontend UI arrete."
    else
        echo "[!] Impossible d'arreter l'UI (peut-etre deja arrete)."
    fi
    rm -f "$UI_PID_FILE"
else
    echo "[Info] Aucun fichier PID trouve pour l'UI."
fi

echo ""
echo "Tous les processus connus d'Alyx ont ete termines."
