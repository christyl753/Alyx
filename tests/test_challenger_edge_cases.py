"""Empirical Challenger Test Suite for api.py:437-452.
Tests tool call/response atomicity, invariant token clamp (<= 3296),
and edge cases with context metadata and prompt lengths.
"""

import unittest
import api
import ai
from core import token_counter


def validate_message_sequence_integrity(optimized_messages):
    """Validates that:
    1. Every role='tool' message is preceded by an assistant message containing its tool_call_id.
    2. Every tool_call in an assistant message has a subsequent matching role='tool' message.
    3. No orphaned assistant or tool messages exist without valid turn structure.
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


class TestEmpiricalChallenger(unittest.TestCase):

    def test_scope_1_extreme_prompts_and_context_metadata(self):
        """Scope item 1 & 2: Test 1k, 10k, 50k chars with max context metadata.
        Total tokens must strictly be <= 3296.
        """
        tools = [ai.outils_disponibles['lister_fichiers'], ai.outils_disponibles['lire_fichier_securise']]
        tools_tokens = token_counter.estimer_tokens_outils(tools)
        ctx = {
            'fenetre_active': {'titre': 'A' * 500, 'processus': 'B' * 100},
            'presse_papiers': 'C' * 400
        }
        etat = "RAM: 98% | CPU: 100% | VRAM: 90%"

        for length in [1000, 10000, 50000]:
            api.messages = [
                {'role': 'system', 'content': 'sys'},
                {'role': 'user', 'content': 'X' * length}
            ]
            opt = api._messages_avec_fenetre(etat_systeme=etat, tools=tools, ctx=ctx)
            total = sum(token_counter.estimer_tokens_message(m) for m in opt) + tools_tokens
            self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS, f"Exceeded MAX_INPUT_TOKENS for prompt len {length}: {total} > {token_counter.MAX_INPUT_TOKENS}")

    def test_scope_3_tool_dissociation_under_clamp(self):
        """Scope item 3: Verify that tool calls and tool responses are never dissociated during clamp reduction.
        Fails if optimized.pop(1) at api.py:449 separates assistant tool_calls from tool responses.
        """
        tools = [ai.outils_disponibles['lister_fichiers']]
        tools_tokens = token_counter.estimer_tokens_outils(tools)

        # Precise calibration where Tour 1 has tool_calls + response + assistant answer,
        # Tour 2 has a short user prompt (<= 50 chars), and context metadata pushes
        # total tokens just beyond MAX_INPUT_TOKENS (3296).
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

        # Check total tokens <= 3296
        self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)

        # Check tool pairing integrity (Scope Item 3 & BLOC B.7)
        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"VIOLATION OF SCOPE ITEM 3 & BLOC B.7: {reason}")


if __name__ == '__main__':
    unittest.main()
