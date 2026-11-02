"""Tests unitaires et de conformité pour l'horloge et la synchronisation temporelle (Milestone 1).

Vérifie :
1. Présence et validité des champs temporels (timestamp ISO, time HH:MM ou HH:MM:SS, date YYYY-MM-DD) dans system_monitor.snapshot().
2. Précision temporelle de snapshot() par rapport à datetime.now() (< 1 seconde).
3. Intégration de la date et de l'heure courantes dans system_monitor.resume_pour_llm().
4. Transmission du timestamp valide dans la boucle WebSocket _boucle_metriques d'api.py.
5. Conformité statique du timer d'horloge Avalonia C# dans AlyxDesktop/AlyxPanel.axaml.cs
   (DispatcherPriority.Normal, cadence sub-seconde <= 500ms, appel UpdateClock à l'ouverture, garde thread-safe).

Lancer : .venv\\Scripts\\python.exe -m unittest discover -s tests -v
"""
import asyncio
from datetime import datetime, timedelta
import json
import os
import re
import sys
import time
import unittest

# Résolution robuste de la racine du dépôt Alyx
current_dir = os.path.dirname(os.path.abspath(__file__))
if ".agents" in current_dir:
    REPO_ROOT = os.path.abspath(os.path.join(current_dir, "..", "..", ".."))
else:
    REPO_ROOT = os.path.dirname(current_dir)

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core import system_monitor
import api


class TestSystemMonitorClock(unittest.TestCase):
    """Tests unitaires pour l'ancrage temporel de core.system_monitor."""

    def test_snapshot_contains_temporal_fields(self):
        """Vérifie que snapshot() contient les clés timestamp, time et date avec des types valides."""
        s = system_monitor.snapshot()
        self.assertIn('timestamp', s, "snapshot() doit contenir la clé 'timestamp'")
        self.assertIn('time', s, "snapshot() doit contenir la clé 'time'")
        self.assertIn('date', s, "snapshot() doit contenir la clé 'date'")
        self.assertIsInstance(s['timestamp'], str, "'timestamp' doit être une chaîne de caractères")
        self.assertIsInstance(s['time'], str, "'time' doit être une chaîne de caractères")
        self.assertIsInstance(s['date'], str, "'date' doit être une chaîne de caractères")

    def test_snapshot_iso_timestamp_format_and_accuracy(self):
        """Vérifie que snapshot()['timestamp'] est un ISO 8601 valide et précis à moins de 1 seconde."""
        t_before = datetime.now()
        s = system_monitor.snapshot()
        t_after = datetime.now()

        self.assertIn('timestamp', s, "snapshot() doit contenir la clé 'timestamp'")
        ts_str = s['timestamp']

        # Validation du parsing ISO 8601
        try:
            parsed = datetime.fromisoformat(ts_str)
        except (ValueError, TypeError) as exc:
            self.fail(f"snapshot()['timestamp'] '{ts_str}' n'est pas un format ISO 8601 valide: {exc}")

        # Tolérance de dérive < 1 seconde
        delta_before = (parsed - t_before).total_seconds()
        delta_after = (t_after - parsed).total_seconds()
        self.assertLess(abs(delta_before), 1.0, f"Le timestamp {parsed} a un décalage > 1s par rapport à t_before {t_before}")
        self.assertLess(abs(delta_after), 1.0, f"Le timestamp {parsed} a un décalage > 1s par rapport à t_after {t_after}")

    def test_snapshot_time_and_date_formats(self):
        """Vérifie les formats HH:MM ou HH:MM:SS pour 'time' et YYYY-MM-DD pour 'date'."""
        s = system_monitor.snapshot()
        now = datetime.now()

        self.assertIn('time', s, "snapshot() doit contenir la clé 'time'")
        self.assertIn('date', s, "snapshot() doit contenir la clé 'date'")

        self.assertRegex(s['time'], r"^\d{2}:\d{2}(?::\d{2})?$", "Le format de 'time' doit être HH:MM ou HH:MM:SS")
        self.assertRegex(s['date'], r"^\d{4}-\d{2}-\d{2}$", "Le format de 'date' doit être YYYY-MM-DD")

        # Vérification de cohérence sur les minutes (avec tolérance pour le basculement de minute)
        expected_minute_prefixes = {
            (now - timedelta(seconds=2)).strftime("%H:%M"),
            now.strftime("%H:%M"),
            (now + timedelta(seconds=2)).strftime("%H:%M"),
        }
        self.assertIn(s['time'][:5], expected_minute_prefixes,
                      f"Les 5 premiers caractères de 'time' ({s['time']}) ne correspondent pas à l'heure courante {now.strftime('%H:%M')}")

        expected_dates = {
            (now - timedelta(minutes=1)).strftime("%Y-%m-%d"),
            now.strftime("%Y-%m-%d"),
            (now + timedelta(minutes=1)).strftime("%Y-%m-%d"),
        }
        self.assertIn(s['date'], expected_dates, f"'date' {s['date']} ne correspond pas à la date courante {now.strftime('%Y-%m-%d')}")

    def test_snapshot_json_serializability(self):
        """Vérifie que snapshot() est sérialisable en JSON (sans objet datetime brut)."""
        s = system_monitor.snapshot()
        self.assertIn('timestamp', s, "snapshot() doit contenir la clé 'timestamp'")
        self.assertIn('time', s, "snapshot() doit contenir la clé 'time'")
        self.assertIn('date', s, "snapshot() doit contenir la clé 'date'")

        try:
            serialized = json.dumps(s)
        except TypeError as exc:
            self.fail(f"snapshot() n'est pas directement sérialisable en JSON: {exc}")

        deserialized = json.loads(serialized)
        self.assertEqual(deserialized['timestamp'], s['timestamp'])
        self.assertEqual(deserialized['time'], s['time'])
        self.assertEqual(deserialized['date'], s['date'])

    def test_snapshot_without_network_preserves_temporal_fields(self):
        """Vérifie que snapshot(reseau=False) préserve l'ancrage temporel."""
        s = system_monitor.snapshot(reseau=False)
        self.assertIn('timestamp', s, "snapshot(reseau=False) doit contenir 'timestamp'")
        self.assertIn('time', s, "snapshot(reseau=False) doit contenir 'time'")
        self.assertIn('date', s, "snapshot(reseau=False) doit contenir 'date'")

    def test_snapshot_timestamp_monotonicity(self):
        """Vérifie que des appels consécutifs produisent des timestamps croissants ou égaux."""
        s1 = system_monitor.snapshot()
        self.assertIn('timestamp', s1, "snapshot() doit contenir la clé 'timestamp'")
        time.sleep(0.02)
        s2 = system_monitor.snapshot()
        self.assertIn('timestamp', s2, "snapshot() doit contenir la clé 'timestamp'")

        t1 = datetime.fromisoformat(s1['timestamp'])
        t2 = datetime.fromisoformat(s2['timestamp'])
        self.assertGreaterEqual(t2, t1, "Le second timestamp doit être >= au premier")


class TestSystemResumeClock(unittest.TestCase):
    """Tests unitaires pour l'ancrage temporel dans le résumé LLM."""

    def test_resume_pour_llm_contains_date_and_time(self):
        """Vérifie que resume_pour_llm() intègre la date et l'heure système."""
        resume = system_monitor.resume_pour_llm()
        self.assertIsInstance(resume, str)
        self.assertIn("CPU", resume, "Les métriques matérielles doivent être présentes")

        now = datetime.now()
        heure_courante = now.strftime("%H:%M")
        date_iso = now.strftime("%Y-%m-%d")
        date_fr = now.strftime("%d/%m/%Y")

        a_heure = (heure_courante in resume) or bool(re.search(r"\b\d{2}:\d{2}\b", resume))
        a_date = (date_iso in resume) or (date_fr in resume) or bool(re.search(r"\b\d{4}-\d{2}-\d{2}\b", resume))

        self.assertTrue(a_heure, f"L'heure courante ({heure_courante}) ou un motif HH:MM doit figurer dans resume_pour_llm: '{resume}'")
        self.assertTrue(a_date, f"La date courante ({date_iso} ou {date_fr}) doit figurer dans resume_pour_llm: '{resume}'")

    def test_context_window_temporal_grounding(self):
        """Vérifie que _messages_avec_fenetre inclut le contexte temporel quand l'état système est requis."""
        ancien_messages = list(api.messages)
        try:
            api.messages[:] = [
                {'role': 'system', 'content': 'System prompt'},
                {'role': 'user', 'content': 'Quelle heure est-il ?'}
            ]
            resume = system_monitor.resume_pour_llm()
            fenetre = api._messages_avec_fenetre(etat_systeme=resume)
            dernier = fenetre[-1]
            self.assertEqual(dernier['role'], 'user')
            self.assertIn("Contexte matériel actuel", dernier['content'])
            self.assertIn(resume, dernier['content'])
        finally:
            api.messages[:] = ancien_messages


class TestWebSocketMetricsClock(unittest.IsolatedAsyncioTestCase):
    """Tests de transmission asynchrone du timestamp dans la boucle WebSocket."""

    class MockSession:
        def __init__(self):
            self.messages = []
            self._occupee = False
            self.recu_event = asyncio.Event()

        def occupee(self):
            return self._occupee

        async def envoyer(self, msg):
            self.messages.append(msg)
            self.recu_event.set()

    async def test_metrics_loop_transmits_valid_timestamp(self):
        """Vérifie que _boucle_metriques transmet un message metrics contenant un timestamp ISO valide."""
        session = self.MockSession()
        t_debut = datetime.now()

        task = asyncio.create_task(api._boucle_metriques(session))

        try:
            await asyncio.wait_for(session.recu_event.wait(), timeout=2.5)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        self.assertGreaterEqual(len(session.messages), 1, "La boucle de métriques doit avoir émis au moins un message")
        msg = session.messages[0]
        self.assertEqual(msg.get('type'), 'metrics')
        self.assertIn('timestamp', msg, "Le payload metrics doit contenir la clé 'timestamp'")

        parsed = datetime.fromisoformat(msg['timestamp'])
        delta = abs((parsed - t_debut).total_seconds())
        self.assertLess(delta, 2.0, f"Le timestamp transmis {parsed} s'écarte trop de l'heure de début {t_debut}")


class TestFrontendClockStaticCompliance(unittest.TestCase):
    """Audit statique automatisé des règles du BLOC B et Milestone 1 pour le composant Avalonia C#."""

    PANEL_CS_PATH = os.path.join(REPO_ROOT, "AlyxDesktop", "AlyxPanel.axaml.cs")
    PANEL_AXAML_PATH = os.path.join(REPO_ROOT, "AlyxDesktop", "AlyxPanel.axaml")

    def setUp(self):
        self.assertTrue(os.path.exists(self.PANEL_CS_PATH), f"Fichier introuvable: {self.PANEL_CS_PATH}")
        with open(self.PANEL_CS_PATH, "r", encoding="utf-8") as f:
            self.cs_content = f.read()

    def test_clock_timer_priority_is_normal(self):
        """Vérifie que _clockTimer utilise DispatcherPriority.Normal pour éviter la famine UI (B.7)."""
        match_init = re.search(r'_clockTimer\s*=\s*new\s+DispatcherTimer\s*\((.*?)\)\s*;', self.cs_content, re.DOTALL)
        self.assertIsNotNone(match_init, "Initialisation de _clockTimer introuvable dans AlyxPanel.axaml.cs")
        args = match_init.group(1)
        self.assertIn("DispatcherPriority.Normal", args,
                      f"_clockTimer doit être initialisé avec DispatcherPriority.Normal pour prévenir la famine UI. Trouvé: {args}")
        self.assertNotIn("DispatcherPriority.Background", args,
                         "_clockTimer ne doit plus utiliser DispatcherPriority.Background")

    def test_clock_timer_cadence_is_subsecond(self):
        """Vérifie que l'intervalle du timer d'horloge est sub-seconde (ex: 250ms) pour éliminer le déphasage."""
        match_init = re.search(r'_clockTimer\s*=\s*new\s+DispatcherTimer\s*\((.*?)\)\s*;', self.cs_content, re.DOTALL)
        self.assertIsNotNone(match_init)
        args = match_init.group(1)

        ms_match = re.search(r'TimeSpan\.FromMilliseconds\((\d+)\)', args)
        if ms_match:
            ms = int(ms_match.group(1))
            self.assertLessEqual(ms, 500, f"La cadence du timer d'horloge ({ms} ms) doit être sub-seconde (<= 500 ms)")
            self.assertGreaterEqual(ms, 50, f"La cadence du timer d'horloge ({ms} ms) ne doit pas être excessivement agressive (>= 50 ms)")
        else:
            self.fail(f"L'intervalle de _clockTimer doit être défini en millisecondes sub-secondes (ex: TimeSpan.FromMilliseconds(250)). Trouvé: {args}")

    def test_panel_activation_calls_update_clock_immediately(self):
        """Vérifie que SetMenuActive(true) invoque immédiatement UpdateClock() à l'ouverture du panneau."""
        match_method = re.search(r'public\s+(?:async\s+)?void\s+SetMenuActive\s*\(\s*bool\s+active\s*\)\s*\{([\s\S]*?)\n\s*\}', self.cs_content)
        self.assertIsNotNone(match_method, "Méthode SetMenuActive introuvable dans AlyxPanel.axaml.cs")
        body = match_method.group(1)

        match_active = re.search(r'if\s*\(\s*active\s*\)\s*\{([\s\S]*?)\}', body)
        self.assertIsNotNone(match_active, "Bloc 'if (active)' introuvable dans SetMenuActive")
        active_block = match_active.group(1)
        self.assertIn("UpdateClock", active_block,
                      "UpdateClock() doit être appelé immédiatement lors de l'activation (if (active)) dans SetMenuActive")

    def test_update_clock_has_thread_safety_guard(self):
        """Vérifie que UpdateClock dispose d'une vérification de thread UI (Dispatcher.UIThread.CheckAccess)."""
        match_method = re.search(r'private\s+void\s+UpdateClock\s*\([^)]*\)\s*\{([\s\S]*?)\n\s*\}', self.cs_content)
        self.assertIsNotNone(match_method, "Méthode UpdateClock introuvable dans AlyxPanel.axaml.cs")
        body = match_method.group(1)
        self.assertTrue(
            "CheckAccess" in body or "Dispatcher.UIThread" in body,
            "UpdateClock doit vérifier l'accès au thread UI (CheckAccess / Dispatcher.UIThread) pour garantir la sécurité multi-thread"
        )

    def test_clock_xaml_textblocks_declared(self):
        """Vérifie la déclaration des contrôles ClockText et DateText dans AlyxPanel.axaml."""
        self.assertTrue(os.path.exists(self.PANEL_AXAML_PATH), f"Fichier introuvable: {self.PANEL_AXAML_PATH}")
        with open(self.PANEL_AXAML_PATH, "r", encoding="utf-8") as f:
            axaml_content = f.read()

        self.assertIn('x:Name="ClockText"', axaml_content, "Contrôle x:Name='ClockText' manquant dans AlyxPanel.axaml")
        self.assertIn('x:Name="DateText"', axaml_content, "Contrôle x:Name='DateText' manquant dans AlyxPanel.axaml")


if __name__ == '__main__':
    unittest.main()
