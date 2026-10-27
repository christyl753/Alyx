#!/bin/bash

echo "=========================================="
echo "   Installation des dependances ALYX"
echo "=========================================="
echo ""

# 1. Verification de Python
echo "[1/6] Verification de Python..."
if ! command -v python3 &> /dev/null; then
    echo "[X] Python3 n'est pas installe."
    echo "Veuillez installer Python 3.10+ via le gestionnaire de paquets de votre distribution."
    exit 1
fi
echo "[OK] Python3 est installe."

# 2. Verification de .NET SDK
echo ""
echo "[2/6] Verification de .NET 8.0 SDK..."
if ! dotnet --list-sdks | grep "8.0" &> /dev/null; then
    echo "[X] .NET 8.0 SDK n'est pas installe."
    echo "Veuillez installer le SDK .NET 8.0 (ex: sudo dnf install dotnet-sdk-8.0 ou sudo apt install dotnet-sdk-8.0)"
    exit 1
fi
echo "[OK] .NET 8.0 SDK est installe."

# 3. Verification des fournisseurs IA (Ollama / LM Studio)
echo ""
echo "[3/6] Verification des moteurs d'IA (Ollama ou LM Studio)..."
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
echo "[4/6] Verification des dependances audio Linux..."
echo "Note: Vous pourriez avoir besoin d'installer manuellement : portaudio19-dev, alsa-utils, espeak"
echo "Ex (Fedora/Nobara) : sudo dnf install portaudio-devel alsa-utils espeak"
echo "Ex (Ubuntu/Debian) : sudo apt install portaudio19-dev alsa-utils espeak"

# 5. Installation des dependances Python
echo ""
echo "[5/6] Configuration de l'environnement virtuel et des dependances..."
if [ ! -d ".venv" ]; then
    echo "Creation de l'environnement virtuel .venv..."
    python3 -m venv .venv
fi

echo "Installation des librairies Python requises..."
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

# 6. Compilation de l'interface (evite un "dotnet run" lent a chaque lancement)
echo ""
echo "[6/6] Compilation de l'interface Alyx (Release)..."
dotnet build AlyxDesktop/AlyxDesktop.csproj -c Release --nologo -v q

chmod +x alyx.sh stop.sh

# Entrée dans le menu des applications (lance le widget en arrière-plan)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/alyx.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Alyx
Comment=Assistant local Alyx (widget de bureau)
Exec="$DIR/alyx.sh"
Icon=$DIR/AlyxDesktop/Assets/logo.png
Terminal=false
Categories=Utility;
DESKTOP
echo "[OK] Alyx ajouté au menu des applications."

echo ""
echo "=========================================="
echo "   Installation terminee avec succes !"
echo "=========================================="
echo "Pour lancer Alyx : ./alyx.sh"
echo "Pour l'arreter   : ./stop.sh"
echo "(Apres une modification du code C#, relancez ./install.sh ou 'dotnet build AlyxDesktop -c Release')"
echo ""
