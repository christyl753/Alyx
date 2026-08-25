"""Sert les fichiers statiques du compagnon mobile (PWA) sur le réseau Wi-Fi local.

Processus séparé, à l'image de stt_server.py : isole un composant simple (fichiers
statiques) du cœur de l'application (api.py, qui gère lui-même l'authentification par
jeton pour le trafic WebSocket réel). Ce serveur-ci ne sert que du HTML/CSS/JS/JSON
public — aucune donnée utilisateur, aucun besoin de jeton pour charger la page elle-
même (le jeton n'intervient qu'au moment de la connexion WebSocket vers api.py,
saisi une fois par l'utilisateur dans l'écran de jumelage de la page).
"""
import os
import sys
from http.server import SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn
from http.server import HTTPServer

import yaml

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_MOBILE_DIR = os.path.join(_PROJECT_ROOT, 'mobile')
_CONFIG_PATH = os.path.join(_PROJECT_ROOT, 'config.yaml')


def _load_config():
    if os.path.exists(_CONFIG_PATH):
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}


_config = _load_config()
_server_config = _config.get('server', {})
PORT = _server_config.get('mobile_port', 8766)
ALLOW_LAN = _server_config.get('allow_lan', True)
BIND_ADDRESS = "0.0.0.0" if ALLOW_LAN else "localhost"


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class MobileHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=_MOBILE_DIR, **kwargs)

    def log_message(self, format, *args):
        pass  # terminal propre, cohérent avec stt_server.py

    def end_headers(self):
        # La page (et le service worker) doivent pouvoir être rechargés sans
        # dépendre du cache HTTP du navigateur : c'est une petite app locale sur un
        # réseau de confiance, pas un site à optimiser pour la bande passante.
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()


if __name__ == '__main__':
    if not os.path.isdir(_MOBILE_DIR):
        print(f"[Mobile] Dossier '{_MOBILE_DIR}' introuvable, arrêt.")
        sys.exit(1)

    server = ThreadingHTTPServer((BIND_ADDRESS, PORT), MobileHandler)
    print(f"[Mobile] Compagnon mobile servi sur http://{BIND_ADDRESS}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()
