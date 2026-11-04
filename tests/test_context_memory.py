"""tests/test_context_memory.py
Suite de tests complète pour la gestion de la mémoire de contexte, budget de tokens,
compactage multi-paliers et persistance atomique de session (Milestone 1 - R1).
Conforme aux exigences BLOC B.1, B.2, B.6, B.7, B.8 et PROJECT.md.
"""
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch, MagicMock

# Contexte racine
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import ai
import api
from core import history, llm_provider, token_counter
from tests.e2e.harness import AirGapAssertionProbe


class TestTokenCounterText(unittest.TestCase):
    """Tests unitaires pour l'heuristique de comptage de tokens en pur Python."""

    def test_empty_string(self):
        self.assertEqual(token_counter.estimer_tokens_texte(""), 0)
        self.assertEqual(token_counter.estimer_tokens_texte(None), 0)

    def test_short_string(self):
        self.assertEqual(token_counter.estimer_tokens_texte("a"), 1)
        self.assertEqual(token_counter.estimer_tokens_texte("bon"), 1)

    def test_french_accents_and_contractions(self):
        texte = "Bonjour Alyx, déplace l'ensemble des fichiers créés récemment vers l'archive."
        tokens = token_counter.estimer_tokens_texte(texte)
        # 12 mots, accents et contractions -> ratio conservateur BPE
        self.assertGreaterEqual(tokens, 15)
        self.assertLessEqual(tokens, 35)

    def test_json_and_code_density(self):
        code = '{"name": "deplacer_fichier", "arguments": {"chemin_source": "C:\\\\doc.pdf"}}'
        tokens = token_counter.estimer_tokens_texte(code)
        # Symboles et ponctuation abondante -> densité élevée
        self.assertGreaterEqual(tokens, 25)

    def test_dense_unspaced_string_fallback(self):
        # Chaîne hexadécimale dense sans espaces
        dense = "a" * 80
        tokens = token_counter.estimer_tokens_texte(dense)
        # Garde-fou (n + 3) // 4 -> au moins 20 tokens pour 80 caractères
        self.assertGreaterEqual(tokens, 20)

    def test_execution_speed_benchmark(self):
        texte = ("Bonjour Alyx ! Analyse le dossier C:\\Rapports et classe les documents T4_2025.\n" * 20)
        t0 = time.perf_counter()
        N = 500
        for _ in range(N):
            token_counter.estimer_tokens_texte(texte)
        duree_ms = (time.perf_counter() - t0) / N * 1000
        # Exigence stricte : < 0.1 ms par appel
        self.assertLess(duree_ms, 0.1, f"Échec de performance token counter: {duree_ms:.4f} ms >= 0.1 ms")


class TestTokenCounterMessageAndTools(unittest.TestCase):
    """Tests d'estimation de tokens pour les messages et schémas d'outils."""

    def test_non_dict_message_returns_zero(self):
        self.assertEqual(token_counter.estimer_tokens_message(None), 0)
        self.assertEqual(token_counter.estimer_tokens_message("string"), 0)

    def test_user_message_overhead(self):
        msg = {'role': 'user', 'content': 'Bonjour Alyx'}
        tokens = token_counter.estimer_tokens_message(msg)
        # Cadrage ChatML (4) + contenu (3) = ~7 tokens
        self.assertGreaterEqual(tokens, 6)

    def test_tool_calls_message(self):
        msg = {
            'role': 'assistant',
            'content': 'Exécution en cours',
            'tool_calls': [{
                'id': 'call_1',
                'type': 'function',
                'function': {'name': 'deplacer_fichier', 'arguments': {'src': 'a', 'dst': 'b'}}
            }]
        }
        tokens = token_counter.estimer_tokens_message(msg)
        self.assertGreater(tokens, 20)

    def test_tool_result_message(self):
        msg = {
            'role': 'tool',
            'name': 'deplacer_fichier',
            'tool_name': 'deplacer_fichier',
            'tool_call_id': 'call_1',
            'content': 'Fichier déplacé avec succès.'
        }
        tokens = token_counter.estimer_tokens_message(msg)
        self.assertGreater(tokens, 15)

    def test_tool_definitions_estimation(self):
        self.assertEqual(token_counter.estimer_tokens_outils(None), 0)
        self.assertEqual(token_counter.estimer_tokens_outils([]), 0)

        tools = [ai.outils_disponibles['deplacer_fichier']]
        tokens = token_counter.estimer_tokens_outils(tools)
        self.assertGreater(tokens, 30)
        # Vérification alias
        self.assertEqual(token_counter.estimer_tokens_tools(tools), tokens)


class TestProviderContextPropagation(unittest.TestCase):
    """Vérification de la transmission de num_ctx et max_tokens aux fournisseurs."""

    def test_stream_ollama_passes_num_ctx(self):
        with patch('core.llm_provider._post_stream') as mock_post:
            mock_post.return_value.iter_lines.return_value = [b'{"message": {"content": "ok"}, "done": true}']
            list(llm_provider._stream_ollama("llama3:8b", [{'role': 'user', 'content': 'hi'}], None))
            mock_post.assert_called_once()
            payload = mock_post.call_args[0][2]
            self.assertIn("options", payload)
            self.assertEqual(payload["options"].get("num_ctx"), 4096)

    def test_stream_openai_passes_num_ctx_and_max_tokens(self):
        with patch('core.llm_provider._post_stream') as mock_post:
            mock_post.return_value.iter_lines.return_value = [b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\ndata: [DONE]\n\n']
            list(llm_provider._stream_openai("lmstudio", "model-local", [{'role': 'user', 'content': 'hi'}], None))
            mock_post.assert_called_once()
            payload = mock_post.call_args[0][2]
            self.assertEqual(payload.get("num_ctx"), 4096)
            self.assertEqual(payload.get("max_tokens"), 800)

    def test_stream_openai_retry_fallback_on_400_removes_num_ctx(self):
        with patch('core.llm_provider._post_stream') as mock_post:
            mock_resp_ok = MagicMock()
            mock_resp_ok.iter_lines.return_value = [b'data: {"choices": [{"delta": {"content": "ok"}}]}\n\ndata: [DONE]\n\n']

            # Premier appel échoue avec HTTP 400 (strict validator), deuxième appel réussit
            mock_post.side_effect = [
                Exception("Erreur lmstudio (HTTP 400): Unknown field num_ctx"),
                mock_resp_ok
            ]

            list(llm_provider._stream_openai("lmstudio", "model-strict", [{'role': 'user', 'content': 'hi'}], None))
            self.assertEqual(mock_post.call_count, 2)
            premier_payload = mock_post.call_args_list[0][0][2]
            deuxieme_payload = mock_post.call_args_list[1][0][2]
            self.assertIn("num_ctx", premier_payload)
            self.assertNotIn("num_ctx", deuxieme_payload)


class TestMultiTierContextCompaction(unittest.TestCase):
    """Validation du compactage multi-paliers et partitionnement en tours atomiques."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def test_partitionnement_en_tours_integre_outils_atomiquement(self):
        """Vérifie que _partitionner_en_tours regroupe user, assistant tool_calls et tool responses dans le même tour."""
        msgs = [
            {'role': 'user', 'content': 'T1 user'},
            {'role': 'assistant', 'content': 'T1 resp'},
            {'role': 'user', 'content': 'T2 user'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}]},
            {'role': 'tool', 'name': 'lister_fichiers', 'tool_call_id': 'c1', 'content': 'fichiers'},
            {'role': 'assistant', 'content': 'T2 final'},
        ]
        tours = api._partitionner_en_tours(msgs)
        self.assertEqual(len(tours), 2)
        self.assertEqual(len(tours[0]), 2)
        self.assertEqual(len(tours[1]), 4)
        # Aucune paire disséquée
        self.assertEqual(tours[1][1]['tool_calls'][0]['id'], tours[1][2]['tool_call_id'])

    def test_tier1_compactage_outils_anciens_preserve_champs_et_appariement(self):
        """Tier 1 condense le contenu d'un outil ancien sans altérer tool_call_id ni name."""
        # Tour 1 ancien avec retour d'outil massif (3 000 caractères)
        gros_contenu = "Contenu de C:/Dossier (150 éléments):\n" + "\n".join(f"📄 f_{i}.txt" for i in range(150))
        api.messages.append({'role': 'user', 'content': 'Liste le dossier'})
        api.messages.append({
            'role': 'assistant',
            'content': '',
            'tool_calls': [{'id': 'call_abc', 'function': {'name': 'lister_fichiers', 'arguments': '{"chemin": "C:/Dossier"}'}}]
        })
        api.messages.append({
            'role': 'tool',
            'name': 'lister_fichiers',
            'tool_name': 'lister_fichiers',
            'tool_call_id': 'call_abc',
            'content': gros_contenu
        })
        api.messages.append({'role': 'assistant', 'content': 'Voici les fichiers.'})

        # Tours 2 et 3 (récents) avec du volume pour déclencher le Tier 1 (> 3296 tokens)
        api.messages.append({'role': 'user', 'content': 'Crée le sous-dossier Archives ' + ('détail ' * 150)})
        api.messages.append({'role': 'assistant', 'content': 'Dossier créé. ' + ('rapport ' * 150)})
        api.messages.append({'role': 'user', 'content': 'Déplace tout dedans ' + ('action ' * 150)})

        contexte = api._messages_avec_fenetre()
        msg_tool = next(m for m in contexte if m.get('role') == 'tool')

        # Invariants stricts
        self.assertEqual(msg_tool['tool_call_id'], 'call_abc')
        self.assertEqual(msg_tool['name'], 'lister_fichiers')
        self.assertLess(len(msg_tool['content']), 250)
        self.assertIn("éléments détaillés omis", msg_tool['content'])

    def test_tier2_eviction_genere_note_faits_cles_dans_system_prompt(self):
        """Vérifie que les tours évincés sont convertis en faits structurés dans system_prompt."""
        for i in range(8):
            api.messages.append({'role': 'user', 'content': f'Action étape {i}: traite le fichier rapport_{i}.pdf ' + ('détail ' * 60)})
            api.messages.append({'role': 'assistant', 'content': f'Rapport {i} traité avec succès. ' + ('résumé ' * 60)})

        contexte = api._messages_avec_fenetre()
        system_content = contexte[0]['content']

        self.assertIn("## Faits clés mémorisés des échanges précédents", system_content)
        self.assertIn("rapport_0.pdf", system_content)

    def test_tier3_preservation_verbatim_des_derniers_tours(self):
        """Vérifie que les 2 derniers tours ne subissent aucune altération."""
        for i in range(5):
            api.messages.append({'role': 'user', 'content': f'Message verbatim {i}'})
            api.messages.append({'role': 'assistant', 'content': f'Réponse verbatim {i}'})

        contexte = api._messages_avec_fenetre()
        self.assertEqual(contexte[-2]['content'], 'Message verbatim 4')
        self.assertEqual(contexte[-1]['content'], 'Réponse verbatim 4')

    def test_20_heavy_turns_strictly_bounded_under_3296_tokens(self):
        """Vérifie que 25 tours volumineux avec outils restent strictement sous 3296 tokens."""
        for i in range(25):
            api.messages.append({'role': 'user', 'content': f'Tour {i} : Lister et ranger les fichiers du lot {i}'})
            call_id = f'call_{i}'
            api.messages.append({
                'role': 'assistant',
                'content': '',
                'tool_calls': [{'id': call_id, 'function': {'name': 'lister_fichiers', 'arguments': f'{{"chemin": "C:/lot_{i}"}}'}}]
            })
            api.messages.append({
                'role': 'tool',
                'name': 'lister_fichiers',
                'tool_name': 'lister_fichiers',
                'tool_call_id': call_id,
                'content': f'Contenu de C:/lot_{i} (50 éléments):\n' + '\n'.join(f'📄 doc_{i}_{j}.dat' for j in range(50))
            })
            api.messages.append({'role': 'assistant', 'content': f'Lot {i} traité avec 50 fichiers identifiés.'})

        contexte = api._messages_avec_fenetre()
        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte)
        self.assertLessEqual(total_tokens, token_counter.MAX_INPUT_TOKENS)
        self.assertLessEqual(total_tokens, 3296)
        # Vérifier la présence de la note mémorisée
        self.assertIn("## Faits clés mémorisés des échanges précédents", contexte[0]['content'])

    def test_resistance_stress_100_tours_borne_et_zero_crash(self):
        """Vérifie que 100 tours ne provoquent aucun crash et respectent la borne MAX_INPUT_TOKENS."""
        for i in range(100):
            api.messages.append({'role': 'user', 'content': f'Requête utilisateur {i}'})
            api.messages.append({'role': 'assistant', 'content': f'Réponse assistant {i}'})

        contexte = api._messages_avec_fenetre()
        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte)
        self.assertLessEqual(total_tokens, token_counter.MAX_INPUT_TOKENS)
        self.assertLessEqual(total_tokens, 3296)

    def test_filet_de_securite_invite_massive(self):
        """Vérifie le clamp d'urgence lorsqu'une invite utilisateur unique dépasse la capacité totale."""
        massive_prompt = "Exécute cette tâche avec ce texte gigantesque : " + ("analyse_fichier_très_long " * 1500)
        api.messages.append({'role': 'user', 'content': massive_prompt})

        contexte = api._messages_avec_fenetre()
        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte)
        self.assertLessEqual(total_tokens, token_counter.MAX_INPUT_TOKENS)
        user_msg = next(m for m in contexte if m.get('role') == 'user')
        self.assertIn("invite utilisateur tronquée pour respecter le budget de 3296 tokens", user_msg['content'])


class TestSessionPersistenceAtomic(unittest.TestCase):
    """Validation de la persistance atomique de session et restauration d'état."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_test_persistence_")
        self._old_dossier_fn = history._dossier_historique
        history._dossier_historique = lambda: self.temp_dir

    def tearDown(self):
        history._dossier_historique = self._old_dossier_fn
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sauvegarder_et_charger_roundtrip(self):
        """Vérifie l'égalité stricte aller-retour des messages incluant tool_calls."""
        messages_test = [
            {"role": "system", "content": "Prompt système initial"},
            {"role": "user", "content": "Liste mes fichiers récents"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_12345",
                        "type": "function",
                        "function": {"name": "lister_fichiers", "arguments": {"chemin": "."}}
                    }
                ]
            },
            {
                "role": "tool",
                "content": '["fichier1.txt", "rapport.pdf"]',
                "name": "lister_fichiers",
                "tool_call_id": "call_12345"
            },
            {"role": "assistant", "content": "Voici vos fichiers : fichier1.txt et rapport.pdf"}
        ]

        ok = history.sauvegarder_etat_session(messages_test, "session_active")
        self.assertTrue(ok)

        fichier = os.path.join(self.temp_dir, "active_session_state.json")
        self.assertTrue(os.path.isfile(fichier))

        restaures = history.charger_etat_session("session_active")
        self.assertIsNotNone(restaures)
        self.assertEqual(len(restaures), len(messages_test))
        self.assertEqual(restaures, messages_test)

    def test_ecriture_atomique_sans_corruption(self):
        """Vérifie qu'un échec d'écriture ne corrompt pas l'état existant."""
        messages_initiaux = [{"role": "user", "content": "Bonjour Alyx"}]
        history.sauvegarder_etat_session(messages_initiaux, "session_active")

        # Simulation d'une coupure/erreur lors du json.dump
        with patch("json.dump", side_effect=IOError("Disque plein simulé")):
            ok = history.sauvegarder_etat_session([{"role": "user", "content": "Coupé"}], "session_active")
            self.assertFalse(ok)

        # Vérification que le fichier initial est resté intact
        restaures = history.charger_etat_session("session_active")
        self.assertEqual(restaures, messages_initiaux)

        # Vérification qu'aucun fichier .tmp orphelin ne subsiste
        tmps = [f for f in os.listdir(self.temp_dir) if f.endswith(".tmp")]
        self.assertEqual(tmps, [])

    def test_recuperation_fichier_corrompu_fallback(self):
        """Vérifie le repli propre sur None en cas de JSON tronqué ou corrompu."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        with open(chemin, "w", encoding="utf-8") as f:
            f.write('{"version": 1, "messages": [{"role": "user", "con')  # JSON tronqué

        res = history.charger_etat_session("session_active")
        self.assertIsNone(res)
        # Le fichier corrompu a été purgé pour éviter les boucles d'erreur
        self.assertFalse(os.path.exists(chemin))

    def test_recuperation_fichier_vide_0_octet(self):
        """Vérifie la robustesse face à un fichier de 0 octet."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        open(chemin, "w").close()
        self.assertEqual(os.path.getsize(chemin), 0)

        res = history.charger_etat_session("session_active")
        self.assertIsNone(res)

    def test_recuperation_json_non_liste(self):
        """Vérifie qu'un format inattendu retourne None."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump({"messages": "ceci_nest_pas_une_liste"}, f)

        res = history.charger_etat_session("session_active")
        self.assertIsNone(res)

    def test_expiration_session_ancienne(self):
        """Vérifie que les sessions de plus de max_age_heures sont ignorées."""
        messages = [{"role": "user", "content": "Session d'il y a 2 jours"}]
        history.sauvegarder_etat_session(messages, "session_active")

        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        age_passe = time.time() - (25 * 3600)

        # Modifie le timestamp dans le payload et l'os.utime
        with open(chemin, 'r', encoding='utf-8') as f:
            d = json.load(f)
        d['saved_at'] = age_passe
        with open(chemin, 'w', encoding='utf-8') as f:
            json.dump(d, f)
        os.utime(chemin, (age_passe, age_passe))

        # À 24h d'expiration, retourne None
        self.assertIsNone(history.charger_etat_session("session_active", max_age_heures=24))
        # À 48h de tolérance, retourne les messages
        self.assertIsNotNone(history.charger_etat_session("session_active", max_age_heures=48))

    def test_reinitialiser_etat_session_idempotent(self):
        """Vérifie la suppression sur disque et l'idempotence."""
        history.sauvegarder_etat_session([{"role": "user", "content": "test"}], "session_active")
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        self.assertTrue(os.path.exists(chemin))

        history.reinitialiser_etat_session("session_active")
        self.assertFalse(os.path.exists(chemin))
        self.assertIsNone(history.charger_etat_session("session_active"))

        # Deuxième appel sans erreur
        history.reinitialiser_etat_session("session_active")

    def test_anti_traversee_repertoire(self):
        """Vérifie que les identifiants malveillants ne sortent pas du dossier."""
        nom_sanitise = history._sanitiser_session_id("../../etc/passwd")
        self.assertNotIn("..", nom_sanitise)
        self.assertNotIn("/", nom_sanitise)
        self.assertNotIn("\\", nom_sanitise)
        self.assertEqual(nom_sanitise, "passwd")

    def test_air_gap_zero_network_io(self):
        """Vérifie avec AirGapAssertionProbe qu'aucune communication externe n'est émise."""
        with AirGapAssertionProbe():
            messages = [{"role": "user", "content": "Message ultra confidentiel air-gapped"}]
            ok = history.sauvegarder_etat_session(messages, "session_active")
            self.assertTrue(ok)
            restaures = history.charger_etat_session("session_active")
            self.assertEqual(restaures, messages)
            history.reinitialiser_etat_session("session_active")

    def test_multi_os_chemin_resolution(self):
        """Vérifie la conformité de résolution des chemins Windows et Linux (B.8)."""
        # Test Windows
        with patch("sys.platform", "win32"), patch.dict(os.environ, {"APPDATA": os.path.join(self.temp_dir, "FakeAppData")}):
            dossier_win = self._old_dossier_fn()
            self.assertTrue(dossier_win.startswith(os.path.join(self.temp_dir, "FakeAppData")))
            self.assertTrue(dossier_win.endswith(os.path.join("Alyx", "history")))

        # Test Linux avec XDG_CONFIG_HOME
        with patch("sys.platform", "linux"), patch.dict(os.environ, {"XDG_CONFIG_HOME": os.path.join(self.temp_dir, "FakeConfig")}):
            dossier_linux = self._old_dossier_fn()
            self.assertTrue(dossier_linux.startswith(os.path.join(self.temp_dir, "FakeConfig")))
            self.assertTrue(dossier_linux.endswith(os.path.join("Alyx", "history")))

    def test_restaurer_etat_session_integration(self):
        """Vérifie que api.restaurer_etat_session restaure les tours et conserve le prompt frais."""
        orig = list(api.messages)
        try:
            del api.messages[1:]
            sauvegarde = [
                {"role": "system", "content": "Ancien prompt système périmé"},
                {"role": "user", "content": "Restaure-moi s'il te plaît"},
                {"role": "assistant", "content": "Te revoici !"}
            ]
            history.sauvegarder_etat_session(sauvegarde, "session_active")

            nb = api.restaurer_etat_session("session_active")
            self.assertEqual(nb, 2)
            self.assertEqual(len(api.messages), 3)
            # Le prompt système d'index 0 n'a PAS été remplacé par l'ancien prompt périmé
            self.assertNotEqual(api.messages[0]['content'], "Ancien prompt système périmé")
            self.assertEqual(api.messages[1]['content'], "Restaure-moi s'il te plaît")
            self.assertEqual(api.messages[2]['content'], "Te revoici !")
        finally:
            api.messages[:] = orig


if __name__ == "__main__":
    unittest.main()
