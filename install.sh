#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

echo "=========================================="
echo "   Installation des dependances ALYX"
echo "=========================================="
echo ""

# 1. Verification de Python
echo "[1/4] Verification de Python..."
if ! command -v python3 &> /dev/null; then
    echo "[X] Python3 n'est pas installe."
    echo "Veuillez installer Python 3.10+ via le gestionnaire de paquets de votre distribution."
    exit 1
fi
echo "[OK] Python3 est installe."

# 2. Verification de .NET SDK
echo ""
echo "[2/4] Verification de .NET 8.0 SDK..."
if ! dotnet --list-sdks | grep "8.0" &> /dev/null; then
    echo "[X] .NET 8.0 SDK n'est pas installe."
    echo "Veuillez installer le SDK .NET 8.0 (ex: sudo dnf install dotnet-sdk-8.0 ou sudo apt install dotnet-sdk-8.0)"
    exit 1
fi
echo "[OK] .NET 8.0 SDK est installe."

# 3. Verification des fournisseurs IA (Ollama / LM Studio)
echo ""
echo "[3/4] Verification des moteurs d'IA (Ollama ou LM Studio)..."
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
echo "[4/5] Verification des dependances audio Linux..."
echo "Note: Vous pourriez avoir besoin d'installer manuellement : portaudio19-dev, alsa-utils, espeak"
echo "Ex (Fedora/Nobara) : sudo dnf install portaudio-devel alsa-utils espeak"
echo "Ex (Ubuntu/Debian) : sudo apt install portaudio19-dev alsa-utils espeak"

# 5. Installation des dependances Python
echo ""
echo "[5/6] Configuration de l'environnement virtuel et des dependances..."
if [ ! -d "$DIR/.venv" ]; then
    echo "Creation de l'environnement virtuel .venv..."
    python3 -m venv "$DIR/.venv"
fi

echo "Installation des librairies Python requises..."
"$DIR/.venv/bin/python" -m pip install --upgrade pip
"$DIR/.venv/bin/python" -m pip install -r "$DIR/requirements.txt"

# 6. Creation de la commande globale 'alyx'
echo ""
echo "[6/6] Creation de la commande globale 'alyx'..."
chmod +x "$DIR/alyx.sh" "$DIR/stop.sh"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$BIN_DIR"
ln -sf "$DIR/alyx.sh" "$BIN_DIR/alyx"
echo "[OK] Lien cree : $BIN_DIR/alyx -> $DIR/alyx.sh"

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
