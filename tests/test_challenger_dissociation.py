import unittest
import api
import ai
from core import token_counter


class TestAdversarialTokenClamp(unittest.TestCase):
    def test_tool_dissociation_under_clamp(self):
        # 2 tours:
        # Tour 1: user, assistant (tool_calls), tool response, assistant answer
        # Tour 2: user (short prompt)
        api.messages = [
            {'role': 'system', 'content': 'sys'},
            {'role': 'user', 'content': 'Demande 1'},
            {
                'role': 'assistant',
                'content': None,
                'tool_calls': [
                    {
                        'id': 'call_abc',
                        'type': 'function',
                        'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "."}'}
                    }
                ]
            },
            {
                'role': 'tool',
                'tool_call_id': 'call_abc',
                'name': 'lister_fichiers',
                'content': 'fichier.txt\n' * 500
            },
            {
                'role': 'assistant',
                'content': 'Voici le résultat : ' + ('info ' * 350)
            },
            {
                'role': 'user',
                'content': 'Demande 2'
            }
        ]
        tools = [ai.outils_disponibles['lister_fichiers']]
        ctx = {
            'fenetre_active': {'titre': 'Fenetre ' * 20, 'processus': 'proc'},
            'presse_papiers': 'Clip ' * 50
        }
        etat = 'RAM: 50% | CPU: 10%'

        opt = api._messages_avec_fenetre(etat_systeme=etat, tools=tools, ctx=ctx)
        
        print("\nOptimized sequence roles and tool info:")
        for idx, m in enumerate(opt):
            print(f"  {idx}: role={m.get('role')} has_tool_calls={bool(m.get('tool_calls'))} tool_call_id={m.get('tool_call_id')}")

        # Check for orphaned tool messages
        # Any tool message must be preceded by an assistant message with matching tool_call_id
        for idx, m in enumerate(opt):
            if m.get('role') == 'tool':
                t_id = m.get('tool_call_id')
                # Preceding message must be assistant with tool_calls containing this id
                has_parent = False
                for prev in opt[:idx]:
                    if prev.get('role') == 'assistant' and prev.get('tool_calls'):
                        if any(tc.get('id') == t_id for tc in prev['tool_calls']):
                            has_parent = True
                            break
                self.assertTrue(has_parent, f"ORPHANED TOOL RESPONSE at index {idx}: tool_call_id={t_id} without preceding assistant tool_calls!")

        # Also check for orphaned assistant with tool_calls without tool response
        for idx, m in enumerate(opt):
            if m.get('role') == 'assistant' and m.get('tool_calls'):
                for tc in m['tool_calls']:
                    tc_id = tc.get('id')
                    has_child = any(sub.get('role') == 'tool' and sub.get('tool_call_id') == tc_id for sub in opt[idx+1:])
                    self.assertTrue(has_child, f"ORPHANED TOOL CALL at index {idx}: tool_call_id={tc_id} without subsequent tool response!")


if __name__ == '__main__':
    unittest.main()
