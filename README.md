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
