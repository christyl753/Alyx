# Alyx (V2)

Alyx est un assistant virtuel local multi-plateforme (Windows et Linux Fedora/Nobara) fonctionnant entièrement hors ligne (Air-Gapped). L'interface utilisateur est développée en C# (.NET 8 Avalonia) et communique en WebSockets avec un backend Python 3.11+.

## 📥 Téléchargement (Releases)

- [🐧 Télécharger pour Linux (zip)](https://github.com/christyl753/Alyx/releases/latest/download/Alyx-Linux.zip)
- [🪟 Télécharger pour Windows (zip)](https://github.com/christyl753/Alyx/releases/latest/download/Alyx-Windows.zip)

---

## 🛠️ Prérequis

- **OS** : Windows 10/11 ou Linux (Fedora 38+, Nobara 38+, Ubuntu 22.04+).
- **Python** : 3.11 ou 3.12 (Python 3.14 non supporté pour le STT).
- **.NET SDK** : .NET 8.0 SDK.
- **Moteur IA local** : Ollama (>= 0.3.0) ou LM Studio (>= 0.2.20).

---

## 📊 Choix du Modèle IA

| Mémoire VRAM / RAM | Modèle | Quantification | Exemples |
| :--- | :--- | :--- | :--- |
| **CPU (sans GPU)** | 7B - 8B | Q4_K_M | `qwen2.5:7b`, `llama3.1:8b` |
| **GPU 6 - 8 Go VRAM** | 7B - 9B | Q4_K_M / Q6_K | `qwen2.5:7b`, `gemma2:9b` |
| **GPU >= 12 Go VRAM** | 14B - 32B | Q6_K / Q8_0 | `qwen2.5:14b`, `qwen2.5:32b` |

### Configuration Rapide

- **Ollama** : `ollama pull qwen2.5:7b` (détection automatique par Alyx).
- **LM Studio** : charger le modèle GGUF et démarrer le **Local Server** (port `1234`).

---

## ⚙️ Installation & Démarrage

### Linux (Fedora / Nobara)

1. **Installer** :
   ```bash
   ./install.sh
   ```
2. **Lancer** :
   ```bash
   alyx
   ```
3. **Arrêter** :
   ```bash
   alyx-stop
   ```

### Windows

1. **Installer** :
   ```bat
   .\install.bat
   ```
2. **Lancer** : Double-cliquer sur `Lancer_Alyx.vbs` (ou taper `alyx` en CLI).
3. **Arrêter** : Double-cliquer sur `Arreter_Alyx.vbs` (ou exécuter `.\stop.bat`).

---

## 📱 Compagnon Mobile (Wi-Fi Local)

1. Sur le PC, cliquer sur **Compagnon mobile** dans l'UI Alyx pour afficher l'adresse et le code d'appairage.
2. Sur le téléphone (même Wi-Fi), ouvrir `http://<IP_PC>:8766` et entrer le code.

---

## 🔧 Configuration (`config.yaml`)

```yaml
server:
  port: 8765
  allow_lan: true
  mobile_port: 8766

providers:
  - name: "ollama"
    api_base: "http://127.0.0.1:11434"
    priority: 1
  - name: "lm_studio"
    api_base: "http://127.0.0.1:1234"
    priority: 2
```
