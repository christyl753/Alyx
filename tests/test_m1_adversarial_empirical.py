"""tests/test_m1_adversarial_empirical.py
Adversarial Stress Test Harness for Milestone 1 (Context Memory Budget, Multi-Tier Compaction & Persistence).
Written by challenger_m1_mem_1 to empirically test invariants, edge cases, and stress limits.
"""
import copy
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import ai
import api
from core import history, llm_provider, token_counter


class TestM1ContextTokenCapInvariant(unittest.TestCase):
    """Challenge 1: Stress test for token budget cap invariant across 50, 100, and 200 turns."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def _generate_turn_messages(self, turn_idx: int) -> list[dict]:
        """Generates a complete conversation turn with user prompt, assistant tool call, tool response, and final assistant reply."""
        call_id = f"call_turn_{turn_idx}_{time.time_ns()}"
        # Varied user prompt with French accents, numbers, paths
        user_msg = {
            'role': 'user',
            'content': f"Étape {turn_idx} : Veuillez analyser le répertoire C:\\Projets\\Lot_{turn_idx} et déplacer l'ensemble des rapports."
        }
        assistant_call_msg = {
            'role': 'assistant',
            'content': f"J'examine le dossier du lot {turn_idx}.",
            'tool_calls': [{
                'id': call_id,
                'type': 'function',
                'function': {
                    'name': 'lister_fichiers',
                    'arguments': json.dumps({'chemin': f"C:\\Projets\\Lot_{turn_idx}"})
                }
            }]
        }
        # Heavy tool output: 50 items, ~1500 characters
        tool_content = f"Contenu de C:\\Projets\\Lot_{turn_idx} (50 éléments):\n" + "\n".join(
            f"📄 rapport_mensuel_archive_{turn_idx}_{j:03d}.pdf" for j in range(50)
        )
        tool_resp_msg = {
            'role': 'tool',
            'name': 'lister_fichiers',
            'tool_name': 'lister_fichiers',
            'tool_call_id': call_id,
            'content': tool_content
        }
        assistant_final_msg = {
            'role': 'assistant',
            'content': f"Lot {turn_idx} analysé : 50 fichiers identifiés et prêts pour le traitement par lots."
        }
        return [user_msg, assistant_call_msg, tool_resp_msg, assistant_final_msg]

    def test_context_window_token_cap_at_every_turn_up_to_200(self):
        """Stress harness verifying <= MAX_INPUT_TOKENS (3296) at EVERY turn from 1 to 200."""
        selected_tools = [ai.outils_disponibles['lister_fichiers'], ai.outils_disponibles['deplacer_fichier']]
        tokens_tools = token_counter.estimer_tokens_outils(selected_tools)

        for turn in range(1, 201):
            turn_msgs = self._generate_turn_messages(turn)
            api.messages.extend(turn_msgs)

            # Test without tools
            contexte_sans_tools = api._messages_avec_fenetre()
            total_sans = sum(token_counter.estimer_tokens_message(m) for m in contexte_sans_tools)
            self.assertLessEqual(
                total_sans,
                token_counter.MAX_INPUT_TOKENS,
                f"[VIOLATION TOKEN CAP] Turn {turn} without tools: {total_sans} > {token_counter.MAX_INPUT_TOKENS}"
            )

            # Test with tools
            contexte_avec_tools = api._messages_avec_fenetre(tools=selected_tools)
            total_avec = sum(token_counter.estimer_tokens_message(m) for m in contexte_avec_tools)
            self.assertLessEqual(
                total_avec + tokens_tools,
                token_counter.MAX_INPUT_TOKENS,
                f"[VIOLATION TOKEN CAP + TOOLS] Turn {turn} with tools: {total_avec + tokens_tools} > {token_counter.MAX_INPUT_TOKENS}"
            )

            # Check point asserts at 50, 100, 200 turns
            if turn in (50, 100, 200):
                system_prompt = contexte_avec_tools[0]['content']
                self.assertIn(
                    "## Faits clés mémorisés des échanges précédents",
                    system_prompt,
                    f"Turn {turn}: Evicted facts note missing from system prompt"
                )


class TestM1AtomicToolPairInvariant(unittest.TestCase):
    """Challenge 2: BLOC B.7.6 invariant stress test: atomic tool pairs never severed."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def _verify_tool_pair_atomicity(self, window_messages: list[dict], context_desc: str):
        """Verifies that:
        1. No tool message is orphan (preceding message must be assistant with matching tool_calls id).
        2. No assistant message has missing tool responses in the active window.
        """
        for i, msg in enumerate(window_messages):
            if msg.get('role') == 'tool':
                self.assertGreater(
                    i, 0,
                    f"[{context_desc}] Tool message at index 0 has no preceding assistant message: {msg}"
                )
                # Find matching assistant message
                # It could be immediately preceding, or preceding before other sibling tool messages
                prev_msg = window_messages[i - 1]
                found_match = False
                # Walk backwards to find assistant
                k = i - 1
                while k >= 0:
                    cand = window_messages[k]
                    if cand.get('role') == 'assistant':
                        tc_list = cand.get('tool_calls') or []
                        tc_ids = [tc.get('id') for tc in tc_list if isinstance(tc, dict)]
                        if msg.get('tool_call_id') in tc_ids:
                            found_match = True
                        break
                    elif cand.get('role') == 'tool':
                        k -= 1
                    else:
                        break

                self.assertTrue(
                    found_match,
                    f"[{context_desc}] Tool message {msg.get('tool_call_id')} has no preceding assistant with matching tool_calls id (at index {i})"
                )

            elif msg.get('role') == 'assistant' and msg.get('tool_calls'):
                tc_list = msg['tool_calls']
                tc_ids = [tc.get('id') for tc in tc_list if isinstance(tc, dict)]
                # Look ahead for each tool call response
                # All responses must be present in the active window
                window_tool_resp_ids = set()
                k = i + 1
                while k < len(window_messages) and window_messages[k].get('role') == 'tool':
                    tid = window_messages[k].get('tool_call_id')
                    if tid:
                        window_tool_resp_ids.add(tid)
                    k += 1

                for expected_id in tc_ids:
                    self.assertIn(
                        expected_id,
                        window_tool_resp_ids,
                        f"[{context_desc}] Assistant message at index {i} has unfulfilled tool_call {expected_id} in active window!"
                    )

    def test_single_tool_call_per_turn_up_to_100_turns(self):
        """Verify tool pair atomicity across 100 turns with single tool calls."""
        for turn in range(1, 101):
            call_id = f"call_{turn}"
            api.messages.extend([
                {'role': 'user', 'content': f'Action {turn}'},
                {'role': 'assistant', 'content': '', 'tool_calls': [{'id': call_id, 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}]},
                {'role': 'tool', 'name': 'lister_fichiers', 'tool_call_id': call_id, 'content': f'resultat_{turn}'},
                {'role': 'assistant', 'content': f'Done {turn}'}
            ])
            contexte = api._messages_avec_fenetre()
            self._verify_tool_pair_atomicity(contexte, f"Single tool turn {turn}")

    def test_multi_tool_calls_in_single_assistant_message(self):
        """Verify tool pair atomicity when an assistant message issues MULTIPLE tool calls."""
        for turn in range(1, 40):
            c1 = f"call_{turn}_a"
            c2 = f"call_{turn}_b"
            c3 = f"call_{turn}_c"
            api.messages.extend([
                {'role': 'user', 'content': f'Multiple actions turn {turn}'},
                {
                    'role': 'assistant',
                    'content': f'Je lance 3 actions pour le tour {turn}',
                    'tool_calls': [
                        {'id': c1, 'function': {'name': 'lister_fichiers', 'arguments': '{"p": 1}'}},
                        {'id': c2, 'function': {'name': 'lire_fichier_securise', 'arguments': '{"p": 2}'}},
                        {'id': c3, 'function': {'name': 'deplacer_fichier', 'arguments': '{"p": 3}'}},
                    ]
                },
                {'role': 'tool', 'name': 'lister_fichiers', 'tool_call_id': c1, 'content': f'list_res_{turn} ' * 30},
                {'role': 'tool', 'name': 'lire_fichier_securise', 'tool_call_id': c2, 'content': f'read_res_{turn} ' * 30},
                {'role': 'tool', 'name': 'deplacer_fichier', 'tool_call_id': c3, 'content': f'move_res_{turn} ' * 30},
                {'role': 'assistant', 'content': f'Toutes les actions {turn} sont terminées.'}
            ])
            contexte = api._messages_avec_fenetre()
            self._verify_tool_pair_atomicity(contexte, f"Multi-tool turn {turn}")


class TestM1MassiveSinglePromptStress(unittest.TestCase):
    """Challenge 3: Massive single-prompt stress testing (50,000 characters)."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def test_massive_prompt_alone_50000_chars(self):
        """Single massive 50k prompt with dense punctuation, JSON, and emojis."""
        raw_parts = [
            "🚀🔥 ANALYSE COMPLEXE BATCH : ",
            '{"action": "batch_migration", "targets": ["rapport_1.pdf", "rapport_2.pdf"], "flags": {"deep": true, "recursive": true}}, ',
            "Vérification des chemins d'accès sous Windows C:\\Users\\tiant\\Dossier Spécial\\Fichiers & Documents — ",
            "Texte dense avec ponctuation abondante :: () {} [] // == != <= >= && || $#@!%^&* ~` "
        ]
        base_unit = "".join(raw_parts)
        repeat_count = (50000 // len(base_unit)) + 1
        massive_prompt = (base_unit * repeat_count)[:50000]
        self.assertEqual(len(massive_prompt), 50000)

        api.messages.append({'role': 'user', 'content': massive_prompt})

        contexte = api._messages_avec_fenetre()
        self.assertGreater(len(contexte), 1)

        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte)
        self.assertLessEqual(
            total_tokens,
            token_counter.MAX_INPUT_TOKENS,
            f"Massive prompt alone exceeded token cap: {total_tokens} > {token_counter.MAX_INPUT_TOKENS}"
        )

        user_msg = next(m for m in contexte if m.get('role') == 'user')
        self.assertIn("invite utilisateur tronquée pour respecter le budget de 3296 tokens", user_msg['content'])

    def test_massive_prompt_with_existing_heavy_history(self):
        """Massive 50k prompt injected AFTER 30 existing heavy turns."""
        for i in range(30):
            api.messages.extend([
                {'role': 'user', 'content': f'Tour préliminaire {i}'},
                {'role': 'assistant', 'content': f'Réponse préliminaire {i}'}
            ])

        massive_prompt = ("🚀 Prompt géant avec JSON et emojis " * 2000)[:50000]
        api.messages.append({'role': 'user', 'content': massive_prompt})

        contexte = api._messages_avec_fenetre()
        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte)
        self.assertLessEqual(
            total_tokens,
            token_counter.MAX_INPUT_TOKENS,
            f"Massive prompt with history exceeded token cap: {total_tokens} > {token_counter.MAX_INPUT_TOKENS}"
        )
        user_msg = next(m for m in reversed(contexte) if m.get('role') == 'user')
        self.assertIn("tronquée", user_msg['content'])


class TestM1TokenCounterBenchmark(unittest.TestCase):
    """Challenge 4: Token counter benchmark across 10,000 calls (< 0.1 ms average)."""

    def test_10000_calls_benchmark(self):
        sample_texts = [
            "Bonjour Alyx, déplace l'ensemble des fichiers rapports vers le dossier Archives.",
            '{"name": "deplacer_fichier", "arguments": {"chemin_source": "C:\\\\doc.pdf", "destination": "C:\\\\Arch"}}',
            "🚀🔥 Analyse approfondie de 500 fichiers logs avec détection d'anomalies B.7.6.",
            "a" * 500,
            "def foo(bar: int) -> bool:\n    return bar > 42 and bar != 100\n",
        ]
        sample_messages = [
            {'role': 'user', 'content': sample_texts[0]},
            {'role': 'assistant', 'content': sample_texts[1], 'tool_calls': [{'id': 'c1', 'function': {'name': 'deplacer', 'arguments': sample_texts[1]}}]},
            {'role': 'tool', 'name': 'deplacer', 'tool_call_id': 'c1', 'content': sample_texts[2]},
        ]

        N = 10000
        t0 = time.perf_counter()
        for i in range(N):
            txt = sample_texts[i % len(sample_texts)]
            msg = sample_messages[i % len(sample_messages)]
            token_counter.estimer_tokens_texte(txt)
            token_counter.estimer_tokens_message(msg)
        elapsed_sec = time.perf_counter() - t0

        avg_ms_per_call = (elapsed_sec / (N * 2)) * 1000
        print(f"\n[BENCHMARK] {N * 2} calls completed in {elapsed_sec:.4f}s — Average: {avg_ms_per_call:.5f} ms/call")
        self.assertLess(
            avg_ms_per_call,
            0.1,
            f"Token counter too slow: {avg_ms_per_call:.5f} ms >= 0.1 ms limit"
        )


class TestM1AdversarialEdgeCases(unittest.TestCase):
    """Adversarial stress and edge cases for compaction, history, and persistence."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_adv_history_")
        self._old_dossier_fn = history._dossier_historique
        history._dossier_historique = lambda: self.temp_dir

    def tearDown(self):
        api.messages[:] = self._orig_messages
        history._dossier_historique = self._old_dossier_fn
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_evicted_facts_note_does_not_cause_token_overflow(self):
        """Stress: Verify that compiling the evicted facts note cannot push total tokens over 3296."""
        # Create 15 turns where each turn has long user intent and multiple tool calls
        for i in range(15):
            api.messages.extend([
                {
                    'role': 'user',
                    'content': f"Opération complexe numéro {i} : migration complète des bases de données et sauvegarde des configurations système locales"
                },
                {
                    'role': 'assistant',
                    'content': f"Début d'exécution de l'étape {i}",
                    'tool_calls': [
                        {
                            'id': f"c_{i}_1",
                            'function': {
                                'name': 'deplacer_fichier',
                                'arguments': json.dumps({'src': f"C:\\data_{i}.db", 'dst': f"D:\\backup_{i}.db"})
                            }
                        },
                        {
                            'id': f"c_{i}_2",
                            'function': {
                                'name': 'lister_fichiers',
                                'arguments': json.dumps({'chemin': f"D:\\backup_{i}"})
                            }
                        }
                    ]
                },
                {'role': 'tool', 'name': 'deplacer_fichier', 'tool_call_id': f"c_{i}_1", 'content': f"Succès {i}"},
                {'role': 'tool', 'name': 'lister_fichiers', 'tool_call_id': f"c_{i}_2", 'content': f"5 fichiers listés {i}"},
                {'role': 'assistant', 'content': f"Étape {i} complètement achevée avec validation."}
            ])

        contexte = api._messages_avec_fenetre()
        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte)
        self.assertLessEqual(
            total_tokens,
            token_counter.MAX_INPUT_TOKENS,
            f"Evicted facts caused token cap violation: {total_tokens} > {token_counter.MAX_INPUT_TOKENS}"
        )

    def test_concurrent_rapid_session_persistence_without_corruption(self):
        """Stress: 100 rapid atomic writes and reads to session storage."""
        msgs = [
            {'role': 'system', 'content': 'Initial'},
            {'role': 'user', 'content': 'Test prompt'},
            {'role': 'assistant', 'content': 'Test response'}
        ]
        for i in range(100):
            msgs.append({'role': 'user', 'content': f'Iter {i}'})
            msgs.append({'role': 'assistant', 'content': f'Resp {i}'})
            ok = history.sauvegarder_etat_session(msgs, session_id="stress_session")
            self.assertTrue(ok)
            restored = history.charger_etat_session("stress_session")
            self.assertIsNotNone(restored)
            self.assertEqual(len(restored), len(msgs))

    def test_session_state_corrupted_json_graceful_recovery(self):
        """Inject garbage into session file and assert charger_etat_session recovers cleanly without throwing."""
        chemin = history._chemin_etat_session("broken_session")
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, 'wb') as f:
            f.write(b"\x00\xff\xfe\x12GarbageTruncatedJSON{")

        self.assertTrue(os.path.exists(chemin))
        restored = history.charger_etat_session("broken_session")
        self.assertIsNone(restored)
        # Corrupted file should be removed
        self.assertFalse(os.path.exists(chemin))


if __name__ == '__main__':
    unittest.main()
