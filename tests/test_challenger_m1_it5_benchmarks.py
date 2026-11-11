"""Empirical Performance, Scalability and Robustness Benchmark Suite for api.py:441-473 clamp.
Teamwork Challenger Milestone 1 Iteration 5 (challenger_m1_it5_2).

Verification criteria:
1. Execution time across extreme workloads < 0.05s (50ms) per call:
   - 100k char prompt (with and without prior history and context metadata)
   - 50 turns history with interleaved tools
   - Multi-line tool outputs (1k, 5k, 10k lines)
   - Combined extreme scenario (50 turns + 100k prompt + massive tool outputs)
2. Zero tool dissociation across all test runs (B.7 invariant)
3. Total tokens strictly <= MAX_INPUT_TOKENS (3296)
"""

import time
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
                return False, f"Orphaned tool response at index {idx} with tool_call_id='{t_id}'"

    for idx, m in enumerate(optimized_messages):
        if m.get('role') == 'assistant' and m.get('tool_calls'):
            for tc in m['tool_calls']:
                tc_id = tc.get('id')
                has_child = any(sub.get('role') == 'tool' and sub.get('tool_call_id') == tc_id for sub in optimized_messages[idx+1:])
                if not has_child:
                    return False, f"Orphaned assistant tool_call at index {idx} with tool_call_id='{tc_id}'"

    return True, "OK"


class TestClampPerformanceAndScalability(unittest.TestCase):

    def setUp(self):
        self.all_tools = [ai.outils_disponibles['lister_fichiers'], ai.outils_disponibles['lire_fichier_securise']]
        self.tools_tokens = token_counter.estimer_tokens_outils(self.all_tools)
        self.heavy_ctx = {
            'fenetre_active': {'titre': 'Document Confidentiel de Recherche ' * 20, 'processus': 'code.exe'},
            'presse_papiers': 'SELECT data, hash, payload FROM secrets WHERE valid = 1;' * 15
        }
        self.heavy_etat = "RAM: 94% (60.2/64 GB) | CPU: 96% | VRAM: 88% (21.1/24 GB) | GPU: 91%"
        self.max_allowed_time = 0.05  # 50 ms budget per call

    def test_benchmark_100k_char_prompt_execution_time(self):
        """Workload 1: 100k char prompt with 0 prior turns and heavy context metadata.
        Target: execution time < 0.05s per call.
        """
        prompt_sizes = [50_000, 100_000, 150_000]
        iterations = 20

        for size in prompt_sizes:
            times = []
            prompt = "A" * size

            for _ in range(iterations):
                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': prompt}
                ]
                t0 = time.perf_counter()
                opt = api._messages_avec_fenetre(
                    etat_systeme=self.heavy_etat,
                    tools=self.all_tools,
                    ctx=self.heavy_ctx
                )
                elapsed = time.perf_counter() - t0
                times.append(elapsed)

                # Validate invariants
                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
                self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Sequence integrity error: {reason}")

            avg_time = sum(times) / len(times)
            max_time = max(times)
            print(f"\n[100k Char Prompt ({size:,} chars)] Avg: {avg_time*1000:.3f}ms | Max: {max_time*1000:.3f}ms | Budget: {self.max_allowed_time*1000:.1f}ms")
            self.assertLess(max_time, self.max_allowed_time, f"Execution time {max_time:.4f}s exceeded 0.05s budget for {size} chars")

    def test_benchmark_50_turns_history_with_tools(self):
        """Workload 2: 50 turns history with interleaved tool calls and responses.
        Target: execution time < 0.05s per call.
        """
        # Construct a massive 50-turn conversation
        conversation = [{'role': 'system', 'content': 'sys'}]
        for turn_idx in range(50):
            conversation.append({
                'role': 'user',
                'content': f"Demande utilisateur du tour {turn_idx}: exécute des diagnostics et analyse."
            })
            if turn_idx % 2 == 0:
                cid = f"call_{turn_idx}"
                conversation.append({
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [{
                        'id': cid,
                        'type': 'function',
                        'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}
                    }]
                })
                conversation.append({
                    'role': 'tool',
                    'tool_call_id': cid,
                    'name': 'lister_fichiers',
                    'content': f"rapport_audit_{turn_idx}_item.json\n" * 30
                })
                conversation.append({
                    'role': 'assistant',
                    'content': f"Tour {turn_idx} analysé avec succès."
                })
            else:
                c1 = f"call_multi_{turn_idx}_1"
                c2 = f"call_multi_{turn_idx}_2"
                conversation.append({
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [
                        {'id': c1, 'type': 'function', 'function': {'name': 'diagnostiquer_reseau', 'arguments': '{}'}},
                        {'id': c2, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}
                    ]
                })
                conversation.append({'role': 'tool', 'tool_call_id': c1, 'name': 'diagnostiquer_reseau', 'content': 'Ping 8.8.8.8: OK (8ms)'})
                conversation.append({'role': 'tool', 'tool_call_id': c2, 'name': 'lister_fichiers', 'content': 'file_a.txt\nfile_b.txt'})
                conversation.append({'role': 'assistant', 'content': f"Tour multi-outils {turn_idx} complété."})

        # Add active user prompt
        conversation.append({'role': 'user', 'content': 'Synthétise les 50 tours précédents et propose un plan d\'action.'})

        iterations = 20
        times = []
        for _ in range(iterations):
            api.messages = [dict(m) for m in conversation]
            t0 = time.perf_counter()
            opt = api._messages_avec_fenetre(
                etat_systeme=self.heavy_etat,
                tools=self.all_tools,
                ctx=self.heavy_ctx
            )
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

            total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
            self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
            valid, reason = validate_message_sequence_integrity(opt)
            self.assertTrue(valid, f"Dissociation in 50-turn history: {reason}")

        avg_time = sum(times) / len(times)
        max_time = max(times)
        print(f"\n[50-Turn History with Tools] Total msgs before clamp: {len(conversation)} | Avg: {avg_time*1000:.3f}ms | Max: {max_time*1000:.3f}ms | Budget: {self.max_allowed_time*1000:.1f}ms")
        self.assertLess(max_time, self.max_allowed_time, f"Execution time {max_time:.4f}s exceeded 0.05s budget for 50-turn history")

    def test_benchmark_multi_line_massive_tool_outputs(self):
        """Workload 3: Multi-line tool outputs in active turn and prior turns (1,000 to 10,000 lines).
        Target: execution time < 0.05s per call.
        """
        line_counts = [1000, 5000, 10000]
        iterations = 15

        for count in line_counts:
            lines = [f"ligne_{i:06d}: chemin/absolu/vers/fichier_de_donnees_{i}.log" for i in range(count)]
            tool_content = "\n".join(lines)

            times = []
            for _ in range(iterations):
                cid1 = "call_massive_1"
                cid2 = "call_massive_2"
                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'Exécute un scan volumineux'},
                    {
                        'role': 'assistant',
                        'content': None,
                        'tool_calls': [
                            {'id': cid1, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "logs"}'}},
                            {'id': cid2, 'type': 'function', 'function': {'name': 'lire_fichier_securise', 'arguments': '{"fichier": "trace.log"}'}}
                        ]
                    },
                    {'role': 'tool', 'tool_call_id': cid1, 'name': 'lister_fichiers', 'content': tool_content},
                    {'role': 'tool', 'tool_call_id': cid2, 'name': 'lire_fichier_securise', 'content': tool_content[:20000]},
                    {'role': 'assistant', 'content': 'mot ' * 2000}
                ]

                t0 = time.perf_counter()
                opt = api._messages_avec_fenetre(
                    etat_systeme=self.heavy_etat,
                    tools=self.all_tools,
                    ctx=self.heavy_ctx
                )
                elapsed = time.perf_counter() - t0
                times.append(elapsed)

                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
                self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Dissociation in massive tool outputs: {reason}")

            avg_time = sum(times) / len(times)
            max_time = max(times)
            print(f"\n[Multi-line Tool Outputs ({count:,} lines, {len(tool_content):,} chars)] Avg: {avg_time*1000:.3f}ms | Max: {max_time*1000:.3f}ms | Budget: {self.max_allowed_time*1000:.1f}ms")
            self.assertLess(max_time, self.max_allowed_time, f"Execution time {max_time:.4f}s exceeded 0.05s budget for {count} lines tool output")

    def test_benchmark_combined_extreme_workload(self):
        """Workload 4: Combined extreme workload:
        - 50 turns history with interleaved tools
        - Active user prompt of 100,000 characters
        - Multi-line tool outputs in prior and active turns
        - Heavy context metadata and system state
        Target: execution time < 0.05s per call, total tokens <= 3296, zero tool dissociation.
        """
        conversation = [{'role': 'system', 'content': 'sys'}]
        for turn_idx in range(50):
            conversation.append({
                'role': 'user',
                'content': f"Demande utilisateur du tour {turn_idx}: commande complexe " + ("X" * 100)
            })
            cid = f"call_comb_{turn_idx}"
            conversation.append({
                'role': 'assistant',
                'content': None,
                'tool_calls': [{
                    'id': cid,
                    'type': 'function',
                    'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}
                }]
            })
            conversation.append({
                'role': 'tool',
                'tool_call_id': cid,
                'name': 'lister_fichiers',
                'content': f"detail_tour_{turn_idx}_element.txt\n" * 40
            })
            conversation.append({
                'role': 'assistant',
                'content': f"Résultat tour {turn_idx} validé " * 10
            })

        # Add extreme active turn with 100k char prompt and multi-line tool calls
        active_cid = "call_active_extreme"
        conversation.append({'role': 'user', 'content': 'PROMPT EXTREME ' + ('Z' * 100_000)})
        conversation.append({
            'role': 'assistant',
            'content': None,
            'tool_calls': [{
                'id': active_cid,
                'type': 'function',
                'function': {'name': 'lister_fichiers', 'arguments': '{}'}
            }]
        })
        conversation.append({
            'role': 'tool',
            'tool_call_id': active_cid,
            'name': 'lister_fichiers',
            'content': "archive_dump_line\n" * 5000
        })

        iterations = 15
        times = []
        for _ in range(iterations):
            api.messages = [dict(m) for m in conversation]
            t0 = time.perf_counter()
            opt = api._messages_avec_fenetre(
                etat_systeme=self.heavy_etat,
                tools=self.all_tools,
                ctx=self.heavy_ctx
            )
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

            total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
            self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
            valid, reason = validate_message_sequence_integrity(opt)
            self.assertTrue(valid, f"Dissociation in combined extreme workload: {reason}")

        avg_time = sum(times) / len(times)
        max_time = max(times)
        p95_time = sorted(times)[int(len(times) * 0.95)]
        print(f"\n[Combined Extreme Workload (50 turns + 100k prompt + 5k lines tool)]")
        print(f"  Avg: {avg_time*1000:.3f}ms | p95: {p95_time*1000:.3f}ms | Max: {max_time*1000:.3f}ms | Budget: {self.max_allowed_time*1000:.1f}ms")
        self.assertLess(max_time, self.max_allowed_time, f"Execution time {max_time:.4f}s exceeded 0.05s budget under combined extreme workload")


if __name__ == '__main__':
    unittest.main()
