"""Préférences utilisateur du moteur (voix, langue), persistées dans %APPDATA%/Alyx/preferences.json."""
import json
import os
import threading

from core.logger import get_logger

logger = get_logger('alyx.preferences')

# Langues de réponse proposées : libellé, consigne ajoutée au prompt système, phrase de test de la voix
LANGUES = {
    'fr': ('Français', "Réponds toujours en français.", "Bonjour, je suis Alyx. Voici ma voix."),
    'en': ('English', "Always answer in English.", "Hello, I am Alyx. This is my voice."),
    'es': ('Español', "Responde siempre en español.", "Hola, soy Alyx. Esta es mi voz."),
    'de': ('Deutsch', "Antworte immer auf Deutsch.", "Hallo, ich bin Alyx. Das ist meine Stimme."),
}

_DEFAUTS = {
    'voice_id': None,    # None = première voix correspondant à la langue
    'rate': 0,           # -10 (lent) … 10 (rapide)
    'volume': 100,       # 0 … 100
    'speak_all': False,  # lire toutes les réponses, pas seulement en mode vocal
    'language': 'fr',
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
    langue = prefs.get('language', 'fr')
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
