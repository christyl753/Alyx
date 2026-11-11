import sys
import unittest
import api
import ai
from core import token_counter


def sweep_dissociation():
    tools = [ai.outils_disponibles['lister_fichiers']]
    tools_tokens = token_counter.estimer_tokens_outils(tools)

    # We want to sweep the size of the assistant message from 1000 to 3000 tokens
    # with user prompt <= 50 chars, and observe if optimized.pop(1) gets called and what it does.
    dissociation_found = False

    for asst_words in range(1200, 2600, 20):
        t1_tool_content = "fichier_test_data.txt\n" * 50
        asst_content = "mot " * asst_words

        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'u1'},
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [{
                    'id': f'call_{asst_words}',
                    'type': 'function',
                    'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}
                }]
            },
            {
                'role': 'tool',
                'tool_call_id': f'call_{asst_words}',
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
        if total > token_counter.MAX_INPUT_TOKENS:
            print(f"[FAIL] asst_words={asst_words}: total={total} > {token_counter.MAX_INPUT_TOKENS}")

        # Check tool pairing
        for idx, m in enumerate(opt):
            if m.get('role') == 'tool':
                t_id = m.get('tool_call_id')
                has_parent = any(prev.get('role') == 'assistant' and prev.get('tool_calls') and any(tc.get('id') == t_id for tc in prev['tool_calls']) for prev in opt[:idx])
                if not has_parent:
                    print(f"[CRITICAL DISSOCIATION] asst_words={asst_words} Orphaned tool response at {idx}: {t_id}")
                    print("Messages in opt:")
                    for i, x in enumerate(opt):
                        print(f"  {i}: {x.get('role')} (tc={bool(x.get('tool_calls'))}, id={x.get('tool_call_id')})")
                    dissociation_found = True
                    break

            if m.get('role') == 'assistant' and m.get('tool_calls'):
                for tc in m['tool_calls']:
                    tc_id = tc.get('id')
                    has_child = any(sub.get('role') == 'tool' and sub.get('tool_call_id') == tc_id for sub in opt[idx+1:])
                    if not has_child:
                        print(f"[CRITICAL DISSOCIATION] asst_words={asst_words} Orphaned assistant tool_call at {idx}: {tc_id}")
                        print("Messages in opt:")
                        for i, x in enumerate(opt):
                            print(f"  {i}: {x.get('role')} (tc={bool(x.get('tool_calls'))}, id={x.get('tool_call_id')})")
                        dissociation_found = True
                        break
        if dissociation_found:
            break

    if not dissociation_found:
        print("[SUCCESS] No tool dissociation found across entire sweep.")

if __name__ == '__main__':
    sweep_dissociation()
