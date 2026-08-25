"""Rappels et notes locaux (function/tasks.py).

Chaque test redirige le stockage vers un dossier temporaire (monkeypatch des
chemins de fichiers) : on ne doit jamais lire/écrire les vraies données de
l'utilisateur pendant les tests.
"""
import function.tasks as tasks


def _isoler_stockage(tmp_path, monkeypatch):
    monkeypatch.setattr(tasks, '_RAPPELS_PATH', str(tmp_path / 'rappels.json'))
    monkeypatch.setattr(tasks, '_NOTES_PATH', str(tmp_path / 'notes.json'))
    monkeypatch.setattr(tasks, '_DATA_DIR', str(tmp_path))


def test_lister_rappels_vide_par_defaut(tmp_path, monkeypatch):
    _isoler_stockage(tmp_path, monkeypatch)
    assert tasks.lister_rappels() == "Aucun rappel actif."


def test_creer_puis_lister_rappel(tmp_path, monkeypatch):
    _isoler_stockage(tmp_path, monkeypatch)
    resultat = tasks.creer_rappel("Acheter du pain", "ce soir")
    assert "#1" in resultat and "Acheter du pain" in resultat

    listing = tasks.lister_rappels()
    assert "#1" in listing and "Acheter du pain" in listing and "ce soir" in listing


def test_numeros_de_rappel_ne_se_reutilisent_pas_apres_suppression():
    """Si #1 est terminé puis qu'on recrée un rappel, il doit devenir #2, jamais
    réutiliser #1 — sinon terminer_rappel(1) redeviendrait ambigu."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tasks._RAPPELS_PATH = f"{d}/rappels.json"
        tasks.creer_rappel("Premier")
        tasks.terminer_rappel(1)
        resultat = tasks.creer_rappel("Deuxieme")
        assert "#2" in resultat


def test_creer_rappel_texte_vide_est_refuse(tmp_path, monkeypatch):
    _isoler_stockage(tmp_path, monkeypatch)
    resultat = tasks.creer_rappel("   ")
    assert resultat.startswith("Erreur")
    assert tasks.lister_rappels() == "Aucun rappel actif."


def test_terminer_rappel_inexistant_ne_touche_pas_les_autres(tmp_path, monkeypatch):
    _isoler_stockage(tmp_path, monkeypatch)
    tasks.creer_rappel("Reste actif")
    resultat = tasks.terminer_rappel(999)
    assert resultat.startswith("Erreur")
    assert "Reste actif" in tasks.lister_rappels()


def test_notes_les_plus_recentes_en_premier(tmp_path, monkeypatch):
    _isoler_stockage(tmp_path, monkeypatch)
    tasks.prendre_note("premiere")
    tasks.prendre_note("seconde")
    listing = tasks.lister_notes()
    assert listing.index("seconde") < listing.index("premiere")


def test_lister_notes_respecte_la_limite(tmp_path, monkeypatch):
    _isoler_stockage(tmp_path, monkeypatch)
    for i in range(5):
        tasks.prendre_note(f"note {i}")
    listing = tasks.lister_notes(nombre=2)
    assert listing.count("note ") == 2


def test_charger_recupere_gracieusement_un_fichier_corrompu(tmp_path, monkeypatch):
    """Un JSON corrompu (coupure de courant pendant une écriture non-atomique d'un
    ancien format, disque plein...) ne doit jamais faire planter Alyx : il faut
    repartir d'une liste vide plutôt que de lever une exception."""
    _isoler_stockage(tmp_path, monkeypatch)
    (tmp_path / 'rappels.json').write_text("{ceci n'est pas du JSON valide")
    assert tasks.lister_rappels() == "Aucun rappel actif."
    # Et l'écriture suivante doit fonctionner malgré le fichier corrompu au départ.
    resultat = tasks.creer_rappel("Nouveau départ")
    assert "#1" in resultat
