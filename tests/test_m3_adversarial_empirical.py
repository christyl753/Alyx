"""Empirical Adversarial Test Suite for Milestone 3 (R3):
JSON Schema Enums & Multi-Turn Memory Preservation.

Tests:
1. Strict schema compliance and bounded enum extraction across all tools in function/.
2. Unbounded parameter invariance (query, chemin, recherche, commande never receive false enums).
3. Adversarial docstring variations and type annotations for _extraire_enum_parametre.
4. Deep multi-turn conversation sessions (10+ turns) with single, parallel, and multi-step tool calls.
5. Invariant checking: No orphan tools, no severed user requests when tool calls start.
6. Anaphoric context preservation across sliding window turns.
"""

import inspect
import sys
import os
import unittest
from pathlib import Path
from typing import Literal, Optional, Union

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import ai
import api
from core import llm_provider
from function import files, system, web, voice, tts, scrap


class TestAdversarialToolSchemas(unittest.TestCase):
    """Adversarially tests schema generation, enum bounding, and open-ended parameter safety."""

    def test_all_registered_tools_schema_validity(self):
        """Every tool in ai.outils_disponibles must produce a valid JSON schema."""
        for name, func in ai.outils_disponibles.items():
            schema = llm_provider._function_to_json_schema(func)
            self.assertEqual(schema.get("type"), "function", f"{name}: root type must be function")
            f_meta = schema.get("function", {})
            self.assertEqual(f_meta.get("name"), func.__name__, f"{name}: function name mismatch")
            self.assertIn("parameters", f_meta, f"{name}: missing parameters")
            params = f_meta["parameters"]
            self.assertEqual(params.get("type"), "object", f"{name}: parameters type must be object")
            self.assertIsInstance(params.get("properties"), dict, f"{name}: properties must be dict")
            self.assertIsInstance(params.get("required"), list, f"{name}: required must be list")

    def test_bounded_parameters_have_exact_enums(self):
        """All bounded action parameters must receive exact, correct enum values."""
        expected_enums = {
            system.controler_media: ("action", ["lecture_pause", "suivant", "precedent"]),
            system.gerer_service: ("action", ["arreter", "demarrer", "desactiver", "activer"]),
            system.gerer_tache_planifiee: ("action", ["desactiver", "activer", "arreter"]),
            system.gerer_app_demarrage: ("action", ["desactiver", "activer"]),
        }

        for func, (param_name, expected_list) in expected_enums.items():
            schema = llm_provider._function_to_json_schema(func)
            props = schema["function"]["parameters"]["properties"]
            self.assertIn(param_name, props, f"{func.__name__} must have property {param_name}")
            prop = props[param_name]
            self.assertIn("enum", prop, f"{func.__name__}:{param_name} MUST have an 'enum' field")
            self.assertEqual(
                sorted(prop["enum"]),
                sorted(expected_list),
                f"{func.__name__}:{param_name} enum mismatch. Expected {expected_list}, got {prop['enum']}"
            )

    def test_unbounded_open_ended_parameters_never_receive_enums(self):
        """Open-ended parameters (query, chemin, commande, etc.) must NEVER have enum constraints."""
        bounded_targets = {
            (system.controler_media, "action"),
            (system.gerer_service, "action"),
            (system.gerer_tache_planifiee, "action"),
            (system.gerer_app_demarrage, "action"),
        }

        # Check all registered tools
        for name, func in ai.outils_disponibles.items():
            schema = llm_provider._function_to_json_schema(func)
            props = schema["function"]["parameters"]["properties"]
            for p_name, p_prop in props.items():
                if (func, p_name) not in bounded_targets:
                    self.assertNotIn(
                        "enum",
                        p_prop,
                        f"Unbounded parameter {func.__name__}:{p_name} erroneously received enum: {p_prop.get('enum')}"
                    )

    def test_specific_critical_unbounded_parameters(self):
        """Explicitly tests known critical parameters that must stay unbounded."""
        checks = [
            (files.creer_fichier, "chemin"),
            (files.ecrire_fichier_securise, "chemin"),
            (files.ecrire_fichier_securise, "contenu"),
            (files.supprimer_fichier, "chemin"),
            (files.lister_fichiers, "dossier"),
            (files.deplacer_fichier, "chemin_source"),
            (files.deplacer_fichier, "dossier_destination"),
            (files.renommer_fichier, "chemin_actuel"),
            (files.renommer_fichier, "nouveau_nom"),
            (system.ouvrir_application, "nom_commande"),
            (system.fermer_application, "nom_app"),
            (system.rechercher_processus, "filtre"),
            (system.executer_commande_systeme, "commande"),
            (web.rechercher_web, "requete"),
            (system.rechercher_ou_jouer_media, "recherche"),
            (system.rechercher_ou_jouer_media, "application"),
        ]

        for func, param in checks:
            schema = llm_provider._function_to_json_schema(func)
            props = schema["function"]["parameters"]["properties"]
            self.assertIn(param, props, f"Parameter {param} not found in {func.__name__}")
            self.assertNotIn(
                "enum",
                props[param],
                f"Critical unbounded parameter {func.__name__}:{param} must not have enum"
            )

    def test_extraire_enum_synthetic_adversarial_cases(self):
        """Adversarial stress-testing of _extraire_enum_parametre with synthetic docstrings."""

        def make_param(annotation=inspect.Parameter.empty, default=inspect.Parameter.empty):
            return inspect.Parameter('x', inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation, default=default)

        # 1. Type annotations: Literal
        p_lit = make_param(annotation=Literal['opt1', 'opt2', 'opt3'])
        self.assertEqual(llm_provider._extraire_enum_parametre(p_lit, ""), ['opt1', 'opt2', 'opt3'])

        # 2. Type annotations: Optional[Literal]
        p_opt_lit = make_param(annotation=Optional[Literal['a', 'b']])
        self.assertEqual(llm_provider._extraire_enum_parametre(p_opt_lit, ""), ['a', 'b'])

        # 3. Docstring with (ex: ...) or (e.g.: ...) MUST NOT generate enum
        p_str = make_param(annotation=str)
        doc_ex = "Chemin vers le fichier cible (ex: 'rapport.pdf', 'notes.txt')."
        self.assertIsNone(llm_provider._extraire_enum_parametre(p_str, doc_ex))

        doc_eg = "Nom du processus à surveiller (e.g.: 'explorer.exe' ou 'chrome.exe')."
        self.assertIsNone(llm_provider._extraire_enum_parametre(p_str, doc_eg))

        # 4. Docstring with open-ended alternatives like 'foo' ou autre
        doc_open = "Plateforme : 'spotify', 'youtube' ou toute autre plateforme installée."
        self.assertIsNone(llm_provider._extraire_enum_parametre(p_str, doc_open))

        # 5. Docstring with single quoted option (must have >= 2 for enum)
        doc_single = "Mode d'affichage : 'plein_ecran'."
        self.assertIsNone(llm_provider._extraire_enum_parametre(p_str, doc_single))

        # 6. Valid docstring with explicit discrete choice prefixes
        doc_prefix1 = "Action à effectuer : 'demarrer', 'arreter' ou 'redemarrer'."
        self.assertEqual(
            llm_provider._extraire_enum_parametre(p_str, doc_prefix1),
            ['demarrer', 'arreter', 'redemarrer']
        )

        doc_prefix2 = "Choix possibles : 'haut', 'bas', 'gauche', 'droite'."
        self.assertEqual(
            llm_provider._extraire_enum_parametre(p_str, doc_prefix2),
            ['haut', 'bas', 'gauche', 'droite']
        )

        doc_prefix3 = "Une parmi 'json', 'yaml', 'toml'."
        self.assertEqual(
            llm_provider._extraire_enum_parametre(p_str, doc_prefix3),
            ['json', 'yaml', 'toml']
        )


class TestDeepMultiTurnMemoryPreservation(unittest.TestCase):
    """Simulates deep multi-turn sessions (10+ turns) with tool calls and verifies memory preservation."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        self._orig_max_context = api.MAX_CONTEXT_MESSAGES

    def tearDown(self):
        api.messages = list(self._orig_messages)
        api.MAX_CONTEXT_MESSAGES = self._orig_max_context

    def test_deep_12_turn_session_no_orphan_tools(self):
        """Simulate a 12-turn conversation with alternating tools and verify no orphan tools exist at any cutoff."""
        api.messages = [{'role': 'system', 'content': 'System prompt'}]
        for i in range(1, 13):
            turn_type = i % 3
            if turn_type == 1:
                # Turn with tool execution (single tool)
                api.messages.append({'role': 'user', 'content': f'Exécute tâche {i}'})
                api.messages.append({
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{'id': f'call_{i}', 'type': 'function', 'function': {'name': 'outil_systeme', 'arguments': {'x': i}}}]
                })
                api.messages.append({
                    'role': 'tool',
                    'name': 'outil_systeme',
                    'tool_call_id': f'call_{i}',
                    'content': f'Résultat tâche {i}'
                })
                api.messages.append({'role': 'assistant', 'content': f'La tâche {i} est terminée avec succès.'})
            elif turn_type == 2:
                # Turn with parallel tools
                api.messages.append({'role': 'user', 'content': f'Exécute tâches parallèles {i}a et {i}b'})
                api.messages.append({
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [
                        {'id': f'call_{i}a', 'type': 'function', 'function': {'name': 'outil_a', 'arguments': {}}},
                        {'id': f'call_{i}b', 'type': 'function', 'function': {'name': 'outil_b', 'arguments': {}}},
                    ]
                })
                api.messages.append({'role': 'tool', 'name': 'outil_a', 'tool_call_id': f'call_{i}a', 'content': f'Résultat {i}a'})
                api.messages.append({'role': 'tool', 'name': 'outil_b', 'tool_call_id': f'call_{i}b', 'content': f'Résultat {i}b'})
                api.messages.append({'role': 'assistant', 'content': f'Les tâches {i}a et {i}b sont terminées.'})
            else:
                # Pure conversation turn without tools
                api.messages.append({'role': 'user', 'content': f'Comment vas-tu à l\'étape {i} ?'})
                api.messages.append({'role': 'assistant', 'content': f'Je vais très bien à l\'étape {i}, prêt pour la suite.'})

        # Test every possible context window size from 2 to total message count
        total_recent = len(api.messages) - 1
        for max_ctx in range(2, total_recent + 5):
            api.MAX_CONTEXT_MESSAGES = max_ctx
            fenetre = api._messages_avec_fenetre()
            self.assertEqual(fenetre[0]['role'], 'system', "Le premier message doit toujours être le prompt système.")

            # Check every tool message in the window
            for idx, msg in enumerate(fenetre):
                if msg.get('role') == 'tool':
                    self.assertGreater(idx, 1, f"Orphan tool message at index {idx} with max_context={max_ctx}")
                    prev_msg = fenetre[idx - 1]
                    if prev_msg.get('role') == 'assistant':
                        call_ids = [c['id'] for c in prev_msg.get('tool_calls', [])]
                        self.assertIn(
                            msg.get('tool_call_id'),
                            call_ids,
                            f"Tool message {msg.get('tool_call_id')} does not match preceding tool_calls: {call_ids}"
                        )
                    elif prev_msg.get('role') == 'tool':
                        # Parallel tool: look backwards to the assistant message
                        found_call = False
                        for back in range(idx - 1, 0, -1):
                            if fenetre[back].get('role') == 'assistant':
                                call_ids = [c['id'] for c in fenetre[back].get('tool_calls', [])]
                                if msg.get('tool_call_id') in call_ids:
                                    found_call = True
                                break
                        self.assertTrue(
                            found_call,
                            f"Parallel tool message {msg.get('tool_call_id')} has no originating assistant tool_call"
                        )

    def test_anaphoric_reference_memory_preservation(self):
        """Simulate realistic multi-turn session with anaphora ('supprime ce fichier', 'arrête ce PID').

        Verifies that when a user refers to an earlier tool's output:
        1. The earlier tool response is preserved in the active sliding window.
        2. Slicing does not discard the historical tool outputs needed for resolution.
        """
        api.MAX_CONTEXT_MESSAGES = 16
        api.messages = [{'role': 'system', 'content': 'System prompt'}]

        # Turn 1: Search files
        api.messages.append({'role': 'user', 'content': 'Recherche les fichiers log dans mon dossier'})
        api.messages.append({
            'role': 'assistant',
            'content': '',
            'tool_calls': [{'id': 'call_find', 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': {'chemin': 'logs'}}}]
        })
        api.messages.append({
            'role': 'tool',
            'name': 'lister_fichiers',
            'tool_call_id': 'call_find',
            'content': 'Fichiers trouvés : debug.log (120 Mo), error.log (2 Mo), system.log (50 Mo)'
        })
        api.messages.append({'role': 'assistant', 'content': 'J\'ai trouvé trois fichiers de logs dont debug.log qui pèse 120 Mo.'})

        # Turn 2: Anaphoric command referring to debug.log
        api.messages.append({'role': 'user', 'content': 'Supprime le premier qui est trop gros'})
        api.messages.append({
            'role': 'assistant',
            'content': '',
            'tool_calls': [{'id': 'call_del', 'type': 'function', 'function': {'name': 'supprimer_fichier', 'arguments': {'chemin': 'logs/debug.log'}}}]
        })
        api.messages.append({
            'role': 'tool',
            'name': 'supprimer_fichier',
            'tool_call_id': 'call_del',
            'content': 'Succès : logs/debug.log supprimé.'
        })
        api.messages.append({'role': 'assistant', 'content': 'Le fichier logs/debug.log a été supprimé.'})

        # Turn 3: Search processes
        api.messages.append({'role': 'user', 'content': 'Quels sont les processus consommateurs ?'})
        api.messages.append({
            'role': 'assistant',
            'content': '',
            'tool_calls': [{'id': 'call_proc', 'type': 'function', 'function': {'name': 'rechercher_processus', 'arguments': {'terme': 'heavy'}}}]
        })
        api.messages.append({
            'role': 'tool',
            'name': 'rechercher_processus',
            'tool_call_id': 'call_proc',
            'content': 'Processus trouvés : heavy_task.exe (PID 8824, CPU 85%)'
        })
        api.messages.append({'role': 'assistant', 'content': 'Le processus heavy_task.exe (PID 8824) consomme 85% du processeur.'})

        # Turn 4: Anaphoric command referring to PID 8824
        api.messages.append({'role': 'user', 'content': 'Tue ce processus immédiatement'})

        fenetre = api._messages_avec_fenetre()

        # In Turn 4 context:
        # Check that Turn 3 tool output (PID 8824) is fully preserved
        has_pid_output = any('PID 8824' in str(m.get('content', '')) for m in fenetre if m.get('role') == 'tool')
        self.assertTrue(has_pid_output, "Le résultat de l'outil contenant le PID 8824 doit être préservé dans la fenêtre active.")

        # Check that Turn 1 & 2 tool outputs are also preserved within the 16-message window
        has_log_output = any('debug.log' in str(m.get('content', '')) for m in fenetre if m.get('role') == 'tool')
        self.assertTrue(has_log_output, "Le résultat de l'outil listant debug.log doit être préservé dans la fenêtre active.")

        # Verify all 3 tool messages were preserved
        tool_count = sum(1 for m in fenetre if m.get('role') == 'tool')
        self.assertEqual(tool_count, 3, f"Les 3 résultats d'outils doivent être présents, trouvé: {tool_count}")

    def test_no_severed_user_request_at_tool_call_boundary(self):
        """When sliding window cuts before a tool execution, it must not sever the user prompt."""
        api.messages = [{'role': 'system', 'content': 'System prompt'}]

        # Add 5 conversational turns
        for i in range(1, 6):
            api.messages.append({'role': 'user', 'content': f'Message utilisateur {i}'})
            api.messages.append({'role': 'assistant', 'content': f'Réponse assistant {i}'})

        # Add Turn 6 with tool execution
        api.messages.append({'role': 'user', 'content': 'Exécute un outil critique'})
        api.messages.append({
            'role': 'assistant',
            'content': '',
            'tool_calls': [{'id': 'call_crit', 'type': 'function', 'function': {'name': 'outil_systeme', 'arguments': {}}}]
        })
        api.messages.append({'role': 'tool', 'name': 'outil_systeme', 'tool_call_id': 'call_crit', 'content': 'Résultat ok'})
        api.messages.append({'role': 'assistant', 'content': 'Terminé.'})

        # Add Turn 7
        api.messages.append({'role': 'user', 'content': 'Que viens-tu de faire ?'})

        # Now test cutting right at Turn 6 boundary (max_context = 5)
        api.MAX_CONTEXT_MESSAGES = 5
        fenetre = api._messages_avec_fenetre()

        # Verify that fenetre[1] (first non-system message) is NOT an assistant with tool_calls
        first_msg = fenetre[1]
        self.assertFalse(
            first_msg.get('tool_calls'),
            "La fenêtre de contexte ne doit jamais commencer par un message assistant avec tool_calls sans son message utilisateur."
        )
        self.assertNotEqual(
            first_msg.get('role'),
            'tool',
            "La fenêtre de contexte ne doit jamais commencer par un message tool."
        )

    def test_history_truncation_preserves_ring_buffer_integrity(self):
        """_tronquer_historique bounds messages to ~2*MAX_CONTEXT_MESSAGES without creating orphan tools."""
        api.MAX_CONTEXT_MESSAGES = 10
        api.messages = [{'role': 'system', 'content': 'System prompt'}]

        # Append 30 turns (120 messages)
        for i in range(1, 31):
            api.messages.append({'role': 'user', 'content': f'Demande {i}'})
            api.messages.append({
                'role': 'assistant',
                'content': '',
                'tool_calls': [{'id': f'call_{i}', 'type': 'function', 'function': {'name': 'outil', 'arguments': {}}}]
            })
            api.messages.append({'role': 'tool', 'name': 'outil', 'tool_call_id': f'call_{i}', 'content': f'Result {i}'})
            api.messages.append({'role': 'assistant', 'content': f'Réponse {i}'})

        self.assertGreater(len(api.messages) - 1, api.MAX_CONTEXT_MESSAGES * 2)

        # Run truncation
        api._tronquer_historique()

        # Messages must be bounded
        self.assertLessEqual(len(api.messages) - 1, api.MAX_CONTEXT_MESSAGES * 2 + 4)

        # First message after system MUST NOT be a tool or an assistant with tool_calls
        first_retained = api.messages[1]
        self.assertNotEqual(first_retained.get('role'), 'tool', "Truncated history must not start with an orphan tool")
        self.assertFalse(first_retained.get('tool_calls'), "Truncated history must not start with an assistant tool_call")

        # Check all tool messages in the truncated history
        for idx in range(1, len(api.messages)):
            m = api.messages[idx]
            if m.get('role') == 'tool':
                prev = api.messages[idx - 1]
                call_ids = [c['id'] for c in prev.get('tool_calls', [])]
                self.assertIn(
                    m.get('tool_call_id'),
                    call_ids,
                    f"Orphan tool found in truncated history at index {idx}"
                )

    def test_all_function_modules_schema_robustness(self):
        """Every function across all function.* modules must safely convert to JSON schema."""
        import importlib
        modules = ['function.files', 'function.system', 'function.web', 'function.voice', 'function.tts', 'function.scrap']

        for mod_name in modules:
            mod = importlib.import_module(mod_name)
            for name, obj in inspect.getmembers(mod, inspect.isfunction):
                if obj.__module__ == mod_name and not name.startswith('_'):
                    try:
                        schema = llm_provider._function_to_json_schema(obj)
                        self.assertEqual(schema['type'], 'function', f"{mod_name}.{name} schema type must be function")
                        self.assertIn('name', schema['function'])
                        self.assertIn('parameters', schema['function'])
                    except Exception as e:
                        self.fail(f"Failed to generate schema for {mod_name}.{name}: {e}")


    def test_multistep_tool_chain_boundary_preservation(self):
        """In multi-step turns (user -> tool1 -> tool2 -> response), user request must not be severed."""
        recents = [
            {'role': 'user', 'content': 'find and clean temp files'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {'name': 'lister_fichiers'}}]},
            {'role': 'tool', 'name': 'lister_fichiers', 'tool_call_id': 'c1', 'content': 'temp1.txt'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c2', 'type': 'function', 'function': {'name': 'supprimer_fichier'}}]},
            {'role': 'tool', 'name': 'supprimer_fichier', 'tool_call_id': 'c2', 'content': 'supprimé'},
            {'role': 'assistant', 'content': 'Fait.'},
            {'role': 'user', 'content': 'Merci'},
        ]

        # Test cut point landing at step 2 of the tool chain (max_messages=4)
        idx = api._index_coupure_sure(recents, 4)
        sliced = recents[idx:]

        # Sliced window must not start with an assistant tool_call missing its user request
        self.assertFalse(
            sliced[0].get('tool_calls'),
            f"Multi-step tool cut severed user request: slice starts with {sliced[0].get('role')} tool_calls"
        )
        self.assertEqual(
            sliced[0].get('role'),
            'user',
            f"Multi-step tool cut should rewind to user prompt, but got {sliced[0].get('role')}"
        )


if __name__ == '__main__':
    unittest.main()


