"""Adversarial stress and verification harness for api.py:441-476.
Teamwork Challenger Milestone 1 Iteration 5 (challenger_m1_it5_1).

Evaluates:
1. Combinations of 1 to 5 large tool responses in active turn.
2. Verification that each tool response is condensed AT MOST ONCE inside the clamp.
3. Unconditional termination (no infinite loop under any combination).
4. Invariants: total_tokens <= 3296 and tool call/response pairing intact.
"""

import unittest
import traceback
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
                return False, f"Orphaned tool response at index {idx} with tool_call_id='{t_id}'"

    for idx, m in enumerate(optimized_messages):
        if m.get('role') == 'assistant' and m.get('tool_calls'):
            for tc in m['tool_calls']:
                tc_id = tc.get('id')
                has_child = any(sub.get('role') == 'tool' and sub.get('tool_call_id') == tc_id for sub in optimized_messages[idx+1:])
                if not has_child:
                    return False, f"Orphaned assistant tool_call at index {idx} with tool_call_id='{tc_id}'"

    return True, "OK"


class TestM1ChallengerMultiToolClampStress(unittest.TestCase):

    def setUp(self):
        self.tools = [
            ai.outils_disponibles['lister_fichiers'],
            ai.outils_disponibles['lire_fichier_securise'],
            ai.outils_disponibles['executer_commande_systeme'],
        ]
        self.tools_tokens = token_counter.estimer_tokens_outils(self.tools)

    def test_active_turn_1_to_5_large_tools_condensed_at_most_once_in_clamp(self):
        """Verify for 1 to 5 large tools in active turn:
        1. Loop terminates unconditionally.
        2. Inside the clamp (api.py:441-473 Step 2), each tool is condensed AT MOST ONCE.
        3. Pairing integrity is 100% intact.
        4. Loop safety net functions cleanly.
        """
        for num_tools in range(1, 6):
            with self.subTest(num_tools=num_tools):
                tcs = []
                tool_msgs = []
                for i in range(num_tools):
                    cid = f"call_clamp_{num_tools}_{i}"
                    tcs.append({
                        'id': cid,
                        'type': 'function',
                        'function': {'name': 'lister_fichiers', 'arguments': f'{{"dir": "{i}"}}'}
                    })
                    # Pathological string where first line > 180 chars, so post-Tier 4 length > 150
                    long_first_line = "path/" + ("a" * 180) + f"/file_{i}.txt"
                    body = ("extra_line_" + ("b" * 80) + "\n") * 10
                    tool_msgs.append({
                        'role': 'tool',
                        'tool_call_id': cid,
                        'name': 'lister_fichiers',
                        'content': f"{long_first_line}\n{body}"
                    })

                asst_msg = {
                    'role': 'assistant',
                    'content': 'mot ' * 2500,  # Forces clamp entry
                    'tool_calls': tcs
                }
                user_msg = {'role': 'user', 'content': 'u'}

                api.messages = [
                    {'role': 'system', 'content': 'system prompt'},
                    user_msg,
                    asst_msg,
                    *tool_msgs
                ]

                orig_condenser = api._condenser_retour_outil
                clamp_calls = []

                def instrumented_condenser(nom, content, max_chars=150):
                    for frame in traceback.extract_stack():
                        if frame.filename.endswith('api.py') and 450 <= frame.lineno <= 465:
                            clamp_calls.append((nom, content))
                            break
                    return orig_condenser(nom, content, max_chars)

                api._condenser_retour_outil = instrumented_condenser
                try:
                    opt = api._messages_avec_fenetre(tools=self.tools)
                finally:
                    api._condenser_retour_outil = orig_condenser

                # 1. Termination check
                self.assertIsNotNone(opt)

                # 2. Inside clamp, exactly num_tools were condensed (at most once per tool)
                self.assertEqual(
                    len(clamp_calls),
                    num_tools,
                    f"Expected exactly {num_tools} clamp condensations, got {len(clamp_calls)}"
                )

                # Verify each tool was condensed at most once
                self.assertEqual(len(clamp_calls), len(set(clamp_calls)))

                # 3. Pairing integrity intact
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Pairing integrity broken for num_tools={num_tools}: {reason}")

    def test_mixed_size_tools_in_clamp_selection(self):
        """Active turn with 5 tools:
        - 3 tools have length <= 150 chars.
        - 2 tools have length > 150 chars (with first line > 150).
        Only the 2 large tools should be condensed in Step 2 of the clamp, each at most once.
        """
        tcs = [
            {'id': 'c0', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
            {'id': 'c1', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
            {'id': 'c2', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
            {'id': 'c3', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
            {'id': 'c4', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
        ]
        tool_msgs = [
            {'role': 'tool', 'tool_call_id': 'c0', 'name': 'lister_fichiers', 'content': 'short_0_' + 'x' * 50},
            {'role': 'tool', 'tool_call_id': 'c1', 'name': 'lister_fichiers', 'content': 'long_1_' + 'y' * 180 + '\nmore'},
            {'role': 'tool', 'tool_call_id': 'c2', 'name': 'lister_fichiers', 'content': 'short_2_' + 'z' * 40},
            {'role': 'tool', 'tool_call_id': 'c3', 'name': 'lister_fichiers', 'content': 'long_3_' + 'w' * 200 + '\nmore'},
            {'role': 'tool', 'tool_call_id': 'c4', 'name': 'lister_fichiers', 'content': 'short_4_' + 'q' * 30},
        ]

        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'u'},
            {'role': 'assistant', 'content': 'mot ' * 2500, 'tool_calls': tcs},
            *tool_msgs
        ]

        orig_condenser = api._condenser_retour_outil
        clamp_calls = []

        def instrumented_condenser(nom, content, max_chars=150):
            for frame in traceback.extract_stack():
                if frame.filename.endswith('api.py') and 450 <= frame.lineno <= 465:
                    clamp_calls.append((nom, content[:30]))
                    break
            return orig_condenser(nom, content, max_chars)

        api._condenser_retour_outil = instrumented_condenser
        try:
            opt = api._messages_avec_fenetre(tools=self.tools)
        finally:
            api._condenser_retour_outil = orig_condenser

        # Exactly 2 calls in the clamp (for c1 and c3)
        self.assertEqual(len(clamp_calls), 2)

        # Pairing integrity
        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"Pairing integrity violated: {reason}")

    def test_multi_turn_history_plus_5_tools_in_active_turn(self):
        """Adversarial combination: 4 complete prior turns followed by an active turn
        containing 5 large tool responses.
        Atomic turn eviction must prune older turns, then condense active tools at most once,
        preserving all invariants.
        """
        messages = [{'role': 'system', 'content': 'sys'}]

        # Add 4 prior turns
        for t in range(4):
            messages.append({'role': 'user', 'content': f'Prior user turn {t}' * 30})
            messages.append({'role': 'assistant', 'content': f'Prior asst response {t}' * 200})

        # Active turn with 5 tools
        tcs = []
        tool_msgs = []
        for i in range(5):
            cid = f"call_prior_active_{i}"
            tcs.append({
                'id': cid,
                'type': 'function',
                'function': {'name': 'executer_commande_systeme', 'arguments': f'{{"cmd": "dir {i}"}}'}
            })
            tool_msgs.append({
                'role': 'tool',
                'tool_call_id': cid,
                'name': 'executer_commande_systeme',
                'content': ("Directory listing output row " + "z" * 120 + "\n") * 50
            })

        active_asst = {
            'role': 'assistant',
            'content': None,
            'tool_calls': tcs
        }
        active_user = {'role': 'user', 'content': 'Check everything ' * 100}

        messages.extend([active_user, active_asst, *tool_msgs])
        api.messages = messages

        opt = api._messages_avec_fenetre(tools=self.tools)

        # Invariant validations
        total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
        self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)

        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"Pairing integrity violated: {reason}")
        self.assertEqual(opt[0]['role'], 'system')

    def test_massive_payload_50k_chars_5_tools_termination(self):
        """Adversarial stress: Active turn with 5 tools having 50,000 characters each,
        along with a 50,000 character user prompt and maximum context metadata.
        Verifies termination in < 0.5s, tokens bounded, pairing intact.
        """
        import time

        tcs = []
        tool_msgs = []
        for i in range(5):
            cid = f"call_massive_{i}"
            tcs.append({
                'id': cid,
                'type': 'function',
                'function': {'name': 'lire_fichier_securise', 'arguments': f'{{"f": "{i}"}}'}
            })
            tool_msgs.append({
                'role': 'tool',
                'tool_call_id': cid,
                'name': 'lire_fichier_securise',
                'content': f"Massive payload header {i} " + ("DATA_" * 10000)
            })

        api.messages = [
            {'role': 'system', 'content': 'sys prompt'},
            {'role': 'user', 'content': 'MASSIVE USER PROMPT ' * 2500},
            {'role': 'assistant', 'content': 'calling massive tools', 'tool_calls': tcs},
            *tool_msgs
        ]

        t0 = time.perf_counter()
        opt = api._messages_avec_fenetre(tools=self.tools)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, 0.5, f"Clamp took too long: {elapsed:.3f}s")
        total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
        self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)

        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"Pairing integrity broken: {reason}")

    def test_idempotence_and_no_state_leakage_across_100_runs(self):
        """Ensure that running _messages_avec_fenetre 100 times in succession
        does not leak state across runs (outils_deja_condenses is per-invocation).
        """
        for run_idx in range(100):
            tcs = [{'id': f'c_{run_idx}', 'type': 'function', 'function': {'name': 'lister_fichiers'}}]
            tool_msgs = [{
                'role': 'tool',
                'tool_call_id': f'c_{run_idx}',
                'name': 'lister_fichiers',
                'content': ('path/' + 'a' * 180 + f'/run_{run_idx}.txt\n') * 10
            }]
            api.messages = [
                {'role': 'system', 'content': 'sys'},
                {'role': 'user', 'content': 'test'},
                {'role': 'assistant', 'content': 'mot ' * 2500, 'tool_calls': tcs},
                *tool_msgs
            ]
            opt = api._messages_avec_fenetre(tools=self.tools)
            self.assertIsNotNone(opt)
            valid, reason = validate_message_sequence_integrity(opt)
            self.assertTrue(valid, f"Integrity broken on iteration {run_idx}: {reason}")

    def test_tool_content_none_and_dict_and_empty(self):
        """Adversarial types: None, dict, int, empty string in tool content."""
        tcs = [
            {'id': 'c_none', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
            {'id': 'c_dict', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
            {'id': 'c_int', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
            {'id': 'c_empty', 'type': 'function', 'function': {'name': 'lister_fichiers'}},
        ]
        tool_msgs = [
            {'role': 'tool', 'tool_call_id': 'c_none', 'name': 'lister_fichiers', 'content': None},
            {'role': 'tool', 'tool_call_id': 'c_dict', 'name': 'lister_fichiers', 'content': {'status': 'success'}},
            {'role': 'tool', 'tool_call_id': 'c_int', 'name': 'lister_fichiers', 'content': 12345},
            {'role': 'tool', 'tool_call_id': 'c_empty', 'name': 'lister_fichiers', 'content': ''},
        ]
        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'test'},
            {'role': 'assistant', 'content': 'mot ' * 2500, 'tool_calls': tcs},
            *tool_msgs
        ]
        opt = api._messages_avec_fenetre(tools=self.tools)
        self.assertIsNotNone(opt)
        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"Integrity broken on strange types: {reason}")

    def test_turn_with_no_user_message_clamp_termination(self):
        """Clamp termination when active turn has assistant + tool responses but NO user message."""
        tcs = [{'id': 'c_no_user', 'type': 'function', 'function': {'name': 'lister_fichiers'}}]
        tool_msgs = [{
            'role': 'tool',
            'tool_call_id': 'c_no_user',
            'name': 'lister_fichiers',
            'content': ('path/' + 'a' * 180 + '/f.txt\n') * 10
        }]
        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'assistant', 'content': 'mot ' * 2500, 'tool_calls': tcs},
            *tool_msgs
        ]
        opt = api._messages_avec_fenetre(tools=self.tools)
        self.assertIsNotNone(opt)
        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"Integrity broken with no user message: {reason}")

    def test_tools_schema_tokens_alone_exceed_max_tokens(self):
        """Adversarial case: Mock tools such that tools_tokens exceeds MAX_INPUT_TOKENS.
        Clamp must reach Step 5 'break' without infinite loop.
        """
        fake_huge_tools = [{'name': f'tool_{i}', 'description': 'desc ' * 50} for i in range(100)]
        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'u'}
        ]
        # Should terminate immediately via break
        opt = api._messages_avec_fenetre(tools=fake_huge_tools)
        self.assertIsNotNone(opt)
        self.assertEqual(opt[0]['role'], 'system')



if __name__ == '__main__':
    unittest.main()
