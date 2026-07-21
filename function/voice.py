# Fichier : function/voice.py
import os
import json
import queue
import tempfile
import wave
import numpy as np
import pyttsx3
import sounddevice as sd

# --- CONFIGURATION ---
SAMPLE_RATE = 16000
WHISPER_MODEL_SIZE = "base"  # Options: tiny, base, small, medium, large-v3

import threading

# --- INITIALISATION TTS (Voix d'Alyx) ---
_tts_queue = queue.Queue()

def _tts_worker():
    """Worker thread dédié à la synthèse vocale pour ne pas bloquer l'API."""
    moteur = pyttsx3.init()
    moteur.setProperty('rate', 170)
    while True:
        texte = _tts_queue.get()
        if texte is None:
            break
        try:
            moteur.say(texte)
            moteur.runAndWait()
        except Exception as e:
            pass
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
