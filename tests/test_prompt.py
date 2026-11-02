"""Tests unitaires hors-ligne (aucun fournisseur LLM requis).

Lancer : .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import api
from core import llm_provider
from core.exceptions import PermissionRequiredException
from function import files


class TestFenetreContexte(unittest.TestCase):
    def setUp(self):
        self._sauvegarde = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._sauvegarde

    def test_ne_separe_pas_tool_call_et_reponse(self):
        ancien_max = api.MAX_CONTEXT_MESSAGES
        api.MAX_CONTEXT_MESSAGES = 3
        try:
            api.messages.extend([
                {'role': 'user', 'content': 'u1'},
                {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'f', 'arguments': {}}}]},
                {'role': 'tool', 'content': 'r1', 'tool_call_id': 'c1'},
                {'role': 'tool', 'content': 'r2', 'tool_call_id': 'c1'},
                {'role': 'user', 'content': 'u2'},
            ])
            fenetre = api._messages_avec_fenetre()
            self.assertEqual(fenetre[0]['role'], 'system')
            # Aucun message 'tool' ne doit apparaître sans son assistant/tool_calls
            for i, msg in enumerate(fenetre):
                if msg['role'] == 'tool':
                    self.assertTrue(any(m.get('tool_calls') for m in fenetre[:i]))
        finally:
            api.MAX_CONTEXT_MESSAGES = ancien_max

    def test_troncature_historique_bornee(self):
        for i in range(api.MAX_CONTEXT_MESSAGES * 3):
            api.messages.append({'role': 'user' if i % 2 == 0 else 'assistant', 'content': str(i)})
        api._tronquer_historique()
        self.assertLessEqual(len(api.messages) - 1, api.MAX_CONTEXT_MESSAGES)
        self.assertEqual(api.messages[0]['role'], 'system')


class TestDecoupageTTS(unittest.TestCase):
    def test_ne_coupe_pas_les_nombres_ni_les_noms_de_fichiers(self):
        phrases, reste = api._extraire_phrases("Version 3.5 du fichier note.txt prête. Ensuite")
        self.assertEqual(phrases, ["Version 3.5 du fichier note.txt prête."])
        self.assertEqual(reste, " Ensuite")

    def test_plusieurs_phrases_dans_un_meme_buffer(self):
        phrases, reste = api._extraire_phrases("Oui! Non? Peut-être.\nFin")
        self.assertEqual(phrases, ["Oui!", "Non?", "Peut-être."])
        self.assertEqual(reste, "Fin")


class TestSandbox(unittest.TestCase):
    def setUp(self):
        self.home = os.path.expanduser("~")
        self.dossier = tempfile.mkdtemp(prefix="alyx_test_", dir=self.home)

    def tearDown(self):
        shutil.rmtree(self.dossier, ignore_errors=True)

    def test_prefixe_du_home_refuse(self):
        voisin = self.home.rstrip("\\/") + "_voisin"
        with self.assertRaises(PermissionError):
            files._resoudre_chemin(os.path.join(voisin, "x.txt"))

    def test_hors_home_refuse(self):
        with self.assertRaises(PermissionError):
            files._resoudre_chemin(os.path.join(tempfile.gettempdir(), "..", "..", "..", "x.txt") if sys.platform != "win32" else "C:\\Windows\\x.txt")

    def test_renommer_ne_sort_pas_du_dossier(self):
        cible = os.path.join(self.dossier, "a.txt")
        open(cible, 'w').close()
        resultat = files.renommer_fichier(cible, os.path.join("..", "..", "evade.txt"))
        self.assertIn("Erreur", resultat)
        self.assertTrue(os.path.exists(cible))
        resultat = files.renommer_fichier(cible, "b.txt")
        self.assertIn("succès", resultat)
        self.assertTrue(os.path.exists(os.path.join(self.dossier, "b.txt")))

    def test_permission_requise_puis_accordee(self):
        cible = os.path.join(self.dossier, "secret.txt")
        with open(cible, 'w', encoding='utf-8') as f:
            f.write("contenu")
        with self.assertRaises(PermissionRequiredException):
            files.lire_fichier_securise(cible)
        resultat = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': cible})
        self.assertIn("contenu", resultat)
        # La permission ne fuit pas sur l'appel suivant
        with self.assertRaises(PermissionRequiredException):
            files.lire_fichier_securise(cible)

    def test_zones_sensibles_interdites_en_ecriture(self):
        for zone in (os.path.join("~", ".ssh", "authorized_keys"), os.path.join("~", ".config", "autostart", "x.desktop")):
            self.assertIn("sensible", files.creer_fichier(zone))
        if os.environ.get('APPDATA'):
            startup = os.path.join(os.environ['APPDATA'], 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
            source = os.path.join(self.dossier, "payload.bat")
            open(source, 'w').close()
            self.assertIn("sensible", files.deplacer_fichier(source, startup))
            self.assertTrue(os.path.exists(source))

    def test_liste_bornee(self):
        for i in range(files.MAX_ENTREES_LISTE + 5):
            open(os.path.join(self.dossier, f"f{i:04d}.txt"), 'w').close()
        resultat = files.lister_fichiers(self.dossier)
        self.assertIn("5 éléments non affichés", resultat)
        self.assertLessEqual(resultat.count("📄"), files.MAX_ENTREES_LISTE)

    def test_pdf_caracteres_hors_latin1(self):
        cible = os.path.join(self.dossier, "doc.pdf")
        resultat = files.executer_avec_permission(files.generer_pdf, {'chemin': cible, 'contenu': "L’été “chaud” — ok… 🚀"})
        self.assertIn("Succès", resultat)
        self.assertTrue(os.path.getsize(cible) > 0)


class TestSchemasEtMessages(unittest.TestCase):
    def test_schema_utilise_la_section_args(self):
        schema = llm_provider._function_to_json_schema(files.renommer_fichier)
        props = schema['function']['parameters']['properties']
        self.assertIn('Nouveau nom', props['nouveau_nom']['description'])
        self.assertEqual(schema['function']['parameters']['required'], ['chemin_actuel', 'nouveau_nom'])
        self.assertNotIn('Args', schema['function']['description'])

    def test_normalisation_tool_calls(self):
        tcs = llm_provider.normaliser_tool_calls([{'function': {'name': 'f', 'arguments': '{"a": 1}'}}])
        self.assertEqual(tcs[0]['function']['arguments'], {'a': 1})
        self.assertTrue(tcs[0]['id'])

    def test_format_openai_strict(self):
        historique = [
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'f', 'arguments': {'a': 1}}}]},
            {'role': 'tool', 'content': 'ok', 'name': 'f', 'tool_name': 'f', 'tool_call_id': 'c1'},
        ]
        sortie = llm_provider._to_openai_messages(historique)
        self.assertEqual(sortie[0]['tool_calls'][0]['id'], 'c1')
        self.assertEqual(json.loads(sortie[0]['tool_calls'][0]['function']['arguments']), {'a': 1})
        self.assertEqual(sortie[1]['tool_call_id'], 'c1')

    def test_format_ollama_natif(self):
        historique = [
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'f', 'arguments': {'a': 1}}}]},
            {'role': 'tool', 'content': 'ok', 'name': 'f', 'tool_name': 'f', 'tool_call_id': 'c1'},
        ]
        sortie = llm_provider._to_ollama_messages(historique)
        self.assertEqual(sortie[0]['tool_calls'], [{'function': {'name': 'f', 'arguments': {'a': 1}}}])
        self.assertEqual(sortie[1], {'role': 'tool', 'content': 'ok', 'tool_name': 'f'})


class TestWidgetBackend(unittest.TestCase):
    def test_snapshot_structure(self):
        from core import system_monitor
        s = system_monitor.snapshot()
        self.assertIn('percent', s['cpu'])
        self.assertGreater(s['ram']['total_gb'], 0)
        self.assertIn('down_mbs', s['net'])
        json.dumps(s)  # sérialisable pour le WebSocket

    def test_processus_tries_et_alyx_marque(self):
        from core import system_monitor
        p = system_monitor.processus(limite=500)
        self.assertGreater(p['total'], 0)
        cpus = [x['cpu'] for x in p['items']]
        self.assertEqual(cpus, sorted(cpus, reverse=True))
        self.assertTrue(any(x['alyx'] and x['pid'] == os.getpid() for x in p['items']))

    def test_terminer_processus_protege(self):
        from core import system_monitor
        ok, message = system_monitor.terminer_processus(os.getpid())
        self.assertFalse(ok)
        self.assertIn("protégé", message)

    def test_controle_media_action_invalide(self):
        from function.system import controler_media
        self.assertIn("inconnue", controler_media("danser"))

    def test_resume_llm(self):
        from core import system_monitor
        self.assertIn("CPU", system_monitor.resume_pour_llm())


class TestVoixEtLangue(unittest.TestCase):
    def setUp(self):
        from core import preferences
        self.preferences = preferences
        self._appdata = os.environ.get('APPDATA')
        self.dossier = tempfile.mkdtemp(prefix="alyx_prefs_")
        os.environ['APPDATA'] = self.dossier  # ne touche pas aux vraies préférences
        preferences._cache = None

    def tearDown(self):
        if self._appdata is None:
            os.environ.pop('APPDATA', None)
        else:
            os.environ['APPDATA'] = self._appdata
        self.preferences._cache = None
        shutil.rmtree(self.dossier, ignore_errors=True)

    def test_preferences_validees_et_persistees(self):
        p = self.preferences.mettre_a_jour({'rate': 42, 'language': 'klingon', 'speak_all': 1, 'inconnu': 'x'})
        self.assertEqual(p['rate'], 10)
        self.assertEqual(p['language'], 'fr')
        self.assertTrue(p['speak_all'])
        self.assertNotIn('inconnu', p)
        self.preferences._cache = None
        self.assertEqual(self.preferences.charger()['rate'], 10)

    def test_prompt_suit_la_langue(self):
        import ai
        self.assertIn("English", ai.prompt_systeme('en'))
        self.assertIn("français", ai.prompt_systeme('fr'))
        self.assertIn("Markdown", ai.prompt_systeme('fr'))

    def test_nettoyage_markdown_latex_pour_la_voix(self):
        from function.tts import nettoyer_pour_voix
        texte = "## Loi d'Ohm\n- **Tension** : $U = R \\times I$ et $\\frac{V}{d}$\n```python\nprint(1)\n```"
        propre = nettoyer_pour_voix(texte)
        for interdit in ("#", "*", "$", "\\", "{", "print"):
            self.assertNotIn(interdit, propre)
        self.assertIn("fois", propre)
        self.assertIn("V sur d", propre)

    def test_choix_voix_par_langue(self):
        from function.tts import voix_pour_langue
        voix = [{'id': 'a', 'lang': 'en-US', 'engine': 'SAPI 5'}, {'id': 'b', 'lang': 'fr-CA', 'engine': 'SAPI 5'},
                {'id': 'c', 'lang': 'fr-FR', 'engine': 'Windows'}]
        self.assertEqual(voix_pour_langue(voix, 'fr')['id'], 'c')  # voix Windows prioritaire
        self.assertIsNone(voix_pour_langue(voix, 'de'))

    def test_micro_memorise_et_erreurs_explicites(self):
        self.assertEqual(self.preferences.mettre_a_jour({'microphone': 'Headset (Play X2)'})['microphone'], 'Headset (Play X2)')
        self.assertIsNone(self.preferences.mettre_a_jour({'microphone': ''})['microphone'])  # "" = défaut système
        muet = api._message_erreur_stt({'error': 'muet', 'device': 'Microphone Array'})
        self.assertIn("Microphone Array", muet)
        self.assertIn("coupé", muet)
        self.assertIn("faster-whisper", api._message_erreur_stt({'error': 'modele'}))
        self.assertIn("rien compris", api._message_erreur_stt({'text': '', 'error': ''}))


if __name__ == '__main__':
    unittest.main()
