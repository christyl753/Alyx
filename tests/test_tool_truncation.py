"""tests/test_tool_truncation.py
Suite de tests complète pour le tronquage intelligent des retours d'outils
et l'intégrité atomique du ring buffer (Milestone 2 - R2).
Conforme aux exigences BLOC B.6, B.7, B.8 et PROJECT.md.
"""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

# Contexte racine
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import ai
import api
from function import files, system
from tests.e2e.harness import AirGapAssertionProbe


class TestFileToolTruncation(unittest.TestCase):
    """Validation du tronquage à la source dans function/files.py."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.dossier = self.tmp_dir.name

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_lister_fichiers_truncation_60_files(self):
        """Vérifie que lister_fichiers avec 60 fichiers retourne exactement 50 entrées et la notice standardisée."""
        nb_fichiers = 60
        for i in range(nb_fichiers):
            nom = f"doc_{i:03d}.txt"
            with open(os.path.join(self.dossier, nom), 'w', encoding='utf-8') as f:
                f.write("test")

        resultat = files.lister_fichiers(self.dossier)

        # 50 fichiers affichés
        self.assertEqual(resultat.count("📄"), files.MAX_ENTREES_LISTE)
        self.assertEqual(files.MAX_ENTREES_LISTE, 50)

        # Notice explicite standardisée
        expected_notice = f"[Sortie tronquée : affichage des 50 premiers éléments sur {nb_fichiers}]"
        self.assertIn(expected_notice, resultat)

    def test_lister_fichiers_under_threshold(self):
        """Vérifie que lister_fichiers sous le seuil n'ajoute pas de notice de troncature."""
        for i in range(15):
            with open(os.path.join(self.dossier, f"f_{i:02d}.txt"), 'w', encoding='utf-8') as f:
                f.write("ok")

        resultat = files.lister_fichiers(self.dossier)
        self.assertEqual(resultat.count("📄"), 15)
        self.assertNotIn("Sortie tronquée", resultat)

    def test_lire_fichier_securise_truncation_16kb(self):
        """Vérifie que lire_fichier_securise avec 16 KB retourne 8 KB et la notice explicite."""
        taille_octets = 16 * 1024  # 16 KB
        chemin = os.path.join(self.dossier, "gros_fichier.txt")
        contenu_source = "A" * taille_octets
        with open(chemin, 'w', encoding='utf-8') as f:
            f.write(contenu_source)

        resultat = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': chemin})

        # La constante doit être 8 KB (8192 octets)
        self.assertEqual(files.TAILLE_MAX_LECTURE, 8 * 1024)

        # Notice explicite standardisée
        expected_notice = f"[Sortie tronquée : affichage des {files.TAILLE_MAX_LECTURE} premiers octets sur {taille_octets}]"
        self.assertIn(expected_notice, resultat)

        # Le contenu commence par les octets lus
        self.assertIn("A" * 100, resultat)

    def test_lire_fichier_securise_under_8kb(self):
        """Vérifie qu'un fichier de 2 KB est lu intégralement sans notice de troncature."""
        taille_octets = 2 * 1024
        chemin = os.path.join(self.dossier, "petit_fichier.txt")
        contenu_source = "B" * taille_octets
        with open(chemin, 'w', encoding='utf-8') as f:
            f.write(contenu_source)

        resultat = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': chemin})
        self.assertNotIn("Sortie tronquée", resultat)
        self.assertIn("B" * taille_octets, resultat)


class TestSystemToolTruncation(unittest.TestCase):
    """Validation du tronquage dans function/system.py."""

    def test_executer_commande_systeme_truncation_over_4000_chars(self):
        """Vérifie que executer_commande_systeme tronque à 4000 caractères avec notice standardisée."""
        sortie_massive = "X" * 6500
        with patch('function.system._run_ps', return_value=(0, sortie_massive)), \
             patch('function.system._run_ps_admin', return_value=(0, sortie_massive)), \
             patch('subprocess.run') as mock_sub:
            mock_sub.return_value.returncode = 0
            mock_sub.return_value.stdout = sortie_massive
            mock_sub.return_value.stderr = ""

            resultat = files.executer_avec_permission(
                system.executer_commande_systeme,
                {'commande': 'echo test'}
            )

        expected_notice = f"\n[Sortie tronquée : affichage des 4000 premiers caractères sur {len(sortie_massive)}]"
        self.assertIn(expected_notice, resultat)
        self.assertTrue(resultat.startswith("X" * 4000))

    def test_executer_commande_systeme_under_threshold(self):
        """Vérifie qu'une commande générant moins de 4000 caractères n'est pas tronquée."""
        sortie_courte = "Ligne 1\nLigne 2\nLigne 3"
        with patch('function.system._run_ps', return_value=(0, sortie_courte)), \
             patch('function.system._run_ps_admin', return_value=(0, sortie_courte)), \
             patch('subprocess.run') as mock_sub:
            mock_sub.return_value.returncode = 0
            mock_sub.return_value.stdout = sortie_courte
            mock_sub.return_value.stderr = ""

            resultat = files.executer_avec_permission(
                system.executer_commande_systeme,
                {'commande': 'echo test'}
            )

        self.assertNotIn("Sortie tronquée", resultat)
        self.assertEqual(resultat, sortie_courte)


class TestDefensiveSanitizer(unittest.TestCase):
    """Validation du sanitiseur défensif tronquer_sortie_outil dans api.py et ai.py."""

    def test_api_tronquer_sortie_outil(self):
        """Vérifie le comportement unitaire de api.tronquer_sortie_outil."""
        court = "Résultat normal de 150 caractères"
        self.assertEqual(api.tronquer_sortie_outil(court), court)

        long_texte = "D" * 5200
        tronque = api.tronquer_sortie_outil(long_texte, max_chars=4000)
        self.assertEqual(len(tronque[:4000]), 4000)
        self.assertIn("[Sortie tronquée : affichage des 4000 premiers caractères sur 5200]", tronque)

    def test_ai_tronquer_sortie_outil(self):
        """Vérifie le comportement unitaire de ai.tronquer_sortie_outil."""
        court = "Résultat CLI normal"
        self.assertEqual(ai.tronquer_sortie_outil(court), court)

        long_texte = "E" * 4800
        tronque = ai.tronquer_sortie_outil(long_texte, max_chars=4000)
        self.assertEqual(len(tronque[:4000]), 4000)
        self.assertIn("[Sortie tronquée : affichage des 4000 premiers caractères sur 4800]", tronque)

    def test_api_ajouter_resultat_clamps_defensively(self):
        """Vérifie que api._ajouter_resultat applique tronquer_sortie_outil défensivement."""
        orig_messages = list(api.messages)
        try:
            del api.messages[1:]
            tc = {'id': 'call_xyz_123', 'function': {'name': 'outil_imprudent'}}
            sortie_brute = "Z" * 12000

            api._ajouter_resultat(tc, sortie_brute)

            self.assertEqual(len(api.messages), 2)
            msg = api.messages[-1]
            self.assertEqual(msg['role'], 'tool')
            self.assertEqual(msg['tool_call_id'], 'call_xyz_123')
            self.assertEqual(msg['name'], 'outil_imprudent')
            self.assertIn("[Sortie tronquée : affichage des 4000 premiers caractères sur 12000]", msg['content'])
            self.assertTrue(msg['content'].startswith("Z" * 4000))
        finally:
            api.messages[:] = orig_messages

    def test_ai_executer_outil_cli_clamps_defensively(self):
        """Vérifie que ai._executer_outil_cli applique tronquer_sortie_outil."""
        massive_output = "M" * 7000

        with patch.dict(ai.outils_disponibles, {'outil_fake': lambda: massive_output}):
            res = ai._executer_outil_cli('outil_fake', {})

        self.assertIn("[Sortie tronquée : affichage des 4000 premiers caractères sur 7000]", res)
        self.assertTrue(res.startswith("M" * 4000))


class TestRingBufferPairIntegrityWithTruncatedOutputs(unittest.TestCase):
    """Validation de l'invariance absolue des paires tool_call/tool_response (BLOC B.7.6)
    en présence de retours d'outils tronqués et volumineux."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def test_ring_buffer_preserves_atomic_pairs_with_truncated_tools(self):
        """Vérifie qu'aucune troncature de ring buffer ne dissocie une paire tool_call/tool_response."""
        with AirGapAssertionProbe():
            # Construction de 6 tours de conversation avec retours d'outils tronqués
            for i in range(6):
                tc_id = f"call_{i}"
                api.messages.append({'role': 'user', 'content': f'Demande utilisateur tour {i}'})
                api.messages.append({
                    'role': 'assistant',
                    'content': f'Appel outil tour {i}',
                    'tool_calls': [{'id': tc_id, 'function': {'name': 'lister_fichiers', 'arguments': '{"dossier": "~"}'}}]
                })
                # Résultat d'outil avec troncature explicite
                contenu_outil = f"Contenu du dossier...\n[Sortie tronquée : affichage des 50 premiers éléments sur {100 + i * 20}]"
                api._ajouter_resultat({'id': tc_id, 'function': {'name': 'lister_fichiers'}}, contenu_outil)
                api.messages.append({'role': 'assistant', 'content': f'Réponse finale tour {i}'})

            contexte = api._messages_avec_fenetre()

            # Vérification de l'intégrité de toutes les paires tool_call / tool
            tool_ids_appeles = set()
            for msg in contexte:
                if msg.get('role') == 'assistant' and msg.get('tool_calls'):
                    for tc in msg['tool_calls']:
                        tool_ids_appeles.add(tc['id'])

                if msg.get('role') == 'tool':
                    tool_id = msg.get('tool_call_id')
                    # Invariant 1: chaque réponse d'outil a son tool_call dans le contexte
                    self.assertIn(
                        tool_id,
                        tool_ids_appeles,
                        f"Violation BLOC B.7.6 : tool_call_id '{tool_id}' est orphelin dans le ring buffer !"
                    )

            # Invariant 2: le premier message non-système n'est JAMAIS un tool ou assistant avec tool_calls orphelins
            premier_non_system = contexte[1]
            self.assertNotEqual(premier_non_system.get('role'), 'tool')

    def test_multicall_atomic_pair_retention_in_ring_buffer(self):
        """Vérifie qu'un tour avec plusieurs tool_calls simultanés conserve l'intégralité de ses réponses."""
        with AirGapAssertionProbe():
            # Tour 1: 3 tool_calls simultanés
            tc1 = {'id': 'call_multi_1', 'function': {'name': 'lister_fichiers', 'arguments': '{}'}}
            tc2 = {'id': 'call_multi_2', 'function': {'name': 'lire_fichier_securise', 'arguments': '{}'}}
            tc3 = {'id': 'call_multi_3', 'function': {'name': 'executer_commande_systeme', 'arguments': '{}'}}

            api.messages.append({'role': 'user', 'content': 'Effectue plusieurs actions en parallèle'})
            api.messages.append({
                'role': 'assistant',
                'content': '',
                'tool_calls': [tc1, tc2, tc3]
            })
            api._ajouter_resultat(tc1, "Sortie lister [Sortie tronquée : affichage des 50 premiers éléments sur 80]")
            api._ajouter_resultat(tc2, "Sortie lire [Sortie tronquée : affichage des 8192 premiers octets sur 16000]")
            api._ajouter_resultat(tc3, "Sortie cmd [Sortie tronquée : affichage des 4000 premiers caractères sur 6000]")
            api.messages.append({'role': 'assistant', 'content': 'Toutes les actions sont terminées.'})

            # Plusieurs tours récents supplémentaires
            for k in range(3):
                api.messages.append({'role': 'user', 'content': f'Question additionnelle {k}'})
                api.messages.append({'role': 'assistant', 'content': f'Réponse additionnelle {k}'})

            contexte = api._messages_avec_fenetre()

            # Si le tour multi-calls est présent, ses 3 réponses d'outils doivent être présentes
            has_multi_assistant = any(
                m.get('role') == 'assistant' and any(tc.get('id') == 'call_multi_1' for tc in m.get('tool_calls', []))
                for m in contexte
            )
            if has_multi_assistant:
                tool_ids_in_context = [m.get('tool_call_id') for m in contexte if m.get('role') == 'tool']
                self.assertIn('call_multi_1', tool_ids_in_context)
                self.assertIn('call_multi_2', tool_ids_in_context)
                self.assertIn('call_multi_3', tool_ids_in_context)

    def test_safe_cut_rewinds_strictly_to_user_boundary(self):
        """Vérifie que la fonction de coupure sûre ne produit jamais de point de départ au milieu d'un tour."""
        msgs = [
            {'role': 'user', 'content': 'User 1'},
            {'role': 'assistant', 'content': 'Resp 1'},
            {'role': 'user', 'content': 'User 2'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'fn1'}}]},
            {'role': 'tool', 'name': 'fn1', 'tool_call_id': 'c1', 'content': 'res1'},
            {'role': 'assistant', 'content': 'Resp 2'},
        ]
        # Si on demande max_messages=2 (ce qui atterrirait sur tool ou assistant tool_calls),
        # _index_coupure_sure doit reculer jusqu'à avant l'assistant/tool
        idx = api._index_coupure_sure(msgs, 2)
        # La tranche msgs[idx:] ne doit pas commencer par tool ni assistant avec tool_calls
        tranche = msgs[idx:]
        self.assertNotEqual(tranche[0].get('role'), 'tool')
        if tranche[0].get('tool_calls'):
            self.fail("La coupure sûre ne doit pas débuter sur un message assistant contenant tool_calls !")


if __name__ == '__main__':
    unittest.main()
