"""tests/test_m3_challenger_alias_stress.py
Suite de tests de résistance contradictoire (Adversarial Stress Testing) pour le Milestone 3 (R3) :
- Robustesse de resoudre_outil() face aux entrées inhabituelles (None, entiers, vide, espaces, casse, tirets multiples, Unicode, caractères spéciaux).
- Robustesse du normalisateur de paramètres (arguments non-dict, None, clés/valeurs vides, collisions d'alias, casse/tirets).
- Robustesse multi-fichiers de deplacer_fichier() (échecs partiels, fichiers inexistants, bac à sable/permissions, collisions, JSON vs liste brute, pile d'annulation).
- Intégrité du ring buffer de contexte sous API WebSocket face aux échecs d'outils.
"""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import ai
import api
from function import files
from tests.e2e.harness import EphemeralSandbox, run_async


class TestToolResolutionAdversarialStress(unittest.TestCase):
    """Stress-test contradictoire sur resoudre_outil() avec des entrées dégradées ou hostiles."""

    def test_none_input_handled_gracefully(self):
        """nom_fonction=None ne lève pas d'exception et renvoie (None, '', {})."""
        fn, canon, args = ai.resoudre_outil(None)
        self.assertIsNone(fn)
        self.assertEqual(canon, "")
        self.assertEqual(args, {})

    def test_integer_inputs_handled_gracefully(self):
        """nom_fonction entier (0, 42, -1) ne lève pas d'exception et renvoie (None, canon, {})."""
        for val in (0, 42, -1, 999999):
            fn, canon, args = ai.resoudre_outil(val)
            self.assertIsNone(fn)
            # 0 étant falsy en Python, (0 or "") s'évalue en "" ; les entiers sont convertis en str et leurs tirets remplacés par '_'
            attendu = "" if val == 0 else str(val).replace('-', '_')
            self.assertEqual(canon, attendu)
            self.assertEqual(args, {})

    def test_empty_and_whitespace_inputs(self):
        """Chaînes vides ou composées exclusivement d'espaces/tabulations/sauts de ligne."""
        for val in ("", "   ", "\t\t", "\n\r\n", " \t \n "):
            fn, canon, args = ai.resoudre_outil(val)
            self.assertIsNone(fn)
            self.assertEqual(canon, "")
            self.assertEqual(args, {})

    def test_leading_and_trailing_whitespace_stripped(self):
        """Les espaces et sauts de ligne en début/fin sont élagués pour les alias et noms canoniques."""
        variantes = [
            ("  move_file  ", files.deplacer_fichier, "deplacer_fichier"),
            ("\tdeplacer_fichier\n", files.deplacer_fichier, "deplacer_fichier"),
            ("   list_files\t", files.lister_fichiers, "lister_fichiers"),
            ("\n  cat  \n", files.lire_fichier_securise, "lire_fichier_securise"),
        ]
        for entree, attendu_fn, attendu_canon in variantes:
            fn, canon, _ = ai.resoudre_outil(entree)
            self.assertEqual(fn, attendu_fn, f"Échec d'élagage pour {repr(entree)}")
            self.assertEqual(canon, attendu_canon)

    def test_mixed_case_and_hyphen_variations(self):
        """Casse panachée (CamelCase, UPPER, alternance) et tirets isolés."""
        tests = [
            ("DePlAcEr_FiChIeR", files.deplacer_fichier, "deplacer_fichier"),
            ("mOvE_fIlEs", files.deplacer_fichier, "deplacer_fichier"),
            ("MOVE-FILE", files.deplacer_fichier, "deplacer_fichier"),
            ("LiSt-FiLeS", files.lister_fichiers, "lister_fichiers"),
            ("LIST_DIR", files.lister_fichiers, "lister_fichiers"),
            ("READ-FILE", files.lire_fichier_securise, "lire_fichier_securise"),
            ("DELETE-FILES", files.supprimer_fichier, "supprimer_fichier"),
        ]
        for entree, attendu_fn, attendu_canon in tests:
            fn, canon, _ = ai.resoudre_outil(entree)
            self.assertEqual(fn, attendu_fn, f"Résolution incorrecte pour {repr(entree)}")
            self.assertEqual(canon, attendu_canon)

    def test_excessive_hyphens_behavior(self):
        """Les tirets consécutifs multiples (---) ne font pas planter la fonction mais ne sont pas résolus."""
        # ai.resoudre_outil utilise .replace('-', '_') : 'move---files' devient 'move___files'
        for input_val in ("move---files", "move--file", "--move-files--", "deplacer---fichier"):
            fn, canon, args = ai.resoudre_outil(input_val)
            self.assertIsNone(fn, f"{input_val} ne devrait pas trouver d'outil avec des triples underscores.")
            self.assertTrue("___" in canon or "__" in canon or canon.startswith("_"))

    def test_unicode_and_french_accents_behavior(self):
        """Évaluation des variantes accentuées françaises et scripts non-latins."""
        # Les fonctions canoniques et ALIAS_OUTILS sont sans accent (ex: deplacer_fichier)
        # Une entrée avec accent 'déplacer_fichier' renvoie None sans planter
        for entree in ("déplacer_fichier", "déplacer", "créer_fichier", "écrire_fichier_sécurisé"):
            fn, canon, _ = ai.resoudre_outil(entree)
            self.assertIsNone(fn, f"L'outil accentué {repr(entree)} a résolu de manière inattendue.")
            self.assertEqual(canon, entree)

        # Alphabets non-latins et emojis
        for entree in ("📁move_file", "переместить_файл", "移动文件", "مجلد"):
            fn, canon, _ = ai.resoudre_outil(entree)
            self.assertIsNone(fn)
            self.assertEqual(canon, entree)

    def test_special_characters_and_injection_attempts(self):
        """Tentatives d'injection de commandes ou caractères spéciaux dans le nom d'outil."""
        injections = [
            "!@#$%^&*()",
            "move;rm -rf /",
            "deplacer_fichier\x00",
            "`whoami`",
            "$(cat /etc/passwd)",
            "../../../etc/passwd",
        ]
        for inj in injections:
            fn, canon, _ = ai.resoudre_outil(inj)
            self.assertIsNone(fn, f"Injection non bloquée : {repr(inj)}")


class TestParameterNormalizerAdversarialStress(unittest.TestCase):
    """Stress-test contradictoire sur la normalisation des paramètres dans resoudre_outil()."""

    def test_none_and_empty_arguments(self):
        """arguments=None et arguments={} renvoient un dictionnaire vide sans erreur."""
        fn, canon, args1 = ai.resoudre_outil("deplacer_fichier", None)
        self.assertEqual(args1, {})
        fn, canon, args2 = ai.resoudre_outil("deplacer_fichier", {})
        self.assertEqual(args2, {})

    def test_non_dict_arguments_raises_type_or_value_error(self):
        """
        Défaut empirique identifié : ai.py:287 utilise dict(arguments) sans vérifier isinstance(arguments, dict).
        Tout argument truthy non-dict (chaîne, entier, liste, booléen) lève ValueError ou TypeError.
        """
        non_dicts = [
            "not-a-dict",
            '{"source": "test.txt"}',
            123,
            [1, 2, 3],
            True,
        ]
        for nd in non_dicts:
            with self.assertRaises((TypeError, ValueError), msg=f"Échec de capture d'erreur pour {type(nd)}"):
                ai.resoudre_outil("deplacer_fichier", nd)

    def test_empty_keys_and_empty_values_preserved(self):
        """Les dictionnaires contenant des clés vides ou des valeurs vides sont traités sans plantage."""
        args_entrants = {
            "": "",
            "source": "rapport.pdf",
            "destination": "",
            "autre_cle": None,
        }
        _, _, args_norm = ai.resoudre_outil("deplacer_fichier", args_entrants)
        self.assertEqual(args_norm.get("chemin_source"), "rapport.pdf")
        self.assertEqual(args_norm.get("dossier_destination"), "")
        self.assertIn("", args_norm)
        self.assertIsNone(args_norm.get("autre_cle"))
        self.assertNotIn("source", args_norm)
        self.assertNotIn("destination", args_norm)

    def test_collision_canonical_key_takes_precedence(self):
        """Si la clé canonique ET un synonyme sont fournis, la clé canonique est prioritaire."""
        args_entrants = {
            "chemin_source": "canonique.pdf",
            "source": "synonyme.pdf",
            "src": "autre_synonyme.pdf",
            "dossier_destination": "dossier_canon/",
            "destination": "dossier_syn/",
        }
        _, _, args_norm = ai.resoudre_outil("deplacer_fichier", args_entrants)
        self.assertEqual(args_norm["chemin_source"], "canonique.pdf")
        self.assertEqual(args_norm["dossier_destination"], "dossier_canon/")
        self.assertNotIn("source", args_norm)
        self.assertNotIn("src", args_norm)
        self.assertNotIn("destination", args_norm)

    def test_collision_canonical_is_none_gets_populated(self):
        """Si la clé canonique est explicitement None, le synonyme renseigne sa valeur."""
        args_entrants = {
            "chemin_source": None,
            "source": "synonyme.pdf",
            "dossier_destination": "dossier_dest/",
        }
        _, _, args_norm = ai.resoudre_outil("deplacer_fichier", args_entrants)
        self.assertEqual(args_norm["chemin_source"], "synonyme.pdf")
        self.assertNotIn("source", args_norm)

    def test_collision_multiple_synonyms_first_encountered_wins(self):
        """Si plusieurs synonymes sont fournis sans clé canonique, un seul est promu et les autres élagués."""
        args_entrants = {
            "source": "source_val.pdf",
            "src": "src_val.pdf",
            "file": "file_val.pdf",
            "destination": "dest/",
        }
        _, _, args_norm = ai.resoudre_outil("deplacer_fichier", args_entrants)
        self.assertIn("chemin_source", args_norm)
        self.assertIn(args_norm["chemin_source"], ("source_val.pdf", "src_val.pdf", "file_val.pdf"))
        self.assertNotIn("source", args_norm)
        self.assertNotIn("src", args_norm)
        self.assertNotIn("file", args_norm)

    def test_case_and_hyphen_insensitivity_in_argument_keys(self):
        """Les clés d'arguments avec tirets ou casse panachée sont reconnues."""
        args_entrants = {
            "SOURCE-PATH": "source.pdf",
            "TARGET-FOLDER": "archives/",
        }
        _, _, args_norm = ai.resoudre_outil("deplacer_fichier", args_entrants)
        self.assertEqual(args_norm.get("chemin_source"), "source.pdf")
        self.assertEqual(args_norm.get("dossier_destination"), "archives/")

    def test_unrelated_parameters_preserved(self):
        """Les paramètres sans alias dans ARG_ALIASES sont préservés intacts."""
        args_entrants = {
            "source": "rapport.pdf",
            "destination": "dest/",
            "custom_flag": True,
            "nested_config": {"retry": 3},
        }
        _, _, args_norm = ai.resoudre_outil("deplacer_fichier", args_entrants)
        self.assertEqual(args_norm["chemin_source"], "rapport.pdf")
        self.assertEqual(args_norm["dossier_destination"], "dest/")
        self.assertEqual(args_norm["custom_flag"], True)
        self.assertEqual(args_norm["nested_config"], {"retry": 3})


class TestMultiFileDeplacerFichierAdversarialStress(unittest.TestCase):
    """Stress-test contradictoire sur le comportement par lot de deplacer_fichier()."""

    def test_empty_collection_inputs(self):
        """Listes, tuples et chaînes JSON vides renvoient le message explicite 'Aucun fichier spécifié à déplacer.'"""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            self.assertEqual(files.deplacer_fichier([], dest), "Aucun fichier spécifié à déplacer.")
            self.assertEqual(files.deplacer_fichier((), dest), "Aucun fichier spécifié à déplacer.")
            self.assertEqual(files.deplacer_fichier("[]", dest), "Aucun fichier spécifié à déplacer.")
            self.assertEqual(files.deplacer_fichier("  []  ", dest), "Aucun fichier spécifié à déplacer.")

    def test_partial_failures_mixed_existing_and_nonexistent(self):
        """Liste de 3 fichiers (2 existants, 1 manquant) : 2 déplacés, 1 échec rapporté avec détail."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            f1 = os.path.join(sbox, "existant1.pdf")
            f2 = os.path.join(sbox, "existant2.pdf")
            f_manquant = os.path.join(sbox, "fantome.pdf")

            with open(f1, "w") as f: f.write("1")
            with open(f2, "w") as f: f.write("2")

            res = files.deplacer_fichier([f1, f_manquant, f2], dest)

            self.assertIn("2/3 fichiers déplacés", res)
            self.assertIn("Erreurs :", res)
            self.assertIn("fantome.pdf", res)

            # Vérification physique sur disque
            self.assertFalse(os.path.exists(f1))
            self.assertFalse(os.path.exists(f2))
            self.assertTrue(os.path.exists(os.path.join(dest, "existant1.pdf")))
            self.assertTrue(os.path.exists(os.path.join(dest, "existant2.pdf")))

    def test_all_files_nonexistent_returns_zero_success(self):
        """Tous les fichiers de la liste sont introuvables : 0 déplacés et liste des erreurs."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            inconnus = [os.path.join(sbox, f"absent_{i}.txt") for i in range(3)]
            res = files.deplacer_fichier(inconnus, dest)

            self.assertIn("0/3 fichiers déplacés", res)
            self.assertIn("Erreurs :", res)

    def test_destination_collision_prevents_overwrite(self):
        """Un fichier portant le même nom existe déjà dans le dossier cible : écrasement bloqué."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            f_src = os.path.join(sbox, "collision.txt")
            f_dst = os.path.join(dest, "collision.txt")

            with open(f_src, "w") as f: f.write("nouveau_contenu")
            with open(f_dst, "w") as f: f.write("ancien_contenu_a_proteger")

            res = files.deplacer_fichier([f_src], dest)

            self.assertIn("0/1 fichiers déplacés", res)
            self.assertIn("existe déjà", res)

            # Le fichier source n'a pas bougé et la destination n'a pas été écrasée
            self.assertTrue(os.path.exists(f_src))
            with open(f_dst, "r") as f:
                self.assertEqual(f.read(), "ancien_contenu_a_proteger")

    def test_destination_collision_in_mixed_batch(self):
        """Dans un lot de 3 fichiers, 1 entre en collision et 2 n'ont pas de conflit."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            f1 = os.path.join(sbox, "ok1.txt")
            f_coll = os.path.join(sbox, "conflit.txt")
            f2 = os.path.join(sbox, "ok2.txt")
            with open(f1, "w") as f: f.write("ok1")
            with open(f_coll, "w") as f: f.write("source_conflit")
            with open(f2, "w") as f: f.write("ok2")

            # Créer le conflit en destination
            with open(os.path.join(dest, "conflit.txt"), "w") as f:
                f.write("cible_existante")

            res = files.deplacer_fichier([f1, f_coll, f2], dest)

            self.assertIn("2/3 fichiers déplacés", res)
            self.assertIn("existe déjà", res)

            self.assertTrue(os.path.exists(os.path.join(dest, "ok1.txt")))
            self.assertTrue(os.path.exists(os.path.join(dest, "ok2.txt")))
            self.assertTrue(os.path.exists(f_coll))  # La source en conflit n'a pas été supprimée
            with open(os.path.join(dest, "conflit.txt"), "r") as f:
                self.assertEqual(f.read(), "cible_existante")

    def test_sandbox_escape_attempt_blocked(self):
        """Tentative de déplacement d'un fichier système hors sandbox (BLOC B.8 / Sécurité)."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            system_path = "C:\\Windows\\System32\\cmd.exe"
            res = files.deplacer_fichier([system_path], dest)

            self.assertIn("0/1 fichiers déplacés", res)
            self.assertIn("Accès refusé", res)

    def test_json_string_vs_raw_list_and_tuple_equivalence(self):
        """Vérifie l'équivalence de traitement entre liste Python, tuple Python et chaîne JSON."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            # 1. Tuple
            t1 = os.path.join(sbox, "t1.txt")
            open(t1, "w").close()
            res_tuple = files.deplacer_fichier((t1,), dest)
            self.assertIn("1 fichiers déplacés avec succès", res_tuple)

            # 2. Chaîne JSON avec espaces
            j1 = os.path.join(sbox, "j1.txt")
            open(j1, "w").close()
            res_json = files.deplacer_fichier(f'  ["{j1.replace(os.sep, "/")}"]  ', dest)
            self.assertIn("1 fichiers déplacés avec succès", res_tuple)

    def test_malformed_json_string_does_not_crash(self):
        """Chaîne ressemblant à du JSON mais syntaxiquement invalide : ne plante pas."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            res = files.deplacer_fichier("[unquoted, invalid: json", dest)
            # Rejeté comme fichier inexistant au lieu de lever JSONDecodeError
            self.assertIn("Erreur", res)

    def test_non_string_elements_in_list(self):
        """Éléments hétérogènes (None, entier) au sein de la liste de fichiers."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "dst")
            os.makedirs(dest, exist_ok=True)

            f1 = os.path.join(sbox, "valide.txt")
            open(f1, "w").close()

            res = files.deplacer_fichier([f1, None, 12345], dest)
            self.assertIn("1/3 fichiers déplacés", res)
            self.assertIn("Erreurs :", res)
            self.assertTrue(os.path.exists(os.path.join(dest, "valide.txt")))

    def test_reversible_undo_journal_for_batch_movement(self):
        """Chaque déplacement par lot alimente le journal d'annulation et peut être défait un par un."""
        with EphemeralSandbox() as sbox:
            src_dir = os.path.join(sbox, "source_dir")
            dest_dir = os.path.join(sbox, "dest_dir")
            os.makedirs(src_dir, exist_ok=True)
            os.makedirs(dest_dir, exist_ok=True)

            f1 = os.path.join(src_dir, "doc1.txt")
            f2 = os.path.join(src_dir, "doc2.txt")
            with open(f1, "w") as f: f.write("contenu1")
            with open(f2, "w") as f: f.write("contenu2")

            files.deplacer_fichier([f1, f2], dest_dir)
            self.assertFalse(os.path.exists(f1))
            self.assertFalse(os.path.exists(f2))

            # Annulation 1 : restaure doc2.txt
            u1 = files.annuler_derniere_action()
            self.assertIn("Annulation réussie", u1)
            self.assertTrue(os.path.exists(f2))
            self.assertFalse(os.path.exists(f1))

            # Annulation 2 : restaure doc1.txt
            u2 = files.annuler_derniere_action()
            self.assertIn("Annulation réussie", u2)
            self.assertTrue(os.path.exists(f1))


class TestServerRingBufferIntegrationUnderFailure(unittest.TestCase):
    """Vérifie l'intégrité du couplage assistant/tool dans le ring buffer WebSocket (BLOC B.7.6)."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    @run_async
    async def test_unknown_tool_preserves_ring_buffer_pairing(self):
        """Un outil introuvable ne plante pas et ajoute un message tool d'erreur apparié."""
        class MockSession:
            def __init__(self):
                self.cancel = asyncio.Event()
                self.messages_recus = []
            async def envoyer(self, msg):
                self.messages_recus.append(msg)

        session = MockSession()
        tc = {
            "id": "call_unknown_1",
            "type": "function",
            "function": {"name": "outil_totalement_inconnu", "arguments": {}},
        }
        api.messages.append({"role": "assistant", "content": "", "tool_calls": [tc]})

        statut = await api._executer_outils(session, [tc], 0, False, 0)
        self.assertEqual(statut, "ok")

        # Vérification du ring buffer : le message tool a bien été ajouté avec le bon tool_call_id
        tool_msg = next((m for m in api.messages if m.get("role") == "tool" and m.get("tool_call_id") == "call_unknown_1"), None)
        self.assertIsNotNone(tool_msg, "Message tool apparié introuvable.")
        self.assertIn("Erreur: Outil", tool_msg["content"])

    @run_async
    async def test_invalid_parameters_type_error_preserves_ring_buffer_pairing(self):
        """Des paramètres invalides (TypeError) ajoutent un message tool d'erreur sans briser le protocole."""
        class MockSession:
            def __init__(self):
                self.cancel = asyncio.Event()
                self.messages_recus = []
            async def envoyer(self, msg):
                self.messages_recus.append(msg)

        session = MockSession()
        # deplacer_fichier nécessite chemin_source et dossier_destination
        tc = {
            "id": "call_type_error_1",
            "type": "function",
            "function": {"name": "deplacer_fichier", "arguments": {"param_invalide": 123}},
        }
        api.messages.append({"role": "assistant", "content": "", "tool_calls": [tc]})

        statut = await api._executer_outils(session, [tc], 0, False, 0)
        self.assertEqual(statut, "ok")

        tool_msg = next((m for m in api.messages if m.get("role") == "tool" and m.get("tool_call_id") == "call_type_error_1"), None)
        self.assertIsNotNone(tool_msg)
        self.assertIn("arguments invalides", tool_msg["content"])

    @run_async
    async def test_non_dict_arguments_unhandled_crash_analysis(self):
        """
        Démontre empiriquement la fragilité : si un tool_call avec argument non-dict parvient à _executer_outils,
        resoudre_outil lève ValueError/TypeError hors du bloc try de fonction(), brisant le ring buffer.
        """
        class MockSession:
            def __init__(self):
                self.cancel = asyncio.Event()
                self.messages_recus = []
            async def envoyer(self, msg):
                self.messages_recus.append(msg)

        session = MockSession()
        tc = {
            "id": "call_crash_1",
            "type": "function",
            "function": {"name": "deplacer_fichier", "arguments": "chaine_non_dict"},
        }
        api.messages.append({"role": "assistant", "content": "", "tool_calls": [tc]})

        # L'appel lève une exception ValueError
        with self.assertRaises(ValueError):
            await api._executer_outils(session, [tc], 0, False, 0)

        # Preuve de violation du ring buffer : aucun message 'tool' n'a pu être enregistré pour call_crash_1
        tool_msg = next((m for m in api.messages if m.get("role") == "tool" and m.get("tool_call_id") == "call_crash_1"), None)
        self.assertIsNone(tool_msg, "Le message tool a été créé alors que la fonction a crashé en amont.")


if __name__ == '__main__':
    unittest.main()
