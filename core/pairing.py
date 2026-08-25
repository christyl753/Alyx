"""Jumelage mobile : jeton partagé + détection de l'IP locale.

Principe de sécurité : api.py n'écoutait jusqu'ici que sur 'localhost' (aucun accès
extérieur possible). L'ouvrir au réseau Wi-Fi local pour l'app mobile introduit une
vraie surface d'attaque — n'importe quel appareil du même Wi-Fi pourrait sinon parler
au backend. Le jeton ci-dessous est donc obligatoire pour toute connexion qui n'arrive
PAS depuis la machine elle-même (127.0.0.1/::1) ; voir api.py:_verifier_origine_connexion.

Rien ne quitte le réseau local : cette isolation est ce qui permet à l'app mobile
d'exister sans trahir le principe "air-gapped" du projet (README).
"""
import os
import psutil
import secrets

from core.logger import get_logger

logger = get_logger('alyx.pairing')

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, 'data')
_TOKEN_PATH = os.path.join(_DATA_DIR, 'pairing_token.txt')

# Longueur choisie pour rester saisissable à la main sur un téléphone si besoin
# (dernier recours si l'IP change), tout en étant impossible à deviner par force brute
# sur un Wi-Fi partagé (32 caractères hex = 128 bits d'entropie).
_LONGUEUR_TOKEN = 32


def obtenir_token() -> str:
    """Charge le jeton de jumelage, ou en génère un nouveau au premier lancement."""
    if os.path.exists(_TOKEN_PATH):
        try:
            with open(_TOKEN_PATH, 'r', encoding='utf-8') as f:
                token = f.read().strip()
            if token:
                return token
        except OSError as e:
            logger.warning(f"Jeton de jumelage illisible ({e}), regénération.")
    return regenerer_token()


def regenerer_token() -> str:
    """Génère un nouveau jeton et invalide immédiatement l'ancien (déconnecte les
    téléphones déjà jumelés — utile si le jeton a fuité ou en cas de doute)."""
    token = secrets.token_hex(_LONGUEUR_TOKEN // 2)
    os.makedirs(_DATA_DIR, exist_ok=True)
    chemin_temp = _TOKEN_PATH + '.tmp'
    with open(chemin_temp, 'w', encoding='utf-8') as f:
        f.write(token)
    os.replace(chemin_temp, _TOKEN_PATH)
    logger.info("Nouveau jeton de jumelage mobile généré.")
    return token


def obtenir_ip_locale() -> str | None:
    """Meilleure estimation de l'IP locale (Wi-Fi/Ethernet) joignable depuis le même
    réseau. Ne fait AUCUNE requête réseau (pas d'appel à un serveur externe) : lecture
    pure des interfaces locales via psutil, cohérent avec le principe air-gapped."""
    try:
        interfaces = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
    except Exception as e:
        logger.warning(f"Impossible de lister les interfaces réseau : {e}")
        return None

    prefixes_ignores = ('lo', 'docker', 'veth', 'br-', 'virbr', 'vmnet')
    candidates = []
    for nom, adresses in interfaces.items():
        if nom.lower().startswith(prefixes_ignores):
            continue
        if nom not in stats or not stats[nom].isup:
            continue
        for addr in adresses:
            # AF_INET = 2 (on évite d'importer socket.AF_INET juste pour ça ici,
            # psutil retourne déjà des AddressFamily comparables)
            if addr.family.name == 'AF_INET' and not addr.address.startswith('127.'):
                candidates.append(addr.address)

    if not candidates:
        return None
    # Wi-Fi/Ethernet classiques (192.168.x.x, 10.x.x.x) avant tout le reste.
    candidates.sort(key=lambda ip: 0 if ip.startswith(('192.168.', '10.', '172.')) else 1)
    return candidates[0]
