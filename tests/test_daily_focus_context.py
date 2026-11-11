"""Unit tests for Daily Tasks, Focus/Gaming mode, and Context Awareness.

Validates:
1. function/reminders.py: local persistence, CRUD, imminent reminders check.
2. function/notes.py: local markdown & json persistence, CRUD, tags filtering.
3. function/system.py: copier_presse_papiers clipboard copying with error handling.
4. core/focus_gaming.py: fullscreen detection, VRAM unload transition on game detection.
5. core/context.py: active window and clipboard capture at invocation.
6. ai.py: dynamic routing of daily tools (reminders, notes, clipboard).
"""
import asyncio
from datetime import datetime, timedelta
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import ai
from core import context, focus_gaming
from function import notes, reminders, system


class TestDailyReminders(unittest.TestCase):
    """Test suite for local reminders management."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_test_reminders_")
        self.reminders_file = os.path.join(self.temp_dir, "reminders.json")
        self.patcher = patch('function.reminders._obtenir_fichier_rappels', return_value=self.reminders_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_creer_rappel_avec_delai_minutes(self):
        resultat = reminders.creer_rappel("Sortir le chien", delai_minutes=15)
        self.assertIn("Rappel programmé avec succès", resultat)
        self.assertIn("Sortir le chien", resultat)

        rappels = reminders._charger_rappels()
        self.assertEqual(len(rappels), 1)
        self.assertEqual(rappels[0]["texte"], "Sortir le chien")
        self.assertFalse(rappels[0]["notifie"])

    def test_creer_rappel_sans_texte_renvoie_erreur(self):
        resultat = reminders.creer_rappel("")
        self.assertIn("Erreur", resultat)
        self.assertEqual(len(reminders._charger_rappels()), 0)

    def test_lister_et_supprimer_rappel(self):
        reminders.creer_rappel("Rappel 1", delai_minutes=10)
        reminders.creer_rappel("Rappel 2", delai_minutes=30)
        rappels = reminders._charger_rappels()
        self.assertEqual(len(rappels), 2)

        id_a_supprimer = rappels[0]["id"]
        res_liste = reminders.lister_rappels()
        self.assertIn("Rappel 1", res_liste)
        self.assertIn("Rappel 2", res_liste)

        res_suppr = reminders.supprimer_rappel(id_a_supprimer)
        self.assertIn("supprimé", res_suppr)

        rappels_apres = reminders._charger_rappels()
        self.assertEqual(len(rappels_apres), 1)
        self.assertEqual(rappels_apres[0]["texte"], "Rappel 2")

        res_invalide = reminders.supprimer_rappel("id_inconnu")
        self.assertIn("Aucun rappel correspondant", res_invalide)

    def test_verifier_rappels_imminents(self):
        # Créer un rappel déjà échu dans le passé
        maintenant = datetime.now()
        echeance_passee = (maintenant - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        reminders.creer_rappel("Rappel échu", date_heure=echeance_passee)

        # Créer un rappel futur non échu
        reminders.creer_rappel("Rappel futur", delai_minutes=60)

        imminents = reminders.verifier_rappels_imminents()
        self.assertEqual(len(imminents), 1)
        self.assertEqual(imminents[0]["texte"], "Rappel échu")

        # Vérifier que le rappel a été marqué comme notifié
        imminents_apres = reminders.verifier_rappels_imminents()
        self.assertEqual(len(imminents_apres), 0)


class TestDailyNotes(unittest.TestCase):
    """Test suite for local quick notes management."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_test_notes_")
        self.notes_dir = os.path.join(self.temp_dir, "notes")
        self.index_file = os.path.join(self.temp_dir, "notes.json")
        os.makedirs(self.notes_dir, exist_ok=True)
        self.patcher = patch(
            'function.notes._obtenir_chemins_notes',
            return_value=(self.notes_dir, self.index_file)
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_ajouter_et_lire_note_rapide(self):
        res = notes.ajouter_note_rapide(
            titre="Courses",
            contenu="Acheter du café et du thé.",
            etiquette="urgent"
        )
        self.assertIn("Note enregistrée avec succès", res)
        self.assertIn("Courses", res)

        index = notes._charger_index_notes()
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["titre"], "Courses")
        self.assertEqual(index[0]["etiquette"], "urgent")

        # Vérifier que le fichier markdown existe physiquement
        fichier_md = os.path.join(self.notes_dir, index[0]["fichier"])
        self.assertTrue(os.path.exists(fichier_md))
        with open(fichier_md, "r", encoding="utf-8") as f:
            contenu_md = f.read()
            self.assertIn("Acheter du café", contenu_md)

        # Lire la note via son titre
        lecture = notes.lire_note_rapide("Courses")
        self.assertIn("Acheter du café et du thé.", lecture)

    def test_lister_notes_avec_filtre_etiquette(self):
        notes.ajouter_note_rapide(titre="Dev Alyx", contenu="Bug API websockets", etiquette="alyx")
        notes.ajouter_note_rapide(titre="Perso", contenu="Acheter cadeaux noel", etiquette="perso")

        toutes = notes.lister_notes_rapides()
        self.assertIn("Dev Alyx", toutes)
        self.assertIn("Perso", toutes)

        filtrees = notes.lister_notes_rapides(etiquette="alyx")
        self.assertIn("Dev Alyx", filtrees)
        self.assertNotIn("Perso", filtrees)

    def test_supprimer_note_rapide(self):
        notes.ajouter_note_rapide(titre="Note Temporaire", contenu="Texte temporaire")
        index = notes._charger_index_notes()
        self.assertEqual(len(index), 1)
        note_id = index[0]["id"]
        fichier_md = os.path.join(self.notes_dir, index[0]["fichier"])
        self.assertTrue(os.path.exists(fichier_md))

        res = notes.supprimer_note_rapide(note_id)
        self.assertIn("supprimée avec succès", res)
        self.assertEqual(len(notes._charger_index_notes()), 0)
        self.assertFalse(os.path.exists(fichier_md))


class TestClipboardSystem(unittest.TestCase):
    """Test suite for clipboard interaction tool."""

    def test_copier_presse_papiers_invalide(self):
        res1 = system.copier_presse_papiers("")
        self.assertIn("Erreur", res1)
        res2 = system.copier_presse_papiers(None)
        self.assertIn("Erreur", res2)

    @patch('subprocess.run')
    def test_copier_presse_papiers_succes_windows(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        with patch('sys.platform', 'win32'):
            res = system.copier_presse_papiers("Texte à copier")
            self.assertIn("copié dans le presse-papiers", res)
            self.assertIn("14 caractères", res)


class TestFocusGamingMode(unittest.TestCase):
    """Test suite for Focus/Gaming fullscreen detection and resource throttling."""

    def setUp(self):
        with focus_gaming._lock:
            focus_gaming._focus_gaming_actif = False
            focus_gaming._dernier_processus_detecte = None

    def tearDown(self):
        with focus_gaming._lock:
            focus_gaming._focus_gaming_actif = False
            focus_gaming._dernier_processus_detecte = None

    def test_detecter_mode_focus_gaming_structure(self):
        """Vérifie que la détection retourne la structure attendue sans planter."""
        est_actif, nom_proc, meta = focus_gaming.detecter_mode_focus_gaming()
        self.assertIsInstance(est_actif, bool)
        self.assertTrue(nom_proc is None or isinstance(nom_proc, str))
        self.assertIsInstance(meta, dict)

    @patch('core.focus_gaming.detecter_mode_focus_gaming')
    @patch('core.llm_provider.decharger_modele')
    def test_evaluer_changement_focus_active_et_decharge_vram(self, mock_decharger, mock_detecter):
        mock_detecter.return_value = (True, "EldenRing.exe", {"type": "game"})
        with patch('ai.MODEL', 'llama3:8b'):
            changement, actif, nom_proc = focus_gaming.evaluer_changement_focus(auto_unload_vram=True)
            self.assertTrue(changement)
            self.assertTrue(actif)
            self.assertEqual(nom_proc, "EldenRing.exe")
            mock_decharger.assert_called_once_with('llama3:8b')

        # Maintenant, désactivation du mode
        mock_detecter.return_value = (False, None, {})
        changement2, actif2, nom_proc2 = focus_gaming.evaluer_changement_focus(auto_unload_vram=True)
        self.assertTrue(changement2)
        self.assertFalse(actif2)
        self.assertIsNone(nom_proc2)


class TestContextInvocation(unittest.TestCase):
    """Test suite for contextual awareness at prompt invocation."""

    @patch('core.context.obtenir_fenetre_active')
    @patch('core.context.obtenir_presse_papiers_invoque')
    def test_capturer_contexte_invocation(self, mock_clip, mock_win):
        mock_win.return_value = {"titre": "Projet Alyx - Visual Studio Code", "processus": "Code.exe"}
        mock_clip.return_value = "def test_fonction(): pass"

        ctx = context.capturer_contexte_invocation()
        self.assertIn("fenetre_active", ctx)
        self.assertIn("presse_papiers", ctx)
        self.assertEqual(ctx["fenetre_active"]["processus"], "Code.exe")
        self.assertEqual(ctx["presse_papiers"], "def test_fonction(): pass")

    @patch('subprocess.run')
    def test_presse_papiers_troncature(self, mock_run):
        long_texte = "A" * 2000
        mock_run.return_value = MagicMock(returncode=0, stdout=long_texte)

        with patch('sys.platform', 'win32'):
            resultat = context.obtenir_presse_papiers_invoque(max_chars=100)
            self.assertIsNotNone(resultat)
            self.assertIn("... [Presse-papiers tronqué à 100 caractères]", resultat)
            self.assertTrue(len(resultat) < 250)


class TestToolRoutingDailyDomains(unittest.TestCase):
    """Test suite for selectionner_outils_pertinents recognizing reminders, notes, and clipboard."""

    def test_router_outils_reminders(self):
        outils = ai.selectionner_outils_pertinents("Rappelle-moi dans 15 minutes d'éteindre le four")
        noms = [fn.__name__ if hasattr(fn, '__name__') else str(fn) for fn in outils]
        self.assertIn("creer_rappel", noms)

    def test_router_outils_notes(self):
        outils = ai.selectionner_outils_pertinents("Prends une note rapide : réunion marketing à 14h")
        noms = [fn.__name__ if hasattr(fn, '__name__') else str(fn) for fn in outils]
        self.assertIn("ajouter_note_rapide", noms)

    def test_router_outils_clipboard(self):
        outils = ai.selectionner_outils_pertinents("Copie cette adresse dans le presse-papiers s'il te plaît")
        noms = [fn.__name__ if hasattr(fn, '__name__') else str(fn) for fn in outils]
        self.assertIn("copier_presse_papiers", noms)


class TestApiRestEndpoints(unittest.IsolatedAsyncioTestCase):
    """Test suite for HTTP REST endpoints /api/status and /api/ready multiplexed on the port."""

    async def test_rest_endpoints_status_and_ready(self):
        import urllib.request
        import websockets
        import api

        server = await websockets.serve(
            api.handler_client,
            "127.0.0.1",
            0,
            origins=[None],
            process_request=api.process_http_request
        )
        port = server.sockets[0].getsockname()[1]
        try:
            def fetch(path):
                req = urllib.request.Request(f"http://127.0.0.1:{port}{path}")
                try:
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        return resp.status, json.loads(resp.read().decode('utf-8'))
                except urllib.error.HTTPError as e:
                    return e.code, json.loads(e.read().decode('utf-8'))

            # /api/status doit répondre 200 OK
            status_code, status_data = await asyncio.to_thread(fetch, "/api/status")
            self.assertEqual(status_code, 200)
            self.assertEqual(status_data.get("status"), "ok")
            self.assertIn("providers", status_data)
            self.assertIn("vram", status_data)

            # /api/ready avant readiness -> 503
            api._backend_pret.clear()
            ready_code, ready_data = await asyncio.to_thread(fetch, "/api/ready")
            self.assertEqual(ready_code, 503)
            self.assertFalse(ready_data.get("ready"))

            # /api/ready après readiness -> 200
            api._backend_pret.set()
            ready_code2, ready_data2 = await asyncio.to_thread(fetch, "/api/ready")
            self.assertEqual(ready_code2, 200)
            self.assertTrue(ready_data2.get("ready"))
        finally:
            server.close()
            await server.wait_closed()


if __name__ == '__main__':
    unittest.main()
