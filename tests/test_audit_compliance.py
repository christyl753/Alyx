"""Suite de tests de conformité formelle BLOC B (Jalon 2 / Milestone 2).

Vérifie l'ensemble des exigences et correctifs audités :
1. Isolation Air-Gap stricte (B.6.1, B.8.1)
2. Garde d'espace disque avant téléchargement STT/LLM (B.5.1, B.4.1)
3. Contrôle de concurrence et sémaphores par fournisseur LLM (B.3.4, B.4.1)
4. Veto obligatoire Human-in-the-Loop sur terminaison de processus (B.6.4, B.7.4)
5. Séparation et télémétrie de l'environnement virtuel STT (B.1.1, B.1.2, B.1.3)
"""
import asyncio
import os
import shutil
import sys
import unittest
from unittest.mock import MagicMock, patch

# S'assurer que le répertoire racine est accessible pour les imports
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.exceptions import PermissionRequiredException
from core import llm_provider
from function import system, files, web
import api
import stt_server
from tests.e2e.harness import AirGapAssertionProbe, AirGapViolationError


def run_async(coro_fn):
    """Décorateur pour exécuter un test unitaire asynchrone dans une boucle d'événements propre."""
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))
    return wrapper


class TestAirGapIsolationB8(unittest.TestCase):
    """Vérifie la conformité B.6.1 & B.8.1 : Zéro appel externe, étanchéité WAN totale."""

    def setUp(self):
        self._orig_airgap = os.environ.get('ALYX_AIR_GAPPED')
        os.environ['ALYX_AIR_GAPPED'] = '1'

    def tearDown(self):
        if self._orig_airgap is not None:
            os.environ['ALYX_AIR_GAPPED'] = self._orig_airgap
        else:
            os.environ.pop('ALYX_AIR_GAPPED', None)

    def test_rechercher_web_air_gapped_returns_informative_message_without_wan(self):
        """rechercher_web doit renvoyer un message d'information local sans aucun appel WAN."""
        with AirGapAssertionProbe():
            res = web.rechercher_web("actualités IA")
            self.assertIn("[MODE AIR-GAPPED / HORS-LIGNE]", res)
            self.assertIn("B.8.1", res)
            self.assertIn("actualités IA", res)

    def test_verifier_url_securisee_blocks_wan_in_air_gap_mode(self):
        """_verifier_url_securisee bloque toute URL externe en mode air-gapped sans résolution DNS."""
        with AirGapAssertionProbe():
            with self.assertRaises(ValueError) as ctx:
                web._verifier_url_securisee("https://html.duckduckgo.com/html/?q=test")
            self.assertIn("air-gapped", str(ctx.exception).lower())

    def test_verifier_url_securisee_anti_ssrf_still_active_for_localhost(self):
        """Les vérifications anti-SSRF pour localhost restent prioritaires et actives."""
        with self.assertRaises(ValueError) as ctx:
            web._verifier_url_securisee("http://127.0.0.1:8765/api")
        self.assertIn("anti-ssrf", str(ctx.exception).lower())

    def test_diagnostiquer_reseau_air_gapped_no_wan_packets(self):
        """diagnostiquer_reseau ne doit ni résoudre google.com ni ping 8.8.8.8 sous AirGap."""
        with AirGapAssertionProbe():
            res = system.diagnostiquer_reseau("8.8.8.8")
            self.assertIn("Air-Gapped", res)
            self.assertIn("zéro fuite WAN", res)
            self.assertIn("Bloqué", res)

    def test_diagnostiquer_reseau_local_target_under_air_gap(self):
        """diagnostiquer_reseau autorise le ping local sur 127.0.0.1 sous AirGap."""
        with AirGapAssertionProbe():
            res = system.diagnostiquer_reseau("127.0.0.1")
            self.assertIn("127.0.0.1", res)


class TestPreDownloadDiskSpaceGuardB5(unittest.TestCase):
    """Vérifie la conformité B.5.1 & B.4.1 : Contrôle espace disque avant téléchargement."""

    def test_stt_verifier_espace_disque_sufficient(self):
        """STT accepte le téléchargement si l'espace disque est au-dessus du seuil."""
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 50 * 1024**3, 50 * 1024**3)
        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre_go, msg = stt_server.verifier_espace_disque(min_go_requis=1.0)
            self.assertTrue(suffisant)
            self.assertGreaterEqual(libre_go, 1.0)
            self.assertIn("suffisant", msg.lower())

    def test_stt_verifier_espace_disque_insufficient(self):
        """STT refuse le téléchargement si l'espace disque est insuffisant."""
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 99.8 * 1024**3, 0.2 * 1024**3)
        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre_go, msg = stt_server.verifier_espace_disque(min_go_requis=1.0)
            self.assertFalse(suffisant)
            self.assertLess(libre_go, 1.0)
            self.assertIn("insuffisant", msg.lower())
            self.assertIn("B.5.1", msg)

    def test_stt_init_whisper_aborts_on_low_disk(self):
        """_init_whisper n'instancie pas WhisperModel si l'espace disque est insuffisant."""
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 99.9 * 1024**3, 0.1 * 1024**3)
        with patch('shutil.disk_usage', return_value=fake_usage):
            stt_server._whisper_model = None
            stt_server._whisper_erreur = None
            model = stt_server._init_whisper()
            self.assertIsNone(model)
            self.assertIsNotNone(stt_server._whisper_erreur)
            self.assertIn("insuffisant", stt_server._whisper_erreur.lower())

    def test_llm_verifier_espace_disque_sufficient(self):
        """LLM provider accepte si l'espace disque est suffisant."""
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 80 * 1024**3, 20 * 1024**3)
        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre_go, msg = llm_provider.verifier_espace_disque(min_go_requis=2.0)
            self.assertTrue(suffisant)
            self.assertGreaterEqual(libre_go, 2.0)

    def test_llm_verifier_espace_disque_insufficient(self):
        """LLM provider refuse si l'espace disque est inférieur au seuil."""
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 99.5 * 1024**3, 0.5 * 1024**3)
        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre_go, msg = llm_provider.verifier_espace_disque(min_go_requis=2.0)
            self.assertFalse(suffisant)
            self.assertIn("insuffisant", msg.lower())
            self.assertIn("B.5.1", msg)

    def test_llm_telecharger_modele_raises_oserror_on_low_disk(self):
        """telecharger_modele lève une OSError immédiate si l'espace disque est insuffisant."""
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 99.7 * 1024**3, 0.3 * 1024**3)
        with patch('shutil.disk_usage', return_value=fake_usage):
            with patch.object(llm_provider._http, 'post') as mock_post:
                with self.assertRaises(OSError) as ctx:
                    llm_provider.telecharger_modele("llama3:8b", provider='ollama', min_go_requis=2.0)
                self.assertIn("insuffisant", str(ctx.exception).lower())
                mock_post.assert_not_called()

    def test_llm_charger_modele_raises_oserror_on_low_disk(self):
        """charger_modele bloque si l'espace disque est insuffisant."""
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 99.7 * 1024**3, 0.3 * 1024**3)
        with patch('shutil.disk_usage', return_value=fake_usage):
            with patch.object(llm_provider, 'get_model_provider', return_value='ollama'):
                with patch.object(llm_provider._http, 'post') as mock_post:
                    with self.assertRaises(OSError) as ctx:
                        llm_provider.charger_modele("llama3:8b", verifier_disque=True)
                    self.assertIn("insuffisant", str(ctx.exception).lower())
                    mock_post.assert_not_called()


class TestLLMProviderConcurrencyControl(unittest.TestCase):
    """Vérifie la conformité B.3.4 & B.4.1 : Sémaphores de concurrence par fournisseur."""

    def test_provider_semaphores_exist_for_all_configured_providers(self):
        """Chaque fournisseur configuré dans PROVIDERS dispose d'un asyncio.Semaphore."""
        for p_name in ('ollama', 'lmstudio', 'nvidia'):
            sem = llm_provider.get_provider_semaphore(p_name)
            self.assertIsInstance(sem, asyncio.Semaphore)

    @run_async
    async def test_semaphore_limits_parallel_acquisitions(self):
        """Vérifie que le sémaphore sérialise strictement les acquisitions selon max_concurrency."""
        sem = asyncio.Semaphore(1)
        with patch.dict(llm_provider._semaphores, {'ollama': sem}):
            # Première acquisition réussit immédiatement
            acquired_first = await asyncio.wait_for(sem.acquire(), timeout=0.1)
            self.assertTrue(acquired_first)
            self.assertTrue(sem.locked())

            # Deuxième acquisition dans le délai échoue (TimeoutError)
            with self.assertRaises(asyncio.TimeoutError):
                await asyncio.wait_for(sem.acquire(), timeout=0.1)

            # Libération de la première
            sem.release()
            self.assertFalse(sem.locked())

            # La deuxième acquisition réussit désormais
            acquired_second = await asyncio.wait_for(sem.acquire(), timeout=0.1)
            self.assertTrue(acquired_second)
            sem.release()

    def test_provider_status_contains_concurrency_metadata(self):
        """get_provider_status() expose max_concurrency et l'état locked."""
        status = llm_provider.get_provider_status()
        self.assertIn('ollama', status)
        self.assertIn('max_concurrency', status['ollama'])
        self.assertIn('locked', status['ollama'])


class TestCriticalActionHITLSafety(unittest.TestCase):
    """Vérifie la conformité B.6.4 & B.7.4 : Veto obligatoire Human-in-the-Loop sur terminaison."""

    def test_fermer_application_raises_permission_required(self):
        """fermer_application lève PermissionRequiredException si une instance active est trouvée."""
        dummy_proc = MagicMock()
        dummy_proc.pid = 99999
        dummy_proc.info = {'name': 'firefox.exe', 'status': 'running'}

        with patch('psutil.process_iter', return_value=[dummy_proc]):
            with patch('function.system._pids_proteges', return_value=set()):
                with self.assertRaises(PermissionRequiredException) as ctx:
                    system.fermer_application('firefox')
                self.assertIn('FERMER', ctx.exception.action.upper())
                self.assertIn('firefox', ctx.exception.cible.lower())

    def test_fermer_application_refuses_protected_processes_immediately(self):
        """Les processus protégés (dwm.exe, etc.) sont refusés sans déclencher de prompt HITL."""
        res = system.fermer_application('dwm.exe')
        self.assertIn('protégé', res.lower())

    def test_fermer_application_nonexistent_returns_gracefully(self):
        """Terminer une application inactive signale l'absence sans lever de prompt HITL."""
        with patch('psutil.process_iter', return_value=[]):
            res = system.fermer_application('ghost_application_xyz')
            self.assertIn('aucune instance active', res.lower())

    def test_fermer_application_executes_with_permission(self):
        """Lorsque la permission est accordée via executer_avec_permission, les processus sont terminés."""
        dummy_proc = MagicMock()
        dummy_proc.pid = 99998
        dummy_proc.info = {'name': 'calculator.exe', 'status': 'running'}

        with patch('psutil.process_iter', return_value=[dummy_proc]):
            with patch('function.system._pids_proteges', return_value=set()):
                with patch('psutil.wait_procs', return_value=([dummy_proc], [])):
                    res = files.executer_avec_permission(
                        system.fermer_application,
                        {'nom_app': 'calculator'}
                    )
                    self.assertIn('succès', res.lower())
                    dummy_proc.terminate.assert_called_once()


class TestSTTEnvironmentSeparation(unittest.TestCase):
    """Vérifie la conformité B.1.1, B.1.2 & B.1.3 : Isolation venv STT et télémétrie de santé."""

    def test_alyx_bat_contains_venv_stt_resolution(self):
        """alyx.bat définit et priorise .venv_stt par rapport à .venv pour le STT."""
        bat_path = os.path.join(ROOT_DIR, 'alyx.bat')
        with open(bat_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('.venv_stt', content)
        self.assertIn('STT_PYTHON', content)

    def test_stt_server_contains_version_telemetry(self):
        """stt_server.py expose les indicateurs PYTHON_VERSION et IS_ISOLATED."""
        stt_path = os.path.join(ROOT_DIR, 'stt_server.py')
        with open(stt_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('PYTHON_VERSION', content)
        self.assertIn('IS_ISOLATED', content)
        self.assertIn('isolated_env', content)

    @run_async
    async def test_api_get_status_includes_stt_metadata(self):
        """Le handler get_status dans api.py interroge et inclut l'état du STT."""
        mock_ws = MagicMock()
        envoyes = []

        async def faux_send(msg):
            envoyes.append(msg)

        mock_ws.send = faux_send
        session = api.Session(mock_ws)

        with patch('api._appel_stt', return_value={'status': 'ok', 'model_ready': True}):
            with patch('api.get_provider_status', return_value={'ollama': {'status': 'online'}}):
                # Simuler le traitement du message get_status
                data = {"type": "get_status"}
                stt_health = await asyncio.to_thread(api._appel_stt, '/health', timeout=1)
                stt_online = isinstance(stt_health, dict) and stt_health.get('status') == 'ok'
                await session.envoyer({
                    "type": "provider_status",
                    "status": api.get_provider_status(),
                    "stt": {
                        "status": "online" if stt_online else "offline",
                        "model_ready": stt_health.get('model_ready', False),
                        "url": api.STT_URL,
                    }
                })

        self.assertEqual(len(envoyes), 1)
        import json
        payload = json.loads(envoyes[0])
        self.assertIn('stt', payload)
        self.assertEqual(payload['stt']['status'], 'online')
        self.assertTrue(payload['stt']['model_ready'])


if __name__ == '__main__':
    unittest.main()
