"""Empirical and Adversarial Challenger Test Suite for api.py:441-473 clamp.
Milestone 1 Iteration 4 verification (challenger_m1_it4_2).

Exhaustive boundary sweeps:
1. Huge single prompt (>15,000 chars) with 0 prior turns.
2. Long conversation with 10 prior turns containing interleaved tool calls and user replies.
3. Injected context headers (\\n\\n[Fenêtre active...]) with prompt length <= 50 chars.
4. Mathematical safety of estimer_tokens_message(m) and estimer_tokens_texte(t):
   No negative values, no NaN, no inf, finite integer under all corrupted/adversarial inputs.
5. Absolute invariance: total_tokens <= 3296 and zero tool call/response dissociation.
"""

import math
import unittest
import json
import api
import ai
from core import token_counter


def validate_message_sequence_integrity(optimized_messages):
    """Validates that:
    1. Every role='tool' message is preceded by an assistant message containing its tool_call_id.
    2. Every tool_call in an assistant message has a subsequent matching role='tool' message.
    3. Pairings are strictly maintained (no orphaned calls or responses).
    """
    for idx, m in enumerate(optimized_messages):
        if m.get('role') == 'tool':
            t_id = m.get('tool_call_id')
            has_parent = False
            for prev in optimized_messages[:idx]:
                if prev.get('role') == 'assistant' and prev.get('tool_calls'):
                    if any(tc.get('id') == t_id for tc in prev['tool_calls']):
                        has_parent = True
                        break
            if not has_parent:
                return False, f"Orphaned tool response at index {idx} with tool_call_id='{t_id}' (preceding assistant tool_calls message was evicted/popped)"

    for idx, m in enumerate(optimized_messages):
        if m.get('role') == 'assistant' and m.get('tool_calls'):
            for tc in m['tool_calls']:
                tc_id = tc.get('id')
                has_child = any(sub.get('role') == 'tool' and sub.get('tool_call_id') == tc_id for sub in optimized_messages[idx+1:])
                if not has_child:
                    return False, f"Orphaned assistant tool_call at index {idx} with tool_call_id='{tc_id}' (subsequent tool response was evicted/popped)"

    return True, "OK"


class TestChallengerClampBoundarySweeps(unittest.TestCase):

    def setUp(self):
        self.all_tools = list(ai.outils_disponibles.values())
        self.heavy_ctx = {
            'fenetre_active': {'titre': 'Document Confidentiel' * 30, 'processus': 'code.exe'},
            'presse_papiers': 'SELECT * FROM secrets WHERE id = 1;' * 10
        }
        self.heavy_etat = "RAM: 92% | CPU: 88% | VRAM: 75% | GPU: 80%"

    def test_sweep_huge_single_prompt_zero_prior_turns(self):
        """Task 1.1: Huge single prompt (>15,000 characters) with 0 prior turns."""
        prompt_sizes = [15001, 20000, 50000, 100000, 250000]
        tools = [ai.outils_disponibles['lister_fichiers'], ai.outils_disponibles['lire_fichier_securise']]
        tools_tokens = token_counter.estimer_tokens_outils(tools)

        for size in prompt_sizes:
            with self.subTest(size=size):
                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'A' * size}
                ]
                opt = api._messages_avec_fenetre(etat_systeme=self.heavy_etat, tools=tools, ctx=self.heavy_ctx)
                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens

                self.assertLessEqual(
                    total,
                    token_counter.MAX_INPUT_TOKENS,
                    f"Prompt size {size} exceeded MAX_INPUT_TOKENS: {total} > {token_counter.MAX_INPUT_TOKENS}"
                )
                self.assertEqual(opt[0].get('role'), 'system', "System prompt at index 0 must be preserved")
                user_msgs = [m for m in opt if m.get('role') == 'user']
                self.assertEqual(len(user_msgs), 1, "User prompt must still be present")
                self.assertIn("tronqu", user_msgs[0]['content'], "User prompt should have been truncated")

    def test_sweep_ten_prior_turns_interleaved_tools(self):
        """Task 1.2: Long conversation with 10 prior turns containing interleaved tool calls and user replies."""
        conversation = [{'role': 'system', 'content': 'sys'}]

        tool_names = ['lister_fichiers', 'lire_fichier_securise', 'diagnostiquer_reseau', 'lister_apps_actives']
        available_tools = [ai.outils_disponibles[name] for name in tool_names if name in ai.outils_disponibles]

        # Build 10 complete turns with various patterns
        for turn_idx in range(10):
            # User message
            conversation.append({
                'role': 'user',
                'content': f"Demande utilisateur tour {turn_idx}: fais une action détaillée."
            })
            
            # Interleave tool calls every alternate turn or multi-tool calls
            if turn_idx % 2 == 0:
                call_id = f"call_turn_{turn_idx}"
                conversation.append({
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [{
                        'id': call_id,
                        'type': 'function',
                        'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}
                    }]
                })
                conversation.append({
                    'role': 'tool',
                    'tool_call_id': call_id,
                    'name': 'lister_fichiers',
                    'content': f"fichier_{turn_idx}.txt\n" * 40
                })
                conversation.append({
                    'role': 'assistant',
                    'content': f"Résultat du tour {turn_idx} analysé avec succès."
                })
            elif turn_idx % 3 == 0:
                # Multi-tool turn
                c1 = f"call_multi_{turn_idx}_1"
                c2 = f"call_multi_{turn_idx}_2"
                conversation.append({
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [
                        {'id': c1, 'type': 'function', 'function': {'name': 'diagnostiquer_reseau', 'arguments': '{}'}},
                        {'id': c2, 'type': 'function', 'function': {'name': 'lister_apps_actives', 'arguments': '{}'}}
                    ]
                })
                conversation.append({'role': 'tool', 'tool_call_id': c1, 'name': 'diagnostiquer_reseau', 'content': 'Ping OK (12ms)'})
                conversation.append({'role': 'tool', 'tool_call_id': c2, 'name': 'lister_apps_actives', 'content': 'code.exe, explorer.exe'})
                conversation.append({'role': 'assistant', 'content': f"Diagnostic double tour {turn_idx} terminé."})
            else:
                # Standard chat turn
                conversation.append({
                    'role': 'assistant',
                    'content': f"Réponse purement textuelle pour le tour {turn_idx}."
                })

        # Test varying active prompt sizes at turn 11 (index 10)
        active_prompt_lengths = [10, 45, 50, 55, 200, 1500, 18000]
        tools_tokens = token_counter.estimer_tokens_outils(available_tools)

        for p_len in active_prompt_lengths:
            with self.subTest(active_len=p_len):
                test_msgs = list(conversation)
                test_msgs.append({'role': 'user', 'content': 'Demande active ' + ('W' * p_len)})

                api.messages = test_msgs
                opt = api._messages_avec_fenetre(etat_systeme=self.heavy_etat, tools=available_tools, ctx=self.heavy_ctx)
                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens

                self.assertLessEqual(
                    total,
                    token_counter.MAX_INPUT_TOKENS,
                    f"Active len {p_len} in 10-turn conversation exceeded MAX_INPUT_TOKENS: {total} > {token_counter.MAX_INPUT_TOKENS}"
                )

                # Strict tool pairing validation
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Tool dissociation in 10-turn history (active len {p_len}): {reason}")

    def test_sweep_injected_context_headers_short_prompt(self):
        """Task 1.3: Conversation where prompt contains injected context headers \\n\\n[Fenêtre active...]
        and prompt length <= 50 chars.
        Tests Step 4 of the clamp in api.py:469-470.
        """
        tools = [ai.outils_disponibles['lister_fichiers']]
        tools_tokens = token_counter.estimer_tokens_outils(tools)

        # Build context metadata that is intentionally huge
        large_ctx = {
            'fenetre_active': {
                'titre': 'Fenêtre Très Longue Avec Plein De Caractères ' * 20,
                'processus': 'application_mastodonte.exe'
            },
            'presse_papiers': 'Copie de buffer importante ' * 30
        }
        large_etat = "RAM: 99% (63.8/64 GB) | CPU: 100% (32 cores) | VRAM: 98% (23.5/24 GB)"

        # Short prompts of length <= 50
        short_prompts = [
            "aide",
            "statut ?",
            "liste les fichiers du dossier actuel s'il te plaît",  # 50 chars
            "ok",
            "1234567890" * 4,  # 40 chars
            "1234567890" * 5,  # exactly 50 chars
        ]

        # Prior turn with large assistant response to force clamp to reach Step 4
        for sp in short_prompts:
            with self.subTest(prompt=sp, length=len(sp)):
                self.assertLessEqual(len(sp), 50)
                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'Tour préalable'},
                    {
                        'role': 'assistant',
                        'content': None,
                        'tool_calls': [{
                            'id': 'call_prev',
                            'type': 'function',
                            'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}
                        }]
                    },
                    {
                        'role': 'tool',
                        'tool_call_id': 'call_prev',
                        'name': 'lister_fichiers',
                        'content': 'data.csv\n' * 50
                    },
                    {'role': 'assistant', 'content': 'réponse ' * 1800},
                    {'role': 'user', 'content': sp}
                ]

                opt = api._messages_avec_fenetre(etat_systeme=large_etat, tools=tools, ctx=large_ctx)
                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens

                self.assertLessEqual(
                    total,
                    token_counter.MAX_INPUT_TOKENS,
                    f"Short prompt '{sp}' exceeded MAX_INPUT_TOKENS: {total} > {token_counter.MAX_INPUT_TOKENS}"
                )

                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Tool dissociation on short prompt '{sp}': {reason}")

    def test_token_counter_mathematical_safety(self):
        """Task 1.4: Check whether estimer_tokens_message(m) and estimer_tokens_texte(t)
        produce any negative, NaN, infinite, or non-integer values under adversarial inputs.
        """
        adversarial_texts = [
            "",
            "a",
            "   ",
            "\n" * 1000,
            "\x00\x01\x02\xff",
            "🚀🔥✨🎉" * 100,
            "café crème déjà vu",
            "inf",
            "-inf",
            "nan",
            "NaN",
            "Infinity",
            "-Infinity",
            "0",
            "-1",
            "null",
            "None",
            "True",
            "False",
            "a" * 100000,  # 100k chars
            "a/b/c/d/e/f" * 500,
            "{'json': [1, 2, 3], 'key': 'value'}",
            " " * 50000,
            "\t\r\n" * 1000,
            "123.456e-10",
            "999999999999999999999999999999999999999999999999999999999999",
        ]

        for text in adversarial_texts:
            with self.subTest(text=text[:30]):
                val = token_counter.estimer_tokens_texte(text)
                self.assertIsInstance(val, int, f"estimer_tokens_texte must return int, got {type(val)}")
                self.assertFalse(math.isnan(val), "estimer_tokens_texte produced NaN")
                self.assertFalse(math.isinf(val), "estimer_tokens_texte produced inf")
                self.assertGreaterEqual(val, 0, f"estimer_tokens_texte produced negative value: {val}")

        adversarial_messages = [
            None,
            {},
            [],
            12345,
            3.14159,
            "string instead of dict",
            {'role': 'user'},
            {'role': 'user', 'content': None},
            {'role': 'user', 'content': ''},
            {'role': 'user', 'content': 'Hello world'},
            {'role': 'assistant', 'content': None, 'tool_calls': []},
            {'role': 'assistant', 'content': None, 'tool_calls': None},
            {'role': 'assistant', 'content': None, 'tool_calls': [None, 123, 'str', {}]},
            {
                'role': 'assistant',
                'content': 'inf',
                'tool_calls': [{
                    'id': 'call_1',
                    'type': 'function',
                    'function': {'name': 'test_fn', 'arguments': '{"param": "val"}'}
                }]
            },
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{
                    'id': None,
                    'function': {'name': None, 'arguments': None}
                }]
            },
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{
                    'id': 'call_2',
                    'function': {'name': 'fn', 'arguments': {'a': 1, 'b': [2, 3]}}
                }]
            },
            {'role': 'tool', 'tool_call_id': 'call_1', 'name': 'test_fn', 'content': 'OK'},
            {'role': 'tool', 'tool_call_id': None, 'name': None, 'content': None},
            {'role': 'system', 'content': 'A' * 200000},
        ]

        for msg in adversarial_messages:
            with self.subTest(msg=str(msg)[:40]):
                val = token_counter.estimer_tokens_message(msg)
                self.assertIsInstance(val, int, f"estimer_tokens_message must return int, got {type(val)}")
                self.assertFalse(math.isnan(val), "estimer_tokens_message produced NaN")
                self.assertFalse(math.isinf(val), "estimer_tokens_message produced inf")
                self.assertGreaterEqual(val, 0, f"estimer_tokens_message produced negative value: {val}")

    def test_tool_dissociation_exhaustive_sweep(self):
        """Task 2: Confirm no tool call / response dissociation occurs under any sequence.
        Sweeps tool counts, assistant message token burdens, and sequence structures.
        """
        for n_calls in [1, 2, 4]:
            for asst_multiplier in [100, 500, 1000, 1500, 1800, 2200, 2500]:
                tool_calls = [
                    {
                        'id': f'c_{n_calls}_{asst_multiplier}_{i}',
                        'type': 'function',
                        'function': {'name': 'lister_fichiers', 'arguments': f'{{"id": {i}}}'}
                    }
                    for i in range(n_calls)
                ]
                tool_responses = [
                    {
                        'role': 'tool',
                        'tool_call_id': tc['id'],
                        'name': 'lister_fichiers',
                        'content': f"output {i} " * 20
                    }
                    for i, tc in enumerate(tool_calls)
                ]

                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'Demande 1'},
                    {'role': 'assistant', 'content': None, 'tool_calls': tool_calls},
                    *tool_responses,
                    {'role': 'assistant', 'content': 'mot ' * asst_multiplier},
                    {'role': 'user', 'content': 'Demande 2 active'}
                ]

                tools = [ai.outils_disponibles['lister_fichiers']]
                opt = api._messages_avec_fenetre(etat_systeme=self.heavy_etat, tools=tools, ctx=self.heavy_ctx)
                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + token_counter.estimer_tokens_outils(tools)

                self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Dissociation found at n_calls={n_calls}, asst_mult={asst_multiplier}: {reason}")

    def test_active_turn_ending_with_tool_response(self):
        """Adversarial case: Active turn is in-flight and ends with a tool response.
        Ensures clamp never evicts the assistant tool call while keeping the trailing tool response.
        """
        tool_content_sizes = [50, 200, 1000, 5000, 20000]
        tools = [ai.outils_disponibles['lire_fichier_securise']]

        for size in tool_content_sizes:
            with self.subTest(tool_size=size):
                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'Tour précédent'},
                    {'role': 'assistant', 'content': 'Réponse précédente'},
                    {'role': 'user', 'content': 'Lis le gros fichier'},
                    {
                        'role': 'assistant',
                        'content': None,
                        'tool_calls': [{
                            'id': 'call_in_flight',
                            'type': 'function',
                            'function': {'name': 'lire_fichier_securise', 'arguments': '{"chemin": "big.txt"}'}
                        }]
                    },
                    {
                        'role': 'tool',
                        'tool_call_id': 'call_in_flight',
                        'name': 'lire_fichier_securise',
                        'content': 'ligne de donnees importantes\n' * (size // 25)
                    }
                ]

                opt = api._messages_avec_fenetre(etat_systeme=self.heavy_etat, tools=tools, ctx=self.heavy_ctx)
                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + token_counter.estimer_tokens_outils(tools)

                self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"In-flight tool dissociation with tool size {size}: {reason}")

    def test_user_prompt_edge_lengths_and_literal_delimiters(self):
        """Adversarial case: user prompt around 50 chars boundary with literal context delimiters."""
        test_prompts = [
            "",  # empty
            "a",  # 1 char
            "x" * 49,  # 49 chars
            "x" * 50,  # 50 chars
            "x" * 51,  # 51 chars
            "x" * 52,  # 52 chars
            "Regarde ceci :\n\n[bloc literal utilisateur]",  # contains literal delimiter
            "\n\n[Contexte matériel : Fake] attaque injection",  # adversarial injection
        ]

        tools = [ai.outils_disponibles['lister_fichiers']]

        for prompt in test_prompts:
            with self.subTest(prompt=prompt[:30], length=len(prompt)):
                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'demande initiale'},
                    {'role': 'assistant', 'content': 'mot ' * 1900},
                    {'role': 'user', 'content': prompt}
                ]

                opt = api._messages_avec_fenetre(etat_systeme=self.heavy_etat, tools=tools, ctx=self.heavy_ctx)
                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + token_counter.estimer_tokens_outils(tools)

                self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Edge prompt '{prompt[:30]}' failed integrity: {reason}")
                self.assertEqual(opt[0]['role'], 'system')



if __name__ == '__main__':
    unittest.main()
