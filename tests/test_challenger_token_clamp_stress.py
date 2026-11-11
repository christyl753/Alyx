"""Adversarial stress harness for api.py:437-452 token clamp under extreme conditions.
Empirically verifies:
1. In 100% of test cases, total_tokens <= 3296.
2. Tool calls and tool responses are never dissociated during clamp reduction.
3. Extreme prompt lengths (1k, 10k, 50k chars), multiple tools, and maximum context metadata.
"""

import unittest
import itertools
from datetime import datetime
import api
import ai
from core import token_counter


def validate_tool_integrity(optimized_messages):
    """Verifies that tool_calls and tool responses are strictly paired and not dissociated."""
    # 1. Check orphaned tool responses
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
                return False, f"Orphaned tool response at index {idx} with tool_call_id='{t_id}' without preceding assistant tool_calls"

    # 2. Check orphaned assistant tool_calls
    for idx, m in enumerate(optimized_messages):
        if m.get('role') == 'assistant' and m.get('tool_calls'):
            for tc in m['tool_calls']:
                tc_id = tc.get('id')
                has_child = any(sub.get('role') == 'tool' and sub.get('tool_call_id') == tc_id for sub in optimized_messages[idx+1:])
                if not has_child:
                    return False, f"Orphaned assistant tool_call at index {idx} with tool_call_id='{tc_id}' without subsequent tool response"

    return True, "OK"


class TestAdversarialTokenClampStress(unittest.TestCase):

    def setUp(self):
        self.all_tools = list(ai.outils_disponibles.values())
        self.max_ctx = {
            'fenetre_active': {
                'titre': 'A' * 500,
                'processus': 'B' * 100
            },
            'presse_papiers': 'C' * 400
        }
        self.max_etat = "RAM: 98% (31.4/32 GB) | CPU: 99.9% (16 cores) | VRAM: 95% (22.8/24 GB) | GPU: 100% | TEMP: 89C"

    def _eval_clamp(self, test_name, messages, tools, ctx, etat):
        api.messages = list(messages)
        opt = api._messages_avec_fenetre(etat_systeme=etat, tools=tools, ctx=ctx)
        
        # Calculate total tokens
        tokens_tools = token_counter.estimer_tokens_outils(tools) if tools else 0
        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in opt) + tokens_tools

        # 1. Invariant check: total_tokens <= 3296
        self.assertLessEqual(
            total_tokens,
            token_counter.MAX_INPUT_TOKENS,
            f"[{test_name}] Invariant breach: total_tokens={total_tokens} > {token_counter.MAX_INPUT_TOKENS}"
        )

        # 2. Tool integrity check
        valid_tools, reason = validate_tool_integrity(opt)
        self.assertTrue(valid_tools, f"[{test_name}] Tool dissociation detected: {reason}")

        return total_tokens, opt

    def test_extreme_prompt_lengths_single_turn(self):
        """Test extreme prompt lengths: 1k, 10k, 50k, 100k chars with max context and tools."""
        lengths = [1000, 10000, 50000, 100000]
        tool_counts = [0, 1, 3, 10, len(self.all_tools)]

        for length in lengths:
            for n_tools in tool_counts:
                tools = self.all_tools[:n_tools] if n_tools > 0 else None
                messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'X' * length}
                ]
                name = f"single_turn_len_{length}_tools_{n_tools}"
                total, opt = self._eval_clamp(name, messages, tools, self.max_ctx, self.max_etat)
                self.assertGreater(len(opt), 1)

    def test_multi_turn_with_tool_pairs_and_varying_user_lengths(self):
        """Test multi-turn histories containing tool calls paired with tool responses under various prompt sizes."""
        user_prompt_lengths = [5, 25, 45, 50, 55, 100, 500, 1000, 10000, 50000]
        
        for u_len in user_prompt_lengths:
            # Construct a conversation with 3 turns:
            # Turn 1: user + assistant (tool_calls) + tool response
            # Turn 2: user + assistant text
            # Turn 3: user (length u_len)
            messages = [
                {'role': 'system', 'content': 'sys'},
                {'role': 'user', 'content': 'Première demande'},
                {
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [{
                        'id': f'call_turn1_{u_len}',
                        'type': 'function',
                        'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}
                    }]
                },
                {
                    'role': 'tool',
                    'tool_call_id': f'call_turn1_{u_len}',
                    'name': 'lister_fichiers',
                    'content': 'item.txt\n' * 50
                },
                {'role': 'assistant', 'content': 'Voici les fichiers.'},
                {'role': 'user', 'content': 'Deuxième demande'},
                {'role': 'assistant', 'content': 'Réponse intermédiaire.'},
                {'role': 'user', 'content': 'K' * u_len}
            ]
            tools = [ai.outils_disponibles['lister_fichiers'], ai.outils_disponibles['lire_fichier_securise']]
            name = f"multi_turn_tool_pairs_user_len_{u_len}"
            total, opt = self._eval_clamp(name, messages, tools, self.max_ctx, self.max_etat)

    def test_consecutive_tool_calls_in_same_turn(self):
        """Test multiple tool calls within a single assistant turn."""
        messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'Effectue plusieurs actions'},
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [
                    {'id': 'c1', 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}},
                    {'id': 'c2', 'type': 'function', 'function': {'name': 'diagnostiquer_reseau', 'arguments': '{}'}},
                    {'id': 'c3', 'type': 'function', 'function': {'name': 'lister_apps_actives', 'arguments': '{}'}}
                ]
            },
            {'role': 'tool', 'tool_call_id': 'c1', 'name': 'lister_fichiers', 'content': 'f.txt\n'*100},
            {'role': 'tool', 'tool_call_id': 'c2', 'name': 'diagnostiquer_reseau', 'content': 'OK\n'*50},
            {'role': 'tool', 'tool_call_id': 'c3', 'name': 'lister_apps_actives', 'content': 'app1, app2\n'*50},
            {'role': 'assistant', 'content': 'Toutes les actions sont terminées.'},
            {'role': 'user', 'content': 'Z' * 20000}
        ]
        tools = self.all_tools[:5]
        total, opt = self._eval_clamp("multi_tool_calls_same_turn", messages, tools, self.max_ctx, self.max_etat)

    def test_adversarial_crafted_token_boundary_sweep(self):
        """Sweep token boundaries around MAX_INPUT_TOKENS (3200 to 3500 tokens in steps of 10)."""
        # We craft messages that land right at the budget threshold
        for target_margin in range(-150, 250, 15):
            # Target token count around 3296 + target_margin
            content_len = max(50, (3296 + target_margin - 500) * 4)
            messages = [
                {'role': 'system', 'content': 'sys'},
                {'role': 'user', 'content': 'U' * content_len}
            ]
            tools = [ai.outils_disponibles['lister_fichiers']]
            name = f"boundary_sweep_margin_{target_margin}"
            total, opt = self._eval_clamp(name, messages, tools, self.max_ctx, self.max_etat)

    def test_deep_history_eviction_with_note_faits(self):
        """Test a deep 30-turn history where note_faits is heavily populated and evicted."""
        messages = [{'role': 'system', 'content': 'sys'}]
        for i in range(25):
            messages.append({'role': 'user', 'content': f'Étape utilisateur numéro {i} avec détails importants {i*100}'})
            messages.append({'role': 'assistant', 'content': f'Réponse assistant pour étape {i} avec confirmation.'})
        # Final massive user prompt
        messages.append({'role': 'user', 'content': 'Demande finale ' + ('W' * 15000)})
        tools = self.all_tools[:3]
        total, opt = self._eval_clamp("deep_history_eviction_note_faits", messages, tools, self.max_ctx, self.max_etat)


if __name__ == '__main__':
    unittest.main()
