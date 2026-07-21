# Alyx (V2)

Alyx est un assistant virtuel local **100% Air-Gapped**. Pensé pour la confidentialité absolue, aucune donnée ne quitte votre machine. L'interface est codée en C# (Avalonia) et communique en temps réel via WebSockets avec un moteur Python. 

Il prend en charge nativement **Windows** et **Linux** (Fedora/Nobara) et s'intègre comme un véritable "sysadmin" virtuel sur votre système.

## 🚀 Fonctionnalités
- **Fonctionnement 100% local (Air-Gapped)** sans aucune télémétrie.
- **Routage multi-fournisseurs dynamique** : Support de Ollama, LM Studio et NVIDIA NIM avec basculement intelligent (Circuit Breaker).
- **Agentivité Système (Human-in-the-Loop)** : L'IA peut fermer/ouvrir des applications, chercher des processus, gérer vos fichiers, et plus encore. (Les actions critiques requièrent votre validation).
- **Communication Zéro-Latence** via WebSocket bidirectionnel.

## 🛠️ Prérequis
- **Python 3.10+** (Testé sur 3.11 / 3.12)
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
Vous avez deux options pour démarrer Alyx :
- **Mode Simple (Recommandé)** : Double-cliquez sur le fichier `Lancer_Alyx.vbs`. Cela démarrera tout en arrière-plan sans afficher de fenêtre noire.
- **Mode Développeur** : Exécutez `.\alyx.bat` dans un terminal pour voir les logs système.

*(Lance l'API Python et le frontend C# en arrière-plan. Les PIDs sont sauvegardés pour un arrêt propre).*

**3. Arrêt**
- **Mode Simple** : Double-cliquez sur `Arreter_Alyx.vbs`. Un message vous confirmera l'arrêt complet.
- **Mode Développeur** : Exécutez `.\stop.bat`.

### Sous Linux (Fedora / Nobara)

**1. Installation (Une seule fois)**
```bash
./install.sh
```
*(Assurez-vous d'avoir les paquets audio comme `portaudio-devel` et `alsa-plugins-pulseaudio` installés).*

**2. Lancement**
```bash
./alyx.sh
```

**3. Arrêt**
```bash
./stop.sh
```

## 🔧 Configuration Avancée

Toutes les configurations clés (ports, TTL de cache, priorités des fournisseurs d'IA, limites de contexte) sont centralisées dans le fichier `config.yaml` à la racine du projet. Vous pouvez le modifier pour changer le comportement de l'assistant sans toucher au code source.
