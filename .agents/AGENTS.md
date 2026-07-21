# Alyx Project Rules

## Environnement & Compatibilité Python

- **Python 3.14 Compatibility** : Dans le projet Alyx, l'utilisation de librairies STT/Audio nécessitant des extensions C complexes (comme PyAV ou faster-whisper) doit être conditionnée ou évitée sur les versions de Python en cours de développement (ex: >= 3.14) afin de garantir la portabilité du projet.

- **Isolation du STT/Audio (Découplage de version Python)** : Pour éviter que la compatibilité de Python 3.14+ ne bloque des fonctionnalités audio critiques (PyAV, faster-whisper), le module STT doit tourner dans un sous-processus/environnement virtuel dédié figé sur une version Python stable (3.11 ou 3.12), communiquant avec l'API principale via HTTP local ou gRPC. Cela permet au cœur d'Alyx de rester sur la dernière version de Python sans dépendre de la maturité des extensions C de l'écosystème audio.

- **Handshake de Démarrage STT** : L'API principale ne doit jamais supposer que le sous-processus STT est prêt immédiatement après son lancement. Elle doit poller un endpoint de santé dédié au STT (ex: `http://127.0.0.1:<port_stt>/health`) avec backoff court avant de router le premier flux audio, et exposer cet état dans le endpoint `/api/.../status` global (voir section Observabilité).

## Exécution & Processus sous Windows

- **Exécution d'environnements virtuels sous Windows** : Pour respecter les politiques de sécurité (Execution Policy) de PowerShell, ne tentez jamais d'activer un environnement virtuel via des scripts `activate.bat` ou `activate.ps1`. Invoquez toujours directement l'exécutable du `.venv` (par exemple : `.\.venv\Scripts\python.exe -m pip install ...`).

- **Lancement Multi-Processus sous Windows** : Dans l'écosystème Alyx sous Windows, le lancement multi-processus (API + UI) doit être géré via un fichier `alyx.bat` utilisant les chemins absolus implicites (`%~dp0`) et `start /B` pour l'API, afin d'éviter le blocage du terminal et de respecter les politiques d'exécution de scripts (pas d'activation de `.venv`). Ce fichier doit également :
  - Rediriger explicitement les flux stdout/stderr de l'API et de l'UI vers des fichiers de logs séparés (ex: `logs\api.log`, `logs\ui.log`) plutôt que de les laisser se perdre.
  - Capturer les PID des processus lancés (ex: dans `run\*.pid`) pour permettre un arrêt propre ultérieur.
  - Si un contrôle plus fin des processus devient nécessaire, un script PowerShell utilisant `Start-Process` est préférable au `.bat`, tout en conservant l'appel direct à l'exécutable du `.venv` (jamais d'activation de script).

- **Arrêt Propre des Processus** : Un script `stop.bat` (ou une gestion de signal dans `alyx.bat`) doit utiliser les PID capturés (voir règle ci-dessus) pour terminer explicitement l'API, l'UI et le sous-processus STT avant de considérer l'arrêt terminé. Cela évite les ports orphelins qui bloquent le redémarrage.

## Fournisseurs d'IA Locaux

- **Support Multi-Fournisseurs d'IA** : Dans l'écosystème Alyx, il faut toujours prendre en compte le support multi-fournisseurs (Ollama, LM Studio, etc.). Ne forcez pas la dépendance stricte à un seul outil dans les scripts d'installation si l'API en supporte plusieurs.

- **Performance de Détection Multi-Fournisseurs** : Lors de la communication avec des API locales (Ollama, LM Studio, NVIDIA, etc.), il est STRICTEMENT INTERDIT de faire des appels réseau synchrones à chaque requête pour vérifier l'état ou résoudre le fournisseur d'un modèle. Vous DEVEZ :
  1. **Utiliser un Cache** : Mettre en cache la liste des modèles avec un TTL (ex: 60s).
  2. **Scan Parallèle** : Scanner les fournisseurs en parallèle (ex: `ThreadPoolExecutor`) avec des timeouts courts (ex: 1.5s).
  3. **Démarrage Asynchrone** : Ne jamais bloquer le démarrage de l'API principale. Utilisez des threads de préchargement et des endpoints d'état (ex: `/api/.../ready`) pour le polling côté interface utilisateur.

- **Résilience des Fournisseurs Locaux (Circuit Breaker)** : En complément du scan parallèle et du cache TTL, tout fournisseur d'IA local (Ollama, LM Studio, NVIDIA, etc.) ayant échoué N fois consécutives (ex: 3) doit être marqué "indisponible" pendant une durée de repos (ex: 30-60s) avant nouvelle tentative, plutôt que d'être retesté à chaque requête. Cela évite l'accumulation de timeouts et permet une bascule (fallback) rapide vers le fournisseur suivant dans l'ordre de priorité défini.

- **Contrôle de Concurrence et Ressources GPU** : Avant de router une requête vers un fournisseur local, l'API doit connaître ses limites de concurrence (ex: un sémaphore par fournisseur pour éviter de saturer un serveur mono-requête) et, si possible, l'état de la VRAM disponible (ex: via `pynvml`) pour éviter de charger un modèle trop volumineux et faire crasher le fournisseur ciblé.

## Configuration & Observabilité

- **Configuration Centralisée** : Toutes les valeurs opérationnelles (TTL du cache, timeouts réseau, seuils du circuit breaker, ports des sous-processus, ordre de priorité des fournisseurs) doivent être définies dans un unique fichier de configuration (ex: `config.yaml` ou `.env`), jamais codées en dur dans plusieurs fichiers. Cela permet de les ajuster sans toucher au code.

- **Observabilité de l'État des Fournisseurs** : L'endpoint `/api/.../ready` doit être complété par un endpoint `/api/.../status` détaillant, pour chaque fournisseur : disponibilité, modèles chargés, latence moyenne. Les logs de l'API doivent être structurés (JSON) plutôt qu'en texte brut, afin de faciliter le debug et une future intégration dashboard.

- **Notification Temps Réel (optionnel, post-MVP)** : Si le polling de `/status` devient fréquent (< 2s d'intervalle) ou coûteux, envisager un flux SSE (`/api/.../events`) pour pousser les changements d'état des fournisseurs à l'UI au lieu de la faire interroger en boucle.

## Gestion des Modèles

- **Vérification Disque avant Téléchargement de Modèle** : Avant tout téléchargement de modèle (STT, LLM local), l'API doit vérifier l'espace disque disponible sur le volume cible et refuser/avertir si l'espace est insuffisant, plutôt que de laisser échouer un téléchargement partiel.