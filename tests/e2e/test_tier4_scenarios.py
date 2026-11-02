"""Tier 4: Real-World Application Scenarios (End-to-End Workflows).
Covers >= 5 realistic multi-step user interaction scenarios:
1. Scenario A: Morning Briefing & System Health Check
2. Scenario B: Daily Note-Taking & File Organization
3. Scenario C: Dangerous Action Safety Veto (HITL Protection)
4. Scenario D: Troubleshooting & Resource Resolution
5. Scenario E: Multilingual Focus Session under Air-Gap Invariant
"""
import asyncio
import datetime
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
    AirGapAssertionProbe,
    run_async,
)
import api
import ai
from core import system_monitor, preferences, llm_provider
from function import files, system


class TestTier4Scenarios(unittest.TestCase):
    """End-to-End Real-World Application Workflows."""

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
    async def test_scenario_a_morning_briefing_and_health_check(self):
        """Scenario A: User requests morning time check, system hardware snapshot, and process audit."""
        now = datetime.datetime.now()
        expected_time = now.strftime("%H:%M")

        # Step 1: User asks for time and date
        self.llm.queue_text_response(f"Bonjour ! Il est actuellement {expected_time}. Le système fonctionne normalement.")

        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()

            # 1. Ask time
            await client.send({'type': 'chat', 'prompt': 'Quelle heure est-il et quel jour sommes-nous ?'})
            messages1, done1 = await client.receive_all_until_type('done', timeout=4.0)
            text1 = "".join(m.get('content', '') for m in messages1 if m.get('type') == 'token')
            self.assertIn(expected_time, text1)

            # 2. Ask system hardware status
            snap = system_monitor.snapshot()
            self.assertIn('cpu', snap)
            self.assertIn('ram', snap)
            self.llm.queue_text_response(f"État du système : CPU à {snap['cpu']['percent']}%, RAM utilisée {snap['ram']['percent']}%.")

            await client.send({'type': 'chat', 'prompt': 'Comment se portent le processeur et la mémoire ?'})
            messages2, done2 = await client.receive_all_until_type('done', timeout=4.0)
            text2 = "".join(m.get('content', '') for m in messages2 if m.get('type') == 'token')
            self.assertIn("CPU", text2)
            self.assertIn("RAM", text2)

            # 3. Request active process list
            await client.send({'type': 'get_processes', 'limit': 10})
            procs_msg = await client.receive_until_type('processes', timeout=4.0)
            self.assertEqual(procs_msg['type'], 'processes')
            self.assertGreater(len(procs_msg['items']), 0)
            # Verify Alyx itself is identified
            self.assertTrue(any(p.get('alyx') for p in procs_msg['items']))

            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_scenario_b_daily_note_taking_and_file_management(self):
        """Scenario B: User creates meeting note, verifies content, and lists directory contents."""
        with EphemeralSandbox() as sbox:
            note_file = os.path.join(sbox, "reunion_projet.txt")

            # Step 1: Ask Alyx to create note
            self.llm.queue_tool_call('creer_fichier', {'chemin': note_file})
            self.llm.queue_text_response("Le fichier reunion_projet.txt a été créé avec succès.")

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()

                await client.send({'type': 'chat', 'prompt': 'Crée le fichier reunion_projet.txt'})
                messages1, done1 = await client.receive_all_until_type('done', timeout=4.0)
                self.assertTrue(os.path.exists(note_file))

                # Step 2: Write meeting notes with permission
                files.executer_avec_permission(
                    files.ecrire_fichier_securise,
                    {'chemin': note_file, 'contenu': "- Ordre du jour\n- Avancement tests E2E\n- Prochaine étape"}
                )

                # Step 3: Ask to read back the note
                self.llm.queue_tool_call('lire_fichier_securise', {'chemin': note_file})
                self.llm.queue_text_response("Voici le contenu de votre note de réunion.")

                await client.send({'type': 'chat', 'prompt': 'Affiche ma note de réunion'})
                req_msg = await client.receive_until_type('action_required', timeout=4.0)
                self.assertIn("LIRE", req_msg['action'].upper())

                # User grants read permission
                await client.send({'type': 'permission_granted'})
                messages2, done2 = await client.receive_all_until_type('done', timeout=4.0)

                # Step 4: List files in sandbox directory
                listing = files.lister_fichiers(sbox)
                self.assertIn("reunion_projet.txt", listing)

                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_scenario_c_dangerous_action_safety_veto(self):
        """Scenario C: User issues destructive deletion command; Alyx requests HITL confirmation; user vetos."""
        with EphemeralSandbox() as sbox:
            important_doc = os.path.join(sbox, "contrat_confidentiel.pdf")
            open(important_doc, 'w').close()

            # LLM initiates destructive action
            self.llm.queue_tool_call('supprimer_fichier', {'chemin': important_doc})
            self.llm.queue_text_response("Compris, la suppression a été annulée suite à votre refus.")

            port = await self.server.start()
            try:
                client = AlyxTestClient(port)
                await client.connect()

                # User asks to delete file
                await client.send({'type': 'chat', 'prompt': 'Supprime le contrat confidentiel'})

                # Backend intercepts and pauses execution
                req = await client.receive_until_type('action_required', timeout=4.0)
                self.assertIn("SUPPRIMER", req['action'].upper())
                self.assertEqual(req['cible'], os.path.abspath(important_doc))
                self.assertTrue(os.path.exists(important_doc))

                # Human-in-the-Loop VETO
                await client.send({'type': 'permission_denied'})

                messages, done = await client.receive_all_until_type('done', timeout=4.0)
                full_text = "".join(m.get('content', '') for m in messages if m.get('type') == 'token')
                self.assertIn("annulée", full_text)

                # Document MUST remain intact on disk
                self.assertTrue(os.path.exists(important_doc))

                await client.close()
            finally:
                await self.server.stop()

    @run_async
    async def test_scenario_d_troubleshooting_and_process_resolution(self):
        """Scenario D: User asks why machine is hot; Alyx audits processes and safely rejects killing protected PID."""
        port = await self.server.start()
        try:
            client = AlyxTestClient(port)
            await client.connect()

            # Step 1: User asks why computer is warm
            self.llm.queue_text_response("Vérification des processus consommateurs en cours...")
            await client.send({'type': 'chat', 'prompt': 'Pourquoi mon PC chauffe ?'})
            await client.receive_all_until_type('done', timeout=4.0)

            # Step 2: Query processes
            await client.send({'type': 'get_processes', 'limit': 5})
            procs = await client.receive_until_type('processes', timeout=4.0)
            self.assertGreater(len(procs['items']), 0)
            top_proc = procs['items'][0]
            self.assertIn('name', top_proc)
            self.assertIn('cpu', top_proc)

            # Step 3: Attempt to kill protected PID (Alyx process itself)
            await client.send({'type': 'kill_process', 'pid': os.getpid()})
            kill_res = await client.receive_until_type('process_killed', timeout=4.0)
            self.assertFalse(kill_res['ok'])
            self.assertIn("protégé", kill_res['message'])

            await client.close()
        finally:
            await self.server.stop()

    @run_async
    async def test_scenario_e_multilingual_focus_session_under_airgap(self):
        """Scenario E: User switches language to English, works with Alyx, under strict Air-Gap verification."""
        orig_prefs = preferences.charger()
        try:
            with AirGapAssertionProbe():
                port = await self.server.start()
                try:
                    client = AlyxTestClient(port)
                    await client.connect()

                    # Step 1: Switch language preference to English
                    await client.send({
                        'type': 'set_voice_settings',
                        'language': 'en',
                        'rate': 0,
                        'volume': 100,
                        'speak_all': False
                    })
                    voice_msg = await client.receive_until_type('voice_settings', timeout=4.0)
                    self.assertEqual(voice_msg['prefs']['language'], 'en')

                    # Step 2: System prompt now provides English instructions
                    prompt_en = ai.prompt_systeme('en')
                    self.assertIn("English", prompt_en)

                    # Step 3: English interaction
                    self.llm.queue_text_response("Everything is running smoothly and 100% offline.")
                    await client.send({'type': 'chat', 'prompt': 'Status report please'})
                    messages, done = await client.receive_all_until_type('done', timeout=4.0)
                    text = "".join(m.get('content', '') for m in messages if m.get('type') == 'token')
                    self.assertIn("running", text)

                    # Step 4: Verify provider status
                    await client.send({'type': 'get_status'})
                    status_msg = await client.receive_until_type('provider_status', timeout=4.0)
                    self.assertEqual(status_msg['type'], 'provider_status')

                    await client.close()
                finally:
                    await self.server.stop()
        finally:
            preferences.mettre_a_jour(orig_prefs)


if __name__ == '__main__':
    unittest.main()
