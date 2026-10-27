# Alyx

Un assistant qui tourne **entièrement sur votre PC**, sans connexion internet, sans compte, sans données envoyées nulle part. Vous lui parlez, il vous répond, et il peut agir sur votre système (ouvrir des apps, gérer des fichiers, contrôler la musique…). Il vit sur votre bureau sous forme d'un petit **orbe flottant** qu'on déplace où on veut.

Fonctionne sous **Windows** et **Linux**.

![Widget Alyx](AlyxDesktop/Assets/logo.png)

## Ce qu'il peut faire

- **Discuter** : posez-lui des questions, demandez-lui de rédiger du texte, d'expliquer un concept…
- **Agir sur votre PC** : ouvrir/fermer des applications, créer/lire/déplacer des fichiers, générer des PDF — il demande toujours votre accord avant de faire quelque chose de sensible.
- **Parler et écouter** : mode vocal intégré (micro + synthèse vocale).
- **Surveiller votre système** : CPU, RAM, GPU, réseau, batterie, processus actifs — le tout en direct dans un panneau dédié.
- **Contrôler vos médias** : lecture, pause, piste suivante (Spotify, navigateur…).
- **Gérer vos modèles IA** : charger et décharger les modèles depuis l'interface, voir la vitesse et la mémoire utilisée.
- **Réglages rapides** : Wi-Fi, Bluetooth, volume, luminosité, démarrage automatique.

## Comment ça marche

Alyx n'embarque pas de modèle d'IA lui-même — il est léger. Il se connecte à un moteur IA local que vous installez à côté :

- **[Ollama](https://ollama.com/)** — le plus simple, en ligne de commande
- **[LM Studio](https://lmstudio.ai/)** — avec une interface graphique pour gérer vos modèles

Alyx détecte automatiquement les modèles disponibles. Vous choisissez lequel utiliser directement depuis son interface.

### Quel modèle choisir ?

| Votre PC | Modèle recommandé | Commande Ollama |
|---|---|---|
| 8–16 Go de RAM, pas de carte graphique puissante | Qwen 2.5 7B | `ollama run qwen2.5:7b` |
| 16+ Go de RAM, carte graphique avec 6+ Go | Llama 3.1 8B ou Gemma 2 9B | `ollama run llama3.1:8b` |

> Avec LM Studio, cherchez le même modèle en format **GGUF** (ex: `Qwen2.5-7B-Instruct-GGUF` en Q4_K_M), puis démarrez le serveur local dans l'onglet **Local Server** (port 1234).

## Installation

### Ce qu'il vous faut

- **Python 3.10 ou plus récent** — [python.org](https://www.python.org/downloads/)
- **.NET 8 SDK** — [dotnet.microsoft.com](https://dotnet.microsoft.com/download)
- **Ollama** ou **LM Studio** (voir ci-dessus)

### Windows

```bat
.\install.bat
```

Ça crée l'environnement Python, installe les dépendances et compile l'interface. Un raccourci **Alyx** est ajouté à votre menu Démarrer.

Pour lancer Alyx :
- Depuis le **menu Démarrer** → cherchez « Alyx »
- Ou double-cliquez sur `Lancer_Alyx.vbs`
- Ou en terminal : `.\alyx.bat`

Pour l'arrêter :
- Clic droit sur l'icône Alyx dans la zone de notification → **Quitter**
- Ou double-cliquez sur `Arreter_Alyx.vbs`
- Ou en terminal : `.\stop.bat`

### Linux (Fedora / Nobara)

```bash
chmod +x install.sh alyx.sh stop.sh
./install.sh
```

> Vous aurez besoin de `portaudio-devel` et `alsa-plugins-pulseaudio` pour le micro.

Pour lancer : `./alyx.sh` (ou depuis le menu des applications).
Pour arrêter : `./stop.sh`

## Utilisation

- **Cliquez sur l'orbe** (ou appuyez sur **Alt+J** sous Windows) pour ouvrir le menu.
- **Glissez l'orbe** pour le déplacer — sa position est mémorisée.
- Le menu affiche 6 bulles : Chat, Système, Tâches, Modèles, Réglages, et Lecteur.
- **Échap** pour fermer le panneau.

## Configuration

Le fichier `config.yaml` à la racine contient tous les réglages (ports, timeouts, fournisseurs IA, taille du contexte). Modifiez-le librement.

## Licence

Projet personnel. Code source disponible tel quel.
