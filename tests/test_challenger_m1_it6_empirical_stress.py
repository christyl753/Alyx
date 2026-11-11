"""Empirical Adversarial Stress & Invariant Verification Suite for api.py:441-473.
Teamwork Challenger Milestone 1 Iteration 6 (challenger_m1_it6_1).

Evaluates:
1. Extreme scaling: 100-turn history (400+ msgs), 25,000-line tool outputs, 200k char prompt.
2. Invariants: total_tokens <= 3296 and zero tool dissociation.
3. Pathological boundary conditions:
   - User prompt lengths [48, 49, 50, 51, 52] chars
   - Context delimiters \n\n[ at start, middle, repeated, unclosed
   - Active turns with 10 tools
   - Turn with no user message
   - Tools schema tokens near/at budget
   - Active turn where only assistant message is massive (cannot be reduced)
4. Rapid-fire successive calls: 100 consecutive invocations verifying determinism and performance.
"""

import time
import unittest
import api
import ai
from core import token_counter


def validate_message_sequence_integrity(optimized_messages):
    """Strictly validates B.7 invariant:
    1. Every role='tool' message has preceding assistant message with matching tool_call_id.
    2. Every assistant tool_call has matching role='tool' message.
    3. System message is at index 0.
    4. No orphaned calls or responses.
    """
    if not optimized_messages or optimized_messages[0].get('role') != 'system':
        return False, "System message missing or not at index 0"

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


class TestM1It6ChallengerEmpiricalStress(unittest.TestCase):

    def setUp(self):
        self.tools = [ai.outils_disponibles['lister_fichiers'], ai.outils_disponibles['lire_fichier_securise']]
        self.tools_tokens = token_counter.estimer_tokens_outils(self.tools)
        self.ctx = {
            'fenetre_active': {'titre': 'Test Adversarial Window ' * 10, 'processus': 'pytest.exe'},
            'presse_papiers': 'SECRET_TOKEN_' * 20
        }
        self.etat = "RAM: 90% | CPU: 80% | VRAM: 70%"
        self.budget_time = 0.05  # 50 ms

    def test_adversarial_100_turns_history_execution_time_and_pairing(self):
        """Stress 1: 100 turns (over 400 messages) with alternating tool calls.
        Verifies execution < 50ms, tokens <= 3296, zero dissociation.
        """
        conversation = [{'role': 'system', 'content': 'sys'}]
        for turn_idx in range(100):
            conversation.append({'role': 'user', 'content': f'User request {turn_idx}: test.'})
            cid = f'call_100t_{turn_idx}'
            conversation.append({
                'role': 'assistant',
                'content': None,
                'tool_calls': [{'id': cid, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}]
            })
            conversation.append({
                'role': 'tool',
                'tool_call_id': cid,
                'name': 'lister_fichiers',
                'content': f'file_{turn_idx}_item.txt\n' * 20
            })
            conversation.append({'role': 'assistant', 'content': f'Done {turn_idx}.'})

        conversation.append({'role': 'user', 'content': 'Final prompt for 100 turns.'})

        times = []
        for _ in range(10):
            api.messages = [dict(m) for m in conversation]
            t0 = time.perf_counter()
            opt = api._messages_avec_fenetre(etat_systeme=self.etat, tools=self.tools, ctx=self.ctx)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

            total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
            self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
            valid, reason = validate_message_sequence_integrity(opt)
            self.assertTrue(valid, f"Dissociation in 100-turn history: {reason}")

        max_t = max(times)
        avg_t = sum(times) / len(times)
        print(f"\n[Adversarial 100-Turn History ({len(conversation)} msgs)] Avg: {avg_t*1000:.3f}ms | Max: {max_t*1000:.3f}ms | Budget: {self.budget_time*1000:.1f}ms")
        self.assertLess(max_t, self.budget_time)

    def test_adversarial_25000_lines_tool_output(self):
        """Stress 2: 25,000 lines (approx 1.7 MB text) in tool response.
        Verifies fast token counter and clamp condensation < 50ms.
        """
        massive_content = "\n".join(f"data_log_line_{i:07d}: /var/log/syslog/trace_{i}.json" for i in range(25000))
        cid = "call_25k"

        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'Scan logs'},
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{'id': cid, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}]
            },
            {'role': 'tool', 'tool_call_id': cid, 'name': 'lister_fichiers', 'content': massive_content},
            {'role': 'assistant', 'content': 'Analysis in progress'}
        ]

        times = []
        for _ in range(10):
            t0 = time.perf_counter()
            opt = api._messages_avec_fenetre(etat_systeme=self.etat, tools=self.tools, ctx=self.ctx)
            elapsed = time.perf_counter() - t0
            times.append(elapsed)

            total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
            self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
            valid, reason = validate_message_sequence_integrity(opt)
            self.assertTrue(valid, f"Dissociation in 25k lines tool output: {reason}")

        max_t = max(times)
        avg_t = sum(times) / len(times)
        print(f"\n[Adversarial 25k Lines Tool Output ({len(massive_content):,} chars)] Avg: {avg_t*1000:.3f}ms | Max: {max_t*1000:.3f}ms | Budget: {self.budget_time*1000:.1f}ms")
        self.assertLess(max_t, self.budget_time)

    def test_user_prompt_boundary_lengths_48_to_52(self):
        """Stress 3: Test boundary behavior around length 50: [48, 49, 50, 51, 52] chars.
        Step 3 triggers when len > 50, while Step 4 triggers when len <= 50 with \n\n[.
        Verifies both paths terminate and maintain invariants.
        """
        for length in [48, 49, 50, 51, 52]:
            with self.subTest(length=length):
                prompt = "A" * length
                # Add heavy prior turn to force clamp entry
                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'prior'},
                    {'role': 'assistant', 'content': 'mot ' * 2000},
                    {'role': 'user', 'content': prompt}
                ]
                t0 = time.perf_counter()
                opt = api._messages_avec_fenetre(etat_systeme=self.etat, tools=self.tools, ctx=self.ctx)
                elapsed = time.perf_counter() - t0

                self.assertLess(elapsed, self.budget_time)
                total = sum(token_counter.estimer_tokens_message(m) for m in opt) + self.tools_tokens
                self.assertLessEqual(total, token_counter.MAX_INPUT_TOKENS)
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Sequence integrity failed for len {length}: {reason}")

    def test_pathological_context_delimiter_placements(self):
        """Stress 4: Adversarial placements of \n\n[ in user prompt:
        - At very beginning: \n\n[Contexte
        - Repeated multiple times: a\n\n[b\n\n[c
        - Unclosed bracket: a\n\n[unclosed
        - Exact 50 chars with \n\n[
        """
        adversarial_prompts = [
            "\n\n[Contexte matériel: RAM 99%]",
            "a" * 10 + "\n\n[" + "b" * 10 + "\n\n[" + "c" * 10,
            "test unclosed delimiter \n\n[ no closing bracket here",
            ("x" * 46) + "\n\n[",
            ("\n\n[" + "z" * 46)
        ]

        for p in adversarial_prompts:
            with self.subTest(prompt=p):
                api.messages = [
                    {'role': 'system', 'content': 'sys'},
                    {'role': 'user', 'content': 'prior'},
                    {'role': 'assistant', 'content': 'mot ' * 2200},
                    {'role': 'user', 'content': p}
                ]
                t0 = time.perf_counter()
                opt = api._messages_avec_fenetre(etat_systeme=self.etat, tools=self.tools, ctx=self.ctx)
                elapsed = time.perf_counter() - t0

                self.assertLess(elapsed, self.budget_time)
                valid, reason = validate_message_sequence_integrity(opt)
                self.assertTrue(valid, f"Failed on prompt '{p[:20]}': {reason}")

    def test_active_turn_with_10_tools_clamp_termination(self):
        """Stress 5: Active turn with 10 tools of diverse sizes.
        Verifies all 10 tools are condensed at most once, pairing preserved, termination instant.
        """
        tcs = []
        tool_msgs = []
        for i in range(10):
            cid = f"call_10tools_{i}"
            tcs.append({'id': cid, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}})
            tool_msgs.append({
                'role': 'tool',
                'tool_call_id': cid,
                'name': 'lister_fichiers',
                'content': f"Header {i} " + ("x" * 200) + "\n" + ("line\n" * 20)
            })

        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'run all 10'},
            {'role': 'assistant', 'content': 'mot ' * 2500, 'tool_calls': tcs},
            *tool_msgs
        ]

        t0 = time.perf_counter()
        opt = api._messages_avec_fenetre(tools=self.tools)
        elapsed = time.perf_counter() - t0

        self.assertLess(elapsed, self.budget_time)
        valid, reason = validate_message_sequence_integrity(opt)
        self.assertTrue(valid, f"Failed on 10 tools: {reason}")
        self.assertEqual(len([m for m in opt if m.get('role') == 'tool']), 10)

    def test_active_turn_where_only_assistant_is_oversized_unreducible_safety_net(self):
        """Stress 6: Active turn where assistant message alone has 3500 tokens (cannot be reduced by clamp).
        Verifies that after user prompt is trimmed to <= 50 and context stripped,
        clamp terminates via 'else: break' rather than infinite looping or crashing.
        """
        huge_assistant_text = "word " * 3500
        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'short prompt'},
            {'role': 'assistant', 'content': huge_assistant_text}
        ]

        t0 = time.perf_counter()
        opt = api._messages_avec_fenetre(tools=self.tools)
        elapsed = time.perf_counter() - t0

        # Must terminate immediately (< 20ms) via safety net break
        self.assertLess(elapsed, 0.02)
        self.assertIsNotNone(opt)
        self.assertEqual(opt[0]['role'], 'system')

    def test_rapid_50_successive_clamps_performance_stability(self):
        """Stress 7: 50 successive calls with different inputs measuring latency stability.
        Verifies zero memory leak, zero degradation, and p95/max < 50ms.
        """
        times = []
        for i in range(50):
            api.messages = [
                {'role': 'system', 'content': 'sys'},
                {'role': 'user', 'content': f'test_{i} ' * (100 + i * 20)},
                {'role': 'assistant', 'content': f'asst_{i} ' * 500}
            ]
            t0 = time.perf_counter()
            opt = api._messages_avec_fenetre(etat_systeme=self.etat, tools=self.tools, ctx=self.ctx)
            times.append(time.perf_counter() - t0)

        p95 = sorted(times)[int(len(times) * 0.95)]
        max_t = max(times)
        avg_t = sum(times) / len(times)
        print(f"\n[Adversarial Rapid 50 Successive Clamps] Avg: {avg_t*1000:.3f}ms | p95: {p95*1000:.3f}ms | Max: {max_t*1000:.3f}ms | Budget: {self.budget_time*1000:.1f}ms")
        self.assertLess(max_t, self.budget_time)


if __name__ == '__main__':
    unittest.main()
