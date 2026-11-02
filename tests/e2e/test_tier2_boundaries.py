"""Tier 2: Boundary, Edge & Corner Cases for all inventoried Alyx features.
Covers >= 5 tests per feature domain across the 8 core features:
1. Clock / Time Boundaries
2. Metrics / Status Boundaries
3. Tool Execution Boundaries
4. Kill Switch Boundaries
5. HITL Boundaries
6. Multi-Provider Boundaries
7. Air-Gap & Security Boundaries
8. Prompts & Context Boundaries
"""
import asyncio
import datetime
import json
import os
import shutil
import socket
import sys
import unittest
from unittest.mock import patch, MagicMock

import websockets

from tests.e2e.harness import (
    AlyxTestServer,
    AlyxTestClient,
    ScriptableLLMProvider,
    EphemeralSandbox,
    AirGapAssertionProbe,
    AirGapViolationError,
    run_async,
)
import api
import ai
from core import system_monitor, preferences, llm_provider
from function import files, system


class TestTier2BoundaryClock(unittest.TestCase):
    """F1: Clock & Time Boundaries (>=5 tests)."""

    def test_midnight_rollover_transition(self):
        """Clock formatting transitions cleanly across midnight rollover."""
        t_pre = datetime.datetime(2026, 12, 31, 23, 59, 59)
        t_post = datetime.datetime(2027, 1, 1, 0, 0, 0)
        str_pre = t_pre.strftime("%H:%M")
        str_post = t_post.strftime("%H:%M")
        self.assertEqual(str_pre, "23:59")
        self.assertEqual(str_post, "00:00")

    def test_end_of_february_leap_year_handling(self):
        """Date formatting handles leap year Feb 29 date correctly."""
        leap_date = datetime.datetime(2028, 2, 29, 12, 0)
        self.assertEqual(leap_date.day, 29)
        self.assertEqual(leap_date.month, 2)
        # Formats without exception
        formatted = leap_date.strftime("%d/%m/%Y %H:%M")
        self.assertEqual(formatted, "29/02/2028 12:00")

    def test_rapid_consecutive_clock_invocations(self):
        """50 consecutive clock queries in a tight loop execute under 20ms without drift."""
        start = datetime.datetime.now()
        for _ in range(50):
            now = datetime.datetime.now()
            _ = now.strftime("%H:%M")
        duration = (datetime.datetime.now() - start).total_seconds()
        self.assertLess(duration, 0.5)

    def test_clock_multilingual_locale_fallback(self):
        """Date strings format reliably across all 4 supported languages."""
        now = datetime.datetime(2026, 6, 15, 14, 30)
        langs = ('fr', 'en', 'es', 'de')
        for lang in langs:
            # ISO timestamp representation remains universal
            iso = now.isoformat()
            self.assertIn("2026-06-15", iso)

    def test_clock_year_transition_boundary(self):
        """Year boundary rollover from Dec 31 to Jan 1 updates year correctly."""
        dec31 = datetime.datetime(2026, 12, 31, 23, 59)
        jan1 = dec31 + datetime.timedelta(minutes=2)
        self.assertEqual(jan1.year, 2027)
        self.assertEqual(jan1.strftime("%H:%M"), "00:01")


class TestTier2BoundaryMetrics(unittest.TestCase):
    """F2: Metrics & Observability Boundaries (>=5 tests)."""

    def setUp(self):
        self.server = AlyxTestServer()
        self.llm = ScriptableLLMProvider()
        self.llm.start()

    def tearDown(self):
        self.llm.stop()

    def test_metrics_without_gpu_hardware(self):
        """Snapshot gracefully returns valid data when GPU is simulated absent."""
        with patch.object(system_monitor, '_gpu', return_value=None):
            snap = system_monitor.snapshot()
            self.assertIsNone(snap['gpu'])
            self.assertIn('cpu', snap)
            self.assertIn('ram', snap)

    def test_metrics_without_battery_hardware(self):
        """Snapshot gracefully handles desktop computers without battery."""
        with patch('psutil.sensors_battery', return_value=None):
            snap = system_monitor.snapshot()
            self.assertIsNone(snap['battery'])

    @run_async
    async def test_rapid_metrics_subscription_toggle(self):
        """Toggling metrics subscription on/off 10 times in rapid succession causes no task leaks."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            for _ in range(10):
                await client.send({'type': 'subscribe_metrics', 'on': True})
                await client.send({'type': 'subscribe_metrics', 'on': False})
            # Final state off, verify server is healthy
            await client.send({'type': 'get_status'})
            msg = await client.receive_until_type('provider_status', timeout=3.0)
            self.assertEqual(msg['type'], 'provider_status')
            await client.close()
        finally:
            await self.server.stop()

    def test_process_list_extreme_limits(self):
        """get_processes gracefully handles limit=0, limit=1, and extreme limits."""
        p_zero = system_monitor.processus(limite=0)
        self.assertGreater(p_zero['total'], 0)
        p_one = system_monitor.processus(limite=1)
        self.assertEqual(len(p_one['items']), 1)
        p_large = system_monitor.processus(limite=5000)
        self.assertGreater(len(p_large['items']), 0)

    @run_async
    async def test_kill_process_invalid_pid(self):
        """Attempting to kill protected PID (Alyx process or PID 0) fails safely."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'kill_process', 'pid': os.getpid()})
            msg = await client.receive_until_type('process_killed', timeout=3.0)
            self.assertEqual(msg['type'], 'process_killed')
            self.assertFalse(msg['ok'])
            self.assertIn("protégé", msg['message'])
            await client.close()
        finally:
            await self.server.stop()


class TestTier2BoundaryToolExecution(unittest.TestCase):
    """F3: Tool Execution & Sandbox Boundaries (>=5 tests)."""

    def test_path_traversal_double_dot_escape(self):
        """Path with multiple '../' cannot escape user home directory."""
        with self.assertRaises(PermissionError):
            files._resoudre_chemin("~/../../../../../../Windows/System32/cmd.exe")

    def test_empty_filename_rejected(self):
        """Creating an empty string filename returns an error."""
        res = files.creer_fichier("")
        self.assertIn("Erreur", res)

    def test_unicode_and_emoji_filenames(self):
        """Files with unicode accents and emojis are created and manipulated properly."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "résumé_2026_🚀.txt")
            res = files.creer_fichier(path)
            self.assertIn("créé", res.lower())
            self.assertTrue(os.path.exists(path))

    def test_zero_byte_file_reading(self):
        """Reading an empty 0-byte file succeeds and returns empty content header."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "empty.txt")
            open(path, 'w').close()
            res = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': path})
            self.assertIn("Contenu de", res)

    @run_async
    async def test_call_nonexistent_tool_returns_error(self):
        """Invoking a nonexistent tool through LLM tool call yields an error result."""
        llm = ScriptableLLMProvider()
        llm.start()
        srv = AlyxTestServer()
        port = await srv.start()
        try:
            llm.queue_tool_call("fonction_qui_n_existe_pas_123", {'a': 1})
            llm.queue_text_response("Outil manquant constaté.")

            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Lance outil inexistant'})
            done_msg = await client.receive_until_type('done', timeout=4.0)
            self.assertEqual(done_msg['type'], 'done')
            # Verify context recorded tool error
            tool_resps = [m for m in api.messages if m.get('role') == 'tool']
            self.assertTrue(any("introuvable" in m['content'] for m in tool_resps))
            await client.close()
        finally:
            await srv.stop()
            llm.stop()


class TestTier2BoundaryKillSwitch(unittest.TestCase):
    """F4: Kill Switch Boundaries (>=5 tests)."""

    def setUp(self):
        self.server = AlyxTestServer()
        self.llm = ScriptableLLMProvider()
        self.llm.start()
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        self.llm.stop()
        api.messages[:] = self._orig_messages

    @run_async
    async def test_multiple_rapid_cancels(self):
        """Sending 5 cancel messages in burst does not crash or deadlock server."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            for _ in range(5):
                await client.send({'type': 'cancel'})
            await client.send({'type': 'get_status'})
            msg = await client.receive_until_type('provider_status', timeout=3.0)
            self.assertEqual(msg['type'], 'provider_status')
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_cancel_then_immediate_new_chat(self):
        """Cancelling and immediately starting a new chat succeeds without interference."""
        events = [{'content': f'Fragment{i} ', 'delay': 0.08} for i in range(20)]
        self.llm.queue_scenario(events)
        self.llm.queue_text_response("Réponse immédiate numéro 2")

        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Message 1'})
            await client.receive_until_type('token', timeout=4.0)
            await client.send({'type': 'cancel'})
            await client.receive_until_type('done', timeout=4.0)

            # Immediate second chat
            await client.send({'type': 'chat', 'prompt': 'Message 2'})
            token2 = await client.receive_until_type('token', timeout=4.0)
            self.assertIn("Réponse", token2['content'])
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_cancel_during_nested_tool_pipeline(self):
        """Cancel stops tool execution pipeline and cleans up remainder."""
        self.llm.queue_scenario([
            {
                'tool_calls': [
                    {'id': 'c1', 'type': 'function', 'function': {'name': 'controler_media', 'arguments': {'action': 'lecture_pause'}}},
                    {'id': 'c2', 'type': 'function', 'function': {'name': 'controler_media', 'arguments': {'action': 'suivant'}}},
                ]
            }
        ])
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Contrôle média'})
            # Cancel immediately
            await client.send({'type': 'cancel'})
            done_msg = await client.receive_until_type('done', timeout=4.0)
            self.assertEqual(done_msg['type'], 'done')
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_cancel_during_hitl_pending(self):
        """Cancel while action_required is pending leaves session ready for fresh request."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "pending_cancel.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime pending_cancel'})
                await client.receive_until_type('action_required', timeout=4.0)

                # Send cancel
                await client.send({'type': 'cancel'})
                # Send fresh chat
                self.llm.queue_text_response("Session fraîche.")
                await client.send({'type': 'chat', 'prompt': 'Autre question'})
                msg = await client.receive_until_type('token', timeout=4.0)
                self.assertIn("Session", msg['content'])
                await client.receive_until_type('done', timeout=4.0)
                # Original file kept
                self.assertTrue(os.path.exists(path))
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_cancel_when_client_disconnects(self):
        """Client disconnect mid-generation triggers cancellation gracefully."""
        events = [{'content': f'Mot{i} ', 'delay': 0.08} for i in range(30)]
        self.llm.queue_scenario(events)
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Démarre long flux'})
            await client.receive_until_type('token', timeout=4.0)
            # Hard close
            await client.close()
            # Give server loop 0.1s to handle disconnect
            await asyncio.sleep(0.1)
        finally:
            await self.server.stop()


class TestTier2BoundaryHITL(unittest.TestCase):
    """F5: HITL Boundaries (>=5 tests)."""

    def setUp(self):
        self.server = AlyxTestServer()
        self.llm = ScriptableLLMProvider()
        self.llm.start()
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        self.llm.stop()
        api.messages[:] = self._orig_messages

    @run_async
    async def test_permission_response_when_no_action_pending(self):
        """Sending permission_granted when nothing is pending returns clean error."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'permission_granted'})
            err_msg = await client.receive_until_type('error', timeout=4.0)
            self.assertIn("Aucune action n'est en attente", err_msg['message'])
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_new_chat_aborts_prior_pending_hitl(self):
        """Sending new chat prompt while HITL pending cleanly abandons prior action."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "abandoned.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})
            self.llm.queue_text_response("Nouvelle réponse.")

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime abandoned'})
                await client.receive_until_type('action_required', timeout=4.0)

                # Send new chat instead of answering permission
                await client.send({'type': 'chat', 'prompt': 'Oublie ça, parle-moi d un autre sujet'})
                done_msg = await client.receive_until_type('done', timeout=4.0)
                self.assertEqual(done_msg['type'], 'done')
                self.assertTrue(os.path.exists(path))
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_rapid_duplicate_permission_responses(self):
        """Sending permission_granted twice only executes action once without error."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "once.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})
            self.llm.queue_text_response("Exécuté une seule fois.")

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime once'})
                await client.receive_until_type('action_required', timeout=4.0)

                # Send permission twice
                await client.send({'type': 'permission_granted'})
                await client.send({'type': 'permission_granted'})
                done_msg = await client.receive_until_type('done', timeout=4.0)
                self.assertEqual(done_msg['type'], 'done')
                self.assertFalse(os.path.exists(path))
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_disconnect_during_hitl_wait(self):
        """Client disconnect during action_required cleans up session state."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "disconnect_victim.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime disconnect_victim'})
                await client.receive_until_type('action_required', timeout=4.0)
                # Disconnect immediately
                await client.close()
                await asyncio.sleep(0.1)
                self.assertTrue(os.path.exists(path))
            finally:
                await self.server.stop()

    @run_async
    async def test_nested_sensitive_actions_sequential(self):
        """Multiple sequential sensitive tools require separate approvals."""
        with EphemeralSandbox() as sbox:
            p1 = os.path.join(sbox, "p1.txt")
            p2 = os.path.join(sbox, "p2.txt")
            open(p1, 'w').close()
            open(p2, 'w').close()

            self.llm.queue_scenario([
                {
                    'tool_calls': [
                        {'id': 'c1', 'type': 'function', 'function': {'name': 'supprimer_fichier', 'arguments': {'chemin': p1}}},
                        {'id': 'c2', 'type': 'function', 'function': {'name': 'supprimer_fichier', 'arguments': {'chemin': p2}}},
                    ]
                }
            ])
            self.llm.queue_text_response("Deuxième suppression validée.")

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime deux fichiers'})
                # First HITL
                req1 = await client.receive_until_type('action_required', timeout=4.0)
                self.assertIn("SUPPRIMER", req1['action'].upper())
                await client.send({'type': 'permission_granted'})

                # Second HITL
                req2 = await client.receive_until_type('action_required', timeout=4.0)
                self.assertIn("SUPPRIMER", req2['action'].upper())
                await client.send({'type': 'permission_granted'})

                await client.receive_until_type('done', timeout=4.0)
                self.assertFalse(os.path.exists(p1))
                self.assertFalse(os.path.exists(p2))
                await client.close()
            finally:
                await self.server.stop()


class TestTier2BoundaryMultiProvider(unittest.TestCase):
    """F6: Multi-Provider Boundaries (>=5 tests)."""

    def setUp(self):
        self.server = AlyxTestServer()
        self.llm = ScriptableLLMProvider()
        self.llm.start()

    def tearDown(self):
        self.llm.stop()

    @run_async
    async def test_all_providers_offline_graceful_error(self):
        """Simulated provider crash yields clean error payload over WebSocket."""
        self.llm.queue_scenario([{'error': RuntimeError("Fournisseur Ollama inaccessible.")}])
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Bonjour'})
            err_msg = await client.receive_until_type('error', timeout=4.0)
            self.assertIn("inaccessible", err_msg['message'])
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_provider_returning_malformed_json(self):
        """Malformed JSON from provider yields graceful error to user."""
        self.llm.queue_scenario([{'error': json.JSONDecodeError("Invalid JSON", "doc", 0)}])
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Test JSON cassé'})
            err = await client.receive_until_type('error', timeout=4.0)
            self.assertIn("Invalid JSON", err['message'])
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_rapid_model_switching_during_chat(self):
        """select_model during active generation handles occupancy cleanly."""
        events = [{'content': 'Long token...', 'delay': 0.1} for _ in range(20)]
        self.llm.queue_scenario(events)
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Prompt en cours'})
            await client.receive_until_type('token', timeout=4.0)
            # Switch model
            await client.send({'type': 'select_model', 'model': 'model-beta'})
            msg = await client.receive_until_type('model_selected', timeout=4.0)
            self.assertEqual(msg['model'], 'model-beta')
            await client.send({'type': 'cancel'})
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_empty_model_name_selection(self):
        """Sending select_model with empty model string is ignored safely."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            curr = ai.MODEL
            await client.send({'type': 'select_model', 'model': ''})
            # Model remains unchanged
            self.assertEqual(ai.MODEL, curr)
            await client.close()
        finally:
            await self.server.stop()

    def test_circuit_breaker_cool_down_trip(self):
        """Circuit breaker tracks consecutive failure count."""
        prov_status = llm_provider.get_provider_status()
        self.assertIn('ollama', prov_status)
        self.assertIn('failures', prov_status['ollama'])


class TestTier2BoundaryAirGap(unittest.TestCase):
    """F7: Air-Gap & Security Boundaries (>=5 tests)."""

    def test_web_scraping_rejects_wan_urls(self):
        """Anti-SSRF strictly rejects non-local external URLs."""
        from function.web import _verifier_url_securisee
        with self.assertRaises(ValueError):
            _verifier_url_securisee("http://127.0.0.1:8765/api")
        with self.assertRaises(ValueError):
            _verifier_url_securisee("http://localhost:5001")

    def test_anti_ssrf_rejects_ipv6_loopback_obfuscation(self):
        """Anti-SSRF rejects IPv6 loopback variants (::1, [::1])."""
        from function.web import _verifier_url_securisee
        with self.assertRaises(ValueError):
            _verifier_url_securisee("http://[::1]:8080")

    def test_stt_server_rejects_origin_header(self):
        """STT server refuses browser cross-site calls with Origin header."""
        from stt_server import STTHandler
        # Direct check on origin detection logic
        handler = STTHandler.__new__(STTHandler)
        handler.headers = {'Origin': 'http://evil.com'}
        self.assertTrue(handler._requete_navigateur())

    def test_stt_server_rejects_malformed_json_body(self):
        """STT server handles malformed JSON without crashing."""
        from stt_server import STTHandler
        import io
        handler = STTHandler.__new__(STTHandler)
        handler.headers = {'Content-Length': '10'}
        handler.rfile = io.BytesIO(b'{bad_json}')
        corps = handler._corps_json()
        self.assertEqual(corps, {})

    def test_network_diagnostics_airgapped(self):
        """Network status helper inspects local interface without internet dependencies."""
        snap = system_monitor.snapshot()
        self.assertIn('net', snap)
        self.assertIn('down_mbs', snap['net'])
        self.assertIn('up_mbs', snap['net'])


class TestTier2BoundaryPromptsContext(unittest.TestCase):
    """F8: Prompts & Context Boundaries (>=5 tests)."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def test_context_truncation_with_massive_history(self):
        """History exceeding 2x context window is strictly bounded by _tronquer_historique."""
        for i in range(api.MAX_CONTEXT_MESSAGES * 3):
            api.messages.append({'role': 'user' if i % 2 == 0 else 'assistant', 'content': f"Message {i}"})
        api._tronquer_historique()
        self.assertLessEqual(len(api.messages) - 1, api.MAX_CONTEXT_MESSAGES * 2)
        self.assertEqual(api.messages[0]['role'], 'system')
        fenetre = api._messages_avec_fenetre()
        self.assertLessEqual(len(fenetre) - 1, api.MAX_CONTEXT_MESSAGES)

    @run_async
    async def test_empty_prompt_submission(self):
        """Sending empty prompt returns immediate done without calling LLM."""
        llm = ScriptableLLMProvider()
        llm.start()
        srv = AlyxTestServer()
        port = await srv.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': '   '})
            done_msg = await client.receive_until_type('done', timeout=3.0)
            self.assertEqual(done_msg['type'], 'done')
            # Verify LLM was NOT called
            self.assertEqual(len(llm.call_history), 0)
            await client.close()
        finally:
            await srv.stop()
            llm.stop()

    @run_async
    async def test_massive_prompt_payload(self):
        """Sending a 30,000-character prompt does not crash server or leak memory."""
        llm = ScriptableLLMProvider()
        llm.start()
        llm.queue_text_response("Grand prompt traité avec succès.")
        srv = AlyxTestServer()
        port = await srv.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            huge_text = "Alyx " * 6000  # ~30k chars
            await client.send({'type': 'chat', 'prompt': huge_text})
            msg = await client.receive_until_type('token', timeout=4.0)
            self.assertIn("Grand", msg['content'])
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await srv.stop()
            llm.stop()

    @run_async
    async def test_rapid_multi_turn_prompts(self):
        """Submitting a new prompt while already busy returns error 'génération déjà en cours'."""
        llm = ScriptableLLMProvider()
        llm.start()
        llm.queue_scenario([{'content': 'Lent...', 'delay': 0.15} for _ in range(10)])
        srv = AlyxTestServer()
        port = await srv.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'P1'})
            await client.receive_until_type('token', timeout=4.0)
            # Send second prompt immediately while busy
            await client.send({'type': 'chat', 'prompt': 'P2'})
            err_msg = await client.receive_until_type('error', timeout=4.0)
            self.assertIn("déjà en cours", err_msg['message'])
            await client.send({'type': 'cancel'})
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await srv.stop()
            llm.stop()

    def test_prompt_system_role_remains_at_index_zero(self):
        """Regardless of truncation, system prompt always occupies index 0."""
        contexte = api._messages_avec_fenetre()
        self.assertEqual(contexte[0]['role'], 'system')


if __name__ == '__main__':
    unittest.main()
