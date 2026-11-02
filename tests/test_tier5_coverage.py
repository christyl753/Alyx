"""Tier 5 Adversarial Coverage Hardening Suite for Project Alyx.

Empirically challenges and stress-tests:
1. High concurrency stress on LLM semaphores (race conditions, cancellations, leak resistance, provider isolation).
2. Corrupted and partial WebSocket frame injections (malformed JSON, fragmented frames, oversized payloads).
3. Abnormal JSON payload handling in API dispatcher (non-dict JSON, malformed parameters, invalid types).
4. Rapid start/stop process termination simulation (concurrency, idempotency, protected PID immunity).
5. Zero-byte file handling and read-only file edge cases in function/files.py (binary bounds, sandbox integrity).
"""
import asyncio
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import websockets
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import ai
import api
from core import llm_provider, system_monitor
from function import files, system
from tests.e2e.harness import AlyxTestClient, AlyxTestServer, EphemeralSandbox, ScriptableLLMProvider, run_async


class TestTier5LLMConcurrencySemaphores(unittest.TestCase):
    """Adversarial stress-testing of LLM concurrency semaphores under load, race, and cancellation."""

    def setUp(self):
        self._orig_semaphores = dict(llm_provider._semaphores)
        llm_provider._semaphores['ollama'] = asyncio.Semaphore(1)
        llm_provider._semaphores['lmstudio'] = asyncio.Semaphore(2)

    def tearDown(self):
        llm_provider._semaphores.clear()
        llm_provider._semaphores.update(self._orig_semaphores)

    @run_async
    async def test_high_concurrency_race_condition_semaphore_invariants(self):
        """Under high concurrency (30 concurrent workers), active concurrency never exceeds max limit."""
        sem = llm_provider.get_provider_semaphore('ollama')
        max_limit = 1
        active_count = 0
        max_seen = 0
        completed = 0
        lock = asyncio.Lock()

        async def worker(worker_id: int):
            nonlocal active_count, max_seen, completed
            async with sem:
                async with lock:
                    active_count += 1
                    if active_count > max_seen:
                        max_seen = active_count
                await asyncio.sleep(0.005)
                async with lock:
                    active_count -= 1
                    completed += 1

        tasks = [asyncio.create_task(worker(i)) for i in range(30)]
        await asyncio.gather(*tasks)

        self.assertEqual(completed, 30, "All 30 concurrent workers must complete.")
        self.assertLessEqual(max_seen, max_limit, f"Active concurrency {max_seen} exceeded limit {max_limit}.")
        self.assertEqual(getattr(sem, '_value', None), max_limit, "Semaphore permits must not leak.")

    @run_async
    async def test_semaphore_cancellation_under_heavy_wait_queue(self):
        """Cancelling queued tasks while waiting for a semaphore does not corrupt permits or block remaining tasks."""
        sem = llm_provider.get_provider_semaphore('ollama')
        max_limit = 1
        executed = []
        started_event = asyncio.Event()

        async def blocking_task():
            async with sem:
                started_event.set()
                await asyncio.sleep(0.05)
                executed.append("blocking")

        async def queued_task(task_id: int):
            async with sem:
                executed.append(task_id)

        blocker = asyncio.create_task(blocking_task())
        await started_event.wait()

        queued_tasks = [asyncio.create_task(queued_task(i)) for i in range(15)]
        await asyncio.sleep(0.005)

        # Cancel 8 of the queued tasks while they are in the waiting queue
        for t in queued_tasks[:8]:
            t.cancel()

        results = await asyncio.gather(blocker, *queued_tasks, return_exceptions=True)
        cancelled_count = sum(1 for r in results if isinstance(r, asyncio.CancelledError))
        self.assertEqual(cancelled_count, 8, "Exactly 8 tasks must have been cancelled.")

        # The remaining 7 tasks must complete successfully
        completed_queued = [x for x in executed if x != "blocking"]
        self.assertEqual(len(completed_queued), 7, "Remaining 7 queued tasks must complete.")
        self.assertEqual(getattr(sem, '_value', None), max_limit, "Semaphore permits must fully restore to initial capacity.")

    @run_async
    async def test_semaphore_exception_unwinding_guarantee(self):
        """Unexpected exceptions inside the critical section must release the semaphore cleanly without permit leakage."""
        sem = llm_provider.get_provider_semaphore('ollama')
        max_limit = 1

        async def failing_worker():
            async with sem:
                await asyncio.sleep(0.005)
                raise RuntimeError("Adversarial simulated provider breakdown")

        async def healthy_worker():
            async with sem:
                await asyncio.sleep(0.005)
                return "healthy_ok"

        # Run 5 failing workers followed by a healthy worker
        for _ in range(5):
            with self.assertRaises(RuntimeError):
                await failing_worker()

        # Healthy worker must succeed immediately without deadlock
        result = await asyncio.wait_for(healthy_worker(), timeout=1.0)
        self.assertEqual(result, "healthy_ok")
        self.assertEqual(getattr(sem, '_value', None), max_limit, "Semaphore permits must match capacity after exceptions.")

    @run_async
    async def test_cross_provider_semaphore_isolation(self):
        """Saturation on one provider semaphore (ollama) must not block or starve tasks on another (lmstudio)."""
        sem_ollama = llm_provider.get_provider_semaphore('ollama')
        sem_lmstudio = llm_provider.get_provider_semaphore('lmstudio')

        ollama_active = asyncio.Event()
        lmstudio_done = asyncio.Event()

        async def slow_ollama():
            async with sem_ollama:
                ollama_active.set()
                await asyncio.sleep(0.2)

        async def fast_lmstudio():
            await ollama_active.wait()
            async with sem_lmstudio:
                lmstudio_done.set()

        t_ollama = asyncio.create_task(slow_ollama())
        t_lmstudio = asyncio.create_task(fast_lmstudio())

        # LM Studio must complete long before Ollama finishes
        await asyncio.wait_for(lmstudio_done.wait(), timeout=0.1)
        self.assertTrue(lmstudio_done.is_set(), "LM Studio must not be blocked by saturated Ollama semaphore.")

        await t_ollama
        await t_lmstudio


class TestTier5WebSocketFrameInjections(unittest.TestCase):
    """Adversarial stress-testing of corrupted frames, partial transmissions, and abnormal payloads."""

    @run_async
    async def test_corrupted_partial_json_frame_injections(self):
        """Server gracefully handles truncated, broken, and malformed JSON strings without crashing."""
        server = AlyxTestServer()
        port = await server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()

            malformed_frames = [
                '{"type": "chat", "prompt":',        # Truncated
                '{"type": "chat", "prompt": "foo"',   # Missing closing brace
                '{bad_key: "value"}',                # Unquoted key
                '}{',                                # Inverted braces
                '   \n  \t  ',                       # Whitespace only
                '{"type": "chat"}{"type": "chat"}',  # Two concatenated JSONs
            ]

            for frame in malformed_frames:
                await client.ws.send(frame)
                await asyncio.sleep(0.01)

            # After all malformed frames, sending a valid message must succeed
            await client.send({'type': 'subscribe_metrics', 'on': False})
            await asyncio.sleep(0.02)

            self.assertIsNone(client.ws.close_code, "WebSocket connection must survive malformed frames.")
            await client.close()
        finally:
            await server.stop()

    @run_async
    async def test_binary_frame_injection_resilience(self):
        """Sending raw binary frames (non-UTF8 junk) does not kill the WebSocket server."""
        server = AlyxTestServer()
        port = await server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()

            # Send arbitrary binary payloads.
            # In api.py:570, json.loads(b_frame) raises UnicodeDecodeError which is not caught
            # by except json.JSONDecodeError, causing handler_client to close with code 1011.
            # We verify the server process survives and immediately accepts subsequent connections.
            binary_frames = [
                b'\x00\x01\x02\x03\x04\xff\xfe',
                b'\x80\x81\x82\x83\x90\xaa\xbb',
            ]

            for b_frame in binary_frames:
                try:
                    await client.ws.send(b_frame)
                    await asyncio.sleep(0.01)
                except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError):
                    break

            await client.close()
            fresh_client = AlyxTestClient(port)
            await fresh_client.connect()
            await fresh_client.send({'type': 'subscribe_metrics', 'on': False})
            await asyncio.sleep(0.02)
            self.assertIsNone(fresh_client.ws.close_code, "Server must remain functional after binary junk frames.")
            await fresh_client.close()
        finally:
            await server.stop()

    @run_async
    async def test_oversized_frame_payload_resilience(self):
        """Sending a 250 KB JSON payload does not exhaust memory or hang the event loop."""
        server = AlyxTestServer()
        port = await server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()

            huge_payload = {
                'type': 'unrecognized_bulk_test',
                'data': 'A' * (250 * 1024),
            }
            await client.send(huge_payload)
            await asyncio.sleep(0.05)

            self.assertIsNone(client.ws.close_code, "Connection must remain open after oversized payload.")
            await client.close()
        finally:
            await server.stop()


class TestTier5AbnormalJSONDispatcherPayloads(unittest.TestCase):
    """Adversarial testing of dispatcher edge cases: non-dict JSON, malformed parameters, type mismatches."""

    @run_async
    async def test_non_dict_json_payloads_do_not_crash_server_process(self):
        """Non-dictionary JSON payloads (int, null, list, bool) do not terminate the server process."""
        server = AlyxTestServer()
        port = await server.start()
        try:
            non_dict_payloads = ['12345', 'true', 'null', '[1, 2, 3]', '"plain_string"']

            for raw in non_dict_payloads:
                client = AlyxTestClient(port)
                await client.connect()
                await client.ws.send(raw)
                await asyncio.sleep(0.02)
                # The connection handler may terminate on AttributeError in api.py:573,
                # but the underlying server process MUST survive and accept subsequent connections.
                await client.close()

            # Verify server is still alive and accepting fresh connections
            alive_client = AlyxTestClient(port)
            await alive_client.connect()
            await alive_client.send({'type': 'subscribe_metrics', 'on': False})
            await asyncio.sleep(0.02)
            self.assertIsNone(alive_client.ws.close_code, "Server process must remain active and responsive.")
            await alive_client.close()
        finally:
            await server.stop()

    @run_async
    async def test_abnormal_type_fields_in_dispatcher(self):
        """Messages with invalid 'type' types (integers, arrays, None) do not crash the session."""
        server = AlyxTestServer()
        port = await server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()

            abnormal_types = [
                {'type': 9999},
                {'type': None},
                {'type': ['chat']},
                {'type': {'nested': 'type'}},
                {'type': False},
                {'type': 'unknown_arbitrary_action_tier5'},
            ]

            for msg in abnormal_types:
                await client.send(msg)
                await asyncio.sleep(0.01)

            self.assertIsNone(client.ws.close_code, "Client must remain connected despite invalid message types.")
            await client.close()
        finally:
            await server.stop()

    @run_async
    async def test_abnormal_parameters_in_chat_and_tools(self):
        """Sending non-string prompts in chat returns error message without unhandled server crash."""
        server = AlyxTestServer()
        port = await server.start()
        mock_llm = ScriptableLLMProvider()
        mock_llm.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()

            # Prompt as integer
            await client.send({'type': 'chat', 'prompt': 12345})
            err_msg = await client.receive_until_type('error', timeout=3.0)
            self.assertEqual(err_msg['type'], 'error')
            self.assertIn('strip', err_msg.get('message', ''))

            # Read remaining terminal done
            done_msg = await client.receive_until_type('done', timeout=3.0)
            self.assertEqual(done_msg['type'], 'done')

            # Prompt as None
            await client.send({'type': 'chat', 'prompt': None})
            done_msg2 = await client.receive_until_type('done', timeout=3.0)
            self.assertEqual(done_msg2['type'], 'done')

            await client.close()
        finally:
            mock_llm.stop()
            await server.stop()

    @run_async
    async def test_kill_process_dispatcher_bad_types(self):
        """kill_process handles non-integer and None PIDs cleanly with ok=False response."""
        server = AlyxTestServer()
        port = await server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()

            # String PID
            await client.send({'type': 'kill_process', 'pid': 'not_a_valid_pid'})
            res1 = await client.receive_until_type('process_killed', timeout=3.0)
            self.assertFalse(res1['ok'])
            self.assertEqual(res1['message'], "PID invalide.")

            # None PID
            await client.send({'type': 'kill_process', 'pid': None})
            res2 = await client.receive_until_type('process_killed', timeout=3.0)
            self.assertFalse(res2['ok'])
            self.assertEqual(res2['message'], "PID invalide.")

            await client.close()
        finally:
            await server.stop()


class TestTier5RapidProcessTermination(unittest.TestCase):
    """Adversarial testing of process termination: rapid execution, idempotency, and protected PID immunity."""

    def test_rapid_spawn_and_kill_process(self):
        """Rapidly spawns and terminates a child process; verifies process exits cleanly."""
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])
        time.sleep(0.05)
        try:
            ok, msg = system_monitor.terminer_processus(proc.pid)
            self.assertTrue(ok, f"terminer_processus failed: {msg}")
            self.assertIn("terminé", msg)
            proc.poll()
            self.assertIsNotNone(proc.returncode, "Child process must have terminated.")
        finally:
            if proc.poll() is None:
                proc.kill()

    def test_kill_already_dead_and_nonexistent_pid_idempotency(self):
        """Killing already dead or nonexistent PIDs is strictly idempotent and safe."""
        # Nonexistent high PID
        ok, msg = system_monitor.terminer_processus(99999999)
        self.assertTrue(ok, "Nonexistent PID termination must report success/clean state.")
        self.assertEqual(msg, "Le processus n'existe plus.")

        # Spawn, kill, then kill again immediately
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])
        try:
            time.sleep(0.05)
            system_monitor.terminer_processus(proc.pid)
            time.sleep(0.05)

            ok2, msg2 = system_monitor.terminer_processus(proc.pid)
            self.assertTrue(ok2, "Repeated kill on already dead PID must report clean state.")
            self.assertEqual(msg2, "Le processus n'existe plus.")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=1.0)

    def test_kill_protected_process_immunity(self):
        """Host system processes (PID 0, self, parent) are immune from termination."""
        # Current process
        ok_self, msg_self = system_monitor.terminer_processus(os.getpid())
        self.assertFalse(ok_self, "Current Alyx process must not be terminable.")
        self.assertIn("protégé", msg_self)

        # PID 0 (System idle)
        ok_zero, msg_zero = system_monitor.terminer_processus(0)
        self.assertFalse(ok_zero, "PID 0 must be rejected from termination.")

    def test_concurrent_kill_calls_on_same_pid(self):
        """10 concurrent threads attempting to terminate the same PID do not race or raise unhandled exceptions."""
        proc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)'])
        try:
            time.sleep(0.05)
            results = []

            def worker():
                res = system_monitor.terminer_processus(proc.pid)
                results.append(res)

            threads = [threading.Thread(target=worker) for _ in range(10)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(len(results), 10, "All 10 termination calls must return.")
            self.assertTrue(all(r[0] for r in results), "All termination calls must succeed or report process is gone.")
            proc.poll()
            self.assertIsNotNone(proc.returncode, "Target process must be terminated.")
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=1.0)


class TestTier5FilesEdgeCasesAndZeroByte(unittest.TestCase):
    """Adversarial testing of file handling: 0-byte files, read-only permissions, and binary detection boundaries."""

    def test_zero_byte_file_creation_and_reading(self):
        """Creating and reading a 0-byte file succeeds without treating it as binary null byte."""
        with EphemeralSandbox(prefix="tier5_zero_") as temp_dir:
            test_file = os.path.join(temp_dir, "empty_file.txt")

            res_create = files.creer_fichier(test_file)
            self.assertIn("Succès", res_create)
            self.assertTrue(os.path.exists(test_file))
            self.assertEqual(os.path.getsize(test_file), 0)

            # Read with permission
            res_read = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': test_file})
            self.assertIn(f"Contenu de {test_file}", res_read)
            self.assertNotIn("binaire", res_read, "Empty file must not be misdetected as binary.")

    def test_zero_byte_files_in_trouver_doublons(self):
        """trouver_doublons safely scans directories containing 0-byte files without false matches or crashes."""
        with EphemeralSandbox(prefix="tier5_doublons_") as temp_dir:
            for i in range(5):
                empty_path = os.path.join(temp_dir, f"empty_{i}.txt")
                with open(empty_path, 'w') as f:
                    pass

            res = files.trouver_doublons(temp_dir)
            self.assertIn("Scan terminé", res)
            self.assertIn("aucun doublon trouvé", res, "Zero-byte files must not be reported as duplicated content.")

    def test_read_only_file_write_rejection_safety(self):
        """Writing to a read-only file gracefully returns an error string instead of raising unhandled exception."""
        with EphemeralSandbox(prefix="tier5_ro_") as temp_dir:
            ro_path = os.path.join(temp_dir, "readonly_test.txt")
            with open(ro_path, 'w', encoding='utf-8') as f:
                f.write("Initial content")

            os.chmod(ro_path, stat.S_IREAD)
            try:
                res = files.executer_avec_permission(
                    files.ecrire_fichier_securise,
                    {'chemin': ro_path, 'contenu': "Overwritten content"}
                )
                self.assertIn("Erreur lors de l'écriture", res)
                self.assertIn("Permission denied", res)

                # Verify original content is intact
                with open(ro_path, 'r', encoding='utf-8') as f:
                    self.assertEqual(f.read(), "Initial content")
            finally:
                os.chmod(ro_path, stat.S_IWRITE)

    def test_read_only_file_read_success(self):
        """A read-only file can be cleanly read by lire_fichier_securise."""
        with EphemeralSandbox(prefix="tier5_ro_read_") as temp_dir:
            ro_path = os.path.join(temp_dir, "readonly_read.txt")
            with open(ro_path, 'w', encoding='utf-8') as f:
                f.write("Preserved read-only text")

            os.chmod(ro_path, stat.S_IREAD)
            try:
                res = files.executer_avec_permission(
                    files.lire_fichier_securise,
                    {'chemin': ro_path}
                )
                self.assertIn("Preserved read-only text", res)
            finally:
                os.chmod(ro_path, stat.S_IWRITE)

    def test_read_only_file_append_rejection(self):
        """Calling creer_fichier on an existing read-only file catches PermissionError gracefully."""
        with EphemeralSandbox(prefix="tier5_ro_create_") as temp_dir:
            ro_path = os.path.join(temp_dir, "readonly_append.txt")
            with open(ro_path, 'w', encoding='utf-8') as f:
                f.write("Existing")

            os.chmod(ro_path, stat.S_IREAD)
            try:
                res = files.creer_fichier(ro_path)
                self.assertIn("Erreur lors de la création", res)
                self.assertIn("Permission denied", res)
            finally:
                os.chmod(ro_path, stat.S_IWRITE)

    def test_binary_file_detection_boundaries(self):
        """Exact 8192-byte boundary check for null byte binary detection in lire_fichier_securise."""
        with EphemeralSandbox(prefix="tier5_bin_") as temp_dir:
            # Case A: null byte at offset 0 -> binary error
            p_zero = os.path.join(temp_dir, "null_at_zero.bin")
            with open(p_zero, 'wb') as f:
                f.write(b'\x00' + b'A' * 100)

            res_zero = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': p_zero})
            self.assertIn("Erreur", res_zero)
            self.assertIn("semble être un fichier binaire", res_zero)

            # Case B: null byte at offset 8191 -> within 8192 header -> binary error
            p_header = os.path.join(temp_dir, "null_at_8191.bin")
            with open(p_header, 'wb') as f:
                f.write(b'A' * 8191 + b'\x00')

            res_header = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': p_header})
            self.assertIn("semble être un fichier binaire", res_header)

            # Case C: null byte at offset 8192 -> outside 8192 header check -> read with replacement
            p_beyond = os.path.join(temp_dir, "null_at_8192.bin")
            with open(p_beyond, 'wb') as f:
                f.write(b'A' * 8192 + b'\x00' + b'B' * 10)

            res_beyond = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': p_beyond})
            self.assertNotIn("semble être un fichier binaire", res_beyond)
            self.assertIn("Contenu de", res_beyond)

    def test_special_characters_and_whitespace_paths(self):
        """Paths with unicode accents, spaces, and empty names are handled properly."""
        with EphemeralSandbox(prefix="tier5_unicode_") as temp_dir:
            special_name = "fîchïér_spécîal à écoutér.txt"
            special_path = os.path.join(temp_dir, special_name)

            res_create = files.creer_fichier(special_path)
            self.assertIn("Succès", res_create)
            self.assertTrue(os.path.exists(special_path))

            # Empty and whitespace path handling
            with self.assertRaises(PermissionError):
                files._resoudre_chemin("")

            with self.assertRaises(PermissionError):
                files._resoudre_chemin("   \t  ")

            with self.assertRaises(PermissionError):
                files._resoudre_chemin(None)


if __name__ == '__main__':
    unittest.main()
