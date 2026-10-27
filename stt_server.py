import os
import sys
import json
import queue
import numpy as np
import sounddevice as sd
import threading
import yaml
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

# stdout peut être redirigé vers un fichier en cp1252 (Windows) : éviter les UnicodeEncodeError
for _flux in (sys.stdout, sys.stderr):
    try:
        _flux.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass

def _charger_port():
    chemin = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.yaml')
    try:
        with open(chemin, 'r', encoding='utf-8') as f:
            return (yaml.safe_load(f) or {}).get('server', {}).get('stt_port', 5001)
    except OSError:
        return 5001

# --- CONFIGURATION ---
SAMPLE_RATE = 16000
WHISPER_MODEL_SIZE = "base"
PORT = _charger_port()
LANGUES_WHISPER = {'fr', 'en', 'es', 'de'}
SEUIL_MUET = 0.0005  # crête max en dessous de laquelle le micro est considéré coupé

_whisper_model = None
_whisper_erreur = None
_whisper_lock = threading.Lock()
# Un seul micro : une seule écoute à la fois
_ecoute_lock = threading.Lock()
_portaudio_lock = threading.Lock()

def _init_whisper():
    global _whisper_model, _whisper_erreur
    with _whisper_lock:
        if _whisper_model is None:
            try:
                from faster_whisper import WhisperModel
                print(f"[STT] Chargement du modèle Whisper '{WHISPER_MODEL_SIZE}'...")
                _whisper_model = WhisperModel(
                    WHISPER_MODEL_SIZE,
                    device="cpu",
                    compute_type="int8"
                )
                _whisper_erreur = None
                print(f"[STT] ✓ Modèle Whisper chargé avec succès")
            except ImportError:
                _whisper_erreur = "faster-whisper n'est pas installé"
                print("[STT] Avertissement: faster-whisper non installé.")
            except Exception as e:
                _whisper_erreur = str(e)
                print(f"[STT] Erreur chargement Whisper: {e}")
    return _whisper_model


# --- MICROS ---
def _api_micros():
    """API audio dont on expose les micros : WASAPI sous Windows (noms complets), sinon celle par défaut."""
    for i, api in enumerate(sd.query_hostapis()):
        if api['name'] == 'Windows WASAPI':
            return i, api
    i = sd.default.hostapi
    return i, sd.query_hostapis(i)

def lister_micros(rafraichir=True):
    """Micros disponibles ; rafraîchit PortAudio pour voir les périphériques branchés depuis le démarrage."""
    with _portaudio_lock:
        if rafraichir:
            try:
                sd._terminate()
                sd._initialize()
            except Exception as e:
                print(f"[STT] Rafraîchissement audio impossible: {e}")
        idx_api, api = _api_micros()
        defaut = api.get('default_input_device', -1)
        micros = []
        for i, d in enumerate(sd.query_devices()):
            if d['hostapi'] == idx_api and d['max_input_channels'] > 0:
                micros.append({'index': i, 'name': d['name'], 'default': i == defaut})
        return micros

def _resoudre_micro(nom):
    """Index du micro demandé (par nom), sinon du micro par défaut."""
    micros = lister_micros(rafraichir=True)
    choisi = next((m for m in micros if nom and m['name'] == nom), None)
    if choisi is None:
        choisi = next((m for m in micros if m['default']), None) or (micros[0] if micros else None)
    return choisi

def _enregistrer(micro, duree_max_secondes, arret_sur_silence=True):
    """Enregistre en mono à la fréquence native du micro ; renvoie (audio 16 kHz float32, crête)."""
    info = sd.query_devices(micro['index'])
    taux = int(info['default_samplerate']) or SAMPLE_RATE
    canaux = max(1, min(2, int(info['max_input_channels'])))
    bloc = taux // 2  # 0,5 s
    file_audio = queue.Queue()

    def callback(indata, frames, time_info, status):
        file_audio.put(indata.mean(axis=1).copy())

    blocs, crete = [], 0.0
    with sd.InputStream(device=micro['index'], samplerate=taux, blocksize=bloc,
                        dtype='float32', channels=canaux, callback=callback):
        max_blocs = int(duree_max_secondes * 2)
        silence_consecutif, a_parle, plancher = 0, False, None
        while len(blocs) < max_blocs:
            try:
                data = file_audio.get(timeout=2)
            except queue.Empty:
                break  # le périphérique audio ne délivre plus rien
            blocs.append(data)
            volume = float(np.abs(data).mean())
            crete = max(crete, float(np.abs(data).max()))
            # Seuil de parole adaptatif : au-dessus du bruit de fond mesuré
            plancher = volume if plancher is None else min(plancher, volume)
            if volume >= max(0.003, plancher * 4):
                a_parle, silence_consecutif = True, 0
            else:
                silence_consecutif += 1
            if arret_sur_silence and a_parle and silence_consecutif >= 3:  # ~1,5 s de silence
                break

    if not blocs:
        return np.zeros(0, dtype=np.float32), 0.0
    audio = np.concatenate(blocs)
    if taux != SAMPLE_RATE:
        n = int(len(audio) * SAMPLE_RATE / taux)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
    return audio, crete

def ecouter(micro_nom=None, langue='fr', duree_max_secondes=8):
    """Renvoie {'text', 'error', 'device'} ; error ∈ {'', 'modele', 'aucun_micro', 'micro', 'muet'}."""
    model = _init_whisper()
    if model is None:
        return {'text': '', 'error': 'modele', 'detail': _whisper_erreur or '', 'device': ''}
    micro = _resoudre_micro(micro_nom)
    if micro is None:
        return {'text': '', 'error': 'aucun_micro', 'device': ''}

    print(f"\n[🎙️ Alyx t'écoute sur « {micro['name']} »...]")
    try:
        audio, crete = _enregistrer(micro, duree_max_secondes)
    except Exception as e:
        print(f"[STT] Erreur micro : {e}")
        return {'text': '', 'error': 'micro', 'detail': str(e), 'device': micro['name']}
    if crete < SEUIL_MUET:
        return {'text': '', 'error': 'muet', 'device': micro['name']}

    try:
        segments, info = model.transcribe(
            audio, language=langue if langue in LANGUES_WHISPER else None, beam_size=5, vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=200)
        )
        texte_final = " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as e:
        print(f"[STT] Erreur transcription : {e}")
        return {'text': '', 'error': 'modele', 'detail': str(e), 'device': micro['name']}
    print(f"[🎙️ Entendu : \"{texte_final}\"]")
    return {'text': texte_final, 'error': '', 'device': micro['name']}

def tester_micro(micro_nom=None, duree=2):
    """Mesure le niveau capté pendant `duree` secondes (crête 0..1)."""
    micro = _resoudre_micro(micro_nom)
    if micro is None:
        return {'level': 0.0, 'error': 'aucun_micro', 'device': ''}
    try:
        _, crete = _enregistrer(micro, duree, arret_sur_silence=False)
    except Exception as e:
        return {'level': 0.0, 'error': 'micro', 'detail': str(e), 'device': micro['name']}
    return {'level': round(crete, 5), 'error': 'muet' if crete < SEUIL_MUET else '', 'device': micro['name']}


class STTHandler(BaseHTTPRequestHandler):
    def _envoyer_json(self, code, payload):
        corps = json.dumps(payload).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.send_header('Content-Length', str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _requete_navigateur(self):
        # Les navigateurs envoient toujours Origin sur un POST cross-site : on refuse (anti-CSRF micro)
        return self.headers.get('Origin') is not None

    def _corps_json(self):
        try:
            longueur = min(int(self.headers.get('Content-Length') or 0), 4096)
            return json.loads(self.rfile.read(longueur) or b'{}') if longueur else {}
        except (ValueError, OSError):
            return {}

    def do_GET(self):
        if self.path == '/health':
            self._envoyer_json(200, {"status": "ok", "model_ready": _whisper_model is not None,
                                     "model_error": _whisper_erreur or ""})
        elif self.path == '/devices':
            if self._requete_navigateur():
                self._envoyer_json(403, {"error": "forbidden"})
                return
            # Pendant une écoute, PortAudio ne doit pas être réinitialisé
            rafraichir = _ecoute_lock.acquire(blocking=False)
            try:
                micros = lister_micros(rafraichir=rafraichir)
            finally:
                if rafraichir:
                    _ecoute_lock.release()
            self._envoyer_json(200, {"devices": [{'name': m['name'], 'default': m['default']} for m in micros]})
        else:
            self._envoyer_json(404, {"error": "not found"})

    def do_POST(self):
        if self._requete_navigateur():
            self._envoyer_json(403, {"error": "forbidden"})
            return
        if self.path in ('/listen', '/test'):
            corps = self._corps_json()
            micro = corps.get('device') if isinstance(corps.get('device'), str) else None
            if not _ecoute_lock.acquire(blocking=False):
                self._envoyer_json(409, {"text": "", "error": "occupe"})
                return
            try:
                if self.path == '/listen':
                    resultat = ecouter(micro, str(corps.get('language') or 'fr'))
                else:
                    resultat = tester_micro(micro)
            finally:
                _ecoute_lock.release()
            self._envoyer_json(200, resultat)
        else:
            self._envoyer_json(404, {"error": "not found"})

    def log_message(self, format, *args):
        # Disable default logging to keep terminal clean
        pass

if __name__ == '__main__':
    # Initial load of model on startup
    threading.Thread(target=_init_whisper, daemon=True).start()

    server = ThreadingHTTPServer(('127.0.0.1', PORT), STTHandler)
    server.daemon_threads = True
    print(f"[STT] Serveur démarré sur http://127.0.0.1:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
