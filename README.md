# Alyx

Alyx est un assistant virtuel doté d'une interface graphique moderne en Avalonia (C#) et d'un backend puissant propulsé par Python (Flask) et Ollama. Alyx est conçu pour être cross-platform (Linux, Windows, macOS).

## Fonctionnalités Principales

- **Chat interactif** avec interface fluide et animée (Avalonia).
- **Intégration d'Ollama** (Modèles locaux comme Gemma, Llama).
- **Reconnaissance vocale** (Speech-to-Text via Whisper).
- **Synthèse vocale** (Text-to-Speech via pyttsx3).
- **Outils Autonomes** (System Control) :
  - Lancement et fermeture d'applications (Windows & Linux).
  - Contrôle du système (Redémarrage).
  - Gestion sécurisée des fichiers (Création, lecture, écriture, corbeille).
  - Génération de documents PDF.

## Prérequis

### 1. Backend (Python)
- **Python 3.10+**
- **Ollama** installé sur votre machine et en cours d'exécution (port par défaut 11434).

Installation des dépendances Python :
```bash
python -m venv .venv
source .venv/bin/activate  # Sur Linux/Mac
.venv\Scripts\activate     # Sur Windows
pip install -r requirements.txt
```

*(Note pour Linux : vous aurez besoin de paquets systèmes comme `portaudio19-dev`, `alsa-utils`, et `espeak` pour l'audio).*

### 2. Frontend (C# / Avalonia)
- **.NET 8.0 SDK**

## Démarrage Rapide

1. **Lancer le serveur Python (API)**
Dans le dossier racine :
```bash
./.venv/bin/python api.py
```
Le serveur démarrera sur le port 5000.

2. **Lancer l'interface graphique (AlyxDesktop)**
Dans un nouveau terminal :
```bash
cd AlyxDesktop
dotnet run
```

L'interface se lancera et se connectera automatiquement à votre API locale !
