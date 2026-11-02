"""Banc d'épreuves adversariales et de stress pour l'horloge et la synchronisation temporelle (Milestone 1).

Rôles du testeur (Critic / Empirical Challenger) :
1. Fuzzing & stress de concurrence : hammer multi-thread sur system_monitor.snapshot() et boucle de métriques.
2. Transitions aux frontières : basculement de minute, passage de minuit, années bissextiles (29 février), fins de mois.
3. Émulation de l'oracle Avalonia C# : validation du dirty-check (0 gaspillage UI) et du forçage à l'activation.
4. Résilience de la boucle WebSocket sous forte charge et churn de souscriptions.
5. Invariants stricts d'isolation air-gap et de priorité DispatcherPriority.Normal.
"""
import asyncio
from datetime import datetime, timedelta
import json
import os
import re
import sys
import threading
import time
import unittest
from unittest.mock import patch

# Résolution de la racine du dépôt Alyx
current_dir = os.path.dirname(os.path.abspath(__file__))
if ".agents" in current_dir:
    REPO_ROOT = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
else:
    REPO_ROOT = os.path.dirname(current_dir)

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import system_monitor
import api


class TestConcurrentSnapshotStress(unittest.TestCase):
    """Épreuves de charge et de concurrence sur core.system_monitor."""

    def test_high_concurrency_multi_threaded_snapshots(self):
        """Stress test : 30 threads appelant simultanément snapshot() (600 appels au total).

        Vérifie :
        - Absence de deadlock ou d'exception sous le verrou _lock.
        - Présence constante des champs temporels (timestamp, time, date).
        - Format ISO 8601 valide sur tous les échantillons.
        - Monotonicité globale des timestamps.
        """
        num_threads = 30
        calls_per_thread = 20
        results = []
        errors = []
        start_barrier = threading.Barrier(num_threads)

        def worker():
            try:
                start_barrier.wait(timeout=5)
                for _ in range(calls_per_thread):
                    s = system_monitor.snapshot(reseau=False)
                    results.append((time.time(), s))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(num_threads)]
        t_start = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        duration = time.time() - t_start

        self.assertEqual(len(errors), 0, f"Des erreurs sont survenues pendant le stress test : {errors}")
        self.assertEqual(len(results), num_threads * calls_per_thread, "Tous les appels doivent avoir abouti")

        # Validation de chaque échantillon
        for wall_time, s in results:
            self.assertIn('timestamp', s)
            self.assertIn('time', s)
            self.assertIn('date', s)
            ts = datetime.fromisoformat(s['timestamp'])
            self.assertLess(abs((ts - datetime.fromtimestamp(wall_time)).total_seconds()), 1.5)

        # Monotonicité des timestamps ordonnés
        sorted_samples = sorted(results, key=lambda x: x[0])
        parsed_ts = [datetime.fromisoformat(s['timestamp']) for _, s in sorted_samples]
        for i in range(1, len(parsed_ts)):
            self.assertGreaterEqual(
                parsed_ts[i],
                parsed_ts[i - 1] - timedelta(milliseconds=50),
                f"Dérive temporelle anormale détectée à l'échantillon {i}"
            )

    def test_concurrent_snapshot_with_network_flag(self):
        """Vérifie la robustesse de snapshot avec reseau=True et reseau=False en accès concurrent."""
        num_threads = 16
        errors = []
        results = []
        barrier = threading.Barrier(num_threads)

        def worker(reseau_flag):
            try:
                barrier.wait(timeout=5)
                for _ in range(10):
                    s = system_monitor.snapshot(reseau=reseau_flag)
                    results.append(s)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(i % 2 == 0,))
            for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Erreurs de concurrence réseau/snapshot : {errors}")
        self.assertEqual(len(results), num_threads * 10)

    def test_concurrent_snapshot_and_processus_listing(self):
        """Vérifie l'absence de conflit entre snapshot() et processus() sous forte contention."""
        errors = []
        stop_event = threading.Event()

        def snapshot_worker():
            try:
                for _ in range(25):
                    s = system_monitor.snapshot(reseau=False)
                    self.assertIn('timestamp', s)
            except Exception as e:
                errors.append(e)

        def process_worker():
            try:
                for _ in range(10):
                    p = system_monitor.processus(limite=10)
                    self.assertIn('items', p)
            except Exception as e:
                errors.append(e)

        threads = (
            [threading.Thread(target=snapshot_worker) for _ in range(4)] +
            [threading.Thread(target=process_worker) for _ in range(4)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Conflit de threads entre snapshot et processus : {errors}")

    def test_high_frequency_snapshot_burst_timing(self):
        """Mesure de latence sur 100 appels consécutifs à snapshot(reseau=False)."""
        t0 = time.perf_counter()
        count = 100
        for _ in range(count):
            s = system_monitor.snapshot(reseau=False)
            self.assertIn('timestamp', s)
        total_time = time.perf_counter() - t0
        avg_time_ms = (total_time / count) * 1000
        # snapshot(reseau=False) ne doit pas dépasser 50ms en moyenne
        self.assertLess(avg_time_ms, 50.0, f"snapshot(reseau=False) est trop lent : {avg_time_ms:.2f} ms / appel")


class TestBoundaryTransitionsAndArithmetic(unittest.TestCase):
    """Épreuves sur les frontières temporelles (minute, minuit, bissextile, fins de mois)."""

    def test_minute_rollover_boundaries(self):
        """Vérifie le formatage et la continuité lors du basculement de minute (ex: 14:59:59.999 -> 15:00:00.001)."""
        t1 = datetime(2026, 11, 2, 14, 59, 59, 999000)
        t2 = datetime(2026, 11, 2, 15, 0, 0, 1000)

        with patch('core.system_monitor.datetime') as mock_dt:
            mock_dt.now.return_value = t1
            s1 = system_monitor.snapshot(reseau=False)

        with patch('core.system_monitor.datetime') as mock_dt:
            mock_dt.now.return_value = t2
            s2 = system_monitor.snapshot(reseau=False)

        self.assertEqual(s1['time'], "14:59:59")
        self.assertEqual(s2['time'], "15:00:00")
        self.assertEqual(s1['date'], "2026-11-02")
        self.assertEqual(s2['date'], "2026-11-02")
        self.assertGreater(datetime.fromisoformat(s2['timestamp']), datetime.fromisoformat(s1['timestamp']))

    def test_midnight_rollover_boundaries(self):
        """Vérifie le passage de minuit (23:59:59 -> 00:00:00) : incrément de date et reset d'heure."""
        t1 = datetime(2026, 11, 2, 23, 59, 59, 990000)
        t2 = datetime(2026, 11, 3, 0, 0, 0, 10000)

        with patch('core.system_monitor.datetime') as mock_dt:
            mock_dt.now.return_value = t1
            s1 = system_monitor.snapshot(reseau=False)

        with patch('core.system_monitor.datetime') as mock_dt:
            mock_dt.now.return_value = t2
            s2 = system_monitor.snapshot(reseau=False)

        self.assertEqual(s1['time'], "23:59:59")
        self.assertEqual(s2['time'], "00:00:00")
        self.assertEqual(s1['date'], "2026-11-02")
        self.assertEqual(s2['date'], "2026-11-03")

    def test_leap_year_transitions(self):
        """Vérifie le comportement temporel sur les dates bissextiles (2024-02-28 -> 2024-02-29 -> 2024-03-01)."""
        cas = [
            (datetime(2024, 2, 28, 23, 59, 59), "2024-02-28", "23:59:59"),
            (datetime(2024, 2, 29, 0, 0, 0), "2024-02-29", "00:00:00"),
            (datetime(2024, 2, 29, 23, 59, 59), "2024-02-29", "23:59:59"),
            (datetime(2024, 3, 1, 0, 0, 0), "2024-03-01", "00:00:00"),
            # Année non-bissextile 2023
            (datetime(2023, 2, 28, 23, 59, 59), "2023-02-28", "23:59:59"),
            (datetime(2023, 3, 1, 0, 0, 0), "2023-03-01", "00:00:00"),
            # Changement d'année
            (datetime(2026, 12, 31, 23, 59, 59), "2026-12-31", "23:59:59"),
            (datetime(2027, 1, 1, 0, 0, 0), "2027-01-01", "00:00:00"),
        ]

        for dt_val, exp_date, exp_time in cas:
            with patch('core.system_monitor.datetime') as mock_dt:
                mock_dt.now.return_value = dt_val
                s = system_monitor.snapshot(reseau=False)
                self.assertEqual(s['date'], exp_date, f"Date incorrecte pour {dt_val}")
                self.assertEqual(s['time'], exp_time, f"Heure incorrecte pour {dt_val}")
                self.assertEqual(s['timestamp'], dt_val.isoformat())

    def test_end_of_month_boundaries_all_12_months(self):
        """Vérifie le passage de fin de mois pour chacun des 12 mois de l'année."""
        fins_de_mois = [
            (datetime(2026, 1, 31, 23, 59, 59), datetime(2026, 2, 1, 0, 0, 0)),
            (datetime(2026, 2, 28, 23, 59, 59), datetime(2026, 3, 1, 0, 0, 0)),
            (datetime(2026, 3, 31, 23, 59, 59), datetime(2026, 4, 1, 0, 0, 0)),
            (datetime(2026, 4, 30, 23, 59, 59), datetime(2026, 5, 1, 0, 0, 0)),
            (datetime(2026, 5, 31, 23, 59, 59), datetime(2026, 6, 1, 0, 0, 0)),
            (datetime(2026, 6, 30, 23, 59, 59), datetime(2026, 7, 1, 0, 0, 0)),
            (datetime(2026, 7, 31, 23, 59, 59), datetime(2026, 8, 1, 0, 0, 0)),
            (datetime(2026, 8, 31, 23, 59, 59), datetime(2026, 9, 1, 0, 0, 0)),
            (datetime(2026, 9, 30, 23, 59, 59), datetime(2026, 10, 1, 0, 0, 0)),
            (datetime(2026, 10, 31, 23, 59, 59), datetime(2026, 11, 1, 0, 0, 0)),
            (datetime(2026, 11, 30, 23, 59, 59), datetime(2026, 12, 1, 0, 0, 0)),
            (datetime(2026, 12, 31, 23, 59, 59), datetime(2027, 1, 1, 0, 0, 0)),
        ]

        for avant, apres in fins_de_mois:
            with patch('core.system_monitor.datetime') as mock_dt:
                mock_dt.now.return_value = avant
                s1 = system_monitor.snapshot(reseau=False)
            with patch('core.system_monitor.datetime') as mock_dt:
                mock_dt.now.return_value = apres
                s2 = system_monitor.snapshot(reseau=False)

            self.assertEqual(s1['date'], avant.strftime("%Y-%m-%d"))
            self.assertEqual(s2['date'], apres.strftime("%Y-%m-%d"))
            self.assertEqual(s1['time'], "23:59:59")
            self.assertEqual(s2['time'], "00:00:00")


class TestAvaloniaClockEngineEmulation(unittest.TestCase):
    """Oracle et émulateur de l'algorithme C# UpdateClock dans AlyxPanel.axaml.cs."""

    class AvaloniaClockOracle:
        """Modélisation exacte de la machine à états C# d'AlyxPanel."""
        def __init__(self):
            self.last_minute = -1
            self.last_hour = -1
            self.last_date = None
            self.last_compact = False
            self.renders = 0
            self.clock_text = ""
            self.date_text = ""

        def update_clock(self, now: datetime, compact: bool, force: bool = False) -> bool:
            # Réplique exacte de la condition C# :
            # if (!force && now.Minute == _lastClockMinute && now.Hour == _lastClockHour
            #     && now.Date == _lastClockDate && compact == _lastClockCompact) return;
            current_date = now.date()
            if (not force and
                now.minute == self.last_minute and
                now.hour == self.last_hour and
                current_date == self.last_date and
                compact == self.last_compact):
                return False  # Dirty-check évite le rendu

            self.last_minute = now.minute
            self.last_hour = now.hour
            self.last_date = current_date
            self.last_compact = compact
            self.renders += 1
            self.clock_text = now.strftime("%H:%M")
            self.date_text = now.strftime("%d/%m/%Y")
            return True

    def test_dirty_check_eliminates_redundant_renders(self):
        """Vérifie que 1 000 ticks à l'intérieur de la même minute ne provoquent qu'un seul rendu."""
        oracle = self.AvaloniaClockOracle()
        base_time = datetime(2026, 11, 2, 10, 15, 0)

        # 1er tick force (démarrage)
        rendered = oracle.update_clock(base_time, compact=False, force=True)
        self.assertTrue(rendered)
        self.assertEqual(oracle.renders, 1)

        # 1 000 ticks successifs toutes les 50ms dans la même minute
        for i in range(1, 1000):
            current = base_time + timedelta(milliseconds=i * 50)  # reste <= 10:15:50
            rendered = oracle.update_clock(current, compact=False, force=False)
            self.assertFalse(rendered, f"Rendu inutile au tick {i} dans la même minute")

        self.assertEqual(oracle.renders, 1, "Un seul rendu doit avoir eu lieu pour toute la minute")

    def test_minute_transition_triggers_render(self):
        """Vérifie que le basculement de minute déclenche immédiatement un rendu."""
        oracle = self.AvaloniaClockOracle()
        t1 = datetime(2026, 11, 2, 10, 15, 59, 750000)
        t2 = datetime(2026, 11, 2, 10, 16, 0, 0)

        oracle.update_clock(t1, compact=False, force=True)
        self.assertEqual(oracle.clock_text, "10:15")
        self.assertEqual(oracle.renders, 1)

        rendered = oracle.update_clock(t2, compact=False, force=False)
        self.assertTrue(rendered, "Le basculement à 10:16 doit déclencher un rendu")
        self.assertEqual(oracle.clock_text, "10:16")
        self.assertEqual(oracle.renders, 2)

    def test_midnight_transition_triggers_date_and_time_render(self):
        """Vérifie que le passage de minuit déclenche un rendu avec mise à jour date + heure."""
        oracle = self.AvaloniaClockOracle()
        t1 = datetime(2026, 11, 2, 23, 59, 59)
        t2 = datetime(2026, 11, 3, 0, 0, 0)

        oracle.update_clock(t1, compact=False, force=True)
        self.assertEqual(oracle.clock_text, "23:59")
        self.assertEqual(oracle.date_text, "02/11/2026")

        rendered = oracle.update_clock(t2, compact=False, force=False)
        self.assertTrue(rendered)
        self.assertEqual(oracle.clock_text, "00:00")
        self.assertEqual(oracle.date_text, "03/11/2026")

    def test_compact_resize_triggers_render_within_same_minute(self):
        """Vérifie que le redimensionnement (<430px) déclenche un rendu même dans la même minute."""
        oracle = self.AvaloniaClockOracle()
        now = datetime(2026, 11, 2, 10, 15, 30)

        oracle.update_clock(now, compact=False, force=True)
        self.assertEqual(oracle.renders, 1)

        # Passage en mode compact (redimensionnement fenêtre)
        rendered = oracle.update_clock(now, compact=True, force=False)
        self.assertTrue(rendered, "Le changement de mode compact doit forcer une mise à jour d'affichage")
        self.assertEqual(oracle.renders, 2)

        # Reste en mode compact -> aucun nouveau rendu
        rendered = oracle.update_clock(now + timedelta(seconds=1), compact=True, force=False)
        self.assertFalse(rendered)
        self.assertEqual(oracle.renders, 2)

    def test_force_flag_bypasses_cache_on_menu_activation(self):
        """Vérifie que force=True outrepasse le dirty-check (scénario SetMenuActive(true))."""
        oracle = self.AvaloniaClockOracle()
        now = datetime(2026, 11, 2, 10, 15, 30)

        oracle.update_clock(now, compact=False, force=False)
        self.assertEqual(oracle.renders, 1)

        # Même milliseconde, mais force=True
        rendered = oracle.update_clock(now, compact=False, force=True)
        self.assertTrue(rendered, "force=True doit forcer l'actualisation immédiate")
        self.assertEqual(oracle.renders, 2)


class TestWebSocketMetricsBurstAndChurn(unittest.IsolatedAsyncioTestCase):
    """Épreuves de charge et de churn sur la boucle WebSocket _boucle_metriques."""

    class MockSession:
        def __init__(self, session_id):
            self.session_id = session_id
            self.messages = []
            self._occupee = False
            self.lock = asyncio.Lock()

        def occupee(self):
            return self._occupee

        async def envoyer(self, msg):
            async with self.lock:
                self.messages.append((time.time(), msg))

    async def test_rapid_subscriber_churn_and_cancellation(self):
        """Simule 10 clients souscrivant et se déconnectant rapidement sans fuite ni crash."""
        sessions = [self.MockSession(i) for i in range(10)]
        tasks = []

        for s in sessions:
            task = asyncio.create_task(api._boucle_metriques(s))
            tasks.append(task)

        # Laisse tourner un court instant
        await asyncio.sleep(0.5)

        # Annulation concurrente de tous les abonnés
        for t in tasks:
            t.cancel()

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            self.assertTrue(r is None or isinstance(r, asyncio.CancelledError))

        # Vérifie qu'au moins un message a été transmis et qu'il est valide
        total_messages = sum(len(s.messages) for s in sessions)
        self.assertGreater(total_messages, 0, "Les abonnés doivent avoir reçu au moins une mise à jour")
        for s in sessions:
            for wall_time, msg in s.messages:
                self.assertEqual(msg['type'], 'metrics')
                self.assertIn('timestamp', msg)
                ts = datetime.fromisoformat(msg['timestamp'])
                self.assertLess(abs((ts - datetime.fromtimestamp(wall_time)).total_seconds()), 2.0)

    async def test_metrics_json_serialization_performance(self):
        """Vérifie la vitesse et la validité de la sérialisation JSON sous rafale de 200 payloads."""
        s = system_monitor.snapshot(reseau=False)
        payload = {
            "type": "metrics",
            "generating": False,
            "timestamp": s.get("timestamp"),
            **s
        }
        t0 = time.perf_counter()
        count = 200
        for _ in range(count):
            encoded = json.dumps(payload)
            self.assertIn('"timestamp":', encoded)
        elapsed = time.perf_counter() - t0
        avg_us = (elapsed / count) * 1_000_000
        # Sérialisation JSON d'un payload metrics doit être < 500 µs
        self.assertLess(avg_us, 500.0, f"Sérialisation JSON trop lente : {avg_us:.1f} µs")


class TestStaticInvariantsAndSafetyAudit(unittest.TestCase):
    """Audit statique des invariants de code et de conformité BLOC B pour l'horloge."""

    def test_airgap_offline_compliance_in_clock_modules(self):
        """Vérifie qu'aucun appel NTP, HTTP ou DNS externe n'est introduit dans le module de métriques."""
        monitor_path = os.path.join(REPO_ROOT, "core", "system_monitor.py")
        with open(monitor_path, "r", encoding="utf-8") as f:
            content = f.read()

        interdits = [
            "pool.ntp.org",
            "time.google.com",
            "time.windows.com",
            "worldtimeapi.org",
            "http://",
            "https://",
            "urllib",
            "requests",
            "httpx",
        ]
        for motif in interdits:
            self.assertNotIn(
                motif,
                content,
                f"Violation potentielle de l'isolation air-gapped (B.8) : motif '{motif}' détecté dans system_monitor.py"
            )

    def test_csharp_clock_timer_invariants(self):
        """Vérifie la présence des 5 invariants de sûreté dans AlyxPanel.axaml.cs."""
        panel_cs = os.path.join(REPO_ROOT, "AlyxDesktop", "AlyxPanel.axaml.cs")
        with open(panel_cs, "r", encoding="utf-8") as f:
            code = f.read()

        # 1. DispatcherPriority.Normal
        self.assertIn("DispatcherPriority.Normal", code)
        # 2. Cadence <= 500ms
        self.assertIn("TimeSpan.FromMilliseconds(250)", code)
        # 3. Forçage à l'ouverture du menu
        self.assertIn("UpdateClock(force: true)", code)
        # 4. Garde thread UI
        self.assertIn("Dispatcher.UIThread.CheckAccess()", code)
        # 5. Culture française statique
        self.assertIn('CultureInfo.GetCultureInfo("fr-FR")', code)


if __name__ == '__main__':
    unittest.main()
