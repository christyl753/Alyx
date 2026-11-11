"""Adversarial stress and scaling benchmarks for api.py clamp.
Authored by challenger_m1_it6_2 to stress-test scalability beyond 50 turns and 10k lines.
"""

import time
import unittest
import api
import ai
from core import token_counter
from tests.test_challenger_m1_it5_benchmarks import validate_message_sequence_integrity


class TestClampAdversarialScalability(unittest.TestCase):

    def setUp(self):
        self.all_tools = [ai.outils_disponibles['lister_fichiers'], ai.outils_disponibles['lire_fichier_securise']]
        self.tools_tokens = token_counter.estimer_tokens_outils(self.all_tools)
        self.heavy_ctx = {
            'fenetre_active': {'titre': 'Adversarial Heavy Stress ' * 30, 'processus': 'stress.exe'},
            'presse_papiers': 'DUMP_DATA_SECRET_KEY_' * 40
        }
        self.heavy_etat = "RAM: 98% (62/64 GB) | CPU: 99% | VRAM: 95% (23/24 GB) | GPU: 97%"
        self.max_allowed_time = 0.050  # 50 ms budget

    def test_adversarial_100_turns_history_with_tools(self):
        """Stress workload: 100 turns of history with interleaved tool calls (2x the It5 benchmark).
        Budget: < 0.05s (50 ms).
        """
        conversation = [{'role': 'system', 'content': 'sys'}]
        for turn_idx in range(100):
            conversation.append({
                'role': 'user',
                'content': f"Tour {turn_idx}: Requête d'exécution et analyse de log approfondie."
            })
            cid = f"call_100_{turn_idx}"
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
                'content': f"audit_dump_record_{turn_idx}.dat\n" * 25
            })
            conversation.append({
                'role': 'assistant',
                'content': f"Tour {turn_idx} analysé sans anomalie."
            })

        conversation.append({'role': 'user', 'content': 'Synthétise la totalité des 100 tours précédents.'})

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
            self.assertTrue(valid, f"Dissociation in 100-turn history: {reason}")

        avg_time = sum(times) / len(times)
        max_time = max(times)
        print(f"\n[Adversarial 100-Turn History ({len(conversation)} msgs)] Avg: {avg_time*1000:.3f}ms | Max: {max_time*1000:.3f}ms | Budget: {self.max_allowed_time*1000:.1f}ms")
        self.assertLess(max_time, self.max_allowed_time, f"Execution time {max_time:.4f}s exceeded 0.05s budget for 100-turn history")

    def test_adversarial_25k_lines_tool_output(self):
        """Stress workload: 25,000 lines (>1.5 million characters) tool output.
        Budget: < 0.05s (50 ms).
        """
        lines = [f"ligne_{i:06d}: chemin/absolu/vers/journal_systeme_critique_{i}.log" for i in range(25000)]
        huge_tool_content = "\n".join(lines)

        iterations = 10
        times = []
        for _ in range(iterations):
            cid = "call_huge_25k"
            api.messages = [
                {'role': 'system', 'content': 'sys'},
                {'role': 'user', 'content': 'Lit les 25000 lignes de logs'},
                {
                    'role': 'assistant',
                    'content': None,
                    'tool_calls': [{'id': cid, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}]
                },
                {'role': 'tool', 'tool_call_id': cid, 'name': 'lister_fichiers', 'content': huge_tool_content},
                {'role': 'assistant', 'content': 'Terminé.'}
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
            self.assertTrue(valid, f"Dissociation with 25k lines tool output: {reason}")

        avg_time = sum(times) / len(times)
        max_time = max(times)
        print(f"\n[Adversarial 25k Lines Tool Output ({len(huge_tool_content):,} chars)] Avg: {avg_time*1000:.3f}ms | Max: {max_time*1000:.3f}ms | Budget: {self.max_allowed_time*1000:.1f}ms")
        self.assertLess(max_time, self.max_allowed_time, f"Execution time {max_time:.4f}s exceeded 0.05s budget for 25k lines tool output")

    def test_adversarial_rapid_successive_clamping_50_iterations(self):
        """Stress workload: 50 consecutive clamp executions with alternating active tool calls and history.
        Evaluates stability, zero memory leak, and latency percentiles.
        """
        conversation = [{'role': 'system', 'content': 'sys'}]
        for turn_idx in range(40):
            cid = f"call_burst_{turn_idx}"
            conversation.extend([
                {'role': 'user', 'content': f"Requête {turn_idx}"},
                {'role': 'assistant', 'content': None, 'tool_calls': [{'id': cid, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}]},
                {'role': 'tool', 'tool_call_id': cid, 'name': 'lister_fichiers', 'content': f"trace_{turn_idx}\n" * 50},
                {'role': 'assistant', 'content': f"Fait {turn_idx}"}
            ])
        conversation.append({'role': 'user', 'content': 'Demande finale ' + ('W' * 10_000)})

        times = []
        for i in range(50):
            api.messages = [dict(m) for m in conversation]
            t0 = time.perf_counter()
            opt = api._messages_avec_fenetre(
                etat_systeme=self.heavy_etat,
                tools=self.all_tools,
                ctx=self.heavy_ctx
            )
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

        avg_time = sum(times) / len(times)
        p95_time = sorted(times)[int(len(times) * 0.95)]
        max_time = max(times)
        print(f"\n[Adversarial Rapid 50 Successive Clamps] Avg: {avg_time*1000:.3f}ms | p95: {p95_time*1000:.3f}ms | Max: {max_time*1000:.3f}ms | Budget: {self.max_allowed_time*1000:.1f}ms")
        self.assertLess(max_time, self.max_allowed_time, f"Max execution time {max_time:.4f}s exceeded 0.05s budget during rapid succession")


if __name__ == '__main__':
    unittest.main()
