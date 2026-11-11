#!/bin/bash
# Script d'arrêt pour Linux (Fedora/Nobara)

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
RUNDIR="$DIR/run"

echo "=========================================="
echo "    Arret des processus Alyx (Linux)"
echo "=========================================="

# $1 = fichier PID, $2 = motif attendu dans la ligne de commande, $3 = libelle
arreter() {
    local pid_file="$1" motif="$2" libelle="$3"
    if [ ! -f "$pid_file" ]; then
        echo "[Info] Aucun fichier PID trouve pour : $libelle."
        return
    fi
    local pid
    pid=$(tr -dc '0-9' < "$pid_file")
    rm -f "$pid_file"

    # Verification d'identite : un PID perime peut avoir ete reattribue a un autre programme
    if [ -z "$pid" ] || ! tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -qE "$motif"; then
        echo "[Info] $libelle n'est plus actif, rien a arreter."
        return
    fi

    echo "[Alyx] Arret : $libelle (PID: $pid)..."
    # Palier 1 : Arret gracieux SIGTERM sur le processus et ses enfants (B.7.3)
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true

    # Attente de 2 secondes (4 iterations de 0.5s - B.7.3)
    for _ in 1 2 3 4; do
        kill -0 "$pid" 2>/dev/null || { echo "[OK] $libelle arrete proprement."; return; }
        sleep 0.5
    done

    # Palier 2 : SIGKILL si le processus persiste
    echo "[Alyx] $libelle (PID: $pid) persiste apres 2s, arret force (SIGKILL)..."
    pkill -KILL -P "$pid" 2>/dev/null || true
    kill -KILL "$pid" 2>/dev/null && echo "[OK] $libelle arrete (force)."
}

# L'API est arretee en dernier
arreter "$RUNDIR/ui.pid" "AlyxDesktop\|dotnet" "UI"
arreter "$RUNDIR/stt.pid" "stt_server.py" "STT"
arreter "$RUNDIR/api.pid" "api.py" "Backend API"

echo ""
echo "Tous les processus connus d'Alyx ont ete termines."
