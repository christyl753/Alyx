import api


def test_context_window_preserves_tool_call_pairs(monkeypatch):
    """B.7 : la fenêtre de contexte ne doit jamais séparer une paire tool_call/tool."""
    monkeypatch.setattr(api, 'MAX_CONTEXT_MESSAGES', 3)

    api.messages[:] = [
        {'role': 'system', 'content': 'sys'},
        {'role': 'user', 'content': 'u1'},
        {'role': 'assistant', 'content': None, 'tool_calls': [{'function': {'name': 'x'}}]},
        {'role': 'tool', 'content': 'resultat', 'name': 'x'},
        {'role': 'user', 'content': 'u2'},
        {'role': 'assistant', 'content': 'reponse finale'},
    ]

    fenetre = api._messages_avec_fenetre()

    assert fenetre[0]['role'] == 'system'
    for i, msg in enumerate(fenetre):
        if msg.get('role') == 'tool':
            assert fenetre[i - 1].get('tool_calls'), \
                "un message 'tool' est apparu sans son 'tool_calls' précédent"


def test_context_window_noop_when_under_limit():
    api.messages[:] = [
        {'role': 'system', 'content': 'sys'},
        {'role': 'user', 'content': 'u1'},
    ]

    fenetre = api._messages_avec_fenetre()

    assert fenetre == api.messages
