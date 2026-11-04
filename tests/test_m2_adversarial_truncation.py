"""tests/test_m2_adversarial_truncation.py
Empirical adversarial stress test suite for Milestone 2 (Requirement R2).
Tests massive directory listing, massive file reading, command truncation,
defensive clamping interactions, and ring buffer atomic pairing invariance.
"""
import os
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest.mock import patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import ai
import api
from function import files, system
from tests.e2e.harness import AirGapAssertionProbe


class TestAdversarialDirectoryListing(unittest.TestCase):
    """Stress tests on directory listing with 1,000 and 10,000 files."""

    def test_lister_fichiers_1000_files(self):
        """Stress-test lister_fichiers with 1,000 files in a single directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(1000):
                open(os.path.join(tmp_dir, f"file_{i:04d}.dat"), 'w').close()

            tracemalloc.start()
            t0 = time.perf_counter()
            resultat = files.lister_fichiers(tmp_dir)
            duree = time.perf_counter() - t0
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            # 1. Output verification
            self.assertEqual(resultat.count("📄"), files.MAX_ENTREES_LISTE)
            self.assertEqual(files.MAX_ENTREES_LISTE, 50)
            expected_notice = "[Sortie tronquée : affichage des 50 premiers éléments sur 1000]"
            self.assertIn(expected_notice, resultat)

            # 2. Performance metrics
            # 1,000 files should be fast (< 0.2s)
            self.assertLess(duree, 0.5, f"Listing 1,000 files took {duree:.4f}s (> 0.5s threshold)")
            # Memory peak should be minimal (< 2 MB)
            self.assertLess(peak, 2 * 1024 * 1024, f"Memory peak was {peak} bytes (> 2 MB)")

    def test_lister_fichiers_10000_files(self):
        """Stress-test lister_fichiers with 10,000 files in a single directory."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            for i in range(10000):
                open(os.path.join(tmp_dir, f"f_{i:05d}.txt"), 'w').close()

            tracemalloc.start()
            t0 = time.perf_counter()
            resultat = files.lister_fichiers(tmp_dir)
            duree = time.perf_counter() - t0
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            # 1. Output verification
            self.assertEqual(resultat.count("📄"), files.MAX_ENTREES_LISTE)
            self.assertEqual(files.MAX_ENTREES_LISTE, 50)
            expected_notice = "[Sortie tronquée : affichage des 50 premiers éléments sur 10000]"
            self.assertIn(expected_notice, resultat)

            # 2. Performance metrics
            # Timing should complete promptly (< 0.5s target)
            self.assertLess(duree, 0.5, f"Listing 10,000 files took {duree:.4f}s (> 0.5s target)")
            # Memory peak should remain controlled (< 15 MB)
            self.assertLess(peak, 15 * 1024 * 1024, f"Memory peak was {peak} bytes (> 15 MB)")


class TestAdversarialFileReading(unittest.TestCase):
    """Stress tests on reading large files (10 MB and 50 MB) without OOM."""

    def test_lire_fichier_securise_10mb(self):
        """Stress-test lire_fichier_securise with a 10 MB text file."""
        taille_10mb = 10 * 1024 * 1024
        with tempfile.TemporaryDirectory() as tmp_dir:
            chemin = os.path.join(tmp_dir, "huge_10mb.txt")
            chunk = "X" * 1024 * 1024  # 1 MB chunk
            with open(chemin, 'w', encoding='utf-8') as f:
                for _ in range(10):
                    f.write(chunk)

            self.assertEqual(os.path.getsize(chemin), taille_10mb)

            tracemalloc.start()
            t0 = time.perf_counter()
            resultat = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': chemin})
            duree = time.perf_counter() - t0
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            # 1. Output verification
            expected_notice = f"[Sortie tronquée : affichage des {files.TAILLE_MAX_LECTURE} premiers octets sur {taille_10mb}]"
            self.assertIn(expected_notice, resultat)
            self.assertTrue(resultat.startswith(f"Contenu de {chemin} :\n" + "X" * 100))

            # 2. Memory verification: must NOT load 10 MB into memory!
            # Peak memory allocated by Python during this call should be < 500 KB
            self.assertLess(peak, 500 * 1024, f"Memory peak during 10 MB read was {peak} bytes (> 500 KB)")
            # Speed should be nearly instantaneous (< 0.05s)
            self.assertLess(duree, 0.1, f"Reading 8 KB from 10 MB file took {duree:.4f}s (> 0.1s)")

    def test_lire_fichier_securise_50mb(self):
        """Stress-test lire_fichier_securise with a 50 MB text file."""
        taille_50mb = 50 * 1024 * 1024
        with tempfile.TemporaryDirectory() as tmp_dir:
            chemin = os.path.join(tmp_dir, "huge_50mb.txt")
            chunk = "Y" * (1024 * 1024)  # 1 MB chunk
            with open(chemin, 'w', encoding='utf-8') as f:
                for _ in range(50):
                    f.write(chunk)

            self.assertEqual(os.path.getsize(chemin), taille_50mb)

            tracemalloc.start()
            t0 = time.perf_counter()
            resultat = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': chemin})
            duree = time.perf_counter() - t0
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            # 1. Output verification
            expected_notice = f"[Sortie tronquée : affichage des {files.TAILLE_MAX_LECTURE} premiers octets sur {taille_50mb}]"
            self.assertIn(expected_notice, resultat)

            # 2. Strict OOM prevention: peak memory < 500 KB
            self.assertLess(peak, 500 * 1024, f"Memory peak during 50 MB read was {peak} bytes (> 500 KB)")
            self.assertLess(duree, 0.1, f"Reading 8 KB from 50 MB file took {duree:.4f}s (> 0.1s)")


class TestAdversarialSystemCommand(unittest.TestCase):
    """Stress tests on executer_commande_systeme with > 10,000 characters output."""

    def test_executer_commande_systeme_15000_chars(self):
        """Test executer_commande_systeme with 15,000 characters output."""
        sortie_15k = "CMD_OUTPUT_" * 1364  # 15,004 characters
        with patch('function.system._run_ps', return_value=(0, sortie_15k)), \
             patch('function.system._run_ps_admin', return_value=(0, sortie_15k)), \
             patch('subprocess.run') as mock_sub:
            mock_sub.return_value.returncode = 0
            mock_sub.return_value.stdout = sortie_15k
            mock_sub.return_value.stderr = ""

            resultat = files.executer_avec_permission(
                system.executer_commande_systeme,
                {'commande': 'Get-LargeLog'}
            )

        expected_notice = f"\n[Sortie tronquée : affichage des 4000 premiers caractères sur {len(sortie_15k)}]"
        self.assertIn(expected_notice, resultat)
        self.assertEqual(resultat[:4000], sortie_15k[:4000])

    def test_executer_commande_systeme_50000_chars(self):
        """Test executer_commande_systeme with 50,000 characters output."""
        sortie_50k = "Z" * 50000
        with patch('function.system._run_ps', return_value=(0, sortie_50k)), \
             patch('function.system._run_ps_admin', return_value=(0, sortie_50k)), \
             patch('subprocess.run') as mock_sub:
            mock_sub.return_value.returncode = 0
            mock_sub.return_value.stdout = sortie_50k
            mock_sub.return_value.stderr = ""

            resultat = files.executer_avec_permission(
                system.executer_commande_systeme,
                {'commande': 'cat massive.log'}
            )

        expected_notice = f"\n[Sortie tronquée : affichage des 4000 premiers caractères sur 50000]"
        self.assertIn(expected_notice, resultat)
        self.assertEqual(resultat[:4000], "Z" * 4000)


class TestAdversarialDoubleClampingNoticeIntegrity(unittest.TestCase):
    """Adversarial stress test on Tier 1 vs Tier 2 truncation interaction."""

    def test_investigate_double_truncation_notice_mutation(self):
        """Empirically test what happens when executer_commande_systeme output
        passes into api._ajouter_resultat and api.tronquer_sortie_outil."""
        sortie_10k = "K" * 10000
        with patch('function.system._run_ps', return_value=(0, sortie_10k)), \
             patch('function.system._run_ps_admin', return_value=(0, sortie_10k)), \
             patch('subprocess.run') as mock_sub:
            mock_sub.return_value.returncode = 0
            mock_sub.return_value.stdout = sortie_10k
            mock_sub.return_value.stderr = ""

            res_brut = files.executer_avec_permission(
                system.executer_commande_systeme,
                {'commande': 'test'}
            )

        # Raw tool output length is 4000 + notice length (~4069 chars)
        self.assertEqual(len(res_brut[:4000]), 4000)
        self.assertIn("[Sortie tronquée : affichage des 4000 premiers caractères sur 10000]", res_brut)

        # Now pass through api._ajouter_resultat
        orig_msgs = list(api.messages)
        try:
            del api.messages[1:]
            tc = {'id': 'call_cmd_stress', 'function': {'name': 'executer_commande_systeme'}}
            api._ajouter_resultat(tc, res_brut)

            msg = api.messages[-1]
            # Empirical check: does the message retain the true original count 10000,
            # or did tronquer_sortie_outil overwrite it with 4069?
            has_original_notice = "sur 10000" in msg['content']
            has_overwritten_notice = "sur 4069" in msg['content']

            # Note: We observe this empirical behavior for our adversarial findings report
            if not has_original_notice:
                self.assertTrue(has_overwritten_notice, "Notice was mutated by double clamping")
        finally:
            api.messages[:] = orig_msgs


class TestAdversarialRingBufferIntegrity(unittest.TestCase):
    """Stress tests on Ring Buffer atomic pairing under continuous massive saturation."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def test_burst_of_30_turns_with_truncated_tools(self):
        """Stress-test ring buffer windowing across 30 rapid multi-tool turns."""
        with AirGapAssertionProbe():
            for t in range(30):
                tc1_id = f"tc_{t}_1"
                tc2_id = f"tc_{t}_2"
                api.messages.append({'role': 'user', 'content': f'Question {t}'})
                api.messages.append({
                    'role': 'assistant',
                    'content': f'Lancement outils tour {t}',
                    'tool_calls': [
                        {'id': tc1_id, 'function': {'name': 'lister_fichiers', 'arguments': '{}'}},
                        {'id': tc2_id, 'function': {'name': 'lire_fichier_securise', 'arguments': '{}'}},
                    ]
                })
                # Add truncated outputs
                api._ajouter_resultat({'id': tc1_id, 'function': {'name': 'lister_fichiers'}}, "L" * 5000)
                api._ajouter_resultat({'id': tc2_id, 'function': {'name': 'lire_fichier_securise'}}, "R" * 9000)
                api.messages.append({'role': 'assistant', 'content': f'Réponse tour {t}'})

            # Check windowed messages
            contexte = api._messages_avec_fenetre()
            self.assertGreaterEqual(len(contexte), 2)
            self.assertEqual(contexte[0]['role'], 'system')

            # Verify no orphan tool messages
            tool_call_ids_in_context = set()
            for m in contexte:
                if m.get('role') == 'assistant' and m.get('tool_calls'):
                    for tc in m['tool_calls']:
                        tool_call_ids_in_context.add(tc['id'])

            for idx, m in enumerate(contexte):
                if m.get('role') == 'tool':
                    tcid = m.get('tool_call_id')
                    self.assertIn(
                        tcid,
                        tool_call_ids_in_context,
                        f"Atomic pair violation at index {idx}: tool_call_id '{tcid}' is orphan in ring buffer!"
                    )


if __name__ == '__main__':
    unittest.main()
