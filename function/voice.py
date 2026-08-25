# Fichier : function/voice.py
import os
import queue
import tempfile
import threading
import wave
import numpy as np
import sounddevice as sd
import yaml

# --- CONFIGURATION ---
SAMPLE_RATE = 16000
WHISPER_MODEL_SIZE = "base"  # Options: tiny, base, small, medium, large-v3

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, 'config.yaml')

def _load_voice_config():
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return (yaml.safe_load(f) or {}).get('voice', {})
    return {}

_voice_config = _load_voice_config()
_piper_model_path_config = _voice_config.get('piper_model_path', 'models/piper/fr_FR-siwis-medium.onnx')
PIPER_MODEL_PATH = (
    _piper_model_path_config if os.path.isabs(_piper_model_path_config)
    else os.path.join(_PROJECT_ROOT, _piper_model_path_config)
)

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

# --- INITIALISATION STT (faster-whisper) ---
_whisper_model = None

def _init_whisper():
    """Charge le modèle Whisper une seule fois (lazy loading)."""
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            print(f"     [Chargement du modèle Whisper '{WHISPER_MODEL_SIZE}'...]")
            _whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type="int8"
            )
            print(f"     [✓ Modèle Whisper chargé avec succès]")
        except ImportError:
            print("     [Avertissement: faster-whisper non installé, mode vocal indisponible]")
        except Exception as e:
            print(f"     [Erreur chargement Whisper: {e}]")
    return _whisper_model


def faire_parler(texte: str) -> None:
    """Fait parler Alyx à voix haute via synthèse vocale locale (Asynchrone)."""
    texte_propre = texte.replace('*', '').replace('#', '').replace('_', '')
    if texte_propre.strip():
        _tts_queue.put(texte_propre)


def ecouter(duree_max_secondes: int = 8) -> str:
    """Écoute le microphone et retranscrit la parole en texte via faster-whisper."""
    model = _init_whisper()
    if model is None:
        return ""

    file_audio = queue.Queue()

    def callback(indata, frames, time_info, status):
        file_audio.put(indata.copy())

    print("\n     [🎙️ Alyx t'écoute... Parle maintenant]")

    try:
        # Enregistrement audio
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            blocksize=8000,
            dtype='float32',
            channels=1,
            callback=callback
        ):
            frames_enregistrees = []
            frames_lus = 0
            max_frames = int((duree_max_secondes * SAMPLE_RATE) / 8000)

            # Détection de silence pour arrêt anticipé
            silence_consecutif = 0
            seuil_silence = 0.01
            max_silence_frames = 4  # ~2 secondes de silence = stop
            a_parle = False

            while frames_lus < max_frames:
                data = file_audio.get()
                frames_enregistrees.append(data)
                frames_lus += 1

                # Détection de silence
                volume = np.abs(data).mean()
                if volume >= seuil_silence:
                    a_parle = True
                    silence_consecutif = 0
                else:
                    silence_consecutif += 1

                # Si on a parlé puis silencieux, on arrête
                if a_parle and silence_consecutif >= max_silence_frames:
                    break

        if not frames_enregistrees:
            return ""

        # Conversion en fichier WAV temporaire pour Whisper
        audio_data = np.concatenate(frames_enregistrees, axis=0)
        audio_int16 = (audio_data * 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            with wave.open(tmp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_int16.tobytes())

        # Transcription
        segments, info = model.transcribe(
            tmp_path,
            language="fr",
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200
            )
        )

        texte_final = " ".join(seg.text.strip() for seg in segments).strip()

        # Nettoyage
        os.unlink(tmp_path)

    except Exception as e:
        print(f"     [Erreur micro : {e}]")
        return ""

    if texte_final:
        print(f"     [🎙️ Entendu : \"{texte_final}\"]")
    else:
        print("     [🎙️ Silence ou incompris.]")

    return texte_final
