import os
import json
import queue
import tempfile
import wave
import numpy as np
import pyttsx3
import sounddevice as sd
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- CONFIGURATION ---
SAMPLE_RATE = 16000
WHISPER_MODEL_SIZE = "base"
PORT = 5001

_whisper_model = None

def _init_whisper():
    global _whisper_model
    if _whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            print(f"[STT] Chargement du modèle Whisper '{WHISPER_MODEL_SIZE}'...")
            _whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device="cpu",
                compute_type="int8"
            )
            print(f"[STT] ✓ Modèle Whisper chargé avec succès")
        except ImportError:
            print("[STT] Avertissement: faster-whisper non installé.")
        except Exception as e:
            print(f"[STT] Erreur chargement Whisper: {e}")
    return _whisper_model

def ecouter(duree_max_secondes=8):
    model = _init_whisper()
    if model is None:
        return ""

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
            seuil_silence = 0.01
            max_silence_frames = 4
            a_parle = False

            while frames_lus < max_frames:
                data = file_audio.get()
                frames_enregistrees.append(data)
                frames_lus += 1

                volume = np.abs(data).mean()
                if volume >= seuil_silence:
                    a_parle = True
                    silence_consecutif = 0
                else:
                    silence_consecutif += 1

                if a_parle and silence_consecutif >= max_silence_frames:
                    break

        if not frames_enregistrees:
            return ""

        audio_data = np.concatenate(frames_enregistrees, axis=0)
        audio_int16 = (audio_data * 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
            with wave.open(tmp_path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(audio_int16.tobytes())

        segments, info = model.transcribe(
            tmp_path, language="fr", beam_size=5, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200)
        )
        texte_final = " ".join(seg.text.strip() for seg in segments).strip()
        os.unlink(tmp_path)
    except Exception as e:
        print(f"[STT] Erreur micro : {e}")
        return ""

    return texte_final

class STTHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/listen':
            texte = ecouter()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"text": texte}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            
    def log_message(self, format, *args):
        # Disable default logging to keep terminal clean
        pass

if __name__ == '__main__':
    # Initial load of model on startup
    threading.Thread(target=_init_whisper, daemon=True).start()
    
    server = HTTPServer(('127.0.0.1', PORT), STTHandler)
    print(f"[STT] Serveur démarré sur http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
