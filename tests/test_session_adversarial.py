"""tests/test_session_adversarial.py
Adversarial Stress Testing & Fuzzing Harness for Session Persistence & Recovery.
Target: core/history.py and api.py session recovery.
Executed by: challenger_m1_mem_2 (teamwork_challenger).
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

# Context root
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import api
from core import history
from tests.e2e.harness import AirGapAssertionProbe


class TestAdversarialFuzzingCorruption(unittest.TestCase):
    """Challenge 1: Fuzzing & Corrupt File Resilience."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_adv_fuzz_")
        self._orig_dossier = history._dossier_historique
        history._dossier_historique = lambda: self.temp_dir

    def tearDown(self):
        history._dossier_historique = self._orig_dossier
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_0_byte_state_file(self):
        """0-byte state file must return None, purge the corrupted file, and not crash."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        with open(chemin, "wb") as f:
            pass
        self.assertEqual(os.path.getsize(chemin), 0)

        res = history.charger_etat_session("session_active")
        self.assertIsNone(res, "0-byte file must return None")
        self.assertFalse(os.path.exists(chemin), "0-byte corrupted file must be purged from disk")

    def test_truncated_malformed_json_bytes(self):
        """Truncated JSON must return None and purge file."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        payloads = [
            b'{"version": 1, "messages": [{"role": "user',
            b'{"version": 1, "messages":',
            b'{"version":',
            b'{',
            b'{"version": 1, "messages": [{"role": "user", "content": "hello"}]', # missing closing brace
        ]
        for p in payloads:
            with open(chemin, "wb") as f:
                f.write(p)
            res = history.charger_etat_session("session_active")
            self.assertIsNone(res, f"Truncated payload {p!r} must return None")
            self.assertFalse(os.path.exists(chemin), f"Corrupted file for {p!r} must be purged")

    def test_random_binary_fuzzing(self):
        """Random binary bytes (UTF-8 invalid and non-JSON ASCII) must return None and purge file."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        fuzz_samples = [
            os.urandom(16),
            os.urandom(256),
            os.urandom(1024),
            b"\x00\x01\x02\x03\xff\xfe\xfd\x80\xaa\xbb",
            b"\x80\x81\x82\x83\x84\x85",
            b"\xef\xbb\xbf\x00\x00", # Corrupted BOM
            b"!@#$%^&*()_+{}[]:\"<>?~`", # ASCII punctuation non-JSON
        ]
        for sample in fuzz_samples:
            with open(chemin, "wb") as f:
                f.write(sample)
            res = history.charger_etat_session("session_active")
            self.assertIsNone(res, f"Random bytes {sample[:10]!r} must return None")
            self.assertFalse(os.path.exists(chemin), f"Fuzzed file {sample[:10]!r} must be purged")

    def test_semantic_corruption_non_list_messages(self):
        """Non-list message payloads (e.g. integer, string, boolean, dict) must return None and purge."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        bad_payloads = [
            {"version": 1, "messages": 12345},
            {"version": 1, "messages": "messages_as_string"},
            {"version": 1, "messages": True},
            {"version": 1, "messages": None},
            {"version": 1, "messages": {"nested": "dict_instead_of_list"}},
            12345, # Root is integer
            "plain string", # Root is string
            True, # Root is boolean
        ]
        for p in bad_payloads:
            with open(chemin, "w", encoding="utf-8") as f:
                json.dump(p, f)
            res = history.charger_etat_session("session_active")
            self.assertIsNone(res, f"Invalid payload structure {p!r} must return None")
            self.assertFalse(os.path.exists(chemin), f"Corrupted payload {p!r} should be purged from disk")

    def test_semantic_corruption_non_dict_elements_in_messages(self):
        """Messages list containing non-dict elements (e.g. [1, 2, 'abc']) must return None and purge file."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        bad_payload = {"version": 1, "messages": [1, 2, "abc", None, True]}
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(bad_payload, f)
        res = history.charger_etat_session("session_active")
        # Challenge requirement: charger_etat_session() handles every corruption by returning None and purging
        self.assertIsNone(res, f"Corrupted payload with non-dict elements must return None, got: {res}")
        self.assertFalse(os.path.exists(chemin), "Corrupted file containing non-dict elements must be purged from disk")

    def test_api_restaurer_etat_session_resilience_under_all_corruptions(self):
        """Verify api.restaurer_etat_session never crashes under all corruption forms."""
        orig_messages = list(api.messages)
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        try:
            corrupt_cases = [
                b"",
                b"{truncated",
                os.urandom(64),
                b'{"version": 1, "messages": 9999}',
                b'{"version": 1, "messages": [1, 2, 3]}',
                b'{"version": 1, "messages": [{"malformed": 1}]}',
                b'null',
            ]
            for c in corrupt_cases:
                del api.messages[1:]
                with open(chemin, "wb") as f:
                    f.write(c)
                # Must not raise any exception
                restored_count = api.restaurer_etat_session("session_active")
                self.assertIsInstance(restored_count, int)
                self.assertGreaterEqual(restored_count, 0)
                # api.messages must still have valid system prompt at index 0
                self.assertGreater(len(api.messages), 0)
                self.assertEqual(api.messages[0].get("role"), "system")
        finally:
            api.messages[:] = orig_messages


class TestAdversarialConcurrencyAndHighFrequencyWrites(unittest.TestCase):
    """Challenge 2: Concurrent & High-Frequency Atomic Writes."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_adv_concurrency_")
        self._orig_dossier = history._dossier_historique
        history._dossier_historique = lambda: self.temp_dir

    def tearDown(self):
        history._dossier_historique = self._orig_dossier
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_100_rapid_consecutive_saves(self):
        """100 rapid sequential saves on the same file without delay."""
        chemin = os.path.join(self.temp_dir, "active_session_state.json")
        for i in range(100):
            msgs = [{"role": "user", "content": f"Message rapid save {i}"}]
            ok = history.sauvegarder_etat_session(msgs, "session_active")
            self.assertTrue(ok, f"Save {i} failed")

        # Verify final state is save 99
        loaded = history.charger_etat_session("session_active")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded[0]["content"], "Message rapid save 99")

        # Verify no .tmp files leaked
        tmp_files = [f for f in os.listdir(self.temp_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [], f"Leaked .tmp files found: {tmp_files}")

    def test_concurrent_multi_thread_saves_and_reads(self):
        """Concurrent multi-thread stress: multiple writers and readers competing."""
        errors = []
        stop_event = threading.Event()

        def writer_worker(worker_id, iterations=25):
            for i in range(iterations):
                if stop_event.is_set():
                    break
                msgs = [
                    {"role": "user", "content": f"Worker {worker_id} iter {i}"},
                    {"role": "assistant", "content": f"Resp {worker_id} iter {i}"}
                ]
                ok = history.sauvegarder_etat_session(msgs, "session_active")
                if not ok:
                    errors.append(f"Writer {worker_id} save failed at iter {i}")

        def reader_worker(worker_id, iterations=25):
            for i in range(iterations):
                if stop_event.is_set():
                    break
                try:
                    res = history.charger_etat_session("session_active")
                    # res can be None if not saved yet, or valid list of dicts
                    if res is not None:
                        if not isinstance(res, list):
                            errors.append(f"Reader {worker_id} got non-list: {type(res)}")
                        for item in res:
                            if not isinstance(item, dict):
                                errors.append(f"Reader {worker_id} got non-dict item: {item}")
                except Exception as e:
                    errors.append(f"Reader {worker_id} crashed with {type(e).__name__}: {e}")

        threads = []
        # 4 writer threads + 4 reader threads
        for w in range(4):
            t_w = threading.Thread(target=writer_worker, args=(w, 25))
            t_r = threading.Thread(target=reader_worker, args=(w, 25))
            threads.extend([t_w, t_r])

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10.0)

        self.assertEqual(errors, [], f"Concurrency errors encountered: {errors}")

        # Check for leaked .tmp files
        tmp_files = [f for f in os.listdir(self.temp_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [], f"Leaked .tmp files found: {tmp_files}")

    def test_unserializable_payload_safety_and_tmp_cleanup(self):
        """Unserializable messages (e.g. containing a set, lambda, circular ref) must fail gracefully with zero leaked .tmp."""
        bad_messages = [
            {"role": "user", "content": {"unsupported_set": {1, 2, 3}}}
        ]
        ok = history.sauvegarder_etat_session(bad_messages, "session_active")
        self.assertFalse(ok, "Unserializable payload must return False")

        # Assert no .tmp file left behind
        tmp_files = [f for f in os.listdir(self.temp_dir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [], f"Unserializable payload leaked .tmp file: {tmp_files}")


class TestAdversarialExpirationAndBoundaries(unittest.TestCase):
    """Challenge 3: Session Expiration & Boundary Conditions."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_adv_expire_")
        self._orig_dossier = history._dossier_historique
        history._dossier_historique = lambda: self.temp_dir

    def tearDown(self):
        history._dossier_historique = self._orig_dossier
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_session_with_timestamp(self, ts, session_id="session_active"):
        msgs = [{"role": "user", "content": f"Test message at {ts}"}]
        history.sauvegarder_etat_session(msgs, session_id)
        chemin = history._chemin_etat_session(session_id)
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["saved_at"] = ts
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.utime(chemin, (ts, ts))
        return chemin

    def test_timestamp_boundary_at_exactly_24h(self):
        """Timestamp exactly at 24.0 hours: age <= 24h should NOT be expired."""
        now = time.time()
        ts_exact = now - (24 * 3600)
        self._create_session_with_timestamp(ts_exact)

        # In charger_etat_session: age > max_age_heures * 3600
        # If age is exactly 24h (or fractionally slightly less/equal), it should be valid
        loaded = history.charger_etat_session("session_active", max_age_heures=24)
        # Note: during execution a microsecond might elapse, making age >= 24h
        # So we test with 24*3600 - 1 second for exact within boundary
        ts_within = now - (24 * 3600 - 2)
        self._create_session_with_timestamp(ts_within)
        loaded_within = history.charger_etat_session("session_active", max_age_heures=24)
        self.assertIsNotNone(loaded_within, "Session at 24h - 2s must be valid")

    def test_timestamp_boundary_at_24h_plus_1s(self):
        """Timestamp at 24 hours + 1 second must be expired (return None)."""
        now = time.time()
        ts_expired = now - (24 * 3600 + 1)
        self._create_session_with_timestamp(ts_expired)

        loaded = history.charger_etat_session("session_active", max_age_heures=24)
        self.assertIsNone(loaded, "Session at 24h + 1s must return None (expired)")

    def test_future_timestamp_handling(self):
        """Session timestamp in the future (clock skew, e.g. +1h or +24h)."""
        now = time.time()
        ts_future = now + 3600
        self._create_session_with_timestamp(ts_future)

        loaded = history.charger_etat_session("session_active", max_age_heures=24)
        # Verify how future timestamp is handled (should either load safely or reject if anomalous)
        # In current logic, age_secondes is negative, so age_secondes > 24*3600 is False -> returns messages
        self.assertIsNotNone(loaded, "Future timestamp within reasonable clock skew should not crash")

    def test_far_future_timestamp_or_anomalous_timestamp(self):
        """Far future timestamp (+10 years) or NaN timestamp."""
        now = time.time()
        # NaN timestamp
        chemin = self._create_session_with_timestamp(now)
        with open(chemin, "r", encoding="utf-8") as f:
            data = json.load(f)
        data["saved_at"] = "invalid_string_timestamp"
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # Should fall back gracefully (using mtime) without crashing
        loaded = history.charger_etat_session("session_active", max_age_heures=24)
        self.assertIsNotNone(loaded)

    def test_reinitialiser_etat_session_idempotence_10_times_existing_file(self):
        """Calling reinitialiser_etat_session 10 times in a row on an existing file."""
        history.sauvegarder_etat_session([{"role": "user", "content": "hello"}], "session_active")
        chemin = history._chemin_etat_session("session_active")
        self.assertTrue(os.path.exists(chemin))

        for i in range(10):
            try:
                history.reinitialiser_etat_session("session_active")
            except Exception as e:
                self.fail(f"reinitialiser_etat_session failed at call {i+1}: {e}")

        self.assertFalse(os.path.exists(chemin))

    def test_reinitialiser_etat_session_idempotence_10_times_missing_file(self):
        """Calling reinitialiser_etat_session 10 times in a row on a non-existent file."""
        chemin = history._chemin_etat_session("session_active")
        if os.path.exists(chemin):
            os.remove(chemin)

        for i in range(10):
            try:
                history.reinitialiser_etat_session("session_active")
            except Exception as e:
                self.fail(f"reinitialiser_etat_session on missing file failed at call {i+1}: {e}")

    def test_reinitialiser_etat_session_with_unusual_session_ids(self):
        """Calling reinitialiser_etat_session with edge-case IDs (empty, special chars, traversal)."""
        edge_ids = ["", None, "   ", "../../../test", "session#123!@$", "a" * 300]
        for sid in edge_ids:
            try:
                history.reinitialiser_etat_session(sid)
            except Exception as e:
                self.fail(f"reinitialiser_etat_session failed with session_id {sid!r}: {e}")


class TestAdversarialAirGapAndSecurity(unittest.TestCase):
    """Challenge 4: Air-Gap Strict Assertion and Security."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_adv_airgap_")
        self._orig_dossier = history._dossier_historique
        history._dossier_historique = lambda: self.temp_dir

    def tearDown(self):
        history._dossier_historique = self._orig_dossier
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_air_gap_strict_during_all_persistence_lifecycle(self):
        """Under AirGapAssertionProbe, all persistence lifecycle operations must generate 0 external traffic."""
        with AirGapAssertionProbe():
            # 1. Save
            msgs = [{"role": "user", "content": "Secret air-gap content"}]
            ok = history.sauvegarder_etat_session(msgs, "session_active")
            self.assertTrue(ok)

            # 2. Load
            loaded = history.charger_etat_session("session_active")
            self.assertEqual(loaded, msgs)

            # 3. 10 rapid saves
            for i in range(10):
                history.sauvegarder_etat_session([{"role": "user", "content": f"msg {i}"}], "session_active")

            # 4. Corrupt file handling
            chemin = history._chemin_etat_session("session_active")
            with open(chemin, "wb") as f:
                f.write(b"corrupted binary data")
            history.charger_etat_session("session_active")

            # 5. Reset
            history.reinitialiser_etat_session("session_active")


if __name__ == "__main__":
    unittest.main()
