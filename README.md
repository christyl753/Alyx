# Alyx (V2)

Alyx est un assistant virtuel local **100% Air-Gapped**. Pensé pour la confidentialité absolue, aucune donnée ne quitte votre machine. L'interface est codée en C# (Avalonia) et communique en temps réel via WebSockets avec un moteur Python. 

Il prend en charge nativement **Windows** et **Linux** (Fedora/Nobara) et s'intègre comme un véritable "sysadmin" virtuel sur votre système.

## 📥 Télécharger Alyx

Téléchargez la dernière version d'Alyx selon votre système (les archives contiennent uniquement les fichiers utiles pour chaque OS) :

- [🐧 Télécharger pour Linux](https://github.com/christyl753/Alyx/releases/latest/download/Alyx-Linux.zip)
- [🪟 Télécharger pour Windows](https://github.com/christyl753/Alyx/releases/latest/download/Alyx-Windows.zip)

## 🚀 Fonctionnalités (V2)
- **Air-Gapped (100% Hors Ligne)** : Aucune télémétrie, aucune API cloud de secours. Confidentialité absolue.
- **Command Palette & Conscience Contextuelle** : Invocation instantanée via `Alt+Espace`. Lecture automatique du presse-papiers et de la fenêtre active à l'invocation.
- **Daily Tasks & Agentivité (Human-in-the-Loop)** : Gestion de rappels, prises de notes, vérification matérielle (batterie, réseau), gestion des fichiers. Validation humaine obligatoire pour les actions destructrices.
- **Mode Focus / Gaming (Nobara)** : Détection d'applications plein écran gourmandes et déchargement intelligent de la VRAM pour un impact FPS nul.
- **Routage multi-fournisseurs dynamique** : Support d'Ollama, LM Studio et NVIDIA NIM avec basculement automatique (Circuit Breaker).
- **Communication Zéro-Latence** : Échanges via WebSocket bidirectionnel pour une fluidité d'exécution instantanée.
- **Interface Néo-Brutaliste** : Contrastes forts, typographie mixte (Inter/Roboto + Fira Code), et indicateurs d'état non-intrusifs (animations subtiles plutôt que texte).

## 📥 Télécharger Alyx

Téléchargez la dernière version d'Alyx selon votre système (les archives contiennent uniquement les fichiers utiles pour chaque OS) :

- [🐧 Télécharger pour Linux](https://github.com/christyl753/Alyx/releases/latest/download/Alyx-Linux.zip)
- [🪟 Télécharger pour Windows](https://github.com/christyl753/Alyx/releases/latest/download/Alyx-Windows.zip)

## 🛠️ Prérequis
- **Python 3.11 ou 3.12** (⚠️ *Attention : Python 3.14 n'est pas supporté* nativement en raison de dépendances C complexes pour le STT et l'Audio. L'architecture V2 isole le STT dans un environnement figé).
- **.NET 8.0 SDK** (pour compiler le frontend Avalonia)
- **Ollama** ou **LM Studio** pour exécuter les modèles en local.

## 🧠 Configuration des Moteurs IA & Modèles Recommandés

Alyx ne contient pas de modèle d'intelligence artificielle intégré (pour rester léger). Il interroge les modèles que vous téléchargez localement. 
*Note importante : La latence perçue par l'utilisateur dépend non seulement de la vitesse de génération du modèle (Tokens/s), mais aussi de la latence réseau locale (WebSocket/HTTP) entre l'interface Alyx et le serveur IA. Il est donc crucial de privilégier des modèles très rapides pour compenser ce délai de transmission.*

Pour une expérience **fluide, rapide et sécuritaire (respect des consignes système)**, voici les recommandations :

### 💻 Recommandations selon votre Matériel (RAM / VRAM)
Le choix du modèle dépend fortement de votre ordinateur. Les modèles d'IA consomment de la mémoire vive (RAM) et, idéalement, de la mémoire vidéo (VRAM) pour être rapides.

- **PC standard (16 Go de RAM, pas de carte graphique dédiée ou GPU faible)** :
  Privilégiez les modèles plus petits (7B à 8B paramètres) avec une forte compression (Quantization). Le traitement se fera sur le processeur (CPU), ce qui est plus lent.
  - *Recommandations* : `qwen2.5:7b` (Ollama) ou **Qwen2.5-7B-Instruct-GGUF en Q4_K_M** (LM Studio).
- **PC Gamer / Station de travail (16-32 Go de RAM, Carte graphique dédiée > 8 Go VRAM)** :
  Vous pouvez utiliser des modèles légèrement plus lourds ou avec une compression moindre, tout en profitant de l'accélération matérielle ultra-rapide du GPU.
  - *Recommandations* : `gemma2:9b`, `llama3.1:8b` (Ollama) ou **Meta-Llama-3.1-8B-Instruct-GGUF en Q6_K** ou **Q8_0** (LM Studio).

### Option 1 : Ollama (Le plus simple)
1. Téléchargez et installez [Ollama](https://ollama.com/).
2. Ouvrez un terminal et téléchargez un modèle recommandé. Par exemple :
   - `ollama run qwen2.5:7b` (Très rapide, excellent en français, parfait pour le rôle d'agent).
   - `ollama run llama3.1:8b` (Très robuste pour suivre des consignes complexes).
   - `ollama run gemma2:9b` (Bonnes capacités de raisonnement).
3. Assurez-vous que l'icône Ollama est active dans votre barre des tâches. Alyx détectera automatiquement les modèles.

### Option 2 : LM Studio (Pour une gestion visuelle avancée)
1. Téléchargez et installez [LM Studio](https://lmstudio.ai/).
2. Cherchez et téléchargez un modèle quantizé (GGUF). Recommandations :
   - **Qwen2.5-7B-Instruct-GGUF** (Q4_K_M ou Q5_K_M).
   - **Meta-Llama-3.1-8B-Instruct-GGUF**.
3. **Étape cruciale** : Allez dans l'onglet **Local Server** (l'icône avec les doubles flèches `<->` à gauche).
4. Assurez-vous que le port est sur `1234` (par défaut).
5. Cliquez sur le bouton **Start Server**. Alyx pourra alors se connecter et voir vos modèles.

## ⚙️ Installation & Démarrage

### Sous Windows

**1. Installation (Une seule fois)**
```bat
.\install.bat
```
*(Cela va créer l'environnement virtuel et installer les dépendances).*

**2. Lancement**
`install.bat` ajoute le dossier du projet à votre PATH utilisateur : après avoir **rouvert un terminal**, la commande `alyx` est disponible depuis n'importe quel dossier.
- **Mode Simple (Recommandé)** : Double-cliquez sur le fichier `Lancer_Alyx.vbs`. Cela démarrera tout en arrière-plan sans afficher de fenêtre noire.
- **Mode Développeur** : Tapez `alyx` dans un terminal pour voir les logs système (équivalent à `.\alyx.bat`).

*(Lance l'API Python et le frontend C# en arrière-plan. Les PIDs sont sauvegardés pour un arrêt propre).*

**3. Arrêt**
- **Mode Simple** : Double-cliquez sur `Arreter_Alyx.vbs`. Un message vous confirmera l'arrêt complet.
- **Mode Développeur** : Exécutez `.\stop.bat`.

### Sous Linux (Fedora / Nobara)

**1. Installation (Une seule fois)**
```bash
./install.sh
```
*(Assurez-vous d'avoir les paquets audio comme `portaudio-devel` et `alsa-plugins-pulseaudio` installés. Le script nettoie les anciens exécutables de test (comme `alyz` ou d'anciens dossiers) et configure les commandes globales `alyx` et `alyx-stop` dans `~/.local/bin`).*

**2. Vérification de l'accès global (PATH)**
Si `~/.local/bin` n'est pas encore présent dans votre variable `PATH`, ajoutez-le dans votre fichier d'environnement (ex: `~/.bashrc` ou `~/.zshrc`) puis rechargez votre terminal :
```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**3. Lancement**
Lancez l'assistant depuis n'importe quel répertoire dans le terminal :
```bash
alyx
```

**4. Arrêt**
Pour arrêter tous les processus d'Alyx (API Backend, micro-service STT, UI C# Avalonia) :
```bash
alyx-stop
```
*(Ou exécutez `./stop.sh` depuis le répertoire du projet).*

## 🔧 Configuration Avancée

Toutes les configurations clés (ports, TTL de cache, priorités des fournisseurs d'IA, limites de contexte) sont centralisées dans le fichier `config.yaml` à la racine du projet. Vous pouvez le modifier pour changer le comportement de l'assistant sans toucher au code source.

## 🏗️ Architecture Technique Fondamentale (V2)
- **Isolation STT** : Exécuté dans un sous-processus figé (Python 3.11/3.12) avec communication via HTTP local ou gRPC.
- **Exécution Saine (Windows)** : Jamais d'activation via `activate.bat`, appels directs exclusifs à l'exécutable `.venv\Scripts\python.exe`.
- **Mécanismes Avancés** : Scan asynchrone des LLMs locaux, vérification d'espace disque avant téléchargement, et ring buffer pour la gestion du contexte.
- **WebSockets Avalonia (C#)** : Événements routés de façon asynchrone sur l'UI Thread (`Dispatcher.UIThread.Post`) pour maintenir 60 FPS fluides.
- **Graceful Shutdown** : Routage dynamique de l'arrêt selon l'OS (SIGTERM/SIGKILL vs Taskkill), capture des PIDs et élimination des processus zombies.
