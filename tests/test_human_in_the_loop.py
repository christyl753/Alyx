"""Validation Human-in-the-Loop (action_required / permission_granted / permission_denied).

Régression pour un bug découvert en testant le compagnon mobile : action_required
plantait la connexion entière (tool_call ollama non JSON-sérialisable) et, même
corrigé, rien ne traitait jamais permission_granted/permission_denied — la fonction
protégée était réexécutée à l'identique et redemandait indéfiniment la permission,
sans jamais s'exécuter pour de vrai.
"""
import asyncio
import json
import pytest

import api
from core.exceptions import PermissionRequiredException, permission_deja_accordee
from function.files import _demander_permission


class FakeToolCall:
    """Simule ollama._types.Message.ToolCall : accès dict-like mais PAS un dict,
    et non JSON-sérialisable tel quel (c'est exactement ce qui cassait avant)."""
    def __init__(self, data):
        self._data = data

    def __getitem__(self, key):
        return self._data[key]

    def get(self, key, default=None):
        return self._data.get(key, default)

    def model_dump(self):
        return json.loads(json.dumps(self._data, default=lambda o: dict(o)))


def test_demander_permission_leve_par_defaut():
    with pytest.raises(PermissionRequiredException):
        _demander_permission("SUPPRIMER un fichier", "/tmp/x")


def test_demander_permission_passe_si_deja_accordee():
    token = permission_deja_accordee.set(True)
    try:
        assert _demander_permission("SUPPRIMER un fichier", "/tmp/x") is True
    finally:
        permission_deja_accordee.reset(token)


def test_permission_deja_accordee_ne_fuit_pas_entre_appels():
    """La bascule ne doit jamais rester active après coup : un appel normal suivant
    doit à nouveau lever, sinon TOUTE action deviendrait silencieusement non protégée."""
    assert permission_deja_accordee.get() is False
    with pytest.raises(PermissionRequiredException):
        _demander_permission("SUPPRIMER un fichier", "/tmp/x")


def test_tool_call_vers_dict_gere_un_objet_non_serialisable():
    """Le coeur du bug : json.dumps() plantait directement sur un ToolCall pydantic."""
    fake = FakeToolCall({'id': 'abc', 'function': {'name': 'supprimer_fichier', 'arguments': {'chemin': '~/x'}}})
    with pytest.raises(TypeError):
        json.dumps(fake)  # confirme que le cas de test est bien représentatif du bug

    resultat = api._tool_call_vers_dict(fake)
    assert json.dumps(resultat)  # ne lève plus
    assert resultat['function']['name'] == 'supprimer_fichier'


def test_tool_call_vers_dict_gere_un_dict_deja_plat():
    """Fournisseurs LM Studio/NVIDIA : tool_call est déjà un dict simple."""
    plat = {'id': 'x', 'function': {'name': 'creer_fichier', 'arguments': {'chemin': '~/x'}}}
    assert api._tool_call_vers_dict(plat) == plat


def test_reprendre_apres_permission_refusee_n_execute_rien(monkeypatch):
    appels = []
    monkeypatch.setitem(api.outils_disponibles, 'supprimer_fichier', lambda **kw: appels.append(kw) or "ne devrait pas s'exécuter")
    api.messages[:] = [{'role': 'system', 'content': 'sys'}]
    monkeypatch.setattr(api.ai, 'MODEL', 'Aucun modèle')  # court-circuite avant le vrai appel LLM

    class FakeWS:
        async def send(self, msg):
            pass

    tool_call = {'id': '1', 'function': {'name': 'supprimer_fichier', 'arguments': {'chemin': '~/x'}}}
    asyncio.run(api._reprendre_apres_permission(FakeWS(), tool_call, autorise=False))

    assert appels == []  # l'outil protégé n'a jamais été appelé
    dernier_message = api.messages[-1]
    assert dernier_message['role'] == 'tool'
    assert 'refusée' in dernier_message['content']


def test_reprendre_apres_permission_accordee_execute_avec_bypass(monkeypatch):
    """Vérifie que l'outil reçoit bien permission_deja_accordee=True pendant son
    exécution (sinon il relèverait PermissionRequiredException une seconde fois)."""
    etats_observes = []

    def outil_protege(**kwargs):
        etats_observes.append(permission_deja_accordee.get())
        return "fait"

    monkeypatch.setitem(api.outils_disponibles, 'supprimer_fichier', outil_protege)
    api.messages[:] = [{'role': 'system', 'content': 'sys'}]
    monkeypatch.setattr(api.ai, 'MODEL', 'Aucun modèle')

    class FakeWS:
        async def send(self, msg):
            pass

    tool_call = {'id': '1', 'function': {'name': 'supprimer_fichier', 'arguments': {'chemin': '~/x'}}}
    asyncio.run(api._reprendre_apres_permission(FakeWS(), tool_call, autorise=True))

    assert etats_observes == [True]
    assert permission_deja_accordee.get() is False  # remis à False après coup
    dernier_message = api.messages[-1]
    assert dernier_message['content'] == 'fait'
