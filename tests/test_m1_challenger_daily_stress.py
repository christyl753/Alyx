"""Aggressive multi-threaded stress harness for Alyx daily tasks.

Adversarially stress-tests:
1. Concurrency safety (50 to 100 parallel writer/reader/deleter threads) in function/reminders.py and function/notes.py.
2. Zero lost updates (100% data persistence without loss).
3. Zero Windows sharing violations ([WinError 32], [WinError 5]).
4. Zero orphaned markdown files on induced simulated disk errors.
5. Atomic temporary file cleanup under disk write failures.
6. Re-entrancy and lock safety under saturated thread pools.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import glob
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from function import notes, reminders


class Test50ThreadRemindersStress(unittest.TestCase):
    """Aggressive 50+ thread stress testing on reminders module."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_stress_reminders_")
        self.reminders_file = os.path.join(self.temp_dir, "reminders.json")
        self.patcher = patch('function.reminders._obtenir_fichier_rappels', return_value=self.reminders_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_50_parallel_writer_threads_zero_lost_updates(self):
        """50 concurrent threads creating 50 reminders simultaneously.

        Must guarantee:
        - 100% of calls succeed without raising exceptions.
        - Zero [WinError 32] or [WinError 5] sharing violations.
        - Exactly 50 distinct reminders persisted in JSON.
        - Zero lost updates.
        """
        num_threads = 50

        def create_worker(index):
            return reminders.creer_rappel(f"Rappel concurrent #{index}", delai_minutes=index + 1)

        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            futures = [pool.submit(create_worker, i) for i in range(num_threads)]
            results = [f.result() for f in as_completed(futures)]

        # Verify all calls reported success
        for res in results:
            self.assertIn("Rappel programmé avec succès", res)

        # Verify persistence integrity
        loaded = reminders._charger_rappels()
        self.assertEqual(
            len(loaded),
            num_threads,
            f"Lost updates detected: expected {num_threads}, persisted {len(loaded)}"
        )

        # Verify unique IDs
        ids = [r["id"] for r in loaded]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate reminder ID found!")

        # Verify zero lingering temporary files
        tmp_files = glob.glob(f"{self.reminders_file}.*.tmp")
        self.assertEqual(tmp_files, [], f"Lingering tmp files found: {tmp_files}")

    def test_50_thread_mixed_workload_stress(self):
        """50 threads performing simultaneous creates, reads, checks, and deletes."""
        # Pre-populate with 20 reminders
        for i in range(20):
            reminders.creer_rappel(f"Initial reminder #{i}", delai_minutes=1)

        errors = []
        created_ids = []

        def worker(thread_id):
            try:
                op = thread_id % 4
                if op == 0:
                    # Writer
                    res = reminders.creer_rappel(f"Mixed reminder {thread_id}", delai_minutes=5)
                    if "Rappel programmé avec succès" not in res:
                        errors.append(f"Create failed: {res}")
                elif op == 1:
                    # Reader
                    lst = reminders.lister_rappels(inclure_passes=True)
                    if not isinstance(lst, str) or len(lst) == 0:
                        errors.append(f"List invalid: {lst}")
                elif op == 2:
                    # Imminent checker
                    imm = reminders.verifier_rappels_imminents()
                    if not isinstance(imm, list):
                        errors.append(f"Verifier invalid: {imm}")
                else:
                    # Deleter: read and delete first available
                    current = reminders._charger_rappels()
                    if current:
                        target = current[0]["id"]
                        reminders.supprimer_rappel(target)
            except Exception as e:
                errors.append(f"Exception in thread {thread_id}: {type(e).__name__}: {e}")

        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(worker, i) for i in range(50)]
            for f in as_completed(futures):
                f.result()

        self.assertEqual(errors, [], f"Errors occurred during mixed workload: {errors}")

        # Ensure valid JSON on disk
        data = reminders._charger_rappels()
        self.assertIsInstance(data, list)

    def test_100_thread_burst_creation(self):
        """Extreme burst: 100 parallel threads hammering creer_rappel."""
        num_threads = 100

        def burst_worker(index):
            return reminders.creer_rappel(f"Burst reminder {index}", delai_minutes=index % 60 + 1)

        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            futures = [pool.submit(burst_worker, i) for i in range(num_threads)]
            results = [f.result() for f in as_completed(futures)]

        for res in results:
            self.assertIn("Rappel programmé avec succès", res)

        loaded = reminders._charger_rappels()
        self.assertEqual(len(loaded), num_threads)


class Test50ThreadNotesStress(unittest.TestCase):
    """Aggressive 50+ thread stress testing on notes module."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_stress_notes_")
        self.notes_dir = os.path.join(self.temp_dir, "notes")
        self.index_file = os.path.join(self.temp_dir, "notes.json")
        os.makedirs(self.notes_dir, exist_ok=True)
        self.patcher = patch(
            'function.notes._obtenir_chemins_notes',
            return_value=(self.notes_dir, self.index_file)
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_50_parallel_notes_writers_zero_lost_updates_and_no_file_desync(self):
        """50 concurrent threads writing 50 separate markdown notes simultaneously.

        Must guarantee:
        - 100% of calls succeed without raising exceptions.
        - Zero [WinError 32] or [WinError 5] sharing violations.
        - Exactly 50 note entries in notes.json index.
        - Exactly 50 .md physical files on disk.
        - 1-to-1 match between index entries and physical .md files (zero desync).
        - Zero lingering temporary files.
        """
        num_threads = 50

        def write_worker(index):
            return notes.ajouter_note_rapide(
                titre=f"Note Concurrente #{index}",
                contenu=f"Contenu de la note #{index} rédigée en parallèle.",
                etiquette=f"tag_{index % 5}"
            )

        with ThreadPoolExecutor(max_workers=num_threads) as pool:
            futures = [pool.submit(write_worker, i) for i in range(num_threads)]
            results = [f.result() for f in as_completed(futures)]

        for res in results:
            self.assertIn("Note enregistrée avec succès", res)

        index = notes._charger_index_notes()
        self.assertEqual(
            len(index),
            num_threads,
            f"Lost note updates: expected {num_threads}, index contains {len(index)}"
        )

        md_files = [f for f in os.listdir(self.notes_dir) if f.endswith(".md")]
        self.assertEqual(
            len(md_files),
            num_threads,
            f"Physical file count mismatch: expected {num_threads}, found {len(md_files)}"
        )

        # Verify every index entry points to an actual file on disk with correct content
        for entry in index:
            expected_file = os.path.join(self.notes_dir, entry["fichier"])
            self.assertTrue(os.path.exists(expected_file), f"Missing file on disk: {entry['fichier']}")
            with open(expected_file, "r", encoding="utf-8") as f:
                content = f.read()
                self.assertIn(entry["titre"], content)

        # Verify zero lingering temporary files
        tmp_files = glob.glob(f"{self.index_file}.*.tmp")
        self.assertEqual(tmp_files, [], f"Lingering tmp files found: {tmp_files}")

    def test_50_thread_notes_mixed_read_write_delete_stress(self):
        """50 threads performing simultaneous creates, full reads, list queries, and deletes."""
        # Seed initial 20 notes
        for i in range(20):
            notes.ajouter_note_rapide(f"Initial Note {i}", f"Initial Content {i}", etiquette="init")

        errors = []

        def mixed_worker(thread_id):
            try:
                op = thread_id % 4
                if op == 0:
                    # Writer
                    res = notes.ajouter_note_rapide(
                        f"Mixed Note {thread_id}",
                        f"Mixed Content {thread_id}",
                        etiquette="mixed"
                    )
                    if "Note enregistrée avec succès" not in res:
                        errors.append(f"Create note failed: {res}")
                elif op == 1:
                    # Index reader / lister
                    res = notes.lister_notes_rapides()
                    if "Notes rapides" not in res and "Aucune note" not in res:
                        errors.append(f"List notes unexpected: {res}")
                elif op == 2:
                    # Note reader
                    curr = notes._charger_index_notes()
                    if curr:
                        target = curr[0]["id"]
                        content = notes.lire_note_rapide(target)
                        if "Erreur" in content:
                            errors.append(f"Read note error: {content}")
                else:
                    # Deleter
                    curr = notes._charger_index_notes()
                    if curr:
                        target = curr[-1]["id"]
                        res = notes.supprimer_note_rapide(target)
                        if "supprimée avec succès" not in res and "Aucune note" not in res:
                            errors.append(f"Delete note unexpected: {res}")
            except Exception as e:
                errors.append(f"Exception in thread {thread_id}: {type(e).__name__}: {e}")

        with ThreadPoolExecutor(max_workers=50) as pool:
            futures = [pool.submit(mixed_worker, i) for i in range(50)]
            for f in as_completed(futures):
                f.result()

        self.assertEqual(errors, [], f"Errors occurred during notes mixed workload: {errors}")

        # Verify consistency: physical files must exactly equal index entries
        index = notes._charger_index_notes()
        index_files = set(n["fichier"] for n in index)
        disk_files = set(f for f in os.listdir(self.notes_dir) if f.endswith(".md"))
        self.assertEqual(
            index_files,
            disk_files,
            "Desynchronization between index and physical files after mixed concurrent workload!"
        )


class TestInducedDiskErrorsAndOrphanRollback(unittest.TestCase):
    """Stress tests verifying zero orphaned files and proper rollback upon simulated failures."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_stress_errors_")
        self.notes_dir = os.path.join(self.temp_dir, "notes")
        self.notes_index = os.path.join(self.temp_dir, "notes.json")
        self.reminders_file = os.path.join(self.temp_dir, "reminders.json")
        os.makedirs(self.notes_dir, exist_ok=True)

        self.patcher_notes = patch(
            'function.notes._obtenir_chemins_notes',
            return_value=(self.notes_dir, self.notes_index)
        )
        self.patcher_reminders = patch(
            'function.reminders._obtenir_fichier_rappels',
            return_value=self.reminders_file
        )
        self.patcher_notes.start()
        self.patcher_reminders.start()

    def tearDown(self):
        self.patcher_notes.stop()
        self.patcher_reminders.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_zero_orphaned_markdown_file_when_index_save_fails(self):
        """When _sauvegarder_index_notes fails, ajouter_note_rapide MUST purge the created .md file."""
        # Mock index saving failure
        with patch('function.notes._sauvegarder_index_notes', return_value=False):
            res = notes.ajouter_note_rapide(
                titre="Note vouée à l'échec",
                contenu="Ce contenu ne doit pas laisser de fichier orphelin sur le disque."
            )

        self.assertIn("Erreur : Impossible de sauvegarder l'index des notes", res)

        # Assert ZERO .md files left in notes_dir
        remaining_files = os.listdir(self.notes_dir)
        self.assertEqual(
            remaining_files,
            [],
            f"Orphaned file(s) left on disk after failed note creation: {remaining_files}"
        )

        # Assert index is unchanged / empty
        index = notes._charger_index_notes()
        self.assertEqual(index, [])

    def test_zero_orphaned_markdown_file_when_index_save_raises_exception(self):
        """Even if os.replace in _sauvegarder_index_notes raises WinError / OSError, no orphans remain."""
        with patch('os.replace', side_effect=OSError("Windows sharing violation [WinError 32]")):
            res = notes.ajouter_note_rapide(
                titre="Note crash WinError 32",
                contenu="Contenu qui subit un crash disque pendant l'écriture atomique."
            )

        self.assertIn("Erreur : Impossible de sauvegarder l'index", res)

        # Verify no .md files left on disk
        md_files = [f for f in os.listdir(self.notes_dir) if f.endswith(".md")]
        self.assertEqual(md_files, [], f"Orphaned md files detected: {md_files}")

        # Verify no .tmp files left in parent directory
        tmp_files = glob.glob(f"{self.notes_index}.*.tmp")
        self.assertEqual(tmp_files, [], f"Orphaned tmp file detected: {tmp_files}")

    def test_deletion_rollback_when_index_save_fails(self):
        """If _sauvegarder_index_notes fails during supprimer_note_rapide, .md file must NOT be deleted."""
        # 1. Create a note successfully first
        res_create = notes.ajouter_note_rapide("Note durable", "Contenu à ne pas détruire prématurément")
        self.assertIn("Note enregistrée avec succès", res_create)
        index_before = notes._charger_index_notes()
        self.assertEqual(len(index_before), 1)
        note_id = index_before[0]["id"]
        filename = index_before[0]["fichier"]
        full_path = os.path.join(self.notes_dir, filename)
        self.assertTrue(os.path.exists(full_path))

        # 2. Attempt deletion while mocking index write failure
        with patch('function.notes._sauvegarder_index_notes', return_value=False):
            res_delete = notes.supprimer_note_rapide(note_id)

        self.assertIn("Erreur : Impossible de sauvegarder l'index des notes", res_delete)

        # 3. Verify .md file was NOT deleted
        self.assertTrue(os.path.exists(full_path), "Physical note was deleted despite index update failure!")

    def test_reminder_tmp_file_cleaned_up_on_atomic_replace_failure(self):
        """Simulate WinError 5 during os.replace in _sauvegarder_rappels and verify tmp cleanup."""
        # Write initial valid reminder
        reminders.creer_rappel("Rappel existant", delai_minutes=10)
        self.assertTrue(os.path.exists(self.reminders_file))

        with patch('os.replace', side_effect=PermissionError("[WinError 5] Access is denied")):
            succes = reminders._sauvegarder_rappels([{"id": "bad", "texte": "do not write"}])

        self.assertFalse(succes)

        # Temporary files must be cleaned up
        tmp_files = glob.glob(f"{self.reminders_file}.*.tmp")
        self.assertEqual(tmp_files, [], f"Lingering tmp file after replace error: {tmp_files}")

        # Original file remains valid
        original_data = reminders._charger_rappels()
        self.assertEqual(len(original_data), 1)
        self.assertEqual(original_data[0]["texte"], "Rappel existant")


class TestAdversarialEdgeCases(unittest.TestCase):
    """Stress tests covering boundary conditions, heavy payloads, and re-entrancy."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_stress_edge_")
        self.notes_dir = os.path.join(self.temp_dir, "notes")
        self.notes_index = os.path.join(self.temp_dir, "notes.json")
        self.reminders_file = os.path.join(self.temp_dir, "reminders.json")
        os.makedirs(self.notes_dir, exist_ok=True)

        self.patcher_notes = patch(
            'function.notes._obtenir_chemins_notes',
            return_value=(self.notes_dir, self.notes_index)
        )
        self.patcher_reminders = patch(
            'function.reminders._obtenir_fichier_rappels',
            return_value=self.reminders_file
        )
        self.patcher_notes.start()
        self.patcher_reminders.start()

    def tearDown(self):
        self.patcher_notes.stop()
        self.patcher_reminders.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_large_note_payload_5mb(self):
        """Write and read back a 5 MB Markdown note without corruption or memory error."""
        large_body = "Alyx Note Ligne de test avec caractères accentués éàèç et symboles.\n" * 70000  # ~5 MB
        res = notes.ajouter_note_rapide("Note Massive 5MB", large_body, etiquette="heavy")
        self.assertIn("Note enregistrée avec succès", res)

        index = notes._charger_index_notes()
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["titre"], "Note Massive 5MB")
        # Preview must be capped
        self.assertLessEqual(len(index[0]["apercu"]), 125)

        # Read back full content
        content = notes.lire_note_rapide(index[0]["id"])
        self.assertIn("Note Massive 5MB", content)
        self.assertIn("Alyx Note Ligne de test", content)

    def test_rapid_sequential_create_and_delete_100_cycles(self):
        """Rapid sequential create -> read -> delete cycles to test handle leaks and lock churn."""
        t_start = time.perf_counter()
        for i in range(100):
            res_add = notes.ajouter_note_rapide(f"Cycle Note {i}", f"Cycle Content {i}")
            self.assertIn("Note enregistrée avec succès", res_add)

            idx = notes._charger_index_notes()
            self.assertEqual(len(idx), 1)

            res_del = notes.supprimer_note_rapide(idx[0]["id"])
            self.assertIn("supprimée avec succès", res_del)

            idx_after = notes._charger_index_notes()
            self.assertEqual(len(idx_after), 0)

        t_elapsed = time.perf_counter() - t_start
        # 100 round-trips should take less than 5 seconds
        self.assertLess(t_elapsed, 5.0, f"Cycles too slow: {t_elapsed:.2f}s")

    def test_whitespace_and_empty_inputs(self):
        """Check empty, whitespace-only, or None inputs."""
        # Reminders
        self.assertIn("Erreur", reminders.creer_rappel(""))
        self.assertIn("Erreur", reminders.creer_rappel("   \t\n  "))
        self.assertIn("Erreur", reminders.supprimer_rappel(""))
        self.assertIn("Erreur", reminders.supprimer_rappel("   "))

        # Notes
        self.assertIn("Erreur", notes.ajouter_note_rapide("", "Contenu"))
        self.assertIn("Erreur", notes.ajouter_note_rapide("   ", "Contenu"))
        self.assertIn("Erreur", notes.ajouter_note_rapide("Titre", ""))
        self.assertIn("Erreur", notes.ajouter_note_rapide("Titre", "   \n\t  "))
        self.assertIn("Erreur", notes.lire_note_rapide(""))
        self.assertIn("Erreur", notes.supprimer_note_rapide(""))


if __name__ == '__main__':
    unittest.main()
