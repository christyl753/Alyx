"""Test Harness and Fixtures for Alyx E2E Opaque-Box Testing."""
import asyncio
import functools
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import websockets

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import api
import ai
from core import llm_provider, preferences


class AirGapViolationError(AssertionError):
    """Raised when an outbound WAN network connection is attempted in air-gap mode."""
    pass


class AirGapAssertionProbe:
    """Context manager intercepting socket.connect to enforce 100% offline air-gap."""
    def __init__(self, allowed_hosts: Optional[List[str]] = None):
        self.allowed_hosts = set(allowed_hosts or ['127.0.0.1', 'localhost', '::1'])
        self._orig_connect = socket.socket.connect

    def __enter__(self):
        probe = self

        def guarded_connect(sock_self, address):
            host = address[0] if isinstance(address, tuple) and len(address) > 0 else address
            if isinstance(host, str):
                cleaned_host = host.lower().strip()
                if cleaned_host not in probe.allowed_hosts and not cleaned_host.startswith('127.'):
                    raise AirGapViolationError(
                        f"Air-gap violation detected: attempt to connect to external target '{address}' (allowed: loopback only)."
                    )
            return probe._orig_connect(sock_self, address)

        socket.socket.connect = guarded_connect
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        socket.socket.connect = self._orig_connect


class EphemeralSandbox:
    """Creates a temporary, safe directory in user home conforming to Alyx sandbox rules."""
    def __init__(self, prefix: str = "alyx_e2e_"):
        self.home = os.path.expanduser("~")
        self.prefix = prefix
        self.path: Optional[str] = None

    def __enter__(self) -> str:
        self.path = tempfile.mkdtemp(prefix=self.prefix, dir=self.home)
        return self.path

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.path and os.path.exists(self.path):
            shutil.rmtree(self.path, ignore_errors=True)


class ScriptableLLMProvider:
    """
    Mock LLM provider enabling deterministic scripted token streams,
    tool calls, stats, and deliberate error injections.
    """
    def __init__(self):
        self.scenarios: List[List[Dict[str, Any]]] = []
        self.call_history: List[Dict[str, Any]] = []
        self._lock = threading.Lock()
        self._orig_api_stream = getattr(api, 'stream_chat', None)
        self._orig_core_stream = getattr(llm_provider, 'stream_chat', None)

    def queue_scenario(self, events: List[Dict[str, Any]]):
        """Queue a list of events to be yielded by the next stream_chat call."""
        with self._lock:
            self.scenarios.append(events)

    def queue_text_response(self, text: str, chunk_size: int = 15):
        """Convenience method to queue streaming tokens for a plain text response."""
        events = []
        for i in range(0, len(text), chunk_size):
            events.append({'content': text[i:i + chunk_size]})
        events.append({'stats': {'tps': 45.0}})
        self.queue_scenario(events)

    def queue_tool_call(self, tool_name: str, arguments: Dict[str, Any], call_id: str = "call_e2e_1"):
        """Convenience method to queue a tool call event."""
        events = [
            {
                'tool_calls': [
                    {
                        'id': call_id,
                        'type': 'function',
                        'function': {
                            'name': tool_name,
                            'arguments': arguments
                        }
                    }
                ]
            }
        ]
        self.queue_scenario(events)

    def _mock_stream_chat(self, model, contexte, tools=None, enregistrer_fermeture=None):
        with self._lock:
            self.call_history.append({
                'model': model,
                'contexte': list(contexte),
                'tools': tools,
                'timestamp': time.time()
            })
            if self.scenarios:
                events = self.scenarios.pop(0)
            else:
                events = [{'content': 'Réponse E2E par défaut.'}, {'stats': {'tps': 30.0}}]

        def generator():
            for ev in events:
                if 'delay' in ev:
                    time.sleep(ev['delay'])
                if 'error' in ev:
                    raise ev['error']
                yield ev

        return generator()

    def start(self):
        self._orig_model = getattr(ai, 'MODEL', 'Aucun modèle')
        ai.MODEL = 'test-e2e-model'
        api.stream_chat = self._mock_stream_chat
        llm_provider.stream_chat = self._mock_stream_chat

    def stop(self):
        if hasattr(self, '_orig_model'):
            ai.MODEL = self._orig_model
        if self._orig_api_stream:
            api.stream_chat = self._orig_api_stream
        if self._orig_core_stream:
            llm_provider.stream_chat = self._orig_core_stream


class AlyxTestClient:
    """Asynchronous WebSocket client mirroring Frontend BackendClient."""
    def __init__(self, port: int):
        self.port = port
        self.uri = f"ws://127.0.0.1:{port}"
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.received_messages: List[Dict[str, Any]] = []

    async def connect(self, origin: Optional[str] = None):
        kwargs = {}
        if origin is not None:
            kwargs['origin'] = origin
        self.ws = await websockets.connect(self.uri, **kwargs)

    async def send(self, payload: Dict[str, Any]):
        if not self.ws:
            raise RuntimeError("Client is not connected.")
        await self.ws.send(json.dumps(payload))

    async def receive(self, timeout: float = 3.0) -> Dict[str, Any]:
        if not self.ws:
            raise RuntimeError("Client is not connected.")
        raw = await asyncio.wait_for(self.ws.recv(), timeout)
        data = json.loads(raw)
        self.received_messages.append(data)
        return data

    async def receive_until_type(self, expected_type: str, timeout: float = 5.0) -> Dict[str, Any]:
        start = time.time()
        while time.time() - start < timeout:
            rem = timeout - (time.time() - start)
            if rem <= 0:
                break
            msg = await self.receive(timeout=rem)
            if msg.get('type') == expected_type:
                return msg
        raise TimeoutError(f"Did not receive message of type '{expected_type}' within {timeout}s.")

    async def receive_all_until_type(self, terminal_type: str, timeout: float = 5.0) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        messages = []
        start = time.time()
        while time.time() - start < timeout:
            rem = timeout - (time.time() - start)
            if rem <= 0:
                break
            msg = await self.receive(timeout=rem)
            messages.append(msg)
            if msg.get('type') == terminal_type:
                return messages, msg
        raise TimeoutError(f"Did not receive terminal message of type '{terminal_type}' within {timeout}s.")

    async def close(self):
        if self.ws:
            await self.ws.close()
            self.ws = None


class AlyxTestServer:
    """Starts an in-process, ephemeral WebSocket server on loopback port 0."""
    def __init__(self):
        self.server = None
        self.port: Optional[int] = None

    async def start(self) -> int:
        self.server = await websockets.serve(
            api.handler_client,
            "127.0.0.1",
            0,
            origins=[None]
        )
        self.port = self.server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            self.server = None


def run_async(coro_fn):
    """Decorator to run an async test inside a clean asyncio loop with timeout."""
    @functools.wraps(coro_fn)
    def wrapper(*args, **kwargs):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(asyncio.wait_for(coro_fn(*args, **kwargs), timeout=15.0))
        finally:
            # Cancel all remaining tasks and close loop
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()
            asyncio.set_event_loop(None)
    return wrapper
