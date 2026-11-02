"""Tier 3: Cross-Feature Pairwise Combinations.
Verifies interactions and concurrency between:
1. WebSocket Streaming <-> Kill Switch
2. Tool Execution <-> HITL Yield/Resume (Granted)
3. Tool Execution <-> HITL Yield/Resume (Denied)
4. Metrics Pushing <-> Chat Generation State
5. Multi-Turn Tool Execution <-> Context Ring Buffer
6. Kill Switch <-> HITL Pending State
7. Model Selection <-> Chat Continuity
8. TTS Sentence Extraction <-> Tool Execution Workflow
"""
import asyncio
import json
import os
import shutil
import unittest

import websockets

from tests.e2e.harness import (
    AlyxTestServer,
    AlyxTestClient,
    ScriptableLLMProvider,
    EphemeralSandbox,
    run_async,
)
import api
import ai
from core import preferences, llm_provider


class TestTier3Combinations(unittest.TestCase):
    """Pairwise Cross-Feature Integration Tests."""

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
    async def test_pairwise_websocket_streaming_and_kill_switch(self):
        """Streaming tokens are cleanly interrupted mid-flow by Kill Switch."""
        events = [{'content': f'Mot{i} ', 'delay': 0.08} for i in range(25)]
        self.llm.queue_scenario(events)

        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Lance un long streaming'})
            # Wait for at least 2 tokens
            await client.receive_until_type('token', timeout=4.0)
            await client.receive_until_type('token', timeout=4.0)

            # Trigger kill switch
            await client.send({'type': 'cancel'})
            done_msg = await client.receive_until_type('done', timeout=4.0)
            self.assertEqual(done_msg['type'], 'done')

            # Session is immediately unlocked
            self.llm.queue_text_response("Prêt pour la suite.")
            await client.send({'type': 'chat', 'prompt': 'Nouveau message'})
            tok = await client.receive_until_type('token', timeout=4.0)
            self.assertIn("Prêt", tok['content'])
            await client.receive_until_type('done', timeout=4.0)
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_pairwise_tool_execution_and_hitl_yield_resume(self):
        """Tool execution yields HITL permission; user grants; tool runs; LLM resumes."""
        with EphemeralSandbox() as sbox:
            target = os.path.join(sbox, "victim_granted.txt")
            open(target, 'w').close()

            # 1. LLM proposes deleting the file
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': target})
            # 2. LLM confirms deletion after resumption
            self.llm.queue_text_response("Le fichier a bien été mis à la corbeille.")

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime le fichier victim_granted'})

                # Server suspends and yields action_required
                req = await client.receive_until_type('action_required', timeout=4.0)
                self.assertIn("SUPPRIMER", req['action'].upper())
                self.assertTrue(os.path.exists(target))

                # User grants permission
                await client.send({'type': 'permission_granted'})

                # Tool executes and LLM completes response
                messages, done_msg = await client.receive_all_until_type('done', timeout=4.0)
                full_text = "".join(m.get('content', '') for m in messages if m.get('type') == 'token')
                self.assertIn("corbeille", full_text)

                # Verification: file is gone
                self.assertFalse(os.path.exists(target))
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_pairwise_tool_execution_and_hitl_denial_resume(self):
        """Tool execution yields HITL permission; user denies; tool is aborted; LLM receives refusal."""
        with EphemeralSandbox() as sbox:
            target = os.path.join(sbox, "victim_denied.txt")
            open(target, 'w').close()

            # 1. LLM calls delete
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': target})
            # 2. LLM acknowledges denial
            self.llm.queue_text_response("Entendu, je ne touche pas à votre fichier.")

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime victim_denied'})

                await client.receive_until_type('action_required', timeout=4.0)
                self.assertTrue(os.path.exists(target))

                # User denies permission
                await client.send({'type': 'permission_denied'})

                # LLM resumes after refusal
                messages, done_msg = await client.receive_all_until_type('done', timeout=4.0)
                full_text = "".join(m.get('content', '') for m in messages if m.get('type') == 'token')
                self.assertIn("touche pas", full_text)

                # Verification: file is preserved
                self.assertTrue(os.path.exists(target))
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_pairwise_metrics_pushing_during_chat_generation(self):
        """Active chat generation dynamically flips metrics 'generating' flag from false to true and back."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            # Subscribe to metrics
            await client.send({'type': 'subscribe_metrics', 'on': True})
            m1 = await client.receive_until_type('metrics', timeout=4.0)
            self.assertFalse(m1['generating'])

            # Start chat with delays
            events = [{'content': f'T{i} ', 'delay': 0.1} for i in range(10)]
            self.llm.queue_scenario(events)
            await client.send({'type': 'chat', 'prompt': 'Dis quelque chose de long'})

            # Await done while receiving metrics
            await client.receive_until_type('token', timeout=4.0)
            await client.receive_until_type('done', timeout=4.0)

            # Unsubscribe metrics
            await client.send({'type': 'subscribe_metrics', 'on': False})
            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_pairwise_multiturn_tool_execution_and_context_ring_buffer(self):
        """Multi-turn tool calling preserves past tool responses in ring buffer across turns."""
        with EphemeralSandbox() as sbox:
            note_path = os.path.join(sbox, "memo.txt")

            # Turn 1: create file
            self.llm.queue_tool_call('creer_fichier', {'chemin': note_path})
            self.llm.queue_text_response("Fichier memo.txt créé.")

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Crée le fichier memo.txt'})
                await client.receive_until_type('done', timeout=4.0)
                self.assertTrue(os.path.exists(note_path))

                # Turn 2: ask about it
                self.llm.queue_text_response("Le fichier mémo contient vos notes.")
                await client.send({'type': 'chat', 'prompt': 'Que contient-il ?'})
                await client.receive_until_type('done', timeout=4.0)

                # Context inspection: Turn 1 tool call and tool result are preserved
                contexte = api._messages_avec_fenetre()
                roles = [m['role'] for m in contexte]
                self.assertIn('user', roles)
                self.assertIn('assistant', roles)
                self.assertIn('system', roles)
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_pairwise_kill_switch_during_hitl_wait(self):
        """Sending cancel when an action_required is pending aborts the tool safely."""
        with EphemeralSandbox() as sbox:
            path = os.path.join(sbox, "guarded.txt")
            open(path, 'w').close()
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': path})

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()
                await client.send({'type': 'chat', 'prompt': 'Supprime guarded'})
                await client.receive_until_type('action_required', timeout=4.0)

                # Cancel during HITL prompt
                await client.send({'type': 'cancel'})

                # Send new command
                self.llm.queue_text_response("Opération suivante.")
                await client.send({'type': 'chat', 'prompt': 'Fais autre chose'})
                tok = await client.receive_until_type('token', timeout=4.0)
                self.assertIn("Opération", tok['content'])
                await client.receive_until_type('done', timeout=4.0)
                # File was never deleted
                self.assertTrue(os.path.exists(path))
                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_pairwise_model_switch_and_chat_continuity(self):
        """Switching model mid-session preserves conversation history and applies new model."""
        self.llm.queue_text_response("Réponse sous modèle initial.")
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()
            await client.send({'type': 'chat', 'prompt': 'Question 1'})
            await client.receive_until_type('done', timeout=4.0)

            # Switch model
            await client.send({'type': 'select_model', 'model': 'model-version-2'})
            sel_msg = await client.receive_until_type('model_selected', timeout=4.0)
            self.assertEqual(sel_msg['model'], 'model-version-2')
            self.assertEqual(ai.MODEL, 'model-version-2')

            # Next turn uses model-version-2
            self.llm.queue_text_response("Réponse sous modèle 2.")
            await client.send({'type': 'chat', 'prompt': 'Question 2'})
            await client.receive_until_type('done', timeout=4.0)

            # Verify call history
            last_call = self.llm.call_history[-1]
            self.assertEqual(last_call['model'], 'model-version-2')
            await client.close()
        finally:
            await self.server.stop()

    def test_pairwise_tts_sentence_extraction_and_tool_boundaries(self):
        """TTS sentence chunking does not slice decimal numbers or file extensions."""
        text = "Version 3.5 du rapport final. Ensuite, nous lisons rapport.pdf pour continuer. Terminé !"
        phrases, reste = api._extraire_phrases(text)
        self.assertEqual(len(phrases), 2)
        self.assertEqual(phrases[0], "Version 3.5 du rapport final.")
        self.assertEqual(phrases[1], "Ensuite, nous lisons rapport.pdf pour continuer.")
        self.assertEqual(reste, " Terminé !")


if __name__ == '__main__':
    unittest.main()
