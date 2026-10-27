# Fichier : function/tts.py
"""Synthèse vocale d'Alyx avec choix de la voix.

Windows : SAPI via comtypes, avec les voix « classiques » ET les voix Windows (OneCore : celles installées
depuis Paramètres > Heure et langue > Voix), que pyttsx3 ne voit pas. Linux : pyttsx3 (espeak).
Toutes les opérations passent par un thread unique (les moteurs ne sont pas thread-safe).
"""
import concurrent.futures
import locale
import queue
import re
import sys
import threading

from core.logger import get_logger

logger = get_logger('alyx.tts')

_CATEGORIES_SAPI = (
    (r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech_OneCore\Voices", "Windows"),
    (r"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Speech\Voices", "SAPI 5"),
)

_file = queue.Queue()
_disponible = threading.Event()
# Le kill switch incrémente la génération : les phrases plus anciennes sont abandonnées
_generation = 0
_generation_lock = threading.Lock()


# ---------- Nettoyage du texte avant lecture ----------
_RE_CODE = re.compile(r"```.*?(```|$)", re.S)
_RE_LIEN = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_RE_FRAC = re.compile(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}")
_RE_COMMANDE = re.compile(r"\\([A-Za-z]+)")
_SYMBOLES = {'times': ' fois ', 'cdot': ' fois ', 'leq': ' inférieur ou égal à ', 'geq': ' supérieur ou égal à ',
             'neq': ' différent de ', 'approx': ' environ ', 'pi': ' pi ', 'alpha': ' alpha ', 'beta': ' bêta ',
             'Delta': ' delta ', 'delta': ' delta ', 'omega': ' oméga ', 'Omega': ' oméga ', 'mu': ' mu ',
             'lambda': ' lambda ', 'theta': ' thêta ', 'sigma': ' sigma ', 'infty': ' infini ', 'sqrt': ' racine de '}


def nettoyer_pour_voix(texte: str) -> str:
    """Retire la syntaxe Markdown / LaTeX pour que la voix ne lise pas « dièse » ou « backslash »."""
    t = _RE_CODE.sub(" ", texte)
    t = _RE_LIEN.sub(r"\1", t)
    t = _RE_FRAC.sub(r"\1 sur \2", t)
    t = _RE_COMMANDE.sub(lambda m: _SYMBOLES.get(m.group(1), " "), t)
    t = re.sub(r"\^\{?2\}?", " au carré", t)
    t = re.sub(r"[#*_`$|{}\\~>]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------- Voix disponibles ----------
def _libelle_langue(code_hex: str) -> str:
    """'40C' (LCID SAPI) → 'fr-FR'."""
    try:
        lcid = int(code_hex.split(';')[0], 16)
        nom = locale.windows_locale.get(lcid, '')
        return nom.replace('_', '-')
    except ValueError:
        return ''


def _decrire(description: str):
    """'Microsoft Zira Desktop - English (United States)' → ('Zira', 'English (United States)')."""
    nom, _, langue = description.partition(' - ')
    nom = nom.replace('Microsoft ', '').replace(' Desktop', '').strip()
    return nom or description, langue.strip()


def _voix_sapi():
    import comtypes.client
    voix = []
    for categorie, moteur in _CATEGORIES_SAPI:
        try:
            cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
            cat.SetId(categorie, False)
            jetons = cat.EnumerateTokens()
        except Exception:
            continue
        for i in range(jetons.Count):
            jeton = jetons.Item(i)
            nom, langue = _decrire(jeton.GetDescription())
            try:
                code = _libelle_langue(jeton.GetAttribute("Language"))
            except Exception:
                code = ''
            voix.append(({'id': jeton.Id, 'name': nom, 'lang': code, 'lang_label': langue, 'engine': moteur}, jeton))
    return voix


# ---------- Thread de synthèse ----------
def _worker_windows():
    import comtypes
    comtypes.CoInitialize()
    import comtypes.client
    sapi = comtypes.client.CreateObject("SAPI.SpVoice")
    jetons = {}

    def lister():
        jetons.clear()
        resultat = []
        for info, jeton in _voix_sapi():
            jetons[info['id']] = jeton
            resultat.append(info)
        return resultat

    lister()
    _disponible.set()
    while True:
        ordre = _file.get()
        if ordre is None:
            break
        genre = ordre[0]
        try:
            if genre == 'say':
                _, texte, gen = ordre
                if gen != _generation:
                    continue
                sapi.Speak(texte, 1)  # SVSFlagsAsync : permet l'arrêt en cours de phrase
                while not sapi.WaitUntilDone(60):
                    if gen != _generation:
                        sapi.Speak("", 3)  # SVSFlagsAsync | SVSFPurgeBeforeSpeak
                        break
            elif genre == 'config':
                reglages = ordre[1]
                if reglages.get('voice_id') in jetons:
                    sapi.Voice = jetons[reglages['voice_id']]
                sapi.Rate = int(reglages.get('rate', 0))
                sapi.Volume = int(reglages.get('volume', 100))
            elif genre == 'voices':
                ordre[1].set_result(lister())
        except Exception as e:
            logger.debug(f"TTS: {e}")
            if genre == 'voices' and not ordre[1].done():
                ordre[1].set_result([])


def _worker_pyttsx3():
    import pyttsx3
    moteur = pyttsx3.init()
    _disponible.set()
    while True:
        ordre = _file.get()
        if ordre is None:
            break
        genre = ordre[0]
        try:
            if genre == 'say':
                _, texte, gen = ordre
                if gen != _generation:
                    continue
                moteur.say(texte)
                moteur.runAndWait()
            elif genre == 'config':
                reglages = ordre[1]
                if reglages.get('voice_id'):
                    moteur.setProperty('voice', reglages['voice_id'])
                # rate -10…10 → ×(1/3…3) autour de 170 mots/min
                moteur.setProperty('rate', int(170 * 3 ** (int(reglages.get('rate', 0)) / 10)))
                moteur.setProperty('volume', int(reglages.get('volume', 100)) / 100)
            elif genre == 'voices':
                voix = []
                for v in moteur.getProperty('voices'):
                    langue = (v.languages[0] if v.languages else '')
                    if isinstance(langue, bytes):
                        langue = langue.decode(errors='ignore').strip('\x05')
                    voix.append({'id': v.id, 'name': v.name, 'lang': str(langue), 'lang_label': str(langue), 'engine': 'espeak'})
                ordre[1].set_result(voix)
        except Exception as e:
            logger.debug(f"TTS: {e}")
            if genre == 'voices' and not ordre[1].done():
                ordre[1].set_result([])


def _demarrer():
    try:
        if sys.platform == 'win32':
            _worker_windows()
        else:
            _worker_pyttsx3()
    except Exception as e:
        logger.warning(f"Synthèse vocale indisponible: {e}")


threading.Thread(target=_demarrer, daemon=True, name='AlyxTTS').start()


# ---------- API ----------
def faire_parler(texte: str) -> None:
    """Fait parler Alyx à voix haute (asynchrone)."""
    if not texte or not _disponible.wait(timeout=5):
        return
    propre = nettoyer_pour_voix(texte)
    if propre:
        _file.put(('say', propre, _generation))


def arreter_parole() -> None:
    """Coupe la phrase en cours et abandonne celles en attente (kill switch)."""
    global _generation
    with _generation_lock:
        _generation += 1


def lister_voix(timeout: float = 8) -> list:
    """Voix installées : [{'id', 'name', 'lang', 'lang_label', 'engine'}]."""
    if not _disponible.wait(timeout=timeout):
        return []
    futur = concurrent.futures.Future()
    _file.put(('voices', futur))
    try:
        return futur.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        return []


def configurer(voice_id=None, rate=0, volume=100) -> None:
    """Applique la voix, la vitesse (-10…10) et le volume (0…100)."""
    _file.put(('config', {'voice_id': voice_id, 'rate': rate, 'volume': volume}))


def voix_pour_langue(voix: list, langue: str):
    """Première voix correspondant à la langue ('fr' → fr-FR, fr-CA…), Windows (OneCore) en priorité."""
    candidates = [v for v in voix if (v.get('lang') or '').lower().startswith(langue.lower())]
    candidates.sort(key=lambda v: v.get('engine') != 'Windows')
    return candidates[0] if candidates else None
