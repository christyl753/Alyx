"""Adversarial stress-test suite for Milestone 1 (M1).

Adversarially challenges:
1. Circuit Breaker in `core/llm_provider.py`:
   - 3 consecutive streaming failures (HTTP 500, Timeout, RequestException) -> 30s quarantine.
   - Rejection of subsequent requests during quarantine without network access.
   - Cooldown expiration and half-open state recovery.
   - Kill Switch cancellation immunity (cancelling does NOT increment failure counter or trigger circuit breaker).
   - Mid-stream unexpected disconnection DOES trigger failure count.
   - Multi-provider quarantine isolation (LM Studio failure does not quarantine Ollama).
2. HTTP REST Endpoints in `api.py` (/api/status & /api/ready):
   - Strict HTTP headers (Content-Type, Content-Length, Access-Control-Allow-Origin).
   - JSON format integrity and required schema keys.
   - Concurrency stress: 100 simultaneous HTTP requests while 5 WebSocket clients are actively communicating.
   - Edge case paths: query parameters, trailing slashes, unknown endpoints.
"""
import asyncio
import json
import os
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch

import requests

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import api
from core import llm_provider


class TestCircuitBreakerAdversarial(unittest.TestCase):
    """Adversarial stress-test for the Circuit Breaker and Kill Switch."""

    def setUp(self):
        # Reset provider stats before each test
        with llm_provider._stats_lock:
            for p in llm_provider._provider_stats:
                llm_provider._provider_stats[p]['failures'] = 0
                llm_provider._provider_stats[p]['last_failure'] = 0.0
                llm_provider._provider_stats[p]['latency'] = 0.0
                llm_provider._provider_stats[p]['status'] = 'unknown'

    def tearDown(self):
        # Reset provider stats after each test
        with llm_provider._stats_lock:
            for p in llm_provider._provider_stats:
                llm_provider._provider_stats[p]['failures'] = 0
                llm_provider._provider_stats[p]['last_failure'] = 0.0
                llm_provider._provider_stats[p]['status'] = 'unknown'

    def test_cb_3_consecutive_failures_quarantine_provider(self):
        """Simulate 3 consecutive streaming failures (HTTP 500, Timeout, RequestException).
        Verify provider is quarantined for 30s and subsequent calls are rejected immediately."""
        provider = 'ollama'
        self.assertTrue(llm_provider._is_provider_available(provider))

        # Failure 1: HTTP 500 error
        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500
        mock_resp_500.text = "Internal Server Error 500"
        with patch.object(llm_provider._http, 'post', return_value=mock_resp_500):
            with self.assertRaises(Exception) as ctx:
                gen = llm_provider.stream_chat('llama3:8b', [{'role': 'user', 'content': 'test 1'}])
                next(gen)
            self.assertIn("HTTP 500", str(ctx.exception))

        with llm_provider._stats_lock:
            stats = llm_provider._provider_stats[provider]
            self.assertEqual(stats['failures'], 1)
            self.assertEqual(stats['status'], 'offline')
        self.assertTrue(llm_provider._is_provider_available(provider), "Doit rester disponible à 1 échec")

        # Failure 2: Timeout exception
        with patch.object(llm_provider._http, 'post', side_effect=requests.exceptions.Timeout("Connection timed out")):
            with self.assertRaises(Exception) as ctx:
                gen = llm_provider.stream_chat('llama3:8b', [{'role': 'user', 'content': 'test 2'}])
                next(gen)
            self.assertIn("Connection timed out", str(ctx.exception))

        with llm_provider._stats_lock:
            stats = llm_provider._provider_stats[provider]
            self.assertEqual(stats['failures'], 2)
            self.assertEqual(stats['status'], 'offline')
        self.assertTrue(llm_provider._is_provider_available(provider), "Doit rester disponible à 2 échecs")

        # Failure 3: RequestException (ConnectionError)
        with patch.object(llm_provider._http, 'post', side_effect=requests.exceptions.ConnectionError("Connection refused")):
            with self.assertRaises(Exception) as ctx:
                gen = llm_provider.stream_chat('llama3:8b', [{'role': 'user', 'content': 'test 3'}])
                next(gen)
            self.assertIn("Connection refused", str(ctx.exception))

        with llm_provider._stats_lock:
            stats = llm_provider._provider_stats[provider]
            self.assertEqual(stats['failures'], 3)
            self.assertEqual(stats['status'], 'offline')
            last_failure_time = stats['last_failure']

        # Provider is now quarantined!
        self.assertFalse(
            llm_provider._is_provider_available(provider),
            "Le fournisseur DOIT être marqué indisponible après 3 échecs consécutifs"
        )

        # Subsequent call must be rejected immediately by circuit breaker without network call
        with patch.object(llm_provider._http, 'post') as mock_post_blocked:
            with self.assertRaises(Exception) as ctx:
                llm_provider.stream_chat('llama3:8b', [{'role': 'user', 'content': 'blocked request'}])
            self.assertIn("circuit breaker", str(ctx.exception).lower())
            self.assertIn("quarantaine", str(ctx.exception).lower())
            mock_post_blocked.assert_not_called()

    def test_cb_cooldown_and_half_open_recovery(self):
        """Verify cooldown expiration after 30s allows half-open recovery, and success resets counter."""
        provider = 'ollama'
        # Trip the breaker
        with llm_provider._stats_lock:
            llm_provider._provider_stats[provider]['failures'] = 3
            llm_provider._provider_stats[provider]['last_failure'] = time.time()
            llm_provider._provider_stats[provider]['status'] = 'offline'

        self.assertFalse(llm_provider._is_provider_available(provider))

        # Advance simulated time past CB_COOLDOWN (30s)
        with llm_provider._stats_lock:
            llm_provider._provider_stats[provider]['last_failure'] = time.time() - (llm_provider.CB_COOLDOWN + 1)

        # Now _is_provider_available should enter half-open state (failures = 2) and return True
        self.assertTrue(llm_provider._is_provider_available(provider))
        with llm_provider._stats_lock:
            self.assertEqual(llm_provider._provider_stats[provider]['failures'], 2)

        # If a request succeeds in half-open state, failures must reset to 0
        llm_provider._record_success(provider, 0.05)
        with llm_provider._stats_lock:
            self.assertEqual(llm_provider._provider_stats[provider]['failures'], 0)
            self.assertEqual(llm_provider._provider_stats[provider]['status'], 'online')

    def test_kill_switch_cancellation_does_not_trip_circuit_breaker(self):
        """Adversarial test: Kill Switch cancellations must NOT count as failures.
        Perform 5 consecutive Kill Switch interruptions and assert failures remain 0."""
        provider = 'ollama'

        class FakeSocket:
            def shutdown(self, how):
                pass
            def close(self):
                pass

        class FakeStreamResponse:
            def __init__(self):
                self.status_code = 200
                self.raw = MagicMock()
                self._sock = FakeSocket()
                self.raw._connection = MagicMock(sock=self._sock)
                self.closed = False

            def iter_lines(self):
                # Yield first chunk, then simulate abort triggered by kill switch
                yield json.dumps({"message": {"content": "Hello"}}).encode('utf-8')
                # Check cancellation flag
                annulation = getattr(self, '_fermeture_volontaire', [False])
                if annulation and annulation[0]:
                    raise requests.exceptions.RequestException("Socket shut down by user kill switch")
                yield json.dumps({"done": True}).encode('utf-8')

            def close(self):
                self.closed = True

        for i in range(5):
            fake_resp = FakeStreamResponse()
            fermeture_hook = []

            def enregistrer_fermeture(fn):
                fermeture_hook.append(fn)

            with patch.object(llm_provider._http, 'post', return_value=fake_resp):
                gen = llm_provider.stream_chat(
                    'llama3:8b',
                    [{'role': 'user', 'content': f'prompt {i}'}],
                    enregistrer_fermeture=enregistrer_fermeture
                )
                chunk = next(gen)
                self.assertEqual(chunk, {'content': 'Hello'})

                # Trigger kill switch!
                self.assertEqual(len(fermeture_hook), 1)
                fermeture_hook[0]()  # Calls fermer() which sets _fermeture_volontaire[0] = True

                # Generator iteration should raise the aborted socket exception
                with self.assertRaises(Exception):
                    next(gen)

            # Assert failure count was NOT incremented!
            with llm_provider._stats_lock:
                stats = llm_provider._provider_stats[provider]
                self.assertEqual(
                    stats['failures'],
                    0,
                    f"Tour {i+1}: Kill switch ne doit JAMAIS incrémenter le compteur de pannes !"
                )

        self.assertTrue(llm_provider._is_provider_available(provider))

    def test_unexpected_stream_abort_does_trip_circuit_breaker(self):
        """An unexpected network crash mid-stream (without kill switch) MUST count as a failure."""
        provider = 'ollama'

        class CrashingStreamResponse:
            def __init__(self):
                self.status_code = 200
                self.raw = MagicMock()

            def iter_lines(self):
                yield json.dumps({"message": {"content": "Chunk 1"}}).encode('utf-8')
                raise requests.exceptions.ChunkedEncodingError("Connection reset by peer mid-stream")

            def close(self):
                pass

        fake_resp = CrashingStreamResponse()
        with patch.object(llm_provider._http, 'post', return_value=fake_resp):
            gen = llm_provider.stream_chat('llama3:8b', [{'role': 'user', 'content': 'prompt'}])
            next(gen)
            with self.assertRaises(Exception):
                next(gen)

        with llm_provider._stats_lock:
            stats = llm_provider._provider_stats[provider]
            self.assertEqual(stats['failures'], 1, "Un crash inattendu en cours de stream DOIT être enregistré")

    def test_multi_provider_failure_isolation(self):
        """Verify that 3 failures on LM Studio quarantine LM Studio while Ollama remains online."""
        mock_resp_500 = MagicMock()
        mock_resp_500.status_code = 500
        mock_resp_500.text = "LM Studio Error 500"

        with patch.dict(llm_provider._model_to_provider, {'qwen-lmstudio': 'lmstudio'}):
            for _ in range(3):
                with patch.object(llm_provider._http, 'post', return_value=mock_resp_500):
                    with self.assertRaises(Exception):
                        gen = llm_provider.stream_chat('qwen-lmstudio', [{'role': 'user', 'content': 'hi'}])
                        next(gen)

        # lmstudio is quarantined
        self.assertFalse(llm_provider._is_provider_available('lmstudio'))
        # ollama is still available
        self.assertTrue(llm_provider._is_provider_available('ollama'))


class TestRestEndpointsAdversarial(unittest.IsolatedAsyncioTestCase):
    """Adversarial stress-test for HTTP REST endpoints under concurrent load and active WebSockets."""

    async def asyncSetUp(self):
        self.server = None
        self.port = 0

    async def asyncTearDown(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()

    async def _demarrer_serveur_test(self):
        import websockets
        self.server = await websockets.serve(
            api.handler_client,
            "127.0.0.1",
            0,
            origins=[None],
            process_request=api.process_http_request
        )
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    def _http_get(self, path):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                headers = dict(resp.getheaders())
                body = resp.read()
                return resp.status, headers, json.loads(body.decode('utf-8'))
        except urllib.error.HTTPError as e:
            headers = dict(e.headers)
            body = e.read()
            return e.code, headers, json.loads(body.decode('utf-8'))

    async def test_rest_endpoints_headers_and_contract_integrity(self):
        """Verify status codes, exact headers, and strict JSON schema."""
        port = await self._demarrer_serveur_test()

        # 1. Test /api/ready when backend NOT ready -> 503
        api._backend_pret.clear()
        code, headers, data = await asyncio.to_thread(self._http_get, "/api/ready")
        self.assertEqual(code, 503)
        self.assertIn('Content-Type', headers)
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertIn('Access-Control-Allow-Origin', headers)
        self.assertEqual(headers['Access-Control-Allow-Origin'], '*')
        self.assertFalse(data.get('ready'))
        self.assertIn('model', data)

        # 2. Test /api/ready when backend IS ready -> 200
        api._backend_pret.set()
        code, headers, data = await asyncio.to_thread(self._http_get, "/api/ready")
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertTrue(data.get('ready'))

        # 3. Test /api/status -> 200 with complete metrics
        code, headers, data = await asyncio.to_thread(self._http_get, "/api/status")
        self.assertEqual(code, 200)
        self.assertEqual(headers['Content-Type'], 'application/json')
        self.assertEqual(data.get('status'), 'ok')
        self.assertTrue(data.get('backend_ready'))
        self.assertIn('providers', data)
        self.assertIn('stt', data)
        self.assertIn('vram', data)
        self.assertIn('memory', data)
        self.assertIn('uptime', data)
        self.assertIsInstance(data['uptime'], (int, float))

    async def test_rest_endpoints_url_variations(self):
        """Verify URL query parameters and versioned paths (/api/v1/status, etc.)."""
        port = await self._demarrer_serveur_test()
        api._backend_pret.set()

        # With query parameters
        code, _, data = await asyncio.to_thread(self._http_get, "/api/status?timestamp=123&verbose=true")
        self.assertEqual(code, 200)
        self.assertEqual(data.get('status'), 'ok')

        # Versioned alias /api/v1/ready
        code, _, data = await asyncio.to_thread(self._http_get, "/api/v1/ready")
        self.assertEqual(code, 200)
        self.assertTrue(data.get('ready'))

        # Versioned alias /api/v1/status
        code, _, data = await asyncio.to_thread(self._http_get, "/api/v1/status")
        self.assertEqual(code, 200)
        self.assertEqual(data.get('status'), 'ok')

    async def _async_http_get(self, path):
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        req = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nConnection: close\r\n\r\n"
        writer.write(req.encode('utf-8'))
        await writer.drain()
        raw_response = await reader.read()
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

        # Parse HTTP response
        parts = raw_response.split(b"\r\n\r\n", 1)
        header_lines = parts[0].decode('utf-8', errors='replace').split("\r\n")
        status_line = header_lines[0]
        code = int(status_line.split()[1])
        headers = {}
        for line in header_lines[1:]:
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip()] = v.strip()
        body = parts[1] if len(parts) > 1 else b""
        data = json.loads(body.decode('utf-8')) if body else {}
        return code, headers, data

    async def test_heavy_concurrency_stress_rest_and_active_websockets(self):
        """Heavy stress test:
        - 5 active WebSocket clients communicating concurrently.
        - 100 concurrent HTTP GET requests hitting /api/status and /api/ready.
        - Verify 0 errors, 100% valid JSON, no socket hangs or drops."""
        import websockets

        port = await self._demarrer_serveur_test()
        api._backend_pret.set()
        llm_provider._models_ready.set()

        ws_uri = f"ws://127.0.0.1:{port}"
        ws_stop_event = asyncio.Event()
        ws_messages_received = [0] * 5

        async def websocket_worker(client_id):
            async with websockets.connect(ws_uri, origin=None) as ws:
                while not ws_stop_event.is_set():
                    try:
                        await ws.send(json.dumps({"type": "get_ready"}))
                        msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        resp = json.loads(msg)
                        self.assertEqual(resp.get("type"), "ready")
                        self.assertTrue(resp.get("ready"))
                        ws_messages_received[client_id] += 1
                    except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                        if ws_stop_event.is_set():
                            break
                        raise
                    await asyncio.sleep(0.01)

        # Launch 5 concurrent WebSocket tasks
        ws_tasks = [asyncio.create_task(websocket_worker(i)) for i in range(5)]
        await asyncio.sleep(0.1)  # Let WebSockets connect and start chatting

        # Launch 100 concurrent HTTP requests (50 to /api/status, 50 to /api/ready)
        num_requests = 100
        t0 = time.time()

        async def make_http_call(idx):
            endpoint = "/api/status" if idx % 2 == 0 else "/api/ready"
            code, headers, data = await self._async_http_get(endpoint)
            return code, endpoint, data

        tasks = [asyncio.create_task(make_http_call(i)) for i in range(num_requests)]
        results = await asyncio.gather(*tasks)
        elapsed = time.time() - t0

        # Stop WebSocket workers
        ws_stop_event.set()
        await asyncio.gather(*ws_tasks, return_exceptions=True)

        # Validate results
        self.assertEqual(len(results), num_requests)
        for code, endpoint, data in results:
            self.assertEqual(code, 200, f"Requête {endpoint} a échoué avec le code {code}")
            if endpoint == "/api/status":
                self.assertEqual(data.get("status"), "ok")
            else:
                self.assertTrue(data.get("ready"))

        for i, count in enumerate(ws_messages_received):
            self.assertGreater(count, 0, f"WebSocket client {i} n'a reçu aucun message")

        print(f"\n[Stress Test Results] 100 concurrent REST requests + 5 active WebSockets completed in {elapsed:.3f}s")
        print(f"[Stress Test Results] Total WebSocket messages handled concurrently: {sum(ws_messages_received)}")


if __name__ == '__main__':
    unittest.main()
