# Alyx

Alyx est un assistant virtuel local. L'interface est codée en C# (Avalonia) et le moteur tourne en Python (Flask). Il se connecte à vos modèles d'IA hébergés localement via Ollama ou LM Studio.

## Fonctionnalités
- Chat textuel et vocal (Whisper + pyttsx3).
- Supporte Ollama et LM Studio.
- Actions système : ouvrir/fermer des applications, gérer des fichiers (créer, lire, déplacer, supprimer), générer des PDF, redémarrer le PC.

## Prérequis
- **Python 3.10+**
- **.NET 8.0 SDK** (pour compiler le frontend)
- **Ollama** ou **LM Studio** pour faire tourner les modèles.

## Démarrage rapide (Windows)

À la racine du projet :

```bat
# 1. Installation des dépendances (à faire une seule fois)
.\install.bat

# 2. Lancement
.\alyx.bat
```

*Note: Quand vous fermez la fenêtre d'Alyx, le processus Python en arrière-plan se coupe tout seul.*

## Installation manuelle (Linux / Mac)

Si vous êtes sur un autre OS, lancez les deux parties séparément :

1. **Backend Python**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python api.py
```
*(Sur Linux, assurez-vous d'avoir installé `portaudio19-dev` et `alsa-utils` pour la gestion du son).*

2. **Frontend C#** (dans un autre terminal)
```bash
cd AlyxDesktop
dotnet run
```
