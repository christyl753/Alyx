"""Suite de tests d'évaluation de la compréhension des tâches d'Alyx (Milestone 3 / R3).

Vérifie de manière exhaustive :
1. La structure Markdown et les ancrages contextuels du prompt système (ai.py).
2. Le routage multilingue (FR, EN, ES, DE) et le décloisonnement des domaines d'outils (ai.py).
3. L'extraction des choix bornés (enum) dans les schémas JSON d'outils (core/llm_provider.py).
4. La rétention multi-tours et la préservation insécable des paires tool_call/tool_response (api.py, B.7.6).
"""
import inspect
import os
import re
import sys
import time
import typing
import unittest
from pathlib import Path

# S'assurer que le répertoire racine est accessible pour les imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import ai
import api
from core import llm_provider, preferences
from function import system, files


class TestSystemPromptStructureAndGrounding(unittest.TestCase):
    """Vérifie la restructuration hiérarchique Markdown et les ancrages contextuels dynamiques."""

    def test_markdown_hierarchy_headers_present_and_ordered(self):
        """Le prompt système doit comporter les 4 en-têtes Markdown obligatoires dans l'ordre."""
        prompt = ai.prompt_systeme('fr')
        headers = [
            "# Identité & Mission",
            "# Directives Opérationnelles",
            "# Utilisation des Outils",
            "# Format de Réponse",
        ]
        indices = []
        for header in headers:
            self.assertIn(header, prompt, f"En-tête manquant dans le prompt : {header}")
            indices.append(prompt.find(header))

        # Vérification de l'ordre séquentiel
        self.assertEqual(indices, sorted(indices), "Les en-têtes Markdown ne respectent pas l'ordre hiérarchique prévu.")

    def test_contextual_grounding_os_and_user_home(self):
        """Le prompt système ancre dynamiquement l'OS hôte réel et le répertoire utilisateur."""
        prompt = ai.prompt_systeme('fr')
        # Ancrage OS
        self.assertIn("- Système d'exploitation :", prompt)
        if sys.platform == 'win32':
            self.assertIn("Windows", prompt)
        elif sys.platform.startswith('linux'):
            self.assertIn("Linux", prompt)

        # Ancrage répertoire utilisateur
        user_home = str(Path.home())
        self.assertIn("- Répertoire utilisateur :", prompt)
        self.assertIn(user_home, prompt)

    def test_temporal_grounding_format(self):
        """Le prompt système comporte un ancrage temporel au format YYYY-MM-DD HH:MM:SS."""
        prompt = ai.prompt_systeme('fr')
        self.assertIn("- Date et Heure locales :", prompt)
        match = re.search(r"- Date et Heure locales :\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", prompt)
        self.assertIsNotNone(match, "Le format de date et heure locales ne respecte pas YYYY-MM-DD HH:MM:SS.")

    def test_custom_timestamp_parameter_injection(self):
        """L'argument timestamp permet d'injecter une date/heure déterministe."""
        fixed_ts = "2026-11-02 14:15:16"
        prompt = ai.prompt_systeme('fr', timestamp=fixed_ts)
        self.assertIn(f"- Date et Heure locales : {fixed_ts}", prompt)

    def test_multilingual_grounding_and_consignes(self):
        """Le prompt adapte son étiquette de langue et sa consigne linguistique pour FR, EN, ES, DE."""
        attentes = {
            'fr': ("Français", "Réponds toujours en français."),
            'en': ("English", "Always answer in English."),
            'es': ("Español", "Responde siempre en español."),
            'de': ("Deutsch", "Antworte immer auf Deutsch."),
        }
        for code, (label, consigne) in attentes.items():
            prompt = ai.prompt_systeme(code)
            self.assertIn(f"- Langue active : {label}", prompt)
            self.assertIn(consigne, prompt)

    def test_airgap_and_security_invariants(self):
        """Le prompt affirme l'exécution 100% hors-ligne (air-gapped) et le modèle Yield/Resume HITL."""
        prompt = ai.prompt_systeme('fr')
        self.assertIn("100% hors-ligne (air-gapped)", prompt)
        self.assertIn("Yield/Resume", prompt)
        self.assertIn("PermissionRequiredException", prompt)
        # Aucune URL externe dans le prompt système
        self.assertNotRegex(prompt, r'https?://[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')


class TestToolSchemaEnumGeneration(unittest.TestCase):
    """Vérifie l'extraction des choix admissibles (enum) pour les paramètres bornés."""

    def test_controler_media_action_enum(self):
        """controler_media:action doit générer un enum strict ['lecture_pause', 'suivant', 'precedent']."""
        schema = llm_provider._function_to_json_schema(system.controler_media)
        props = schema['function']['parameters']['properties']
        self.assertIn('action', props)
        self.assertIn('enum', props['action'], "La propriété 'action' de controler_media doit comporter un champ 'enum'.")
        self.assertEqual(props['action']['enum'], ['lecture_pause', 'suivant', 'precedent'])

    def test_gerer_service_action_enum(self):
        """gerer_service:action doit générer un enum ['arreter', 'demarrer', 'desactiver', 'activer']."""
        schema = llm_provider._function_to_json_schema(system.gerer_service)
        props = schema['function']['parameters']['properties']
        self.assertIn('action', props)
        self.assertIn('enum', props['action'], "La propriété 'action' de gerer_service doit comporter un champ 'enum'.")
        self.assertEqual(props['action']['enum'], ['arreter', 'demarrer', 'desactiver', 'activer'])

    def test_gerer_app_demarrage_action_enum(self):
        """gerer_app_demarrage:action doit générer un enum ['desactiver', 'activer']."""
        schema = llm_provider._function_to_json_schema(system.gerer_app_demarrage)
        props = schema['function']['parameters']['properties']
        self.assertIn('action', props)
        self.assertIn('enum', props['action'], "La propriété 'action' de gerer_app_demarrage doit comporter un champ 'enum'.")
        self.assertEqual(props['action']['enum'], ['desactiver', 'activer'])

    def test_gerer_tache_planifiee_action_enum(self):
        """gerer_tache_planifiee:action doit générer un enum ['desactiver', 'activer', 'arreter']."""
        schema = llm_provider._function_to_json_schema(system.gerer_tache_planifiee)
        props = schema['function']['parameters']['properties']
        self.assertIn('action', props)
        self.assertIn('enum', props['action'], "La propriété 'action' de gerer_tache_planifiee doit comporter un champ 'enum'.")
        self.assertEqual(props['action']['enum'], ['desactiver', 'activer', 'arreter'])

    def test_no_false_positive_enum_for_open_ended_arguments(self):
        """Les exemples de chemins ou noms libres (ex: '...') ne doivent JAMAIS être transformés en enum."""
        fonctions_libres = [
            (files.creer_fichier, 'chemin'),
            (files.lister_fichiers, 'dossier'),
            (system.ouvrir_application, 'nom_commande'),
            (system.gerer_service, 'nom_service'),
            (files.trouver_doublons, 'dossier'),
        ]
        for fn, param_nom in fonctions_libres:
            schema = llm_provider._function_to_json_schema(fn)
            props = schema['function']['parameters']['properties']
            self.assertIn(param_nom, props)
            self.assertNotIn('enum', props[param_nom], f"Faux positif: {fn.__name__}:{param_nom} ne doit pas avoir d'enum.")

    def test_literal_type_annotation_extraction(self):
        """Une annotation typing.Literal['a', 'b'] produit un enum JSON Schema correspondant."""
        def fonction_test_literal(mode: typing.Literal['rapide', 'complet', 'silencieux']):
            """Fonction de test avec type Literal."""
            pass

        schema = llm_provider._function_to_json_schema(fonction_test_literal)
        props = schema['function']['parameters']['properties']
        self.assertIn('mode', props)
        self.assertIn('enum', props['mode'])
        self.assertEqual(props['mode']['enum'], ['rapide', 'complet', 'silencieux'])

    def test_docstring_une_parmi_extraction(self):
        """Une formulation 'Une parmi 'val1', 'val2'' dans la docstring produit un enum."""
        def fonction_test_doc(format_sortie: str):
            """Fonction de test.

            Args:
                format_sortie: Une parmi 'json', 'yaml', 'xml'.
            """
            pass

        schema = llm_provider._function_to_json_schema(fonction_test_doc)
        props = schema['function']['parameters']['properties']
        self.assertIn('format_sortie', props)
        self.assertIn('enum', props['format_sortie'])
        self.assertEqual(props['format_sortie']['enum'], ['json', 'yaml', 'xml'])


class TestMultiTurnContextAndToolPairPreservation(unittest.TestCase):
    """Vérifie la préservation insécable des paires tool_call/tool_response et la mémoire anaphorique."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        self._orig_max_context = api.MAX_CONTEXT_MESSAGES

    def tearDown(self):
        api.messages.clear()
        api.messages.extend(self._orig_messages)
        api.MAX_CONTEXT_MESSAGES = self._orig_max_context

    def test_tool_calls_and_tool_responses_preserved_across_turns(self):
        """Les tool_calls et réponses d'outils des tours précédents sont conservés dans la fenêtre active."""
        api.messages.clear()
        api.messages.append({'role': 'system', 'content': 'prompt'})

        # Tour 1
        t1_user = {'role': 'user', 'content': 'Liste les fichiers de Téléchargements'}
        t1_tc = {
            'role': 'assistant',
            'content': '',
            'tool_calls': [{
                'id': 'call_lister_01',
                'type': 'function',
                'function': {'name': 'lister_fichiers', 'arguments': {'dossier': '~/Downloads'}}
            }]
        }
        t1_resp = {
            'role': 'tool',
            'name': 'lister_fichiers',
            'tool_name': 'lister_fichiers',
            'tool_call_id': 'call_lister_01',
            'content': '["rapport_annuel.pdf", "bilan.xlsx", "presentation.pptx"]'
        }
        t1_summary = {'role': 'assistant', 'content': 'Voici les fichiers trouvés : rapport_annuel.pdf, bilan.xlsx et presentation.pptx.'}

        # Tour 2 (résolution anaphorique : "supprime le deuxième")
        t2_user = {'role': 'user', 'content': 'Supprime le deuxième fichier.'}

        api.messages.extend([t1_user, t1_tc, t1_resp, t1_summary, t2_user])

        fenetre = api._messages_avec_fenetre()

        # Vérifications
        self.assertEqual(fenetre[0]['role'], 'system')
        # Le tool_call du tour 1 doit être présent
        tc_msgs = [m for m in fenetre if m.get('tool_calls')]
        self.assertTrue(len(tc_msgs) >= 1, "Le message assistant avec tool_calls du tour 1 a été indûment supprimé.")
        self.assertEqual(tc_msgs[0]['tool_calls'][0]['id'], 'call_lister_01')

        # La réponse de l'outil du tour 1 doit être présente
        tool_msgs = [m for m in fenetre if m.get('role') == 'tool']
        self.assertTrue(len(tool_msgs) >= 1, "Le message de résultat d'outil du tour 1 a été indûment supprimé.")
        self.assertEqual(tool_msgs[0]['tool_call_id'], 'call_lister_01')
        self.assertIn("rapport_annuel.pdf", tool_msgs[0]['content'])

        # Le dernier message utilisateur doit être t2_user
        self.assertEqual(fenetre[-1]['content'], t2_user['content'])

    def test_anaphoric_memory_lookup_contains_exact_tool_output(self):
        """Le contexte transmis au LLM contient le texte brut des résultats d'outils antérieurs."""
        api.messages.clear()
        api.messages.append({'role': 'system', 'content': 'prompt'})
        api.messages.extend([
            {'role': 'user', 'content': 'Trouve le processus discord'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'call_pid', 'type': 'function', 'function': {'name': 'rechercher_processus', 'arguments': {'filtre': 'discord'}}}]},
            {'role': 'tool', 'name': 'rechercher_processus', 'tool_name': 'rechercher_processus', 'tool_call_id': 'call_pid', 'content': 'Processus trouvés :\n- discord.exe (PID: 8492)'},
            {'role': 'assistant', 'content': 'Discord s\'exécute avec le PID 8492.'},
            {'role': 'user', 'content': 'Arrête-le'},
        ])

        fenetre = api._messages_avec_fenetre()
        contenus = [m.get('content', '') for m in fenetre]
        self.assertTrue(any("PID: 8492" in c for c in contenus), "Le PID retourné par l'outil au tour 1 n'est plus accessible au tour 2.")

    def test_hardware_context_injected_only_on_latest_user_message(self):
        """L'état matériel (etat_systeme) n'est injecté que sur le dernier message utilisateur."""
        api.messages.clear()
        api.messages.append({'role': 'system', 'content': 'prompt'})
        api.messages.extend([
            {'role': 'user', 'content': 'Requête 1'},
            {'role': 'assistant', 'content': 'Réponse 1'},
            {'role': 'user', 'content': 'Requête 2'},
        ])

        etat = "CPU: 15% | RAM: 50%"
        fenetre = api._messages_avec_fenetre(etat_systeme=etat)

        # Requête 1 ne doit PAS comporter le contexte matériel
        req1 = next(m for m in fenetre if m.get('content', '').startswith('Requête 1'))
        self.assertNotIn(etat, req1['content'])

        # Requête 2 doit comporter le contexte matériel
        req2 = next(m for m in fenetre if m.get('content', '').startswith('Requête 2'))
        self.assertIn(etat, req2['content'])

    def test_ring_buffer_safe_cut_never_orphans_tool_response(self):
        """Lors d'une coupure d'historique, aucun message 'tool' n'est séparé de son assistant(tool_calls)."""
        api.MAX_CONTEXT_MESSAGES = 6
        api.messages.clear()
        api.messages.append({'role': 'system', 'content': 'prompt'})

        # Insérer 5 paires d'appels d'outils
        for i in range(5):
            api.messages.append({'role': 'user', 'content': f'Demande {i}'})
            api.messages.append({
                'role': 'assistant',
                'content': '',
                'tool_calls': [{'id': f'c_{i}', 'type': 'function', 'function': {'name': 'test_fn', 'arguments': {}}}]
            })
            api.messages.append({
                'role': 'tool',
                'name': 'test_fn',
                'tool_name': 'test_fn',
                'tool_call_id': f'c_{i}',
                'content': f'Résultat {i}'
            })
            api.messages.append({'role': 'assistant', 'content': f'Synthèse {i}'})

        fenetre = api._messages_avec_fenetre()

        # Invariant absolu (B.7.6) : pour chaque message 'tool', son assistant émetteur doit précéder
        for idx, msg in enumerate(fenetre):
            if msg.get('role') == 'tool':
                tcid = msg.get('tool_call_id')
                precedents_tc = [
                    tc['id']
                    for prev in fenetre[:idx]
                    if prev.get('tool_calls')
                    for tc in prev['tool_calls']
                ]
                self.assertIn(tcid, precedents_tc, f"Le message tool {tcid} est orphelin dans la fenêtre de contexte.")


class TestMultilingualToolRouter(unittest.TestCase):
    """Vérifie le routage multilingue (FR, EN, ES, DE) et le décloisonnement des outils."""

    def test_media_routing_multilingual(self):
        """Les requêtes multimédia sont correctement routées en FR, EN, ES, DE."""
        requetes = [
            ("mets la musique sur pause", [system.controler_media, system.rechercher_ou_jouer_media]),
            ("play some lofi music on spotify", [system.controler_media, system.rechercher_ou_jouer_media]),
            ("reproducir musica o pausar cancion", [system.controler_media, system.rechercher_ou_jouer_media]),
            ("spiele musik ab oder naechster titel", [system.controler_media, system.rechercher_ou_jouer_media]),
        ]
        for prompt, outils_attendus in requetes:
            outils = ai.selectionner_outils_pertinents(prompt)
            for attendu in outils_attendus:
                self.assertIn(attendu, outils, f"L'outil {attendu.__name__} n'a pas été sélectionné pour la requête: '{prompt}'")

    def test_application_lifecycle_routing_multilingual(self):
        """L'ouverture et la fermeture d'applications sont routées en FR, EN, ES, DE."""
        requetes = [
            ("ferme firefox et quitte le programme", [system.fermer_application]),
            ("close discord and kill the process", [system.fermer_application]),
            ("cerrar aplicacion firefox", [system.fermer_application]),
            ("schliesse das programm firefox", [system.fermer_application]),
            ("ouvre l'explorateur de fichiers", [system.ouvrir_explorateur]),
            ("open file explorer", [system.ouvrir_explorateur]),
        ]
        for prompt, outils_attendus in requetes:
            outils = ai.selectionner_outils_pertinents(prompt)
            for attendu in outils_attendus:
                self.assertIn(attendu, outils, f"L'outil {attendu.__name__} n'a pas été sélectionné pour la requête: '{prompt}'")

    def test_file_operations_routing_multilingual(self):
        """Les opérations sur les fichiers sont routées en FR, EN, ES, DE."""
        requetes = [
            ("crée un fichier note.txt sur le bureau", [files.creer_fichier]),
            ("create a new file report.txt", [files.creer_fichier]),
            ("borrar archivo temporal", [files.supprimer_fichier]),
            ("loesche datei temp.txt", [files.supprimer_fichier]),
            ("trouve les doublons dans mes documents", [files.trouver_doublons]),
            ("find duplicate files in documents", [files.trouver_doublons]),
            ("buscar duplicados en mis archivos", [files.trouver_doublons]),
            ("suche nach dateiduplikaten", [files.trouver_doublons]),
        ]
        for prompt, outils_attendus in requetes:
            outils = ai.selectionner_outils_pertinents(prompt)
            for attendu in outils_attendus:
                self.assertIn(attendu, outils, f"L'outil {attendu.__name__} n'a pas été sélectionné pour la requête: '{prompt}'")

    def test_maintenance_desiloing_multilingual(self):
        """Les requêtes de nettoyage activent conjointement les outils de fichiers et de maintenance système."""
        requetes = [
            "nettoie les fichiers temporaires et les caches du système",
            "clean temporary files and system cache",
            "limpiar archivos temporales y cache del sistema",
            "bereinige temporaere dateien und systemcache",
        ]
        for prompt in requetes:
            outils = ai.selectionner_outils_pertinents(prompt)
            # Doit inclure à la fois les outils de nettoyage système ET de suppression de fichiers
            self.assertIn(system.nettoyer_caches, outils, f"nettoyer_caches manquant pour: '{prompt}'")
            self.assertIn(files.supprimer_fichier, outils, f"supprimer_fichier manquant pour: '{prompt}'")

    def test_telemetry_and_hardware_routing_multilingual(self):
        """La désactivation de la télémétrie et l'inspection matérielle sont routées en FR, EN, ES, DE."""
        requetes_telemetrie = [
            "désactive la télémétrie partout sur le pc",
            "disable telemetry and diagtrack on windows",
            "desactivar telemetria del sistema",
            "deaktiviere telemetrie und diagtrack",
        ]
        for prompt in requetes_telemetrie:
            outils = ai.selectionner_outils_pertinents(prompt)
            self.assertIn(system.desactiver_telemetrie_pc, outils, f"desactiver_telemetrie_pc manquant pour: '{prompt}'")

    def test_routing_latency_strictly_sub_millisecond(self):
        """La latence moyenne de routage doit être strictement inférieure à 1.0 ms."""
        t0 = time.perf_counter()
        nb_iterations = 2000
        for _ in range(nb_iterations):
            ai.selectionner_outils_pertinents("nettoyer les fichiers temporaires et vérifier la batterie")
        latence_moyenne_ms = ((time.perf_counter() - t0) / nb_iterations) * 1000
        self.assertLess(latence_moyenne_ms, 1.0, f"Latence {latence_moyenne_ms:.4f} ms dépasse 1.0 ms")


if __name__ == '__main__':
    unittest.main()
