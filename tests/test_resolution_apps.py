"""Résolution des noms d'applications : langage naturel -> nom de processus réel.

Cas de référence : « ferme nobara welcome app » doit viser le processus
« nobara-welcome ». L'ancienne implémentation faisait une égalité stricte et
échouait, alors même que l'application tournait.
"""

from function.scrap import normaliser_texte, racine, tokeniser
from function.system import _tokeniser, _candidats_pour, _correspond


def test_normaliser_supprime_les_accents():
    """L'utilisateur tape « tache », le fichier .desktop contient « tâche »."""
    assert normaliser_texte('Surveillance du Système') == 'surveillance du systeme'
    assert normaliser_texte('tâche') == 'tache'


def test_racine_rapproche_singulier_et_pluriel():
    assert racine('taches') == racine('tache')
    # Transformation appliquée des deux côtés : rester stable suffit, même si le
    # résultat n'est pas un vrai mot.
    assert racine('processus') == racine('processus')


def test_tokeniser_retire_les_mots_de_liaison():
    assert tokeniser('gestionnaire de tâches') == ['gestionnaire', 'taches']


def test_tokeniser_ignore_les_mots_vides_et_separateurs():
    assert _tokeniser('nobara welcome app') == ['nobara', 'welcome']
    assert _tokeniser('Nobara-Welcome') == ['nobara', 'welcome']
    assert _tokeniser('mon_application.desktop') == ['mon']


def test_tokeniser_conserve_les_tokens_si_tout_est_mot_vide():
    """'app' seul ne doit pas produire une liste vide (sinon aucun candidat)."""
    assert _tokeniser('app') == ['app']


def test_candidats_recomposent_le_nom_de_processus():
    """Le coeur du bug : 'nobara welcome app' doit proposer 'nobara-welcome'."""
    candidats = _candidats_pour('nobara welcome app')
    assert 'nobara-welcome' in candidats
    assert 'nobarawelcome' in candidats


def test_candidats_vides_pour_une_demande_vide():
    assert _candidats_pour('   ') == []


def test_correspond_gere_la_troncature_linux_a_15_caracteres():
    """/proc/<pid>/comm tronque à 15 caracteres : 'chrome_crashpad_handler' y devient
    'chrome_crashpad'. La comparaison doit malgré tout réussir."""
    nom_tronque = 'chrome_crashpad'
    assert len(nom_tronque) == 15
    assert _correspond('chrome_crashpad_handler', [nom_tronque])


def test_correspond_exact_et_suffixe_executable():
    assert _correspond('firefox', ['firefox'])
    assert _correspond('firefox', ['firefox.exe'])


def test_correspond_rejette_un_nom_different():
    assert not _correspond('firefox', ['brave'])
    # Un préfixe court ne doit pas suffire : seul le cas "nom tronqué à 15" compte.
    assert not _correspond('firefox-esr-longname', ['firefox'])
