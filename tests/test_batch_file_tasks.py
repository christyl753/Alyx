"""tests/test_batch_file_tasks.py
Suite de tests de validation pour le Milestone 3 (R3) :
- Résolution des alias d'outils (ALIAS_OUTILS) et normalisation des synonymes d'arguments (ARG_ALIASES)
- Défense multi-fichiers dans deplacer_fichier
- Guidance in-context et exemples few-shot dans le prompt système (<150 tokens)
- Intégration dans le handler CLI et le serveur WebSocket
- Scénario E2E complet de traitement par lots de fichiers via EphemeralSandbox et ScriptableLLMProvider
"""
import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from typing import Any, Dict, List

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import ai
import api
from core import llm_provider
from core.token_counter import estimer_tokens_texte
from function import files
from tests.e2e.harness import (
    AlyxTestClient,
    AlyxTestServer,
    EphemeralSandbox,
    ScriptableLLMProvider,
    run_async,
)


class TestToolAliasResolution(unittest.TestCase):
    """Vérifie la résolution des variantes et alias d'outils (BLOC B / R3)."""

    def test_canonical_names_resolve_directly(self):
        """Les noms canoniques sont directement résolus vers leur fonction correspondante."""
        f, canon, args = ai.resoudre_outil('deplacer_fichier')
        self.assertEqual(f, files.deplacer_fichier)
        self.assertEqual(canon, 'deplacer_fichier')

        f, canon, args = ai.resoudre_outil('lister_fichiers')
        self.assertEqual(f, files.lister_fichiers)
        self.assertEqual(canon, 'lister_fichiers')

    def test_file_movement_aliases(self):
        """Tous les alias de déplacement de fichier pointent vers deplacer_fichier."""
        aliases = [
            'move_file', 'move_files', 'move', 'mv',
            'deplacer_fichiers', 'deplacer', 'deplacement_fichier',
            'ranger_fichier', 'ranger_fichiers'
        ]
        for alias in aliases:
            f, canon, _ = ai.resoudre_outil(alias)
            self.assertEqual(f, files.deplacer_fichier, f"L'alias '{alias}' n'a pas résolu vers deplacer_fichier.")
            self.assertEqual(canon, 'deplacer_fichier')

    def test_file_listing_aliases(self):
        """Tous les alias de listage pointent vers lister_fichiers."""
        aliases = [
            'list_files', 'list_file', 'list_dir', 'listdir', 'ls', 'dir',
            'lister_fichier', 'lister_dossier', 'lister_repertoire',
            'liste_fichiers', 'liste_dossier'
        ]
        for alias in aliases:
            f, canon, _ = ai.resoudre_outil(alias)
            self.assertEqual(f, files.lister_fichiers, f"L'alias '{alias}' n'a pas résolu vers lister_fichiers.")
            self.assertEqual(canon, 'lister_fichiers')

    def test_file_reading_writing_deletion_aliases(self):
        """Les alias de lecture, écriture, suppression et création pointent vers les outils canoniques."""
        for alias in ['read_file', 'cat', 'view_file', 'lire_fichier']:
            f, canon, _ = ai.resoudre_outil(alias)
            self.assertEqual(f, files.lire_fichier_securise)
            self.assertEqual(canon, 'lire_fichier_securise')

        for alias in ['write_file', 'ecrire_fichier', 'enregistrer_fichier']:
            f, canon, _ = ai.resoudre_outil(alias)
            self.assertEqual(f, files.ecrire_fichier_securise)
            self.assertEqual(canon, 'ecrire_fichier_securise')

        for alias in ['delete_file', 'delete_files', 'remove_file', 'rm', 'trash_file', 'supprimer_fichiers']:
            f, canon, _ = ai.resoudre_outil(alias)
            self.assertEqual(f, files.supprimer_fichier)
            self.assertEqual(canon, 'supprimer_fichier')

        for alias in ['create_file', 'touch', 'new_file', 'creer_fichiers']:
            f, canon, _ = ai.resoudre_outil(alias)
            self.assertEqual(f, files.creer_fichier)
            self.assertEqual(canon, 'creer_fichier')

        for alias in ['create_folder', 'create_directory', 'mkdir', 'new_folder', 'creer_repertoire']:
            f, canon, _ = ai.resoudre_outil(alias)
            self.assertEqual(f, files.creer_dossier)
            self.assertEqual(canon, 'creer_dossier')

        for alias in ['rename_file', 'rename', 'renommer_fichiers']:
            f, canon, _ = ai.resoudre_outil(alias)
            self.assertEqual(f, files.renommer_fichier)
            self.assertEqual(canon, 'renommer_fichier')

    def test_system_and_application_aliases(self):
        """Les alias d'applications et du système sont correctement mappés."""
        f, canon, _ = ai.resoudre_outil('open_app')
        self.assertEqual(canon, 'ouvrir_application')

        f, canon, _ = ai.resoudre_outil('close_app')
        self.assertEqual(canon, 'fermer_application')

        f, canon, _ = ai.resoudre_outil('list_apps')
        self.assertEqual(canon, 'lister_apps_actives')

        f, canon, _ = ai.resoudre_outil('clipboard')
        self.assertEqual(canon, 'lire_presse_papiers')

        f, canon, _ = ai.resoudre_outil('ps')
        self.assertEqual(canon, 'rechercher_processus')

        f, canon, _ = ai.resoudre_outil('cmd')
        self.assertEqual(canon, 'executer_commande_systeme')

        f, canon, _ = ai.resoudre_outil('search_web')
        self.assertEqual(canon, 'rechercher_web')

        f, canon, _ = ai.resoudre_outil('undo')
        self.assertEqual(canon, 'annuler_derniere_action')

    def test_case_and_hyphen_insensitivity(self):
        """La résolution est insensible à la casse et tolère les tirets à la place des underscores."""
        variantes = [
            'MOVE-FILES', 'Move_Files', 'move-file', 'LiSt-FiLeS',
            'LIST_DIR', 'Deplacer_Fichiers', 'DEPLACER-FICHIER'
        ]
        for var in variantes:
            f, canon, _ = ai.resoudre_outil(var)
            self.assertIsNotNone(f, f"Échec de résolution pour la variante '{var}'.")
            self.assertIn(canon, ('deplacer_fichier', 'lister_fichiers'))

    def test_unknown_tool_returns_none(self):
        """Un outil inexistant renvoie (None, nom_nettoye, args)."""
        f, canon, args = ai.resoudre_outil('outil_completement_inconnu', {'arg1': 1})
        self.assertIsNone(f)
        self.assertEqual(canon, 'outil_completement_inconnu')
        self.assertEqual(args, {'arg1': 1})


class TestArgumentAliasNormalization(unittest.TestCase):
    """Vérifie la normalisation des synonymes d'arguments (BLOC B / R3)."""

    def test_deplacer_fichier_argument_synonyms(self):
        """Mappe 'source'/'destination', 'src'/'dst', 'file'/'folder' vers chemin_source/dossier_destination."""
        paires = [
            ({'source': 'a.pdf', 'destination': 'dest/'}, 'chemin_source', 'dossier_destination'),
            ({'src': 'a.pdf', 'dst': 'dest/'}, 'chemin_source', 'dossier_destination'),
            ({'file': 'a.pdf', 'target': 'dest/'}, 'chemin_source', 'dossier_destination'),
            ({'file_path': 'a.pdf', 'target_folder': 'dest/'}, 'chemin_source', 'dossier_destination'),
            ({'source_path': 'a.pdf', 'destination_folder': 'dest/'}, 'chemin_source', 'dossier_destination'),
        ]
        for entrants, attendu_src, attendu_dst in paires:
            _, _, args_norm = ai.resoudre_outil('deplacer_fichier', entrants)
            self.assertEqual(args_norm.get(attendu_src), 'a.pdf')
            self.assertEqual(args_norm.get(attendu_dst), 'dest/')
            # Les anciennes clés non-canoniques ont été retirées
            for k in entrants:
                if k not in (attendu_src, attendu_dst):
                    self.assertNotIn(k, args_norm)

    def test_lister_fichiers_argument_synonyms(self):
        """Mappe 'path', 'folder', 'directory', 'dir', 'chemin' vers 'dossier'."""
        for syn in ['path', 'folder', 'directory', 'dir', 'chemin']:
            _, _, args_norm = ai.resoudre_outil('lister_fichiers', {syn: '~/Docs'})
            self.assertEqual(args_norm.get('dossier'), '~/Docs')
            if syn != 'dossier':
                self.assertNotIn(syn, args_norm)

    def test_ecrire_fichier_argument_synonyms(self):
        """Mappe 'file'/'text' ou 'path'/'content' vers 'chemin'/'contenu'."""
        _, _, args_norm = ai.resoudre_outil('ecrire_fichier_securise', {'file': 'note.txt', 'text': 'bonjour'})
        self.assertEqual(args_norm, {'chemin': 'note.txt', 'contenu': 'bonjour'})

        _, _, args_norm = ai.resoudre_outil('ecrire_fichier_securise', {'path': 'note.txt', 'content': 'salut'})
        self.assertEqual(args_norm, {'chemin': 'note.txt', 'contenu': 'salut'})

    def test_renommer_fichier_argument_synonyms(self):
        """Mappe 'source'/'new_name' vers 'chemin_actuel'/'nouveau_nom'."""
        _, _, args_norm = ai.resoudre_outil('renommer_fichier', {'source': 'a.txt', 'new_name': 'b.txt'})
        self.assertEqual(args_norm, {'chemin_actuel': 'a.txt', 'nouveau_nom': 'b.txt'})

    def test_canonical_arguments_not_overwritten(self):
        """Si l'argument canonique est déjà présent, un synonyme additionnel ne l'écrase pas."""
        args_entrants = {
            'chemin_source': 'exact.pdf',
            'source': 'synonyme.pdf',
            'dossier_destination': 'dossier_canon/'
        }
        _, _, args_norm = ai.resoudre_outil('deplacer_fichier', args_entrants)
        self.assertEqual(args_norm['chemin_source'], 'exact.pdf')
        self.assertEqual(args_norm['dossier_destination'], 'dossier_canon/')
        self.assertNotIn('source', args_norm)


class TestMultiFileDefensiveHandling(unittest.TestCase):
    """Vérifie l'adaptateur défensif multi-fichiers dans function/files.py:deplacer_fichier."""

    def test_move_multiple_files_as_list(self):
        """deplacer_fichier accepte une liste de chemins sources et déplace tous les fichiers."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "archives")
            os.makedirs(dest, exist_ok=True)

            fichiers = [
                os.path.join(sbox, f"rapport_{i}.pdf")
                for i in range(1, 4)
            ]
            for f in fichiers:
                open(f, 'w').close()

            res = files.deplacer_fichier(fichiers, dest)
            self.assertIn("3 fichiers déplacés avec succès", res)

            # Vérification de l'état réel sur le disque
            for f in fichiers:
                self.assertFalse(os.path.exists(f))
                nom = os.path.basename(f)
                self.assertTrue(os.path.exists(os.path.join(dest, nom)))

    def test_move_multiple_files_as_tuple(self):
        """deplacer_fichier accepte un tuple de chemins sources."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "archives")
            os.makedirs(dest, exist_ok=True)
            f1 = os.path.join(sbox, "a.pdf")
            f2 = os.path.join(sbox, "b.pdf")
            open(f1, 'w').close()
            open(f2, 'w').close()

            res = files.deplacer_fichier((f1, f2), dest)
            self.assertIn("2 fichiers déplacés avec succès", res)
            self.assertTrue(os.path.exists(os.path.join(dest, "a.pdf")))
            self.assertTrue(os.path.exists(os.path.join(dest, "b.pdf")))

    def test_move_empty_list_returns_explicit_message(self):
        """deplacer_fichier avec une liste vide retourne un message explicite."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "archives")
            os.makedirs(dest, exist_ok=True)
            res = files.deplacer_fichier([], dest)
            self.assertIn("Aucun fichier", res)

    def test_move_partial_failure_returns_summary(self):
        """deplacer_fichier rapporte les réussites et échecs partiels."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "archives")
            os.makedirs(dest, exist_ok=True)
            f1 = os.path.join(sbox, "existant.pdf")
            open(f1, 'w').close()
            f_inconnu = os.path.join(sbox, "introuvable.pdf")

            res = files.deplacer_fichier([f1, f_inconnu], dest)
            self.assertIn("1/2 fichiers déplacés", res)
            self.assertIn("Erreurs", res)
            self.assertTrue(os.path.exists(os.path.join(dest, "existant.pdf")))

    def test_move_json_encoded_list_string_defensively(self):
        """deplacer_fichier décode défensivement une liste sérialisée en JSON."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "archives")
            os.makedirs(dest, exist_ok=True)
            f1 = os.path.join(sbox, "j1.pdf")
            f2 = os.path.join(sbox, "j2.pdf")
            open(f1, 'w').close()
            open(f2, 'w').close()

            json_str = json.dumps([f1, f2])
            res = files.deplacer_fichier(json_str, dest)
            self.assertIn("2 fichiers déplacés avec succès", res)
            self.assertTrue(os.path.exists(os.path.join(dest, "j1.pdf")))
            self.assertTrue(os.path.exists(os.path.join(dest, "j2.pdf")))

    def test_cli_executor_supports_aliases_and_argument_synonyms(self):
        """ai._executer_outil_cli utilise resoudre_outil avec succès."""
        with EphemeralSandbox() as sbox:
            dest = os.path.join(sbox, "archives")
            os.makedirs(dest, exist_ok=True)
            f1 = os.path.join(sbox, "cli_test.pdf")
            open(f1, 'w').close()

            res = ai._executer_outil_cli('move_files', {'source': f1, 'destination': dest})
            self.assertIn("avec succès", res)
            self.assertTrue(os.path.exists(os.path.join(dest, "cli_test.pdf")))


class TestSystemPromptBatchGuidance(unittest.TestCase):
    """Vérifie la présence et le budget de la section Tâches par Lots dans le prompt système."""

    def test_batch_guidance_section_present(self):
        """Le prompt système comporte la section # Tâches par Lots & Manipulation de Fichiers."""
        prompt = ai.prompt_systeme('fr')
        self.assertIn("# Tâches par Lots & Manipulation de Fichiers", prompt)
        self.assertIn("lister_fichiers", prompt)
        self.assertIn("deplacer_fichier", prompt)
        self.assertIn("wildcard", prompt)

    def test_batch_guidance_section_token_budget_strictly_under_150(self):
        """La section Tâches par Lots consomme strictement moins de 150 tokens."""
        prompt = ai.prompt_systeme('fr')
        debut = prompt.find("# Tâches par Lots & Manipulation de Fichiers")
        self.assertNotEqual(debut, -1)
        fin = prompt.find("# Format de Réponse", debut)
        self.assertNotEqual(fin, -1)
        section = prompt[debut:fin].strip()

        tokens = estimer_tokens_texte(section)
        self.assertLess(tokens, 150, f"La section Tâches par Lots dépasse 150 tokens ({tokens} tokens).")

    def test_markdown_hierarchy_preserved_with_batch_section(self):
        """Les 4 en-têtes obligatoires et la section par lots restent dans un ordre séquentiel valide."""
        prompt = ai.prompt_systeme('fr')
        headers = [
            "# Identité & Mission",
            "# Directives Opérationnelles",
            "# Utilisation des Outils",
            "# Tâches par Lots & Manipulation de Fichiers",
            "# Format de Réponse",
        ]
        indices = []
        for h in headers:
            idx = prompt.find(h)
            self.assertNotEqual(idx, -1, f"En-tête manquant : {h}")
            indices.append(idx)
        self.assertEqual(indices, sorted(indices), "L'ordre hiérarchique des en-têtes Markdown est altéré.")


class TestBatchFileTasksEndToEndScenario(unittest.TestCase):
    """
    Test E2E complet du scénario utilisateur :
    1. Dossier contenant 3 rapports PDF, 2 fichiers d'autres types et un sous-dossier archives/
    2. Tour 1 : Modèle appelle l'alias 'list_files' avec paramètre 'path' -> reçoit la liste exacte
    3. Tour 2 : Modèle émet 3 appels simultanés avec alias 'move_files' et arguments 'source'/'destination'
    4. Vérification de l'intégrité des fichiers, des non-rapports préservés et de l'historique ring-buffer.
    """

    def setUp(self):
        self.server = AlyxTestServer()
        self.llm = ScriptableLLMProvider()
        self.llm.start()
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        self.llm.stop()
        api.messages[:] = self._orig_messages

    @run_async
    async def test_e2e_batch_file_organization_with_aliases_and_ring_buffer_integrity(self):
        """Scénario utilisateur réel : découverte et déplacement par lot de 3 rapports via alias."""
        with EphemeralSandbox() as sbox:
            # 1. Création de l'arborescence de test
            rep1 = os.path.join(sbox, "rapport_trimestriel_1.pdf")
            rep2 = os.path.join(sbox, "rapport_trimestriel_2.pdf")
            rep3 = os.path.join(sbox, "rapport_trimestriel_3.pdf")
            note = os.path.join(sbox, "notes.txt")
            data = os.path.join(sbox, "data.csv")
            archives_dir = os.path.join(sbox, "archives")

            for fpath, content in [
                (rep1, "Rapport 1 contenu"),
                (rep2, "Rapport 2 contenu"),
                (rep3, "Rapport 3 contenu"),
                (note, "Note de réunion"),
                (data, "id,valeur\n1,100"),
            ]:
                with open(fpath, 'w', encoding='utf-8') as f:
                    f.write(content)
            os.makedirs(archives_dir, exist_ok=True)

            # 2. Scénario LLM :
            # Tour 1 : Le LLM décide d'appeler l'alias 'list_files' avec l'argument 'path'
            self.llm.queue_tool_call(
                tool_name='list_files',
                arguments={'path': sbox},
                call_id='call_list_1'
            )

            # Tour 2 : Après avoir reçu le listing, le LLM émet 3 appels parallèles avec alias 'move_files'
            # et synonymes d'arguments 'source' et 'destination'
            self.llm.queue_scenario([
                {
                    'tool_calls': [
                        {
                            'id': 'call_mv_1',
                            'type': 'function',
                            'function': {
                                'name': 'move_files',
                                'arguments': {'source': rep1, 'destination': archives_dir}
                            }
                        },
                        {
                            'id': 'call_mv_2',
                            'type': 'function',
                            'function': {
                                'name': 'move_file',
                                'arguments': {'src': rep2, 'dst': archives_dir}
                            }
                        },
                        {
                            'id': 'call_mv_3',
                            'type': 'function',
                            'function': {
                                'name': 'deplacer_fichier',
                                'arguments': {'file': rep3, 'target': archives_dir}
                            }
                        }
                    ]
                }
            ])

            # Réponse textuelle finale du LLM
            self.llm.queue_text_response("Les 3 rapports ont été déplacés dans le dossier archives avec succès.")

            # 3. Exécution via WebSocket client
            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()

                # Envoi de la demande de l'utilisateur
                prompt_user = "Range tous les rapports PDF du dossier dans archives."
                await client.send({'type': 'chat', 'prompt': prompt_user})

                # Attendre les notifications d'exécution d'actions système et la fin de génération
                all_msgs, done_msg = await client.receive_all_until_type('done', timeout=6.0)

                # Vérifier la présence des notifications système
                actions = [m['content'] for m in all_msgs if m.get('type') == 'system_action']
                self.assertTrue(any('list_files' in a for a in actions), "Action list_files non notifiée.")
                self.assertTrue(any('move' in a or 'deplacer' in a for a in actions), "Action move non notifiée.")

                # Vérifier la réponse terminée
                self.assertEqual(done_msg['type'], 'done')

                # 4. Assertions sur le disque (état du bac à sable)
                # Les 3 rapports doivent se trouver dans archives/
                arch_rep1 = os.path.join(archives_dir, "rapport_trimestriel_1.pdf")
                arch_rep2 = os.path.join(archives_dir, "rapport_trimestriel_2.pdf")
                arch_rep3 = os.path.join(archives_dir, "rapport_trimestriel_3.pdf")

                self.assertTrue(os.path.exists(arch_rep1), "rapport_trimestriel_1.pdf non trouvé dans archives.")
                self.assertTrue(os.path.exists(arch_rep2), "rapport_trimestriel_2.pdf non trouvé dans archives.")
                self.assertTrue(os.path.exists(arch_rep3), "rapport_trimestriel_3.pdf non trouvé dans archives.")

                # Les fichiers d'origine ont disparu de la racine
                self.assertFalse(os.path.exists(rep1))
                self.assertFalse(os.path.exists(rep2))
                self.assertFalse(os.path.exists(rep3))

                # Les fichiers hors-périmètre (non-rapports) sont strictement intacts à la racine
                self.assertTrue(os.path.exists(note), "notes.txt a été déplacé ou altéré par erreur.")
                self.assertTrue(os.path.exists(data), "data.csv a été déplacé ou altéré par erreur.")

                # 5. Assertions sur l'intégrité du Ring Buffer (B.7 / R2 / R3)
                contexte = api._messages_avec_fenetre()
                tool_call_ids = set()
                tool_response_ids = set()

                for m in contexte:
                    if m.get('role') == 'assistant' and m.get('tool_calls'):
                        for tc in m['tool_calls']:
                            tool_call_ids.add(tc['id'])
                    elif m.get('role') == 'tool':
                        tool_response_ids.add(m.get('tool_call_id'))

                # Vérifier qu'aucun tool call ou réponse n'est orphelin
                self.assertEqual(tool_call_ids, tool_response_ids, "Dissociation détectée dans le ring buffer de contexte.")
                self.assertIn('call_list_1', tool_call_ids)
                self.assertIn('call_mv_1', tool_call_ids)
                self.assertIn('call_mv_2', tool_call_ids)
                self.assertIn('call_mv_3', tool_call_ids)

                await client.close()
            finally:
                await self.server.stop()


if __name__ == '__main__':
    unittest.main()
