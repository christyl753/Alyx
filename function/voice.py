# Fichier : function/voice.py
import queue
import numpy as np
import sounddevice as sd

# --- CONFIGURATION ---
SAMPLE_RATE = 16000
WHISPER_MODEL_SIZE = "base"  # Options: tiny, base, small, medium, large-v3

# --- SYNTHÈSE VOCALE : voir function/tts.py (choix de la voix, arrêt immédiat) ---
from .tts import faire_parler, arreter_parole  # noqa: F401 (réexport)

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
                try:
                    data = file_audio.get(timeout=2)
                except queue.Empty:
                    break  # le périphérique audio ne délivre plus rien
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

        # Whisper accepte directement un tableau float32 mono 16 kHz (pas de fichier temporaire)
        audio_data = np.concatenate(frames_enregistrees, axis=0).flatten()

        # Transcription
        segments, info = model.transcribe(
            audio_data,
            language="fr",
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=200
            )
        )

        texte_final = " ".join(seg.text.strip() for seg in segments).strip()

    except Exception as e:
        print(f"     [Erreur micro : {e}]")
        return ""

    if texte_final:
        print(f"     [🎙️ Entendu : \"{texte_final}\"]")
    else:
        print("     [🎙️ Silence ou incompris.]")

    return texte_final
