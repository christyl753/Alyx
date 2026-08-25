"""Jumelage mobile (core/pairing.py) et porte d'entrée réseau (api._verifier_origine_connexion).

C'est la seule barrière entre "aucun accès extérieur" (comportement historique) et
"ouvert au Wi-Fi local" : chaque cas doit être vérifié explicitement.
"""
import core.pairing as pairing
import api


class FakeConnection:
    def __init__(self, ip):
        self.remote_address = (ip, 54321) if ip else None

    def respond(self, status, text):
        return ("REJECTED", status, text)


class FakeRequest:
    def __init__(self, path):
        self.path = path


def _isoler_token(tmp_path, monkeypatch):
    monkeypatch.setattr(pairing, '_TOKEN_PATH', str(tmp_path / 'pairing_token.txt'))
    monkeypatch.setattr(pairing, '_DATA_DIR', str(tmp_path))


def test_token_stable_entre_deux_lectures(tmp_path, monkeypatch):
    _isoler_token(tmp_path, monkeypatch)
    assert pairing.obtenir_token() == pairing.obtenir_token()


def test_regenerer_token_change_la_valeur(tmp_path, monkeypatch):
    _isoler_token(tmp_path, monkeypatch)
    ancien = pairing.obtenir_token()
    nouveau = pairing.regenerer_token()
    assert nouveau != ancien
    assert pairing.obtenir_token() == nouveau


def test_token_recupere_un_fichier_vide_ou_absent(tmp_path, monkeypatch):
    _isoler_token(tmp_path, monkeypatch)
    (tmp_path / 'pairing_token.txt').write_text('')
    token = pairing.obtenir_token()
    assert token  # une nouvelle valeur a été générée, jamais une chaîne vide


def test_loopback_toujours_accepte_sans_token(tmp_path, monkeypatch):
    _isoler_token(tmp_path, monkeypatch)
    monkeypatch.setattr(api, 'ALLOW_LAN', True)
    for ip in ('127.0.0.1', '::1'):
        assert api._verifier_origine_connexion(FakeConnection(ip), FakeRequest('/')) is None


def test_lan_sans_token_est_rejete(tmp_path, monkeypatch):
    _isoler_token(tmp_path, monkeypatch)
    monkeypatch.setattr(api, 'ALLOW_LAN', True)
    resultat = api._verifier_origine_connexion(FakeConnection('192.168.1.50'), FakeRequest('/'))
    assert resultat is not None


def test_lan_avec_mauvais_token_est_rejete(tmp_path, monkeypatch):
    _isoler_token(tmp_path, monkeypatch)
    monkeypatch.setattr(api, 'ALLOW_LAN', True)
    resultat = api._verifier_origine_connexion(
        FakeConnection('192.168.1.50'), FakeRequest('/?token=ceci-nest-pas-le-bon-token')
    )
    assert resultat is not None


def test_lan_avec_bon_token_est_accepte(tmp_path, monkeypatch):
    _isoler_token(tmp_path, monkeypatch)
    monkeypatch.setattr(api, 'ALLOW_LAN', True)
    token = pairing.obtenir_token()
    resultat = api._verifier_origine_connexion(
        FakeConnection('192.168.1.50'), FakeRequest(f'/?token={token}')
    )
    assert resultat is None


def test_ancien_token_ne_fonctionne_plus_apres_regeneration(tmp_path, monkeypatch):
    _isoler_token(tmp_path, monkeypatch)
    monkeypatch.setattr(api, 'ALLOW_LAN', True)
    ancien_token = pairing.obtenir_token()
    pairing.regenerer_token()
    resultat = api._verifier_origine_connexion(
        FakeConnection('192.168.1.50'), FakeRequest(f'/?token={ancien_token}')
    )
    assert resultat is not None


def test_allow_lan_false_desactive_toute_verification(tmp_path, monkeypatch):
    """Comportement historique : si l'admin repasse allow_lan à false, le serveur ne
    doit de toute façon plus écouter que sur localhost (BIND_ADDRESS) — mais même si
    une connexion LAN atteignait ce code, elle ne doit pas planter."""
    _isoler_token(tmp_path, monkeypatch)
    monkeypatch.setattr(api, 'ALLOW_LAN', False)
    resultat = api._verifier_origine_connexion(FakeConnection('192.168.1.50'), FakeRequest('/'))
    assert resultat is None
