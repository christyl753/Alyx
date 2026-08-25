#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo "=========================================="
echo "   Installation des dependances ALYX"
echo "=========================================="
echo ""

# 1. Verification de Python
echo "[1/7] Verification de Python..."
if ! command -v python3 &> /dev/null; then
    echo "[X] Python3 n'est pas installe."
    echo "Veuillez installer Python 3.10+ via le gestionnaire de paquets de votre distribution."
    exit 1
fi
echo "[OK] Python3 est installe."
PYTHON_MINOR=$(python3 -c 'import sys; print(sys.version_info[1])')
if [ "$PYTHON_MINOR" -lt 11 ] || [ "$PYTHON_MINOR" -ge 14 ]; then
    echo "[!] Python 3.$PYTHON_MINOR detecte : seules les versions 3.11 et 3.12 sont supportees."
    echo "    Au-dela (3.14+), le module STT (faster-whisper) est indisponible (dependances C absentes/incompatibles)."
    echo "    et sera silencieusement desactive. Installez Python 3.11 ou 3.12 pour beneficier de la reconnaissance vocale."
fi

# 2. Verification de .NET SDK
echo ""
echo "[2/7] Verification de .NET 8.0 SDK..."
if ! dotnet --list-sdks | grep "8.0" &> /dev/null; then
    echo "[X] .NET 8.0 SDK n'est pas installe."
    echo "Veuillez installer le SDK .NET 8.0 (ex: sudo dnf install dotnet-sdk-8.0 ou sudo apt install dotnet-sdk-8.0)"
    exit 1
fi
echo "[OK] .NET 8.0 SDK est installe."

# 3. Verification des fournisseurs IA (Ollama / LM Studio)
echo ""
echo "[3/7] Verification des moteurs d'IA (Ollama ou LM Studio)..."
IA_DETECTED=0

if command -v ollama &> /dev/null; then
    echo "[OK] Ollama est installe."
    IA_DETECTED=1
fi

if command -v lms &> /dev/null; then
    echo "[OK] LM Studio est installe."
    IA_DETECTED=1
fi

if [ "$IA_DETECTED" -eq 0 ]; then
    echo "[!] Ni Ollama ni LM Studio n'ont ete detectes dans le PATH."
    echo "L'assistant necessite un moteur d'IA local."
    echo "Veuillez installer Ollama (https://ollama.com/) ou LM Studio (https://lmstudio.ai/)."
fi

# 4. Dependances systeme audio (Linux)
echo ""
echo "[4/7] Verification des dependances audio Linux..."
echo "Note: Vous pourriez avoir besoin d'installer manuellement : portaudio19-dev, alsa-utils"
echo "Ex (Fedora/Nobara) : sudo dnf install portaudio-devel alsa-utils"
echo "Ex (Ubuntu/Debian) : sudo apt install portaudio19-dev alsa-utils"

# 5. Installation des dependances Python
echo ""
echo "[5/7] Configuration de l'environnement virtuel et des dependances..."
if [ ! -d "$DIR/.venv" ]; then
    echo "Creation de l'environnement virtuel .venv..."
    python3 -m venv "$DIR/.venv"
fi

echo "Installation des librairies Python requises..."
"$DIR/.venv/bin/python" -m pip install --upgrade pip
"$DIR/.venv/bin/python" -m pip install -r "$DIR/requirements.txt"

# 6. Telechargement du modele de voix Piper (une seule fois, ensuite 100% local)
echo ""
echo "[6/7] Telechargement de la voix francaise Piper (TTS)..."
PIPER_DIR="$DIR/models/piper"
PIPER_MODEL="$PIPER_DIR/fr_FR-siwis-medium.onnx"
PIPER_CONFIG="$PIPER_DIR/fr_FR-siwis-medium.onnx.json"
PIPER_BASE_URL="https://huggingface.co/rhasspy/piper-voices/resolve/main/fr/fr_FR/siwis/medium"

mkdir -p "$PIPER_DIR"
if [ -f "$PIPER_MODEL" ] && [ -f "$PIPER_CONFIG" ]; then
    echo "[OK] Voix Piper deja presente ($PIPER_MODEL)."
else
    if command -v curl &> /dev/null; then
        curl -fL -o "$PIPER_MODEL" "$PIPER_BASE_URL/fr_FR-siwis-medium.onnx" \
            && curl -fL -o "$PIPER_CONFIG" "$PIPER_BASE_URL/fr_FR-siwis-medium.onnx.json"
    elif command -v wget &> /dev/null; then
        wget -O "$PIPER_MODEL" "$PIPER_BASE_URL/fr_FR-siwis-medium.onnx" \
            && wget -O "$PIPER_CONFIG" "$PIPER_BASE_URL/fr_FR-siwis-medium.onnx.json"
    else
        echo "[!] Ni curl ni wget disponibles : impossible de telecharger la voix Piper."
    fi

    if [ -f "$PIPER_MODEL" ] && [ -f "$PIPER_CONFIG" ]; then
        echo "[OK] Voix Piper telechargee dans $PIPER_DIR."
    else
        echo "[!] Echec du telechargement de la voix Piper. Le mode vocal (parole) sera indisponible."
        echo "    Vous pourrez reessayer plus tard en relancant ce script."
        rm -f "$PIPER_MODEL" "$PIPER_CONFIG"
    fi
fi

# 7. Creation de la commande globale 'alyx'
echo ""
echo "[7/7] Creation de la commande globale 'alyx'..."
chmod +x "$DIR/alyx.sh" "$DIR/stop.sh"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"

# Nettoyage des anciens liens ou dossiers de test (alyz, ancien alyx)
rm -rf "$BIN_DIR/alyx" "$BIN_DIR/alyz"

ln -sf "$DIR/alyx.sh" "$BIN_DIR/alyx"
ln -sf "$DIR/stop.sh" "$BIN_DIR/alyx-stop"
echo "[OK] Liens crees :"
echo "     - $BIN_DIR/alyx -> $DIR/alyx.sh"
echo "     - $BIN_DIR/alyx-stop -> $DIR/stop.sh"

case ":$PATH:" in
    *":$BIN_DIR:"*)
        echo "[OK] $BIN_DIR est deja dans votre PATH."
        ;;
    *)
        echo "[!] $BIN_DIR n'est pas dans votre PATH."
        echo "    Ajoutez cette ligne a votre ~/.bashrc (ou ~/.zshrc), puis rouvrez votre terminal :"
        echo "    export PATH=\"\$HOME/.local/bin:\$PATH\""
        ;;
esac

echo ""
echo "=========================================="
echo "   Installation terminee avec succes !"
echo "=========================================="
echo "Lancez Alyx depuis n'importe quel dossier avec la commande :"
echo "    alyx"
echo ""
