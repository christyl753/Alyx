# Fichier : function/voice.py
import json
import os
import queue
import threading
import urllib.error
import urllib.request
import sounddevice as sd
import yaml

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, 'config.yaml')

def _load_config():
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}

_config = _load_config()
_voice_config = _config.get('voice', {})
_stt_config = _config.get('stt', {})

# --- CONFIGURATION TTS ---
_piper_model_path_config = _voice_config.get('piper_model_path', 'models/piper/fr_FR-siwis-medium.onnx')
PIPER_MODEL_PATH = (
    _piper_model_path_config if os.path.isabs(_piper_model_path_config)
    else os.path.join(_PROJECT_ROOT, _piper_model_path_config)
)

# --- CONFIGURATION STT ---
# Pas de second modèle faster-whisper chargé ici : ce serait une DUPLICATION de
# stt_server.py, en violation de l'isolation STT documentée (AGENTS.md B.1 — sous-
# processus figé en Python 3.11/3.12). ecouter() ci-dessous appelle ce même
# micro-service en HTTP, exactement comme le fait api.py pour le flux WebSocket
# principal : une seule implémentation STT dans tout le projet, jamais deux qui
# pourraient diverger silencieusement.
_STT_PORT = _stt_config.get('port', 5001)
_STT_TIMEOUT = _stt_config.get('request_timeout', 20)

# --- INITIALISATION TTS (Piper : voix française neuronale, locale) ---
_tts_queue = queue.Queue()
_piper_voice = None

def _init_piper():
    """Charge le modèle Piper une seule fois (lazy loading)."""
    global _piper_voice
    if _piper_voice is None:
        if not os.path.exists(PIPER_MODEL_PATH):
            print(f"     [Avertissement: modèle vocal Piper introuvable ({PIPER_MODEL_PATH}). "
                  f"Relancez install.sh/install.bat pour le télécharger. Mode vocal (voix) indisponible.]")
            return None
        try:
            from piper import PiperVoice
            print(f"     [Chargement de la voix Piper '{os.path.basename(PIPER_MODEL_PATH)}'...]")
            _piper_voice = PiperVoice.load(PIPER_MODEL_PATH)
            print(f"     [✓ Voix Piper chargée avec succès]")
        except ImportError:
            print("     [Avertissement: piper-tts non installé, mode vocal (voix) indisponible]")
        except Exception as e:
            print(f"     [Erreur chargement Piper: {e}]")
    return _piper_voice

def _tts_worker():
    """Worker thread dédié à la synthèse vocale pour ne pas bloquer l'API."""
    while True:
        texte = _tts_queue.get()
        if texte is None:
            break
        try:
            voice = _init_piper()
            if voice is not None:
                for chunk in voice.synthesize(texte):
                    sd.play(chunk.audio_float_array, samplerate=chunk.sample_rate)
                    sd.wait()
        except Exception as e:
            print(f"     [Erreur TTS: {e}]")
        finally:
            _tts_queue.task_done()

# Démarrage du thread TTS en mode démon (s'arrêtera avec le programme)
threading.Thread(target=_tts_worker, daemon=True).start()

def faire_parler(texte: str) -> None:
    """Fait parler Alyx à voix haute via synthèse vocale locale (Asynchrone)."""
    texte_propre = texte.replace('*', '').replace('#', '').replace('_', '')
    if texte_propre.strip():
        _tts_queue.put(texte_propre)


def ecouter(duree_max_secondes: int | None = None) -> str:
    """
    Écoute le microphone et retranscrit la parole en texte.

    Utilisé par le mode CLI autonome (ai.py exécuté directement, sans l'UI C#) :
    délègue au micro-service STT isolé (stt_server.py) exactement comme le fait
    l'API WebSocket principale. Si le micro-service n'est pas démarré (CLI lancée
    seule, sans passer par alyx.sh/alyx.bat), échoue silencieusement — cohérent
    avec le rôle de la CLI, un outil de test léger, pas le chemin de production.
    """
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{_STT_PORT}/listen", method="POST")
        timeout = _STT_TIMEOUT if duree_max_secondes is None else duree_max_secondes + 5
        print("\n     [🎙️ Alyx t'écoute... Parle maintenant]")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode('utf-8'))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        print(f"     [Service STT injoignable sur le port {_STT_PORT} ({e}). "
              f"Lancez stt_server.py séparément pour activer le mode vocal en CLI.]")
        return ""
    except Exception as e:
        print(f"     [Erreur micro : {e}]")
        return ""

    texte_final = data.get('text', '')
    if texte_final:
        print(f"     [🎙️ Entendu : \"{texte_final}\"]")
    else:
        print("     [🎙️ Silence ou incompris.]")

    return texte_final
