# Alyx (V2)

Alyx est un assistant virtuel local multi-plateforme (Windows et Linux Fedora/Nobara) fonctionnant entièrement hors ligne (Air-Gapped). L'interface utilisateur est développée en C# (.NET 8 Avalonia) et communique en temps réel via WebSockets bidirectionnels avec un backend Python 3.11+.

## 📥 Téléchargement (Releases)

- [🐧 Télécharger pour Linux (zip)](https://github.com/christyl753/Alyx/releases/latest/download/Alyx-Linux.zip)
- [🪟 Télécharger pour Windows (zip)](https://github.com/christyl753/Alyx/releases/latest/download/Alyx-Windows.zip)

---

## 🛠️ Spécifications & Fonctionnalités

- **Exécution 100% Locale (Air-Gapped)** : Aucune télémétrie, aucun appel d'API cloud externe.
- **Command Palette & Conscience Contextuelle** : Raccourci d'invocation (`Alt+Espace`), capture du presse-papiers et de la fenêtre active au déclenchement.
- **Agentivité & Contrôle Système** : Gestion des fichiers, exécution d'applications, rappels/notes locaux, suivi matériel (batterie, réseau).
- **Human-in-the-Loop (Validation de sécurité)** : Interception et suspension backend pour toute action système destructrice (`supprimer_fichier`, etc.), avec reprise explicite par jeton de contexte après validation UI.
- **Compagnon Mobile PWA (Wi-Fi Local)** : Interface PWA installable sur smartphone pour contrôler l'agent depuis le réseau local. Authentification obligatoire par jeton d'appairage HMAC/128-bit.
- **Mode Focus / Gaming (Nobara/Linux)** : Détection d'applications plein écran gourmandes et suspension des routines/déchargement de VRAM.
- **Routage Multi-Fournisseurs IA** : Support asynchrone d'Ollama, LM Studio et NVIDIA NIM avec mécanisme de Circuit Breaker.
- **Protocole WebSocket Basse Latence** : Communication binaire/JSON `TCP_NODELAY` activée sur client et serveur, éliminant les délais d'agglomération de Nagle.

---

## 💻 Prérequis Système

- **Système d'exploitation** : Windows 10/11 ou Linux (Fedora 38+, Nobara 38+, Ubuntu 22.04+).
- **Python** : Version 3.11 ou 3.12 recommandée. *(Note : Python 3.14+ n'est pas supporté pour le STT en raison d'incompatibilités des extensions C de PyAV / faster-whisper)*.
- **SDK .NET** : .NET 8.0 SDK (requis pour l'exécution et la compilation du client C# Avalonia).
- **Moteur d'inférence LLM** : Ollama (>= 0.3.0) ou LM Studio (>= 0.2.20).

---

## 📊 Dimensionnement Matériel et Choix des Modèles

Le choix du modèle LLM doit être adapté aux capacités mémoire (VRAM GPU et RAM système) de la machine d'exécution :

| Configuration Matérielle | VRAM / RAM requise | Taille Modèle | Quantification | Moteur recommandé | Exemples de modèles |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CPU uniquement (Sans GPU)** | VRAM N/A, RAM >= 16 Go | 7B à 8B | Q4_K_M | Ollama / LM Studio | `qwen2.5:7b`, `llama3.1:8b` |
| **GPU Accéléré (6 Go - 8 Go VRAM)** | VRAM 6-8 Go, RAM >= 16 Go | 7B à 9B | Q4_K_M / Q5_K_M / Q6_K | Ollama / LM Studio | `qwen2.5:7b`, `gemma2:9b`, `llama3.1:8b` |
| **GPU Haut de Gamme (12 Go - 24 Go VRAM)** | VRAM >= 12 Go, RAM >= 32 Go | 14B à 32B | Q6_K / Q8_0 / FP16 | Ollama / LM Studio / NIM | `qwen2.5:14b`, `qwen2.5:32b` |

*Performances constatées :*
- Inférence CPU (AVX2/AVX-512) : 5 à 15 tokens/seconde.
- Accélération GPU (CUDA/ROCm) : 40 à 120+ tokens/seconde.

### Configuration des Moteurs IA

#### Configuration Ollama
1. Installer [Ollama](https://ollama.com/).
2. Télécharger un modèle recommandé via le terminal :
   ```bash
   ollama pull qwen2.5:7b
   ```
3. L'API Alyx scannera et détectera automatiquement le modèle au démarrage.

#### Configuration LM Studio
1. Installer [LM Studio](https://lmstudio.ai/).
2. Télécharger le fichier GGUF correspondant (ex: `Qwen2.5-7B-Instruct-GGUF` en `Q4_K_M`).
3. Démarrer le serveur HTTP local (**Local Server**, port `1234`).

---

## ⚙️ Installation & Démarrage

### Sous Linux (Fedora / Nobara)

1. **Installation** :
   ```bash
   ./install.sh
   ```
   *Le script vérifie l'environnement Python/.NET, télécharge la voix Piper TTS, nettoie les anciens exécutables et crée les raccourcis dans `~/.local/bin` (`alyx` et `alyx-stop`).*

2. **Vérification de la variable PATH** (si `~/.local/bin` n'est pas inclus) :
   ```bash
   echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
   source ~/.bashrc
   ```

3. **Lancement de l'agent** :
   ```bash
   alyx
   ```

4. **Arrêt des processus** :
   ```bash
   alyx-stop
   ```

### Sous Windows

1. **Installation** :
   ```bat
   .\install.bat
   ```
   *Configuration du venv Python, des dépendances et enregistrement du dossier dans le PATH utilisateur.*

2. **Lancement** :
   - **Mode Arrière-plan (VBS)** : Double-cliquer sur `Lancer_Alyx.vbs`.
   - **Mode Console (CLI)** : Ouvrir un terminal et taper `alyx`.

3. **Arrêt** :
   - Double-cliquer sur `Arreter_Alyx.vbs` ou exécuter `.\stop.bat`.

---

## 📱 Compagnon Mobile (Interface Web PWA)

L'application compagnon permet de piloter l'agent depuis un smartphone connecté au même réseau Wi-Fi local.

1. Dans l'UI de desktop C#, cliquer sur **Compagnon mobile** pour afficher le QR Code, l'adresse IP locale (`http://<IP_PC>:8766`) et le code d'appairage.
2. Ouvrir le navigateur mobile à l'adresse indiquée et saisir le code d'appairage.
3. Sécurité réseau :
   - Le serveur WebSocket (`api.py`) n'autorise les connexions distantes (non-loopback) que si un jeton d'appairage valide est fourni.
   - Les connexions réseau LAN peuvent être désactivées via la directive `server.allow_lan: false` dans `config.yaml`.

---

## 🔧 Configuration (`config.yaml`)

Les paramètres clés du système sont définis dans `config.yaml` à la racine du projet :

```yaml
server:
  port: 8765
  allow_lan: true
  mobile_port: 8766

llm_provider:
  max_context_messages: 40
  scan_timeout: 1.5

providers:
  - name: "ollama"
    api_base: "http://127.0.0.1:11434"
    priority: 1
  - name: "lm_studio"
    api_base: "http://127.0.0.1:1234"
    priority: 2

voice:
  piper_model_path: "models/piper/fr_FR-siwis-medium.onnx"
```

---

## 🏗️ Architecture Technique

- **Sous-système WebSocket** : Échanges JSON/Binaire sur port `8765`. Options socket `TCP_NODELAY` activées des deux côtés.
- **Résolution Déterministe des Processus** : Matching hybride normalisé (tokenisation, résolution d'entrées XDG `.desktop`, contournement de la limite `TASK_COMM_LEN` de 15 caractères sous Linux `/proc/<pid>/comm`).
- **Pipeline STT & TTS** : Micro-service STT isolé (Whisper/faster-whisper) communiquant en HTTP/gRPC local ; synthèse vocale Piper TTS exécutée dans un worker thread asynchrone découpé par ponctuation.
- **Ring Buffer de Contexte** : Fenêtre glissante garantissant la préservation des paires indissociables `tool_call` / `tool_response`.
- **Shutdown & Process Lifecycle** : Routage d'arrêt par PID (`run/*.pid`) avec signalement progressif (SIGTERM -> délai -> SIGKILL sur Linux, `taskkill /F` sur Windows).
