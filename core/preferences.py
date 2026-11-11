"""Préférences utilisateur du moteur (voix, langue), persistées dans %APPDATA%/Alyx/preferences.json."""
import json
import locale
import os
import sys
import threading

from core.logger import get_logger

logger = get_logger('alyx.preferences')

# Voix vocales stables prises en charge (STT Whisper & TTS)
LANGUES_VOIX_STABLES = {'fr', 'en'}

# Langues de réponse proposées : libellé, consigne ajoutée au prompt système, phrase de test de la voix
LANGUES = {
    'fr': ('Français', "Réponds toujours en français.", "Bonjour, je suis Alyx. Voici ma voix."),
    'en': ('English', "Always answer in English.", "Hello, I am Alyx. This is my voice."),
    'es': ('Español', "Responde siempre en español.", "Hola, soy Alyx. Hola, soy Alyx. Esta es mi voz."),
    'de': ('Deutsch', "Antworte immer auf Deutsch.", "Hallo, ich bin Alyx. Das ist meine Stimme."),
}


def _detecter_langue_os() -> str:
    """Détecte la langue de l'interface du système d'exploitation ('fr', 'en', 'es', 'de'), repli sur 'fr'."""
    if sys.platform == 'win32':
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            code_win = locale.windows_locale.get(lang_id, '')[:2].lower()
            if code_win in LANGUES:
                return code_win
            primaire = {0x0C: 'fr', 0x09: 'en', 0x0A: 'es', 0x07: 'de'}.get(lang_id & 0xFF)
            if primaire in LANGUES:
                return primaire
        except Exception:
            pass

    for var in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        val = (os.environ.get(var) or '').strip()
        if val and val.upper() not in ('C', 'POSIX') and not val.upper().startswith('C.'):
            code_env = val.split('.')[0].split('_')[0].split('-')[0].lower()
            if code_env in LANGUES:
                return code_env

    try:
        loc = (locale.getlocale()[0] or '').lower()
        if loc:
            for prefixe, code in (('french', 'fr'), ('english', 'en'), ('spanish', 'es'), ('german', 'de')):
                if loc.startswith(prefixe):
                    return code
            code_loc = loc.split('_')[0].split('-')[0]
            if code_loc in LANGUES:
                return code_loc
    except Exception:
        pass

    return 'fr'


_DEFAUTS = {
    'voice_id': None,    # None = première voix correspondant à la langue
    'rate': 0,           # -10 (lent) … 10 (rapide)
    'volume': 100,       # 0 … 100
    'speak_all': False,  # lire toutes les réponses, pas seulement en mode vocal
    'language': _detecter_langue_os(),
    'model': None,       # dernier modèle choisi (restauré au démarrage)
    'microphone': None,  # nom du micro ; None = micro par défaut du système
}

_lock = threading.Lock()
_cache = None


def _chemin():
    base = os.environ.get('APPDATA') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, 'Alyx', 'preferences.json')


def _valider(prefs: dict) -> dict:
    propre = dict(_DEFAUTS)
    try:
        propre['rate'] = max(-10, min(10, int(prefs.get('rate', 0))))
        propre['volume'] = max(0, min(100, int(prefs.get('volume', 100))))
    except (TypeError, ValueError):
        pass
    propre['speak_all'] = bool(prefs.get('speak_all', False))
    langue = prefs.get('language', _DEFAUTS['language'])
    propre['language'] = langue if langue in LANGUES else 'fr'
    modele = prefs.get('model')
    propre['model'] = modele if isinstance(modele, str) and modele else None
    micro = prefs.get('microphone')
    propre['microphone'] = micro if isinstance(micro, str) and micro else None
    voix = prefs.get('voice_id')
    propre['voice_id'] = voix if isinstance(voix, str) and voix else None
    return propre


def charger() -> dict:
    """Préférences courantes (copie), lues une seule fois sur disque."""
    global _cache
    with _lock:
        if _cache is None:
            try:
                with open(_chemin(), 'r', encoding='utf-8') as f:
                    _cache = _valider(json.load(f))
            except (OSError, ValueError):
                _cache = dict(_DEFAUTS)
        return dict(_cache)


def mettre_a_jour(changements: dict) -> dict:
    """Fusionne les changements, valide, enregistre et renvoie les préférences complètes."""
    global _cache
    actuelles = charger()
    actuelles.update({k: v for k, v in changements.items() if k in _DEFAUTS})
    nouvelles = _valider(actuelles)
    with _lock:
        _cache = nouvelles
        try:
            os.makedirs(os.path.dirname(_chemin()), exist_ok=True)
            with open(_chemin(), 'w', encoding='utf-8') as f:
                json.dump(nouvelles, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.error(f"Préférences non enregistrées: {e}")
    return dict(nouvelles)


def consigne_langue(code: str) -> str:
    return LANGUES.get(code, LANGUES['fr'])[1]


def phrase_test(code: str) -> str:
    return LANGUES.get(code, LANGUES['fr'])[2]


def langues() -> list:
    return [{'code': code, 'label': v[0]} for code, v in LANGUES.items()]


try:
    import yaml
except ImportError:
    yaml = None

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')
_config_cache = (0.0, {})
_config_lock = threading.Lock()


def charger_config() -> dict:
    """Charge le fichier unique de configuration config.yaml (conformité B.4.1) avec cache mtime et thread-safety."""
    global _config_cache
    if not yaml:
        return dict(_config_cache[1]) if _config_cache[1] else {}
    with _config_lock:
        if os.path.exists(CONFIG_PATH):
            try:
                mtime = os.path.getmtime(CONFIG_PATH)
                if mtime == _config_cache[0] and _config_cache[1]:
                    return dict(_config_cache[1])
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                _config_cache = (mtime, data)
                return dict(data)
            except Exception as e:
                logger.warning(f"Erreur lecture config.yaml : {e}")
        return dict(_config_cache[1]) if _config_cache[1] else {}


def get_context_config() -> dict:
    """Retourne les paramètres de contexte/historique avec valeurs par défaut défensives (B.4.1)."""
    cfg = charger_config().get('context', {})
    return {
        'nb_tours_recents_verbatim': int(cfg.get('nb_tours_recents_verbatim', 2)),
        'retention_jours': int(cfg.get('retention_jours', 90)),
    }


def get_tools_config() -> dict:
    """Retourne les paramètres des outils avec valeurs par défaut défensives (B.4.1)."""
    cfg = charger_config().get('tools', {})
    return {
        'budget_max_outils': int(cfg.get('budget_max_outils', 1000)),
        'max_outils_routage': int(cfg.get('max_outils_routage', 6)),
        'max_entrees_liste': int(cfg.get('max_entrees_liste', 50)),
        'taille_max_lecture': int(cfg.get('taille_max_lecture', 8192)),
    }


def get_stt_config() -> dict:
    """Retourne les paramètres STT avec valeurs par défaut défensives (B.4.1)."""
    cfg = charger_config()
    stt_cfg = cfg.get('stt', {})
    server_cfg = cfg.get('server', {})
    return {
        'port': int(server_cfg.get('stt_port', stt_cfg.get('port', 5001))),
        'min_disk_free_gb': float(server_cfg.get('min_disk_free_gb', stt_cfg.get('min_disk_free_gb', 1.0))),
        'sample_rate': int(stt_cfg.get('sample_rate', 16000)),
        'model_size': str(stt_cfg.get('model_size', 'base')),
        'seuil_muet': float(stt_cfg.get('seuil_muet', 0.0005)),
    }

