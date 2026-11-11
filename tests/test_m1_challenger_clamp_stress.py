"""Adversarial stress and verification harness for api.py:437-452.
Teamwork Challenger Milestone 1 Iteration 3 (challenger_m1_it3_1).

Evaluates:
1. Extreme prompt lengths (1k, 10k, 50k chars), multiple tools, and maximum context metadata.
2. Invariant total_tokens <= 3296.
3. Tool call / tool response pair atomicity during clamp reduction.
"""

import unittest
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
                return False, f"Orphaned tool response at index {idx} with tool_call_id='{t_id}' (preceding assistant tool_calls message was popped)"

    for idx, m in enumerate(optimized_messages):
        if m.get('role') == 'assistant' and m.get('tool_calls'):
            for tc in m['tool_calls']:
                tc_id = tc.get('id')
                has_child = any(sub.get('role') == 'tool' and sub.get('tool_call_id') == tc_id for sub in optimized_messages[idx+1:])
                if not has_child:
                    return False, f"Orphaned assistant tool_call at index {idx} with tool_call_id='{tc_id}' (subsequent tool response was popped)"

    return True, "OK"


class TestM1ChallengerClampStress(unittest.TestCase):

    def setUp(self):
        self.max_ctx = {
            'fenetre_active': {'titre': 'A' * 500, 'processus': 'B' * 100},
            'presse_papiers': 'C' * 400
        }
        self.max_etat = "RAM: 98% (31.4/32 GB) | CPU: 100% | VRAM: 95% | GPU: 99%"

    def test_extreme_prompts_and_context_metadata_clamp_invariant(self):
        """Empirically verify total_tokens <= 3296 across 1k, 10k, 50k chars with max context metadata."""
        tools = [ai.outils_disponibles['lister_fichiers'], ai.outils_disponibles['lire_fichier_securise']]
        tools_tokens = token_counter.estimer_tokens_outils(tools)

        for length in [1000, 10000, 50000]:
            api.messages = [
                {'role': 'system', 'content': 'sys'},
                {'role': 'user', 'content': 'X' * length}
            ]
            opt = api._messages_avec_fenetre(etat_systeme=self.max_etat, tools=tools, ctx=self.max_ctx)
            total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens
            self.assertLessEqual(
                total,
                token_counter.MAX_INPUT_TOKENS,
                f"Exceeded MAX_INPUT_TOKENS for prompt length {length}: {total} > {token_counter.MAX_INPUT_TOKENS}"
            )
            # Verify system prompt remains at index 0
            self.assertEqual(opt[0].get('role'), 'system')
            # Verify user prompt remains present
            self.assertTrue(any(m.get('role') == 'user' for m in opt))

    def test_repro_tool_call_dissociation_under_clamp(self):
        """Empirically exposes tool call / response dissociation bug in api.py:448-449.
        When user_msg has length <= 50, optimized.pop(1) removes messages sequentially
        instead of atomically, orphaning tool responses.
        """
        tools = [ai.outils_disponibles['lister_fichiers']]
        tools_tokens = token_counter.estimer_tokens_outils(tools)

        t1_tool_content = "fichier_test_data.txt\n" * 50
        asst_content = "mot " * 1820

        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'u1'},
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{
                    'id': 'call_dissoc_1820',
                    'type': 'function',
                    'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}
                }]
            },
            {
                'role': 'tool',
                'tool_call_id': 'call_dissoc_1820',
                'name': 'lister_fichiers',
                'content': t1_tool_content
            },
            {'role': 'assistant', 'content': asst_content},
            {'role': 'user', 'content': 'u2'}
        ]

        etat = "RAM 90%"
        ctx = None

        opt = api._messages_avec_fenetre(etat_systeme=etat, tools=tools, ctx=ctx)
        total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens

        self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)

        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"TOOL DISSOCIATION IN VIOLATION OF B.7: {reason}")

    def test_multiple_prior_turns_with_parallel_tool_calls(self):
        """Adversarial test: 5 prior turns with 3 parallel tool calls each,
        verifying atomic eviction preserves tool_call / tool_response pairs
        and bounds total tokens <= 3296.
        """
        tools = [ai.outils_disponibles['lister_fichiers']]
        tools_tokens = token_counter.estimer_tokens_outils(tools)

        messages = [{'role': 'system', 'content': 'sys'}]
        for t in range(5):
            messages.append({'role': 'user', 'content': f'user_prompt_{t}'})
            tcs = [
                {'id': f'call_{t}_{i}', 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}}
                for i in range(3)
            ]
            messages.append({'role': 'assistant', 'content': None, 'tool_calls': tcs})
            for i in range(3):
                messages.append({
                    'role': 'tool',
                    'tool_call_id': f'call_{t}_{i}',
                    'name': 'lister_fichiers',
                    'content': f'file_{t}_{i}.txt\n' * 20
                })
            messages.append({'role': 'assistant', 'content': f'summary_{t} ' * 400})

        messages.append({'role': 'user', 'content': 'active user prompt ' * 200})

        api.messages = messages
        opt = api._messages_avec_fenetre(tools=tools)
        total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens

        self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"Parallel tool call pairing integrity violated: {reason}")
        self.assertEqual(opt[0].get('role'), 'system')
        self.assertTrue(any(m.get('role') == 'user' for m in opt))

    def test_odd_token_boundaries_and_empty_payloads(self):
        """Adversarial test: tests exact token boundaries (3295, 3296, 3297 tokens),
        empty tool output, whitespace-only user prompt, and multi-tool active turns.
        """
        tools = [ai.outils_disponibles['lister_fichiers']]
        tools_tokens = token_counter.estimer_tokens_outils(tools)

        # 1. Empty tool content
        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'u'},
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{'id': 'call_empty_1', 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}]
            },
            {'role': 'tool', 'tool_call_id': 'call_empty_1', 'name': 'lister_fichiers', 'content': ''},
            {'role': 'user', 'content': '   '}
        ]
        opt = api._messages_avec_fenetre(tools=tools)
        total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens
        self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"Integrity failed on empty payload: {reason}")

        # 2. Odd token boundaries near 3296
        for offset in [-2, -1, 0, 1, 2, 10]:
            target_tokens = token_counter.MAX_INPUT_TOKENS + offset
            # create user prompt of length roughly target_tokens * 3.5
            prompt = "word " * int(target_tokens * 0.7)
            api.messages = [
                {'role': 'system', 'content': 'sys'},
                {'role': 'user', 'content': prompt}
            ]
            opt = api._messages_avec_fenetre(tools=tools)
            t_total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens
            self.assertLessEqual(t_total, token_counter.MAX_INPUT_TOKENS)

    def test_active_turn_large_tool_output_infinite_loop(self):
        """Adversarial stress challenge: An active turn with a tool output whose
        condensed format exceeds 150 chars (e.g. lister_fichiers with long paths,
        or executer_commande_systeme with stdout > 150 chars) MUST NOT trigger an
        infinite loop in api.py:451-460 Step 2.
        """
        import subprocess
        import sys

        code = '''
import api, ai
from core import token_counter

tools = [ai.outils_disponibles['lister_fichiers']]
tool_content = ('dummy_path/' + 'a' * 180 + '/file.txt' + chr(10)) * 10
asst_content = 'mot ' * 2500

api.messages = [
    {'role': 'system', 'content': 'sys'},
    {'role': 'user', 'content': 'liste'},
    {
        'role': 'assistant',
        'content': None,
        'tool_calls': [{
            'id': 'call_1',
            'type': 'function',
            'function': {'name': 'lister_fichiers', 'arguments': '{}'}
        }]
    },
    {
        'role': 'tool',
        'tool_call_id': 'call_1',
        'name': 'lister_fichiers',
        'content': tool_content
    },
    {'role': 'assistant', 'content': asst_content}
]
api._messages_avec_fenetre(tools=tools)
'''
        try:
            proc = subprocess.run([sys.executable, '-c', code], timeout=3.0, capture_output=True, text=True)
            if proc.returncode != 0:
                self.fail(f"Subprocess failed with error: {proc.stderr}")
        except subprocess.TimeoutExpired:
            self.fail(
                "CRITICAL DEFECT: api._messages_avec_fenetre hung in an infinite loop in api.py:451-460 "
                "(Step 2 condenses tool output but condensed result exceeds 150 chars, causing continuous re-selection)"
            )



if __name__ == '__main__':
    unittest.main()
