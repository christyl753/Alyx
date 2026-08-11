#!/bin/bash
# Script d'arrêt pour Linux (Fedora/Nobara)

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
RUNDIR="$DIR/run"

API_PID_FILE="$RUNDIR/api.pid"
STT_PID_FILE="$RUNDIR/stt.pid"
UI_PID_FILE="$RUNDIR/ui.pid"

echo "=========================================="
echo "    Arret des processus Alyx (Linux)"
echo "=========================================="

# Arret propre par paliers : SIGTERM, attente, puis SIGKILL si necessaire.
arreter_processus() {
    local nom="$1"
    local pid_file="$2"

    if [ ! -f "$pid_file" ]; then
        echo "[Info] Aucun fichier PID trouve pour $nom."
        return
    fi

    local pid
    pid=$(cat "$pid_file")
    echo "[Alyx] Tentative d'arret du $nom (PID: $pid)..."

    if kill -0 "$pid" 2>/dev/null; then
        kill -TERM "$pid" 2>/dev/null
        for _ in $(seq 1 10); do
            kill -0 "$pid" 2>/dev/null || break
            sleep 0.5
        done
        if kill -0 "$pid" 2>/dev/null; then
            echo "[!] $nom ne repond pas au SIGTERM, arret force (SIGKILL)."
            kill -9 "$pid" 2>/dev/null
        fi
        echo "[OK] $nom arrete."
    else
        echo "[!] $nom deja arrete."
    fi

    rm -f "$pid_file"
}

arreter_processus "Backend API" "$API_PID_FILE"
arreter_processus "Micro-service STT" "$STT_PID_FILE"
arreter_processus "Frontend UI" "$UI_PID_FILE"

echo ""
echo "Tous les processus connus d'Alyx ont ete termines."
