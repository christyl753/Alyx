"""tests/test_m2_challenger_r2_stress.py
Suite de tests adversariaux et de résistance empirique pour le Milestone 2 (R2) :
Tronquage intelligent des retours d'outils et intégrité atomique du ring buffer.

Probes exécutées :
1. Ring Buffer Fuzzing : génération de topologies de dialogue aléatoires (appels parallèles,
   enchaînements, rejets HITL, abandons, annulations kill switch) et vérification exhaustive
   que TOUT point de coupure produit par `_index_coupure_sure` ou par le compactage multi-paliers
   d'_messages_avec_fenetre n'engendre JAMAIS d'orphelin tool_call ou tool_response (BLOC B.7.6).
2. Defensive Sanitizer Stress Test : injection de charges hostiles/chaotiques dans `tronquer_sortie_outil`
   (100k emojis Unicode, clusters ZWJ, None, objets circulaires, bytearrays, entiers géants,
   types hétérogènes, bornes extrêmes de max_chars).
"""
import copy
import json
import os
import random
import sys
import time
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import ai
import api
from core import token_counter
from tests.e2e.harness import AirGapAssertionProbe


class TestDefensiveSanitizerAdversarialStress(unittest.TestCase):
    """Probe 1 : Tests d'adversité sur tronquer_sortie_outil dans api.py et ai.py."""

    def test_100k_unicode_emojis_payload(self):
        """Charge extrême : 100 000 emojis '🎉' (400 Ko+ UTF-8).
        Vérifie le clamp strict à 4000 caractères, la notice exacte et la performance (< 10 ms)."""
        payload = "🎉" * 100_000

        t0 = time.perf_counter()
        res_api = api.tronquer_sortie_outil(payload, max_chars=4000)
        duree_api_ms = (time.perf_counter() - t0) * 1000

        res_ai = ai.tronquer_sortie_outil(payload, max_chars=4000)

        # Performance : ne doit pas bloquer la boucle d'événements
        self.assertLess(duree_api_ms, 15.0, f"Temps de traitement trop long: {duree_api_ms:.2f} ms")

        # Validation de l'écrêtage
        prefixe_attendu = "🎉" * 4000
        notice_attendue = "\n[Sortie tronquée : affichage des 4000 premiers caractères sur 100000]"

        self.assertEqual(res_api, prefixe_attendu + notice_attendue)
        self.assertEqual(res_ai, prefixe_attendu + notice_attendue)
        self.assertEqual(len(prefixe_attendu), 4000)

    def test_complex_grapheme_clusters_and_zwj_sequences(self):
        """Séquences ZWJ complexes : 2 000 emojis famille 👨‍👩‍👧‍👦 (7 codepoints par glyphe)."""
        emoji_famille = "\U0001F468\u200D\U0001F469\u200D\U0001F467\u200D\U0001F466"
        payload = emoji_famille * 2000  # 14 000 codepoints
        total_len = len(payload)

        res = api.tronquer_sortie_outil(payload, max_chars=4000)
        self.assertTrue(res.startswith(payload[:4000]))
        self.assertIn(f"[Sortie tronquée : affichage des 4000 premiers caractères sur {total_len}]", res)

    def test_none_and_empty_payloads(self):
        """Payloads vides et None : doivent renvoyer une chaîne vide sans lever d'exception."""
        self.assertEqual(api.tronquer_sortie_outil(None), "")
        self.assertEqual(ai.tronquer_sortie_outil(None), "")
        self.assertEqual(api.tronquer_sortie_outil(""), "")
        self.assertEqual(ai.tronquer_sortie_outil(""), "")

    def test_circular_data_structures(self):
        """Structures de données circulaires (récursion infinie potentielle)."""
        # Dict circulaire
        d = {"nom": "alyx", "version": 2}
        d["self"] = d
        res_dict = api.tronquer_sortie_outil(d, max_chars=4000)
        self.assertIn("{...}", res_dict)
        self.assertIsInstance(res_dict, str)

        # Liste circulaire
        lst = [1, 2, 3]
        lst.append(lst)
        res_lst = api.tronquer_sortie_outil(lst, max_chars=4000)
        self.assertIn("[...]", res_lst)
        self.assertIsInstance(res_lst, str)

    def test_binary_and_bytearray_payloads(self):
        """Octets bruts et bytearrays volumineux."""
        # Bytearray de 20 000 octets contenant des zéros, ff et des séquences non-ASCII
        brut = bytearray(b"\x00\xff\xfe\x01\x80\x7f" * 3500)
        res = api.tronquer_sortie_outil(brut, max_chars=4000)

        self.assertIsInstance(res, str)
        self.assertTrue(res.startswith(str(brut)[:4000]))
        self.assertIn(f"[Sortie tronquée : affichage des 4000 premiers caractères sur {len(str(brut))}]", res)

    def test_giant_integers_and_special_numeric_types(self):
        """Entier volumineux (1000 chiffres) et flottants spéciaux (NaN, Inf)."""
        entier_volumineux = 10 ** 1000
        res_int = api.tronquer_sortie_outil(entier_volumineux, max_chars=400)
        self.assertIn(f"[Sortie tronquée : affichage des 400 premiers caractères sur {len(str(entier_volumineux))}]", res_int)
        self.assertTrue(res_int.startswith("10000"))

        self.assertEqual(api.tronquer_sortie_outil(float('nan')), "nan")
        self.assertEqual(api.tronquer_sortie_outil(float('inf')), "inf")

    def test_adversarial_vulnerability_giant_int_exceeds_sys_limit(self):
        """Vulnérabilité identifiée : Si un outil produit un entier dépassant la limite CVE-2020-10735
        (4300 chiffres, ex: 10**5000), str(resultat) lève ValueError au lieu d'un clamp sécurisé."""
        entier_geant = 10 ** 5000
        with self.assertRaises(ValueError) as ctx:
            api.tronquer_sortie_outil(entier_geant)
        self.assertIn("Exceeds the limit (4300 digits)", str(ctx.exception))

    def test_adversarial_vulnerability_unstringable_tool_return_orphans_tool_call(self):
        """Vulnérabilité identifiée : Si un outil retourne un objet dont la conversion str() échoue
        (ou un entier > 4300 chiffres), tronquer_sortie_outil lève une exception non interceptée dans
        _ajouter_resultat (appelé hors du try/except dans _executer_outils).
        Conséquence : la tool response n'est jamais ajoutée, laissant le tool_call orphelin dans messages (B.7.6)."""
        class BrokenStr:
            def __str__(self):
                raise RuntimeError("Erreur interne __str__")

        orig_msgs = list(api.messages)
        try:
            del api.messages[1:]
            tc = {'id': 'call_broken_1', 'function': {'name': 'outil_corrompu'}}
            api.messages.append({'role': 'assistant', 'content': 'Appel', 'tool_calls': [tc]})

            # _ajouter_resultat tente de tronquer le résultat et crash
            with self.assertRaises(RuntimeError):
                api._ajouter_resultat(tc, BrokenStr())

            # Constat empirique : api.messages contient le tool_call mais AUCUNE tool response
            self.assertEqual(len(api.messages), 2)
            self.assertEqual(api.messages[-1].get('role'), 'assistant')
            self.assertFalse(any(m.get('role') == 'tool' for m in api.messages))
        finally:
            api.messages[:] = orig_msgs

    def test_adversarial_vulnerability_safe_cut_index_error_on_zero(self):
        """Vulnérabilité identifiée : _index_coupure_sure lève IndexError si max_messages <= 0
        car start_idx = len(recents) et recents[start_idx] est hors limites."""
        recents = [{'role': 'user', 'content': 'test'}]
        with self.assertRaises(IndexError):
            api._index_coupure_sure(recents, 0)

    def test_extreme_and_boundary_max_chars(self):
        """Valeurs limites pour max_chars (0, négatif, égalité exacte, supérieur à la taille)."""
        texte = "Message de test avec cinquante caractères exactement."

        # Égalité exacte
        res_exact = api.tronquer_sortie_outil(texte, max_chars=len(texte))
        self.assertEqual(res_exact, texte)
        self.assertNotIn("Sortie tronquée", res_exact)

        # max_chars = 0
        res_zero = api.tronquer_sortie_outil(texte, max_chars=0)
        self.assertEqual(res_zero, f"\n[Sortie tronquée : affichage des 0 premiers caractères sur {len(texte)}]")

        # max_chars très grand (pas de troncature)
        res_grand = api.tronquer_sortie_outil(texte, max_chars=1_000_000)
        self.assertEqual(res_grand, texte)

    def test_condenser_retour_outil_chaos(self):
        """Robustesse chaotique de _condenser_retour_outil face à des formats aberrants."""
        # Contenu None ou vide
        self.assertEqual(api._condenser_retour_outil("lister_fichiers", None), "")
        self.assertEqual(api._condenser_retour_outil("lister_fichiers", ""), "")

        # Outil lister avec 10 000 lignes
        lignes = "\n".join([f"fichier_{i}.txt" for i in range(10000)])
        cond = api._condenser_retour_outil("lister_fichiers", lignes)
        self.assertIn("fichier_0.txt", cond)
        self.assertIn("9999 éléments détaillés omis", cond)

        # Outil lire avec contenu massif sans retour à la ligne (100k caractères)
        long_monobloc = "X" * 100_000
        cond_lire = api._condenser_retour_outil("lire_fichier_securise", long_monobloc)
        self.assertIn("100000 car.", cond_lire)
        self.assertLess(len(cond_lire), 200)

        # Outil système avec sortie multiligne
        sortie_cmd = "\n".join([f"Process {i} RUNNING" for i in range(500)])
        cond_cmd = api._condenser_retour_outil("executer_commande_systeme", sortie_cmd, max_chars=120)
        self.assertIn("Process 0 RUNNING", cond_cmd)
        self.assertIn("sortie condensée", cond_cmd)


class TestRingBufferFuzzingAndPairIntegrity(unittest.TestCase):
    """Probe 2 : Fuzzing rigoureux de l'intégrité atomique des paires tool_call/tool_response (BLOC B.7.6)."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def _valider_integrite_paires(self, messages_sequence, source_description=""):
        """Oracle de vérification stricte BLOC B.7.6 :
        1. Aucun message 'tool' n'est orphelin (son tool_call_id DOIT exister dans un assistant précédent).
        2. Aucun message 'assistant' avec 'tool_calls' n'a de réponse 'tool' dissociée.
        3. Le premier message d'une tranche n'est JAMAIS un 'tool' orphelin."""
        tool_calls_declares = set()
        tool_responses_recues = set()

        for idx, msg in enumerate(messages_sequence):
            role = msg.get('role')

            if role == 'assistant' and msg.get('tool_calls'):
                for tc in msg['tool_calls']:
                    tc_id = tc['id']
                    tool_calls_declares.add(tc_id)

            elif role == 'tool':
                tc_id = msg.get('tool_call_id')
                # Invariant fondamental 1 : toute réponse d'outil doit avoir son appel dans la séquence
                self.assertIn(
                    tc_id,
                    tool_calls_declares,
                    f"VIOLATION BLOC B.7.6 dans [{source_description}] à l'index {idx} : "
                    f"tool response avec tool_call_id='{tc_id}' est orpheline sans tool_call assistant !"
                )
                tool_responses_recues.add(tc_id)

        # Si le premier message n'est pas 'system', il ne doit pas être un rôle 'tool'
        non_system = [m for m in messages_sequence if m.get('role') != 'system']
        if non_system:
            self.assertNotEqual(
                non_system[0].get('role'),
                'tool',
                f"VIOLATION BLOC B.7.6 dans [{source_description}] : le contexte commence par un message 'tool' orphelin !"
            )

    def test_exhaustive_safe_cut_on_parallel_tool_calls(self):
        """Fuzzing exhaustif de _index_coupure_sure sur un tour à 4 tool_calls parallèles.
        Pour TOUTE valeur de max_messages >= 1 (de 1 à N+5), la tranche ne doit JAMAIS
        dissocier une paire tool_call / tool_response."""
        tc_ids = [f"call_p_{k}" for k in range(4)]
        tcs = [{'id': cid, 'function': {'name': f'outil_{k}'}} for k, cid in enumerate(tc_ids)]

        recents = [
            {'role': 'user', 'content': 'Lance 4 outils en parallèle'},
            {'role': 'assistant', 'content': 'Exécution parallèle', 'tool_calls': tcs},
            {'role': 'tool', 'name': 'outil_0', 'tool_call_id': tc_ids[0], 'content': 'res 0'},
            {'role': 'tool', 'name': 'outil_1', 'tool_call_id': tc_ids[1], 'content': 'res 1'},
            {'role': 'tool', 'name': 'outil_2', 'tool_call_id': tc_ids[2], 'content': 'res 2'},
            {'role': 'tool', 'name': 'outil_3', 'tool_call_id': tc_ids[3], 'content': 'res 3'},
            {'role': 'assistant', 'content': 'Toutes les opérations sont terminées.'},
        ]

        # Tester TOUTES les coupes possibles de max_messages = 1 à 15
        for max_msg in range(1, 16):
            idx = api._index_coupure_sure(recents, max_msg)
            tranche = recents[idx:]
            self._valider_integrite_paires(tranche, f"Parallel tools, max_messages={max_msg}")

    def test_exhaustive_safe_cut_on_sequential_chained_tool_calls(self):
        """Fuzzing exhaustif sur des appels d'outils enchaînés séquentiellement au sein du même échange."""
        recents = [
            {'role': 'user', 'content': 'Enchaîne étape 1 puis étape 2'},
            {'role': 'assistant', 'content': 'Étape 1', 'tool_calls': [{'id': 'call_chain_1', 'function': {'name': 'fn1'}}]},
            {'role': 'tool', 'name': 'fn1', 'tool_call_id': 'call_chain_1', 'content': 'res 1'},
            {'role': 'assistant', 'content': 'Étape 2', 'tool_calls': [{'id': 'call_chain_2', 'function': {'name': 'fn2'}}]},
            {'role': 'tool', 'name': 'fn2', 'tool_call_id': 'call_chain_2', 'content': 'res 2'},
            {'role': 'assistant', 'content': 'Terminé.'},
        ]

        for max_msg in range(1, 15):
            idx = api._index_coupure_sure(recents, max_msg)
            tranche = recents[idx:]
            self._valider_integrite_paires(tranche, f"Chained tools, max_messages={max_msg}")

    def test_exhaustive_safe_cut_on_hitl_rejections_and_yields(self):
        """Fuzzing exhaustif sur un cycle HITL avec suspension, refus utilisateur et abandon."""
        recents = [
            {'role': 'user', 'content': 'Supprime le fichier critique'},
            {'role': 'assistant', 'content': 'Demande permission', 'tool_calls': [{'id': 'call_hitl_1', 'function': {'name': 'supprimer_fichier'}}]},
            {'role': 'tool', 'name': 'supprimer_fichier', 'tool_call_id': 'call_hitl_1', 'content': "L'utilisateur a refusé cette action."},
            {'role': 'assistant', 'content': 'Bien reçu, action annulée.'},
            {'role': 'user', 'content': 'Deuxième tentative avec deux actions'},
            {'role': 'assistant', 'content': 'Tentative', 'tool_calls': [
                {'id': 'call_hitl_2a', 'function': {'name': 'action_a'}},
                {'id': 'call_hitl_2b', 'function': {'name': 'action_b'}}
            ]},
            {'role': 'tool', 'name': 'action_a', 'tool_call_id': 'call_hitl_2a', 'content': "Action non validée par l'utilisateur (abandonnée)."},
            {'role': 'tool', 'name': 'action_b', 'tool_call_id': 'call_hitl_2b', 'content': "Action non validée par l'utilisateur (abandonnée)."},
            {'role': 'assistant', 'content': 'Abandon enregistré.'},
        ]

        for max_msg in range(1, 20):
            idx = api._index_coupure_sure(recents, max_msg)
            tranche = recents[idx:]
            self._valider_integrite_paires(tranche, f"HITL Rejections, max_messages={max_msg}")

    def test_randomized_chaotic_dialog_generator_fuzzing(self):
        """Générateur aléatoire de dialogues chaotiques (30 tours hétérogènes).
        Simule des combinaisons arbitraires d'outils, de textes et de réponses.
        Vérifie l'oracle d'intégrité sur 100 découpages aléatoires."""
        rng = random.Random(42)  # Déterministe pour reproductibilité
        dialog = []
        call_counter = 0

        for turn_idx in range(25):
            dialog.append({'role': 'user', 'content': f'Demande fuzzer tour {turn_idx}'})

            mode = rng.choice(['direct', 'single_tool', 'multi_tool', 'chained_tool', 'rejected_tool'])
            if mode == 'direct':
                dialog.append({'role': 'assistant', 'content': f'Réponse directe tour {turn_idx}'})

            elif mode == 'single_tool':
                cid = f"fuzz_call_{call_counter}"
                call_counter += 1
                dialog.append({'role': 'assistant', 'content': 'Appel outil', 'tool_calls': [{'id': cid, 'function': {'name': 'outil_fuzz'}}]})
                dialog.append({'role': 'tool', 'name': 'outil_fuzz', 'tool_call_id': cid, 'content': f'Sortie tour {turn_idx}'})
                dialog.append({'role': 'assistant', 'content': f'Conclusion tour {turn_idx}'})

            elif mode == 'multi_tool':
                nb_tools = rng.randint(2, 5)
                cids = [f"fuzz_call_{call_counter + k}" for k in range(nb_tools)]
                call_counter += nb_tools
                tcs = [{'id': cid, 'function': {'name': f'multi_fn_{k}'}} for k, cid in enumerate(cids)]
                dialog.append({'role': 'assistant', 'content': 'Multi outils', 'tool_calls': tcs})
                for k, cid in enumerate(cids):
                    dialog.append({'role': 'tool', 'name': f'multi_fn_{k}', 'tool_call_id': cid, 'content': f'Sortie multi {k}'})
                dialog.append({'role': 'assistant', 'content': f'Fin multi tour {turn_idx}'})

            elif mode == 'chained_tool':
                for step in range(2):
                    cid = f"fuzz_call_{call_counter}"
                    call_counter += 1
                    dialog.append({'role': 'assistant', 'content': f'Étape {step}', 'tool_calls': [{'id': cid, 'function': {'name': f'step_{step}'}}]})
                    dialog.append({'role': 'tool', 'name': f'step_{step}', 'tool_call_id': cid, 'content': f'Sortie étape {step}'})
                dialog.append({'role': 'assistant', 'content': f'Fin chaîne tour {turn_idx}'})

            elif mode == 'rejected_tool':
                cid = f"fuzz_call_{call_counter}"
                call_counter += 1
                dialog.append({'role': 'assistant', 'content': 'Outil sensible', 'tool_calls': [{'id': cid, 'function': {'name': 'danger_fn'}}]})
                dialog.append({'role': 'tool', 'name': 'danger_fn', 'tool_call_id': cid, 'content': "L'utilisateur a refusé cette action."})
                dialog.append({'role': 'assistant', 'content': 'Action refusée prise en compte.'})

        # Test sur toutes les coupures de 1 à len(dialog)
        for max_msg in range(1, len(dialog) + 5):
            idx = api._index_coupure_sure(dialog, max_msg)
            tranche = dialog[idx:]
            self._valider_integrite_paires(tranche, f"Fuzzing dialog, max_messages={max_msg}")

    def test_messages_avec_fenetre_pair_integrity_under_heavy_saturation(self):
        """Vérifie que api._messages_avec_fenetre() sous saturation sévère (20 tours volumineux)
        respecte simultanément :
        1. Le budget de tokens MAX_INPUT_TOKENS (<= 3296 tokens).
        2. L'intégrité atomique absolue des paires tool_call / tool_response.
        3. La présence du prompt système en tête."""
        with AirGapAssertionProbe():
            for i in range(20):
                cid = f"heavy_call_{i}"
                api.messages.append({'role': 'user', 'content': f'Exécute la tâche lourde numéro {i} avec fichier volumineux'})
                api.messages.append({
                    'role': 'assistant',
                    'content': f'Démarrage tâche {i}',
                    'tool_calls': [{'id': cid, 'function': {'name': 'lister_fichiers', 'arguments': '{"dir": "C:\\\\"}'}}]
                })
                # Sortie d'outil volumineuse déjà tronquée par Tier 1
                sortie = "Fichier...\n" * 40 + f"[Sortie tronquée : affichage des 50 premiers éléments sur {200 + i*10}]"
                api._ajouter_resultat({'id': cid, 'function': {'name': 'lister_fichiers'}}, sortie)
                api.messages.append({'role': 'assistant', 'content': f'Résultat complet pour la tâche {i}. Tout est en ordre.'})

            contexte_optimise = api._messages_avec_fenetre()

            # Oracle 1 : Budget de tokens
            tokens_totaux = sum(token_counter.estimer_tokens_message(m) for m in contexte_optimise)
            self.assertLessEqual(
                tokens_totaux,
                api.MAX_INPUT_TOKENS,
                f"Dépassement du budget de tokens : {tokens_totaux} > {api.MAX_INPUT_TOKENS}"
            )

            # Oracle 2 : Intégrité des paires tool_call / tool_response
            self._valider_integrite_paires(contexte_optimise, "_messages_avec_fenetre sous saturation lourde")

            # Oracle 3 : Prompt système présent et non orphelin
            self.assertEqual(contexte_optimise[0]['role'], 'system')

    def test_tronquer_historique_preserves_atomic_pairs(self):
        """Vérifie que api._tronquer_historique() (lorsque le nombre de messages dépasse
        MAX_CONTEXT_MESSAGES * 2) conserve l'intégrité atomique des paires tool_call/tool_response
        et préserve le prompt système en position 0."""
        with AirGapAssertionProbe():
            # Générer plus de 80 messages avec divers outils (25 tours * 4 msgs = 100 msgs)
            for i in range(25):
                cid = f"hist_call_{i}"
                api.messages.append({'role': 'user', 'content': f'Message historique {i}'})
                api.messages.append({
                    'role': 'assistant',
                    'content': f'Action {i}',
                    'tool_calls': [{'id': cid, 'function': {'name': f'action_{i}'}}]
                })
                api._ajouter_resultat({'id': cid, 'function': {'name': f'action_{i}'}}, f"Résultat historique {i}")
                api.messages.append({'role': 'assistant', 'content': f'Fin {i}'})

            nb_avant = len(api.messages)
            self.assertGreater(nb_avant - 1, api.MAX_CONTEXT_MESSAGES * 2)

            api._tronquer_historique()

            nb_apres = len(api.messages)
            self.assertLess(nb_apres, nb_avant)
            self.assertEqual(api.messages[0]['role'], 'system')
            self._valider_integrite_paires(api.messages, "api._tronquer_historique")


if __name__ == '__main__':
    unittest.main()
