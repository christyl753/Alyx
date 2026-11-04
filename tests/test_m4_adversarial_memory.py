"""tests/test_m4_adversarial_memory.py
Milestone 4: Adversarial Stress Testing & Verification Suite (challenger_m4_1_gen2).
Adversarially tests and validates:
1. Multi-turn conversation sessions (50 to 100 turns) with single and multi-step tool calls.
2. Invariant B.7.6 verification: ring buffer safe-cut never orphans tool_call or tool_response.
3. Token ceiling verification: estimated tokens of context window never exceeds MAX_INPUT_TOKENS = 3296.
4. Exhaustive fuzzing of ring buffer cut points across heterogeneous dialog structures.
5. Air-gap verification: zero outbound WAN connections during all memory operations.
6. Atomic persistence & restoration under 100-turn history load.
"""
import copy
import json
import os
import random
import sys
import unittest
from unittest.mock import patch, MagicMock

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import ai
import api
from core import history, token_counter
from tests.e2e.harness import AirGapAssertionProbe, AirGapViolationError


class TestM4AdversarialMemoryIntegrity(unittest.TestCase):
    """Adversarial stress testing of Alyx context memory, token budgeting, and ring buffer."""

    def setUp(self):
        self._orig_messages = copy.deepcopy(api.messages)
        self._orig_max_context = api.MAX_CONTEXT_MESSAGES
        api.messages.clear()
        api.messages.append({'role': 'system', 'content': ai.prompt_systeme('fr')})

    def tearDown(self):
        api.messages.clear()
        api.messages.extend(self._orig_messages)
        api.MAX_CONTEXT_MESSAGES = self._orig_max_context

    def _valider_integrite_paires_b76(self, context_messages: list[dict], context_label: str = ""):
        """Oracle de vérification stricte de l'invariant BLOC B.7.6.
        1. Aucun message 'tool' n'existe sans un message 'assistant' antérieur le précédant
           qui contient un tool_call avec le même 'tool_call_id'.
        2. Tout message 'assistant' ayant des 'tool_calls' doit avoir TOUTES ses réponses
           'tool' correspondantes présentes dans la fenêtre de contexte retournée.
        """
        tool_call_ids_emitted = set()
        tool_call_ids_responded = set()

        for i, msg in enumerate(context_messages):
            role = msg.get('role')

            if role == 'assistant' and msg.get('tool_calls'):
                for tc in msg['tool_calls']:
                    tc_id = tc.get('id')
                    self.assertTrue(
                        tc_id,
                        f"[{context_label}] tool_call à l'index {i} manque d'ID: {tc}"
                    )
                    tool_call_ids_emitted.add(tc_id)

            elif role == 'tool':
                tc_id = msg.get('tool_call_id')
                self.assertTrue(
                    tc_id,
                    f"[{context_label}] Message tool à l'index {i} manque de tool_call_id: {msg}"
                )
                self.assertIn(
                    tc_id,
                    tool_call_ids_emitted,
                    f"[{context_label}] Message tool orphelin détecté à l'index {i}: "
                    f"tool_call_id '{tc_id}' n'a pas de tool_call parent antérieur dans le contexte."
                )
                tool_call_ids_responded.add(tc_id)

        # Vérification symétrique : chaque tool_call émis a reçu sa réponse dans le contexte
        missing_responses = tool_call_ids_emitted - tool_call_ids_responded
        self.assertFalse(
            missing_responses,
            f"[{context_label}] Tool_calls sans réponse correspondante dans le contexte (coupure asymétrique) : {missing_responses}"
        )

    def test_100_turns_extreme_multiturn_simulation_tokens_and_pairs(self):
        """Stress-test 100 tours complets avec alternance de tours simples, multi-step,
        parallèles, erreurs et refus HITL.
        Vérifie à CHAQUE tour que:
        - Les paires tool_call/tool_response respectent strictement l'invariant B.7.6.
        - Le total des tokens de contexte reste <= MAX_INPUT_TOKENS (3296).
        - Le prompt système préserve l'ancrage temporel.
        """
        random.seed(42)

        for tour_idx in range(1, 101):
            pattern = tour_idx % 5

            if pattern == 0:
                # Tour simple texte (utilisateur pose une question, assistant répond)
                api.messages.append({'role': 'user', 'content': f'Tour {tour_idx}: Quelle est la mémoire disponible ?'})
                api.messages.append({'role': 'assistant', 'content': f'Tour {tour_idx}: Il reste 12.4 Go de RAM disponible.'})

            elif pattern == 1:
                # Tour avec un appel d'outil unique (lister_fichiers)
                cid = f"call_list_{tour_idx}"
                api.messages.append({'role': 'user', 'content': f'Tour {tour_idx}: Liste les fichiers du dossier C:/dossier_{tour_idx}'})
                api.messages.append({
                    'role': 'assistant',
                    'content': '',
                    'tool_calls': [{'id': cid, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': f'{{"dossier": "C:/dossier_{tour_idx}"}}'}}]
                })
                # Résultat avec troncature standard
                api.messages.append({
                    'role': 'tool',
                    'name': 'lister_fichiers',
                    'tool_name': 'lister_fichiers',
                    'tool_call_id': cid,
                    'content': f"Contenu de C:/dossier_{tour_idx} (50 éléments):\n" + "\n".join(f"📄 doc_{tour_idx}_{k}.txt" for k in range(50))
                })
                api.messages.append({'role': 'assistant', 'content': f'Tour {tour_idx}: Dossier listé, 50 fichiers trouvés.'})

            elif pattern == 2:
                # Tour multi-step séquentiel : assistant appelle outil 1, reçoit réponse, puis appelle outil 2
                cid1 = f"call_seq1_{tour_idx}"
                cid2 = f"call_seq2_{tour_idx}"
                api.messages.append({'role': 'user', 'content': f'Tour {tour_idx}: Déplace les rapports du lot {tour_idx}'})
                api.messages.append({
                    'role': 'assistant',
                    'content': 'Analyse préalable...',
                    'tool_calls': [{'id': cid1, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "C:/Rapports"}'}}]
                })
                api.messages.append({
                    'role': 'tool',
                    'name': 'lister_fichiers',
                    'tool_name': 'lister_fichiers',
                    'tool_call_id': cid1,
                    'content': f"📄 rapport_a_{tour_idx}.pdf\n📄 rapport_b_{tour_idx}.pdf"
                })
                api.messages.append({
                    'role': 'assistant',
                    'content': 'Déplacement en cours...',
                    'tool_calls': [{'id': cid2, 'type': 'function', 'function': {'name': 'deplacer_fichier', 'arguments': f'{{"chemin_source": "rapport_a_{tour_idx}.pdf", "dossier_destination": "C:/Archives"}}'}}]
                })
                api.messages.append({
                    'role': 'tool',
                    'name': 'deplacer_fichier',
                    'tool_name': 'deplacer_fichier',
                    'tool_call_id': cid2,
                    'content': 'Fichier rapport_a.pdf déplacé vers C:/Archives.'
                })
                api.messages.append({'role': 'assistant', 'content': f'Tour {tour_idx}: Tous les rapports du lot {tour_idx} ont été traités.'})

            elif pattern == 3:
                # Tour multi-outils parallèles (2 tool_calls émis dans le même message assistant)
                cid_p1 = f"call_par1_{tour_idx}"
                cid_p2 = f"call_par2_{tour_idx}"
                api.messages.append({'role': 'user', 'content': f'Tour {tour_idx}: Déplace rapport1 et rapport2 simultanément.'})
                api.messages.append({
                    'role': 'assistant',
                    'content': 'Lancement des opérations en parallèle...',
                    'tool_calls': [
                        {'id': cid_p1, 'type': 'function', 'function': {'name': 'deplacer_fichier', 'arguments': f'{{"chemin_source": "f1_{tour_idx}.dat", "dossier_destination": "C:/Dst"}}'}},
                        {'id': cid_p2, 'type': 'function', 'function': {'name': 'deplacer_fichier', 'arguments': f'{{"chemin_source": "f2_{tour_idx}.dat", "dossier_destination": "C:/Dst"}}'}}
                    ]
                })
                api.messages.append({
                    'role': 'tool',
                    'name': 'deplacer_fichier',
                    'tool_name': 'deplacer_fichier',
                    'tool_call_id': cid_p1,
                    'content': 'OK f1'
                })
                api.messages.append({
                    'role': 'tool',
                    'name': 'deplacer_fichier',
                    'tool_name': 'deplacer_fichier',
                    'tool_call_id': cid_p2,
                    'content': 'OK f2'
                })
                api.messages.append({'role': 'assistant', 'content': f'Tour {tour_idx}: Déplacements terminés avec succès.'})

            elif pattern == 4:
                # Tour HITL avec refus utilisateur (Yield/Resume)
                cid_h = f"call_hitl_{tour_idx}"
                api.messages.append({'role': 'user', 'content': f'Tour {tour_idx}: Supprime le fichier critique {tour_idx}.sys'})
                api.messages.append({
                    'role': 'assistant',
                    'content': 'Demande de permission requise.',
                    'tool_calls': [{'id': cid_h, 'type': 'function', 'function': {'name': 'supprimer_fichier', 'arguments': f'{{"chemin": "{tour_idx}.sys"}}'}}]
                })
                api.messages.append({
                    'role': 'tool',
                    'name': 'supprimer_fichier',
                    'tool_name': 'supprimer_fichier',
                    'tool_call_id': cid_h,
                    'content': "Action refusée par l'utilisateur."
                })
                api.messages.append({'role': 'assistant', 'content': f'Tour {tour_idx}: Suppression annulée conformément à votre refus.'})

            # Troncature historique périodique (comme dans api.py:596)
            api._tronquer_historique()

            # Vérification empirique de _messages_avec_fenetre à chaque tour
            contexte = api._messages_avec_fenetre()

            # 1. Borne stricte sur les tokens
            total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte)
            self.assertLessEqual(
                total_tokens,
                token_counter.MAX_INPUT_TOKENS,
                f"Dépassement du budget token au tour {tour_idx}: {total_tokens} > {token_counter.MAX_INPUT_TOKENS}"
            )
            self.assertLessEqual(
                total_tokens,
                3296,
                f"Dépassement de la constante 3296 tokens au tour {tour_idx}: {total_tokens}"
            )

            # 2. Intégrité BLOC B.7.6
            self._valider_integrite_paires_b76(contexte, f"Tour {tour_idx}")

            # 3. Ancrage temporel dans le system_prompt
            self.assertIn("Date et Heure locales :", contexte[0]['content'])

    def test_ring_buffer_safe_cut_exhaustive_fuzzing(self):
        """Fuzzing exhaustif de _index_coupure_sure sur des fenêtres de 1 à N messages.
        Garantit que quelque soit la taille de la coupure demandée, le sous-ensemble
        de messages conservé ne brise JAMAIS une paire tool_call / tool_response.
        """
        recents = [
            {'role': 'user', 'content': 'Tour 1 : Lister'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}]},
            {'role': 'tool', 'name': 'lister_fichiers', 'tool_call_id': 'c1', 'content': 'Fichiers: a, b, c'},
            {'role': 'assistant', 'content': 'Résultat 1'},

            {'role': 'user', 'content': 'Tour 2 : Déplacer multi-step'},
            {'role': 'assistant', 'content': 'Etape 1', 'tool_calls': [{'id': 'c2', 'function': {'name': 'deplacer_fichier', 'arguments': '{"source":"a"}'}}]},
            {'role': 'tool', 'name': 'deplacer_fichier', 'tool_call_id': 'c2', 'content': 'OK a'},
            {'role': 'assistant', 'content': 'Etape 2', 'tool_calls': [{'id': 'c3', 'function': {'name': 'deplacer_fichier', 'arguments': '{"source":"b"}'}}]},
            {'role': 'tool', 'name': 'deplacer_fichier', 'tool_call_id': 'c3', 'content': 'OK b'},
            {'role': 'assistant', 'content': 'Résultat 2'},

            {'role': 'user', 'content': 'Tour 3 : Parallèle 3 calls'},
            {'role': 'assistant', 'content': 'Parallèle', 'tool_calls': [
                {'id': 'c4', 'function': {'name': 'deplacer_fichier', 'arguments': '{"source":"x"}'}},
                {'id': 'c5', 'function': {'name': 'deplacer_fichier', 'arguments': '{"source":"y"}'}},
                {'id': 'c6', 'function': {'name': 'deplacer_fichier', 'arguments': '{"source":"z"}'}}
            ]},
            {'role': 'tool', 'name': 'deplacer_fichier', 'tool_call_id': 'c4', 'content': 'OK x'},
            {'role': 'tool', 'name': 'deplacer_fichier', 'tool_call_id': 'c5', 'content': 'OK y'},
            {'role': 'tool', 'name': 'deplacer_fichier', 'tool_call_id': 'c6', 'content': 'OK z'},
            {'role': 'assistant', 'content': 'Résultat 3'},

            {'role': 'user', 'content': 'Tour 4 : HITL refus'},
            {'role': 'assistant', 'content': 'Suppression', 'tool_calls': [{'id': 'c7', 'function': {'name': 'supprimer_fichier', 'arguments': '{"chemin":"del.txt"}'}}]},
            {'role': 'tool', 'name': 'supprimer_fichier', 'tool_call_id': 'c7', 'content': 'Refusé'},
            {'role': 'assistant', 'content': 'Annulé.'},
        ]

        # Tester pour TOUTES les valeurs de max_messages de 1 à len(recents)
        for max_msg in range(1, len(recents) + 1):
            cut_idx = api._index_coupure_sure(recents, max_msg)
            conserve = recents[cut_idx:]

            # Vérifier l'intégrité des paires dans le segment conservé
            self._valider_integrite_paires_b76(conserve, f"Safe-cut max_messages={max_msg}")

    def test_token_budget_defensive_safety_net_under_pathological_inputs(self):
        """Vérifie que même sous des entrées pathologiques extrêmes:
        1. Une invite utilisateur de 50 000 caractères est tronquée avec notice explicite
        2. Le total de tokens ne dépasse JAMAIS 3296 tokens
        3. L'intégrité de la structure est préservée
        """
        prompt_gigantesque = "Analyse et résume ce fichier : " + ("données_très_longues " * 3000)
        api.messages.append({'role': 'user', 'content': prompt_gigantesque})

        contexte = api._messages_avec_fenetre()
        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte)

        self.assertLessEqual(total_tokens, token_counter.MAX_INPUT_TOKENS)
        self.assertLessEqual(total_tokens, 3296)

        user_msg = next(m for m in contexte if m.get('role') == 'user')
        self.assertIn("invite utilisateur tronquée pour respecter le budget de 3296 tokens", user_msg['content'])

    def test_air_gap_zero_wan_under_continuous_multi_turn_load(self):
        """Garantit l'absence totale de communication réseau externe (Air-gap BLOC B.8)
        pendant 50 tours consécutifs d'appels à _messages_avec_fenetre et à la persistance.
        """
        with AirGapAssertionProbe():
            for i in range(50):
                api.messages.append({'role': 'user', 'content': f'Requête air-gap tour {i}'})
                api.messages.append({'role': 'assistant', 'content': f'Réponse locale tour {i}'})
                if i % 10 == 0:
                    api._messages_avec_fenetre()
                    history.sauvegarder_etat_session(api.messages, "session_airgap_stress")

            # Vérification finale
            ctx = api._messages_avec_fenetre()
            self.assertLessEqual(sum(token_counter.estimer_tokens_message(m) for m in ctx), 3296)

        # Nettoyage
        history.reinitialiser_etat_session("session_airgap_stress")

    def test_session_persistence_roundtrip_under_massive_history(self):
        """Vérifie la sérialisation atomique, la désérialisation et la restauration
        d'une session contenant 100 tours avec métadonnées et tool_calls.
        """
        for i in range(100):
            api.messages.append({'role': 'user', 'content': f'Tour {i}'})
            if i % 2 == 0:
                cid = f"call_persist_{i}"
                api.messages.append({
                    'role': 'assistant',
                    'content': f'Action {i}',
                    'tool_calls': [{'id': cid, 'type': 'function', 'function': {'name': 'lister_fichiers', 'arguments': '{"dossier":"."}'}}]
                })
                api.messages.append({
                    'role': 'tool',
                    'name': 'lister_fichiers',
                    'tool_call_id': cid,
                    'content': 'f1.txt, f2.txt'
                })
            api.messages.append({'role': 'assistant', 'content': f'Fin tour {i}'})

        succes = history.sauvegarder_etat_session(api.messages, "session_test_m4")
        self.assertTrue(succes, "La sauvegarde de session a échoué")

        # Chargement
        restaure = history.charger_etat_session("session_test_m4")
        self.assertIsNotNone(restaure)
        self.assertEqual(len(restaure), len(api.messages))

        # Restauration dans l'API
        api.messages.clear()
        api.messages.append({'role': 'system', 'content': 'prompt'})
        nb_restaures = api.restaurer_etat_session("session_test_m4")
        self.assertGreater(nb_restaures, 0)

        # Validation de la fenêtre après restauration
        contexte = api._messages_avec_fenetre()
        self.assertLessEqual(sum(token_counter.estimer_tokens_message(m) for m in contexte), 3296)
        self._valider_integrite_paires_b76(contexte, "Session restaurée 100 tours")

        # Nettoyage
        history.reinitialiser_etat_session("session_test_m4")

    def test_empirical_demonstration_tools_token_pressure_on_user_query(self):
        """Vérifie que le routage granulaire d'outils et le budget dynamique protègent l'invite utilisateur.
        Constat factuel après remédiation :
        - prompt_systeme('fr') consomme ~772 tokens.
        - Le sous-domaine de fichiers sélectionne <= 6 outils (<= 1000 tokens).
        - L'invite utilisateur au tour 0 reste intacte sans troncature.
        - Le total d'entrée reste strictement sous la borne de 3296 tokens.
        """
        user_query = "Trouve les fichiers factures dans Telechargements et range les dans Compta"
        api.messages.append({'role': 'user', 'content': user_query})

        tools_fichiers = ai.selectionner_outils_pertinents(user_query)
        self.assertLessEqual(len(tools_fichiers), 6)
        tokens_tools = token_counter.estimer_tokens_outils(tools_fichiers)
        self.assertLessEqual(tokens_tools, 1000)

        # Appel avec les outils du domaine
        contexte = api._messages_avec_fenetre(tools=tools_fichiers)
        user_msg = next(m for m in contexte if m.get('role') == 'user')

        # Constat vérifié : l'invite utilisateur est intacte et non tronquée
        self.assertEqual(user_msg['content'], user_query)
        self.assertNotIn("tronquée", user_msg['content'])

        total_tokens = sum(token_counter.estimer_tokens_message(m) for m in contexte) + token_counter.estimer_tokens_outils(tools_fichiers)
        self.assertLessEqual(total_tokens, 3296)

        # L'invariant BLOC B.7.6 reste néanmoins respecté (0 orphelins)
        self._valider_integrite_paires_b76(contexte, "Sous-domaine fichiers sans saturation")


    def test_multistep_cancellation_preserves_pair_integrity(self):
        """Vérifie que l'interruption d'une chaîne multi-step (ex: Kill Switch pendant un tour)
        ne laisse aucun tool_call ou tool_response orphelin dans l'historique ou dans la fenêtre.
        """
        api.messages.append({'role': 'user', 'content': 'Tâche multi-step interrompue'})
        cid1 = 'call_step1_interrupted'
        api.messages.append({
            'role': 'assistant',
            'content': 'Étape 1 en cours...',
            'tool_calls': [{'id': cid1, 'function': {'name': 'lister_fichiers', 'arguments': '{"dossier":"."}'}}]
        })
        api.messages.append({
            'role': 'tool',
            'name': 'lister_fichiers',
            'tool_call_id': cid1,
            'content': 'liste_fichiers'
        })
        # Assistant interrompu avant d'émettre l'étape 2
        api.messages.append({
            'role': 'assistant',
            'content': "Génération interrompue par l'utilisateur."
        })

        contexte = api._messages_avec_fenetre()
        self._valider_integrite_paires_b76(contexte, "Chaîne interrompue par Kill Switch")


if __name__ == '__main__':
    unittest.main()
