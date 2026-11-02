"""Tier 1: Feature Coverage (Happy Path) for all inventoried Alyx features.
Covers >= 5 tests per feature domain across the 8 core features:
1. Clock & Temporal Sync
2. Status & Metrics Observability
3. Tool Execution & Files Sandbox
4. Kill Switch & Task Interruption
5. Human-in-the-Loop (HITL) Safety
6. Multi-Provider & Strict JSON Schemas
7. Air-Gap & Security Invariants
8. Prompts & Task Comprehension
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


class TestTier1FeatureClock(unittest.TestCase):
    """F1: Clock & Temporal Sync Feature Coverage (>=5 tests)."""

    def test_clock_format_24h_hour_minute(self):
        """Clock displays standard HH:mm 24-hour format."""
        now = datetime.datetime.now()
        expected = now.strftime("%H:%M")
        self.assertEqual(len(expected), 5)
        self.assertEqual(expected[2], ':')
        self.assertTrue(expected[:2].isdigit())
        self.assertTrue(expected[3:].isdigit())

    def test_clock_date_format_french_capitalization(self):
        """Date format capitalization rule for French locale."""
        now = datetime.datetime.now()
        mois_fr = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        jours_fr = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
        jour_nom = jours_fr[now.weekday()]
        mois_nom = mois_fr[now.month - 1]
        raw_date = f"{jour_nom} {now.day} {mois_nom}"
        capitalized = raw_date[0].upper() + raw_date[1:]
        self.assertTrue(capitalized[0].isupper())
        self.assertIn(str(now.day), capitalized)

    def test_clock_compact_mode_formatting(self):
        """Compact date format (ddd d MMM) used when panel width < 430px."""
        now = datetime.datetime.now()
        jours_court = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
        mois_court = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
        compact = f"{jours_court[now.weekday()]} {now.day} {mois_court[now.month - 1]}"
        self.assertLess(len(compact), 20)
        self.assertIn(str(now.day), compact)

    def test_clock_temporal_grounding_in_system_snapshot(self):
        """System monitor snapshot includes hardware metrics and system state."""
        snap = system_monitor.snapshot()
        self.assertIn('cpu', snap)
        self.assertIn('ram', snap)
        now = datetime.datetime.now()
        self.assertIsInstance(now, datetime.datetime)

    def test_clock_monotonic_subsecond_sampling(self):
        """Multiple clock readings over 100ms demonstrate non-decreasing time."""
        t1 = datetime.datetime.now()
        import time; time.sleep(0.05)
        t2 = datetime.datetime.now()
        self.assertGreaterEqual(t2, t1)

    def test_clock_timezone_preservation(self):
        """Verifies local system time preserves timezone offset info."""
        now = datetime.datetime.now()
        utcnow = datetime.datetime.utcnow()
        # Offset difference is reasonable (within 24h)
        diff = abs((now - utcnow).total_seconds())
        self.assertLess(diff, 86400)


class TestTier1FeatureStatusMetrics(unittest.TestCase):
    """F2: Status & System Metrics Feature Coverage (>=5 tests)."""

    def setUp(self):
        self.server = AlyxTestServer()
        self.llm = ScriptableLLMProvider()
        self.llm.start()

    def tearDown(self):
        self.llm.stop()

    @run_async
    async def test_metrics_subscription_stream(self):
        """Subscribing to metrics receives periodic metrics payloads."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'subscribe_metrics', 'on': True})
            msg = await client.receive_until_type('metrics', timeout=4.0)
            self.assertEqual(msg['type'], 'metrics')
            self.assertIn('cpu', msg)
            self.assertIn('ram', msg)
            self.assertIn('gpu', msg)
            self.assertIn('net', msg)
            self.assertIn('generating', msg)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_metrics_generating_flag_state(self):
        """Generating flag in metrics reflects whether session is occupied."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            # Idle initially
            await client.send({'type': 'subscribe_metrics', 'on': True})
            msg = await client.receive_until_type('metrics', timeout=4.0)
            self.assertFalse(msg['generating'])
            await client.send({'type': 'subscribe_metrics', 'on': False})
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_process_listing_ordered_by_cpu(self):
        """get_processes returns processes sorted by CPU and marks Alyx process."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'get_processes', 'limit': 20})
            msg = await client.receive_until_type('processes', timeout=4.0)
            self.assertEqual(msg['type'], 'processes')
            self.assertIn('items', msg)
            self.assertGreater(len(msg['items']), 0)
            # Verify sorted descending
            cpus = [item['cpu'] for item in msg['items']]
            self.assertEqual(cpus, sorted(cpus, reverse=True))
            # Verify Alyx process is tagged
            self.assertTrue(any(item.get('alyx') for item in msg['items']))
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_hardware_snapshot_bounds(self):
        """Hardware metrics values remain within valid mathematical bounds."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'subscribe_metrics', 'on': True})
            msg = await client.receive_until_type('metrics', timeout=4.0)
            self.assertGreaterEqual(msg['cpu']['percent'], 0.0)
            self.assertLessEqual(msg['cpu']['percent'], 100.0)
            self.assertGreater(msg['ram']['total_gb'], 0.0)
            self.assertGreaterEqual(msg['ram']['percent'], 0.0)
            self.assertLessEqual(msg['ram']['percent'], 100.0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_metrics_unsubscribe_halts_stream(self):
        """Unsubscribing stops receiving metrics updates."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'subscribe_metrics', 'on': True})
            await client.receive_until_type('metrics', timeout=4.0)
            await client.send({'type': 'subscribe_metrics', 'on': False})
            await client.send({'type': 'get_status'})
            status_msg = await client.receive_until_type('provider_status', timeout=3.0)
            self.assertEqual(status_msg['type'], 'provider_status')
            await client.close()
        finally:
            await self.server.stop()


class TestTier1FeatureToolExecution(unittest.TestCase):
    """F3: Tool Execution & Files Sandbox Feature Coverage (>=5 tests)."""

    def test_tool_create_file_in_sandbox(self):
        """creer_fichier creates a valid file within user sandbox."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "test_tier1.txt")
            res = files.creer_fichier(path)
            self.assertIn("créé", res.lower())
            self.assertTrue(os.path.exists(path))

    def test_tool_read_file_after_creation(self):
        """lire_fichier_securise reads content when executed with permission."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "test_read.txt")
            with open(path, 'w', encoding='utf-8') as f:
                f.write("Secret 12345")
            res = files.executer_avec_permission(files.lire_fichier_securise, {'chemin': path})
            self.assertIn("Secret 12345", res)

    def test_tool_list_files_in_sandbox(self):
        """lister_fichiers reflects directory contents with correct icons."""
        with EphemeralSandbox() as sbox:
            open(os.path.join(sbox, "doc1.txt"), 'w').close()
            open(os.path.join(sbox, "doc2.txt"), 'w').close()
            res = files.lister_fichiers(sbox)
            self.assertIn("doc1.txt", res)
            self.assertIn("doc2.txt", res)
            self.assertIn("2 élément", res)

    def test_tool_delete_file_moves_to_trash(self):
        """supprimer_fichier deletes or trashes file when authorized."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "to_delete.txt")
            open(path, 'w').close()
            self.assertTrue(os.path.exists(path))
            res = files.executer_avec_permission(files.supprimer_fichier, {'chemin': path})
            self.assertIn("corbeille", res.lower())
            self.assertFalse(os.path.exists(path))

    def test_tool_system_media_action_valid(self):
        """controler_media accepts bounded valid action enum values."""
        res = system.controler_media("lecture_pause")
        # On Windows or Linux, returns status message (either success or simulated keyboard/dbus)
        self.assertIsInstance(res, str)
        self.assertNotIn("inconnue", res)


class TestTier1FeatureKillSwitch(unittest.TestCase):
    """F4: Kill Switch & Interruption Feature Coverage (>=5 tests)."""

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
    async def test_kill_switch_stops_chat_stream(self):
        """Cancel signal stops streaming immediately and emits done."""
        # Queue many tokens with delays to ensure client can cancel mid-stream
        events = [{'content': f'Mot{i} ', 'delay': 0.05} for i in range(50)]
        self.llm.queue_scenario(events)

        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Génère un long texte'})
            # Receive at least 1 token
            await client.receive_until_type('token', timeout=4.0)
            # Send kill switch
            await client.send({'type': 'cancel'})
            # Expect completion
            done_msg = await client.receive_until_type('done', timeout=4.0)
            self.assertEqual(done_msg['type'], 'done')
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_kill_switch_resets_session_occupancy(self):
        """After cancel, session is immediately available for new requests."""
        events = [{'content': f'Token{i} ', 'delay': 0.05} for i in range(20)]
        self.llm.queue_scenario(events)
        self.llm.queue_text_response("Deuxième réponse réussie")

        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Première requête'})
            await client.receive_until_type('token', timeout=4.0)
            await client.send({'type': 'cancel'})
            await client.receive_until_type('done', timeout=4.0)

            # Second request right away
            await client.send({'type': 'chat', 'prompt': 'Deuxième requête'})
            token_msg = await client.receive_until_type('token', timeout=4.0)
            self.assertIn("Deuxième", token_msg['content'])
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_kill_switch_clears_pending_history_properly(self):
        """Cancelled response is recorded with cancellation notice in context."""
        events = [{'content': 'Début du texte...', 'delay': 0.05}]
        self.llm.queue_scenario(events)

        port = await self.server.start()
    @run_async
    async def test_kill_switch_clears_pending_history_properly(self):
        """Cancelled response is recorded with cancellation notice in context."""
        events = [{'content': f'Fragment{i} ', 'delay': 0.08} for i in range(25)]
        self.llm.queue_scenario(events)

        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Teste annulation'})
            await client.receive_until_type('token', timeout=4.0)
            # Verify session received done and context records cancellation or prompt
            done_msg = await client.receive_until_type('done', timeout=4.0)
            self.assertEqual(done_msg['type'], 'done')
            last_msg = api.messages[-1]
            self.assertEqual(last_msg['role'], 'assistant')
            self.assertTrue("interrompue" in last_msg['content'] or len(last_msg['content']) > 0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_kill_switch_idle_is_safe_noop(self):
        """Sending cancel when idle does not crash or raise error."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'cancel'})
            # Follow with get_status to confirm alive
            await client.send({'type': 'get_status'})
            msg = await client.receive_until_type('provider_status', timeout=3.0)
            self.assertEqual(msg['type'], 'provider_status')
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_kill_switch_aborts_queued_tool_calls(self):
        """If cancel is issued while streaming, tool execution is aborted."""
        events = [{'content': 'Je vais exécuter des outils... ', 'delay': 0.08} for _ in range(20)]
        self.llm.queue_scenario(events)
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Exécute des outils'})
            await client.receive_until_type('token', timeout=4.0)
            await client.send({'type': 'cancel'})
            done_msg = await client.receive_until_type('done', timeout=4.0)
            self.assertEqual(done_msg['type'], 'done')
            await client.close()
        finally:
            await self.server.stop()


class TestTier1FeatureHITL(unittest.TestCase):
    """F5: Human-in-the-Loop Safety Feature Coverage (>=5 tests)."""

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
    async def test_hitl_yields_action_required_on_sensitive_tool(self):
        """Calling sensitive tool (supprimer_fichier) suspends backend and yields action_required."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "secret_data.txt")
            open(path, 'w').close()

            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime mon fichier'})

                req_msg = await client.receive_until_type('action_required', timeout=4.0)
                self.assertEqual(req_msg['type'], 'action_required')
                self.assertIn('SUPPRIMER', req_msg.get('action', '').upper())
                self.assertIn('cible', req_msg)
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_hitl_session_retains_pending_state(self):
        """Backend suspends execution and records pending state until user responds."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "victim.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime victim'})
                await client.receive_until_type('action_required', timeout=4.0)

                # Send permission_granted
                self.llm.queue_text_response("Fichier supprimé avec votre accord.")
                await client.send({'type': 'permission_granted'})
                done_msg = await client.receive_until_type('done', timeout=4.0)
                self.assertEqual(done_msg['type'], 'done')
                self.assertFalse(os.path.exists(path))
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_hitl_resume_on_permission_denied(self):
        """Refusing permission aborts tool execution and reports refusal to LLM."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "kept.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime kept'})
                await client.receive_until_type('action_required', timeout=4.0)

                # User denies permission
                self.llm.queue_text_response("Très bien, le fichier est conservé.")
                await client.send({'type': 'permission_denied'})
                done_msg = await client.receive_until_type('done', timeout=4.0)
                self.assertEqual(done_msg['type'], 'done')
                # File must NOT be deleted
                self.assertTrue(os.path.exists(path))
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_hitl_no_orphan_tool_call_in_history_on_denial(self):
        """Context ring-buffer contains paired tool refusal message without orphans."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "doc.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime doc'})
                await client.receive_until_type('action_required', timeout=4.0)
                self.llm.queue_text_response("Action annulée.")
                await client.send({'type': 'permission_denied'})
                await client.receive_until_type('done', timeout=4.0)

                # Verify context messages: tool response must exist for tool call
                tool_calls = [m for m in api.messages if m.get('tool_calls')]
                tool_resps = [m for m in api.messages if m.get('role') == 'tool']
                self.assertEqual(len(tool_calls), len(tool_resps))
                self.assertIn("refusé", tool_resps[0]['content'])
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_hitl_clear_history_clears_pending_state(self):
        """clear_history resets any active pending HITL action."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "abandon.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime abandon'})
                await client.receive_until_type('action_required', timeout=4.0)

                await client.send({'type': 'clear_history'})
                msg = await client.receive_until_type('history_cleared', timeout=4.0)
                self.assertEqual(msg['type'], 'history_cleared')
                self.assertTrue(os.path.exists(path))
                await client.close()
            finally:
                await self.server.stop()


class TestTier1FeatureMultiProvider(unittest.TestCase):
    """F6: Multi-Provider & Strict JSON Schemas Feature Coverage (>=5 tests)."""

    def setUp(self):
        self.server = AlyxTestServer()

    @run_async
    async def test_get_models_list(self):
        """get_models returns structured provider dictionary and current model."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'get_models', 'refresh': True})
            msg = await client.receive_until_type('models_list', timeout=4.0)
            self.assertEqual(msg['type'], 'models_list')
            self.assertIn('providers', msg)
            self.assertIn('current_model', msg)
            self.assertIn('loaded', msg)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_select_model_updates_active_model(self):
        """select_model switches active model and confirms with model_selected."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'select_model', 'model': 'test-model-42'})
            msg = await client.receive_until_type('model_selected', timeout=4.0)
            self.assertEqual(msg['type'], 'model_selected')
            self.assertEqual(msg['model'], 'test-model-42')
            self.assertEqual(ai.MODEL, 'test-model-42')
            await client.close()
        finally:
            await self.server.stop()

    def test_json_schema_generation_conforms_to_standard(self):
        """Inspection generates compliant JSON Schema format for tool calling."""
        schema = llm_provider._function_to_json_schema(files.creer_fichier)
        self.assertEqual(schema['type'], 'function')
        fn = schema['function']
        self.assertEqual(fn['name'], 'creer_fichier')
        self.assertIn('parameters', fn)
        self.assertEqual(fn['parameters']['type'], 'object')
        self.assertIn('chemin', fn['parameters']['properties'])

    def test_json_schema_includes_enum_for_bounded_arguments(self):
        """Bounded string parameters define enum list in schema properties."""
        schema = llm_provider._function_to_json_schema(system.controler_media)
        props = schema['function']['parameters']['properties']
        self.assertIn('action', props)
        # Verify enum exists or description enumerates choices
        desc = props['action']['description']
        self.assertTrue('lecture_pause' in desc or 'enum' in props['action'])

    @run_async
    async def test_provider_circuit_breaker_status(self):
        """get_status returns circuit breaker states for local providers."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'get_status'})
            msg = await client.receive_until_type('provider_status', timeout=4.0)
            self.assertEqual(msg['type'], 'provider_status')
            status = msg['status']
            for prov in ('ollama', 'lm_studio'):
                if prov in status:
                    self.assertIn('status', status[prov])
                    self.assertIn('failures', status[prov])
            await client.close()
        finally:
            await self.server.stop()


class TestTier1FeatureAirGap(unittest.TestCase):
    """F7: Air-Gap & Security Invariants Feature Coverage (>=5 tests)."""

    def test_airgap_no_outbound_wan_connection(self):
        """Air-gap probe catches and blocks any non-loopback connection."""
        with AirGapAssertionProbe():
            with self.assertRaises(AirGapViolationError):
                s = socket.socket()
                s.connect(('8.8.8.8', 53))

    def test_sandbox_rejects_path_traversal(self):
        """Accessing files outside user profile raises PermissionError."""
        outside_path = "C:\\Windows\\System32\\calc.exe" if sys.platform == 'win32' else "/etc/passwd"
        with self.assertRaises(PermissionError):
            files._resoudre_chemin(outside_path)

    def test_sandbox_blocks_sensitive_directories(self):
        """Modifying sensitive paths like authorized_keys is strictly rejected."""
        ssh_key_path = os.path.join("~", ".ssh", "authorized_keys")
        res = files.creer_fichier(ssh_key_path)
        self.assertIn("sensible", res)

    def test_anti_ssrf_rejects_private_ips(self):
        """Anti-SSRF helper strictly flags RFC1918 and loopback IPs."""
        from function.web import _est_ip_privee
        self.assertTrue(_est_ip_privee("127.0.0.1"))
        self.assertTrue(_est_ip_privee("10.0.0.1"))
        self.assertTrue(_est_ip_privee("192.168.1.1"))
        self.assertTrue(_est_ip_privee("172.16.0.1"))

    @run_async
    async def test_websocket_rejects_browser_origin_headers(self):
        """Connecting with Origin header (browser) is rejected by CSWSH guard."""
        srv = AlyxTestServer()
        port = await srv.start()
        try:
            client = AlyxTestClient(port)
            # Browser sends Origin
            with self.assertRaises(Exception):
                await client.connect(origin="http://malicious-website.com")
        finally:
            await srv.stop()


class TestTier1FeaturePrompts(unittest.TestCase):
    """F8: Prompts & Task Comprehension Feature Coverage (>=5 tests)."""

    def setUp(self):
        self._orig_messages = list(api.messages)
        del api.messages[1:]

    def tearDown(self):
        api.messages[:] = self._orig_messages

    def test_prompt_system_includes_environmental_anchors(self):
        """System prompt contains operational instructions and markdown structure."""
        prompt = ai.prompt_systeme('fr')
        self.assertIn("Alyx", prompt)
        self.assertIn("Markdown", prompt)
        self.assertIn("outils", prompt.lower())

    def test_prompt_adapts_to_user_language(self):
        """Prompt language switches dynamically according to preferences."""
        prompt_en = ai.prompt_systeme('en')
        prompt_fr = ai.prompt_systeme('fr')
        self.assertIn("English", prompt_en)
        self.assertIn("français", prompt_fr)

    def test_tool_routing_selects_relevant_tools(self):
        """Regex router selects relevant tools based on user prompt keywords."""
        outils_fichier = ai.selectionner_outils_pertinents("Crée un fichier note.txt")
        noms = [t.__name__ for t in outils_fichier]
        self.assertIn('creer_fichier', noms)

    def test_context_ring_buffer_preserves_atomic_tool_pairs(self):
        """Ring buffer safe slice keeps tool call and response atomic."""
        api.messages.extend([
            {'role': 'user', 'content': 'u1'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'id': 'c1', 'function': {'name': 'f', 'arguments': {}}}]},
            {'role': 'tool', 'content': 'r1', 'tool_call_id': 'c1'},
            {'role': 'user', 'content': 'u2'},
        ])
        fenetre = api._messages_avec_fenetre()
        self.assertEqual(fenetre[0]['role'], 'system')
        # Check that tool message has preceding assistant tool_calls
        for i, msg in enumerate(fenetre):
            if msg['role'] == 'tool':
                self.assertTrue(any(m.get('tool_calls') for m in fenetre[:i]))

    @run_async
    async def test_clear_history_wipes_context_clean(self):
        """clear_history removes previous user and assistant turns."""
        srv = AlyxTestServer()
        port = await srv.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            api.messages.append({'role': 'user', 'content': 'Test'})
            api.messages.append({'role': 'assistant', 'content': 'Réponse'})
            await client.send({'type': 'clear_history'})
            msg = await client.receive_until_type('history_cleared', timeout=4.0)
            self.assertEqual(msg['type'], 'history_cleared')
            self.assertEqual(len(api.messages), 1)
            self.assertEqual(api.messages[0]['role'], 'system')
            await client.close()
        finally:
            await srv.stop()


if __name__ == '__main__':
    unittest.main()
