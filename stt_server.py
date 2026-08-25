import os
import json
import queue
import tempfile
import wave
import numpy as np
import sounddevice as sd
import threading
import yaml
from http.server import BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer

# --- CONFIGURATION ---
# Centralisée dans config.yaml (section 'stt') pour rester cohérente avec le reste du
# projet (AGENTS.md B.4) et pour que la langue transcrite ne soit jamais dupliquée /
# désynchronisée entre plusieurs fichiers ("module linguistique propre").
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, 'config.yaml')


def _load_stt_config():
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return (yaml.safe_load(f) or {}).get('stt', {})
    return {}


_stt_config = _load_stt_config()

SAMPLE_RATE = 16000
WHISPER_MODEL_SIZE = _stt_config.get('model_size', 'base')
PORT = _stt_config.get('port', 5001)
LANGUE = _stt_config.get('language', 'fr')
DUREE_MAX_SECONDES = _stt_config.get('max_record_seconds', 8)
SEUIL_SILENCE = _stt_config.get('silence_threshold', 0.01)
MAX_FRAMES_SILENCE = _stt_config.get('max_silence_frames', 4)

_whisper_model = None
_whisper_lock = threading.Lock()
_whisper_echec_definitif = False  # ImportError : inutile de retenter à chaque appel.


def _init_whisper():
    """Charge faster-whisper une seule fois. Thread-safe (le serveur est threadé)."""
    global _whisper_model, _whisper_echec_definitif
    if _whisper_model is not None or _whisper_echec_definitif:
        return _whisper_model

    with _whisper_lock:
        if _whisper_model is not None or _whisper_echec_definitif:
            return _whisper_model
        try:
            from faster_whisper import WhisperModel
            print(f"[STT] Chargement du modèle Whisper '{WHISPER_MODEL_SIZE}' (langue: {LANGUE})...")
            _whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type="int8"
            )
            print("[STT] ✓ Modèle Whisper chargé avec succès")
        except ImportError:
            # Cas attendu sur Python >= 3.14 (voir requirements.txt) : pas la peine de
            # retenter à chaque requête, ça ne changera pas tant que l'environnement
            # n'aura pas été recréé avec la bonne version de Python.
            print("[STT] Avertissement: faster-whisper non installé (Python >= 3.14 ?). "
                  "Mode vocal indisponible tant que l'environnement n'est pas recréé en 3.11/3.12.")
            _whisper_echec_definitif = True
        except Exception as e:
            # Erreur potentiellement transitoire (ex: modèle en cours de téléchargement,
            # disque plein) : on retentera au prochain appel.
            print(f"[STT] Erreur chargement Whisper : {e}")
    return _whisper_model


def ecouter(duree_max_secondes=None) -> tuple:
    """
    Enregistre et transcrit une phrase.
    Retourne (texte, raison) — raison ∈ {'ok', 'silence', 'modele_indisponible', 'erreur_micro'}
    afin que l'appelant distingue "personne n'a parlé" (normal, à réessayer sans
    pénalité) d'une vraie panne (micro absent/occupé, modèle manquant).
    """
    duree_max_secondes = duree_max_secondes or DUREE_MAX_SECONDES
    model = _init_whisper()
    if model is None:
        return "", "modele_indisponible"

    file_audio = queue.Queue()

    def callback(indata, frames, time_info, status):
        file_audio.put(indata.copy())

    print("\n[🎙️ Alyx t'écoute... Parle maintenant]")
    try:
        with sd.InputStream(
            samplerate=SAMPLE_RATE, blocksize=8000, dtype='float32', channels=1, callback=callback
        ):
            frames_enregistrees = []
            frames_lus = 0
            max_frames = int((duree_max_secondes * SAMPLE_RATE) / 8000)
            silence_consecutif = 0
            a_parle = False

            while frames_lus < max_frames:
                data = file_audio.get()
                frames_enregistrees.append(data)
                frames_lus += 1

                volume = np.abs(data).mean()
                if volume >= SEUIL_SILENCE:
                    a_parle = True
                    silence_consecutif = 0
                else:
                    silence_consecutif += 1

                if a_parle and silence_consecutif >= MAX_FRAMES_SILENCE:
                    break

        if not frames_enregistrees or not a_parle:
            return "", "silence"

        audio_data = np.concatenate(frames_enregistrees, axis=0)
        audio_int16 = (audio_data * 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            with wave.open(tmp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_int16.tobytes())

        try:
            segments, info = model.transcribe(
                tmp_path, language=LANGUE, beam_size=5, vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200)
            )
            texte_final = " ".join(seg.text.strip() for seg in segments).strip()
        finally:
            os.unlink(tmp_path)

    except Exception as e:
        print(f"[STT] Erreur micro : {e}")
        return "", "erreur_micro"

    return (texte_final, "ok") if texte_final else ("", "silence")


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Serveur threadé : /health doit pouvoir répondre pendant qu'un /listen
    (jusqu'à quelques secondes) est en cours, sinon l'UI ne peut plus savoir si le
    service est vivant ou figé — une des causes de "mode vocal qui semble mort"."""
    daemon_threads = True


class STTHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            pret = _whisper_model is not None
            self.wfile.write(json.dumps({"status": "ok", "modele_charge": pret}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/listen':
            texte, raison = ecouter()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"text": texte, "reason": raison}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Disable default logging to keep terminal clean
        pass


if __name__ == '__main__':
    # Initial load of model on startup
    threading.Thread(target=_init_whisper, daemon=True).start()

    server = ThreadingHTTPServer(('127.0.0.1', PORT), STTHandler)
    print(f"[STT] Serveur démarré sur http://127.0.0.1:{PORT} (langue: {LANGUE})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
