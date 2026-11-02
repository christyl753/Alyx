"""Suite de tests de résistance et de validation empirique (Milestone 2 - Challenger).

Adversarially challenge and stress-test:
1. LLM provider concurrency semaphores under race/burst conditions, cancellation, and exceptions.
2. Disk space exhaustion boundaries in stt_server and llm_provider (exact boundaries, 0 bytes, exceptions).
3. Edge cases and failure modes in api._stream_llm integration.
"""
import asyncio
import os
import shutil
import sys
import time
import random
import unittest
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core import llm_provider
import stt_server
import api


def run_async(coro_fn):
    """Exécute une coroutine dans une boucle asyncio isolée."""
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))
    return wrapper


class TestLLMConcurrencySemaphoreStress(unittest.TestCase):
    """Tests de charge et d'adversité sur les sémaphores de concurrence LLM (B.3.4)."""

    def setUp(self):
        self._orig_semaphores = dict(llm_provider._semaphores)
        llm_provider._semaphores['ollama'] = asyncio.Semaphore(1)
        llm_provider._semaphores['lmstudio'] = asyncio.Semaphore(1)
        llm_provider._semaphores['nvidia'] = asyncio.Semaphore(1)

    def tearDown(self):
        llm_provider._semaphores.clear()
        llm_provider._semaphores.update(self._orig_semaphores)

    @run_async
    async def test_burst_concurrency_strict_invariant(self):
        """Sous un burst de 50 requêtes simultanées, l'exécution active ne dépasse JAMAIS max_concurrency (1)."""
        sem = llm_provider.get_provider_semaphore('ollama')
        active_count = 0
        max_seen = 0
        completed = 0
        lock = asyncio.Lock()

        async def worker(worker_id):
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

        tasks = [asyncio.create_task(worker(i)) for i in range(50)]
        await asyncio.gather(*tasks)

        self.assertEqual(completed, 50, "Toutes les 50 tâches doivent avoir été exécutées")
        self.assertEqual(max_seen, 1, f"L'invariant de concurrence stricte (<=1) a été violé : max_seen={max_seen}")
        self.assertEqual(active_count, 0, "Le compteur actif doit être à 0 en fin d'exécution")
        self.assertFalse(sem.locked(), "Le sémaphore doit être déverrouillé après le burst")
        self.assertEqual(getattr(sem, '_value', None), 1, "La capacité restante du sémaphore doit être de 1")

    @run_async
    async def test_adversarial_chaos_burst(self):
        """Burst chaotique de 100 coroutines mixant succès, exceptions, annulations et temps de calcul aléatoires."""
        sem = llm_provider.get_provider_semaphore('ollama')
        active_count = 0
        max_seen = 0
        lock = asyncio.Lock()

        async def chaos_worker(wid, behavior):
            nonlocal active_count, max_seen
            try:
                async with sem:
                    async with lock:
                        active_count += 1
                        if active_count > max_seen:
                            max_seen = active_count

                    duration = random.uniform(0.001, 0.01)
                    await asyncio.sleep(duration)

                    if behavior == 'raise':
                        raise ValueError(f"Chaos error in worker {wid}")

                    async with lock:
                        active_count -= 1
            except (ValueError, asyncio.CancelledError):
                async with lock:
                    if active_count > 0:
                        active_count -= 1
                if behavior == 'raise':
                    return 'error_caught'
                raise

        tasks = []
        for i in range(100):
            behavior = 'raise' if i % 5 == 0 else ('cancel' if i % 7 == 0 else 'normal')
            t = asyncio.create_task(chaos_worker(i, behavior))
            tasks.append((t, behavior))

        # Annuler les tâches désignées au vol pendant la file d'attente
        await asyncio.sleep(0.005)
        for t, behavior in tasks:
            if behavior == 'cancel':
                t.cancel()

        for t, behavior in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass

        self.assertEqual(max_seen, 1, f"Invariant violé lors du chaos : max_seen={max_seen}")
        self.assertEqual(active_count, 0, "Compteur actif non nul après chaos")
        self.assertFalse(sem.locked(), "Sémaphore resté verrouillé après chaos")
        self.assertEqual(getattr(sem, '_value', None), 1, "Fuite de permis détectée après chaos")

    @run_async
    async def test_semaphore_release_on_unhandled_exception(self):
        """En cas d'exception non gérée pendant l'inférence, le sémaphore est libéré immédiatement sans blocage."""
        sem = llm_provider.get_provider_semaphore('ollama')
        executed_subsequent = False

        async def failing_worker():
            async with sem:
                raise RuntimeError("Panne critique inattendue pendant l'inférence LLM")

        async def normal_worker():
            nonlocal executed_subsequent
            async with sem:
                executed_subsequent = True

        with self.assertRaises(RuntimeError):
            await failing_worker()

        self.assertFalse(sem.locked(), "Le sémaphore ne doit pas rester verrouillé après exception")
        await asyncio.wait_for(normal_worker(), timeout=1.0)
        self.assertTrue(executed_subsequent, "Le worker suivant doit avoir pu acquérir le sémaphore")
        self.assertFalse(sem.locked())

    @run_async
    async def test_cancelled_waiters_do_not_corrupt_semaphore(self):
        """Les annulations de requêtes en file d'attente ne doivent ni corrompre le sémaphore ni voler des permis."""
        sem = llm_provider.get_provider_semaphore('ollama')
        gate = asyncio.Event()
        task1_acquired = asyncio.Event()
        task4_executed = False

        async def task1_holder():
            async with sem:
                task1_acquired.set()
                await gate.wait()

        async def task2_cancelled():
            async with sem:
                pass

        async def task3_cancelled():
            async with sem:
                pass

        async def task4_survivor():
            nonlocal task4_executed
            async with sem:
                task4_executed = True

        t1 = asyncio.create_task(task1_holder())
        await task1_acquired.wait()

        t2 = asyncio.create_task(task2_cancelled())
        t3 = asyncio.create_task(task3_cancelled())
        t4 = asyncio.create_task(task4_survivor())

        await asyncio.sleep(0.02)

        t2.cancel()
        t3.cancel()
        await asyncio.sleep(0.02)

        gate.set()
        await t1

        await asyncio.wait_for(t4, timeout=1.0)
        self.assertTrue(task4_executed, "Task 4 doit s'exécuter malgré l'annulation de t2 et t3")
        self.assertFalse(sem.locked())
        self.assertEqual(getattr(sem, '_value', None), 1, "Le sémaphore doit avoir exactement 1 permis disponible")

    @run_async
    async def test_multi_provider_semaphore_independence(self):
        """Un blocage sur le fournisseur 'ollama' ne doit pas bloquer les inférences sur 'lmstudio'."""
        sem_ollama = llm_provider.get_provider_semaphore('ollama')
        sem_lmstudio = llm_provider.get_provider_semaphore('lmstudio')

        ollama_gate = asyncio.Event()
        lmstudio_executed = False

        async def slow_ollama():
            async with sem_ollama:
                await ollama_gate.wait()

        async def fast_lmstudio():
            nonlocal lmstudio_executed
            async with sem_lmstudio:
                lmstudio_executed = True

        t_ollama = asyncio.create_task(slow_ollama())
        await asyncio.sleep(0.02)

        t0 = time.time()
        await asyncio.wait_for(fast_lmstudio(), timeout=0.5)
        duration = time.time() - t0

        self.assertTrue(lmstudio_executed)
        self.assertLess(duration, 0.2, "L'inférence lmstudio ne doit pas attendre ollama")

        ollama_gate.set()
        await t_ollama

    @run_async
    async def test_cancelled_session_blocks_behind_active_inference(self):
        """Observation d'adversité : si une session est déjà annulée mais que le sémaphore est occupé,
        _stream_llm attend l'acquisition du sémaphore avant de vérifier session.cancel.
        """
        sem = llm_provider.get_provider_semaphore('ollama')
        holder_gate = asyncio.Event()

        class MockSession:
            def __init__(self):
                self.cancel = MagicMock()
                self.cancel.is_set.return_value = True

        async def holder():
            async with sem:
                await holder_gate.wait()

        t_hold = asyncio.create_task(holder())
        await asyncio.sleep(0.02)

        session_cancelled = MockSession()
        with patch('api.get_model_provider', return_value='ollama'):
            # La requête annulée tente d'entrer dans _stream_llm
            # Elle doit attendre le sémaphore même si elle est déjà annulée
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(api._stream_llm(session_cancelled, 'test', [], None, False), timeout=0.05)

        holder_gate.set()
        await t_hold

    def test_provider_status_reflects_locked_state(self):
        """get_provider_status() rapporte correctement locked=True quand le sémaphore est pris."""
        sem = llm_provider.get_provider_semaphore('ollama')

        async def check_status_during_hold():
            async with sem:
                status = llm_provider.get_provider_status()
                self.assertTrue(status['ollama']['locked'], "locked doit être True pendant l'acquisition")
                self.assertEqual(status['ollama']['max_concurrency'], 0,
                                 "Constat empirique: _value passe à 0 quand acquis")

        asyncio.run(check_status_during_hold())
        status_after = llm_provider.get_provider_status()
        self.assertFalse(status_after['ollama']['locked'])
        self.assertEqual(status_after['ollama']['max_concurrency'], 1)


class TestDiskSpaceExhaustionBoundariesStress(unittest.TestCase):
    """Tests aux limites d'épuisement de l'espace disque (B.5.1)."""

    def test_boundary_just_below_stt_threshold(self):
        """STT : 1 octet sous le seuil (1.0 Go - 1 o) -> Refus strict."""
        free_bytes = (1024 ** 3) - 1
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 100 * 1024**3 - free_bytes, free_bytes)

        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre_go, msg = stt_server.verifier_espace_disque(min_go_requis=1.0)
            self.assertFalse(suffisant, "Doit refuser quand free_bytes < min_go_requis")
            self.assertLess(libre_go, 1.0)
            self.assertIn("insuffisant", msg.lower())

    def test_boundary_exact_match_threshold(self):
        """STT : Correspondance exacte avec le seuil (1.0 Go exact).
        La condition libre_go < min_go_requis (1.0 < 1.0 = False) autorise le seuil limite exact.
        """
        free_bytes = 1024 ** 3
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 100 * 1024**3 - free_bytes, free_bytes)

        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre_go, msg = stt_server.verifier_espace_disque(min_go_requis=1.0)
            self.assertTrue(suffisant)
            self.assertEqual(libre_go, 1.0)

    def test_boundary_just_above_stt_threshold(self):
        """STT : 1 Ko au-dessus du seuil (1.0 Go + 1024 o) -> Autorisé."""
        free_bytes = (1024 ** 3) + 1024
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 100 * 1024**3 - free_bytes, free_bytes)

        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre_go, msg = stt_server.verifier_espace_disque(min_go_requis=1.0)
            self.assertTrue(suffisant, "Doit autoriser quand free_bytes > min_go_requis")
            self.assertGreater(libre_go, 1.0)

    def test_boundary_just_below_llm_threshold(self):
        """LLM : 1 octet sous le seuil (2.0 Go - 1 o) -> Refus strict et OSError."""
        free_bytes = (2 * 1024 ** 3) - 1
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 100 * 1024**3 - free_bytes, free_bytes)

        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre_go, msg = llm_provider.verifier_espace_disque(min_go_requis=2.0)
            self.assertFalse(suffisant)
            self.assertLess(libre_go, 2.0)

            with patch.object(llm_provider._http, 'post') as mock_post:
                with self.assertRaises(OSError) as ctx:
                    llm_provider.telecharger_modele("mistral:7b", provider='ollama', min_go_requis=2.0)
                self.assertIn("insuffisant", str(ctx.exception).lower())
                mock_post.assert_not_called()

    def test_zero_bytes_free_stt_and_llm(self):
        """Disque plein à 100% (0 octet libre) -> Refus absolu immédiat sans crash."""
        zero_usage = shutil._ntuple_diskusage(100 * 1024**3, 100 * 1024**3, 0)

        with patch('shutil.disk_usage', return_value=zero_usage):
            # STT
            stt_suffisant, stt_libre, stt_msg = stt_server.verifier_espace_disque()
            self.assertFalse(stt_suffisant)
            self.assertEqual(stt_libre, 0.0)

            # STT init
            stt_server._whisper_model = None
            stt_server._whisper_erreur = None
            model = stt_server._init_whisper()
            self.assertIsNone(model)
            self.assertIn("insuffisant", stt_server._whisper_erreur.lower())

            # LLM
            llm_suffisant, llm_libre, llm_msg = llm_provider.verifier_espace_disque()
            self.assertFalse(llm_suffisant)
            self.assertEqual(llm_libre, 0.0)

            with self.assertRaises(OSError):
                llm_provider.telecharger_modele("llama3:8b")

    def test_negative_free_bytes_quota_overflow(self):
        """Dépassement de quota disque (free négatif) -> Refus immédiat."""
        neg_usage = shutil._ntuple_diskusage(100 * 1024**3, 101 * 1024**3, -1024**2)

        with patch('shutil.disk_usage', return_value=neg_usage):
            suffisant, libre_go, msg = stt_server.verifier_espace_disque()
            self.assertFalse(suffisant)
            self.assertLess(libre_go, 0.0)

            llm_suf, llm_lib, _ = llm_provider.verifier_espace_disque()
            self.assertFalse(llm_suf)
            self.assertLess(llm_lib, 0.0)

    def test_disk_access_error_fail_open_behavior(self):
        """Vérifie le comportement en cas d'erreur d'accès disque (PermissionError/OSError).

        Observation d'adversité :
        En cas d'exception sur shutil.disk_usage (ex: PermissionError, déconnexion),
        le bloc except attrape l'erreur et retourne :
        (True, 999.0, 'Vérification espace disque ignorée : ...')
        Le système adopte donc un comportement 'fail-open' avec journalisation d'un avertissement.
        """
        with patch('shutil.disk_usage', side_effect=PermissionError("Disque verrouillé / Permission refusée")):
            suffisant, libre_go, msg = stt_server.verifier_espace_disque()
            self.assertTrue(suffisant, "Constat: stt_server verifier_espace_disque fail-open sur exception")
            self.assertEqual(libre_go, 999.0)
            self.assertIn("ignorée", msg)

        with patch('shutil.disk_usage', side_effect=OSError("Périphérique E/S déconnecté")):
            suffisant, libre_go, msg = llm_provider.verifier_espace_disque()
            self.assertTrue(suffisant, "Constat: llm_provider verifier_espace_disque fail-open sur exception")
            self.assertEqual(libre_go, 999.0)
            self.assertIn("ignorée", msg)


if __name__ == '__main__':
    unittest.main()
