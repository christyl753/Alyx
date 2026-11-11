"""Suite de tests adversariaux et de stress pour le Jalon 1 (Milestone 1).

Éprouve empiriquement et de façon agressive :
1. Les Tâches Quotidiennes (function/reminders.py, function/notes.py) :
   - Cas limites de délais (délai négatif, délai zéro, valeurs non entières, dates passées).
   - Concurrence et rappels multiples à la même seconde (intégrité des IDs, détection exhaustive).
   - Caractères spéciaux, Unicode, RTL, emojis, et injection de code/markdown dans les notes.
   - Tentatives d'injection de chemins relatifs ou absolus (path traversal) et noms réservés Windows.
   - Résilience et persistance atomique sur disque (crash simulé pendant écriture, corruption JSON).
2. Le Mode Focus / Gaming (core/focus_gaming.py) :
   - Fenêtres sans titre ou avec caractères non-standards.
   - Fenêtres multi-écrans (coordonnées négatives, moniteurs déportés, tolérance aux bords, maximized vs fullscreen).
   - Robustesse face aux processus introuvables (PID 0, NoSuchProcess, AccessDenied).
   - Exclusion stricte du processus Alyx lui-même.
   - Mesure empirique de la consommation CPU et impact FPS (benchmarking 1000 itérations).
"""
import ctypes
from datetime import datetime, timedelta
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from core import focus_gaming
from function import notes, reminders


class TestAdversarialReminders(unittest.TestCase):
    """Stress tests et attaques sur la gestion des rappels locaux."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_adv_reminders_")
        self.reminders_file = os.path.join(self.temp_dir, "reminders.json")
        self.patcher = patch('function.reminders._obtenir_fichier_rappels', return_value=self.reminders_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_delai_negatif_ou_zero(self):
        """Vérifie le comportement de creer_rappel avec delai_minutes <= 0."""
        # delai_minutes = 0 : le code doit utiliser le repli de sécurité (+10 min)
        res_zero = reminders.creer_rappel("Rappel zéro", delai_minutes=0)
        self.assertIn("Rappel programmé avec succès", res_zero)
        rappels = reminders._charger_rappels()
        self.assertEqual(len(rappels), 1)
        # Vérifie que l'échéance calculée n'est pas dans le passé ou nulle
        dt_echeance = datetime.strptime(rappels[0]["echeance"], "%Y-%m-%d %H:%M:%S")
        self.assertTrue(dt_echeance >= datetime.now())

        # delai_minutes négatif (-15) : repli conservateur sans crasher
        res_neg = reminders.creer_rappel("Rappel négatif", delai_minutes=-15)
        self.assertIn("Rappel programmé avec succès", res_neg)
        rappels_2 = reminders._charger_rappels()
        self.assertEqual(len(rappels_2), 2)
        dt_echeance_neg = datetime.strptime(rappels_2[1]["echeance"], "%Y-%m-%d %H:%M:%S")
        self.assertTrue(dt_echeance_neg >= datetime.now())

    def test_delai_chaine_et_types_invalides(self):
        """Vérifie la robustesse aux entrées mal typées pour delai_minutes."""
        # Chaîne convertible "20"
        res1 = reminders.creer_rappel("Rappel chaîne 20", delai_minutes="20")
        self.assertIn("Rappel programmé avec succès", res1)

        # Chaîne non numérique : vérifie la gestion de l'exception
        try:
            res_invalide = reminders.creer_rappel("Rappel abc", delai_minutes="abc")
            self.assertTrue(isinstance(res_invalide, str))
        except ValueError as e:
            self.assertIn("invalid literal for int()", str(e))

    def test_date_heure_formats_multiples_et_invalides(self):
        """Vérifie la parsing de dates et le comportement en cas de format invalide."""
        # Format HH:MM (heure du jour)
        maintenant = datetime.now()
        heure_proche = (maintenant + timedelta(minutes=5)).strftime("%H:%M")
        res_hhmm = reminders.creer_rappel("Rappel HH:MM", date_heure=heure_proche)
        self.assertIn("Rappel programmé avec succès", res_hhmm)

        # Format date passée explicite
        date_passee = "2020-01-01 12:00:00"
        res_passee = reminders.creer_rappel("Rappel passé", date_heure=date_passee)
        self.assertIn("Rappel programmé avec succès", res_passee)
        
        # Ce rappel passé doit être immédiatement notifié
        imminents = reminders.verifier_rappels_imminents()
        textes_imminents = [r["texte"] for r in imminents]
        self.assertIn("Rappel passé", textes_imminents)

        # Format date corrompu / invalide
        res_corrompu = reminders.creer_rappel("Rappel corrompu", date_heure="date_invalide_9999")
        self.assertIn("Rappel programmé avec succès", res_corrompu)
        rappels = reminders._charger_rappels()
        r_corr = [r for r in rappels if r["texte"] == "Rappel corrompu"][0]
        self.assertIsNotNone(r_corr["echeance"])

    def test_rappels_multiples_meme_seconde(self):
        """Éprouve la création et la notification de 100 rappels à la même seconde."""
        maintenant = datetime.now()
        echeance_commune = (maintenant - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

        # Insérer 100 rappels avec la même échéance
        for i in range(100):
            res = reminders.creer_rappel(f"Rappel concurrent #{i}", date_heure=echeance_commune)
            self.assertIn("Rappel programmé avec succès", res)

        tous_rappels = reminders._charger_rappels()
        self.assertEqual(len(tous_rappels), 100)

        # Vérifier l'unicité stricte de tous les identifiants générés
        ids = [r["id"] for r in tous_rappels]
        self.assertEqual(len(ids), len(set(ids)), "Collision d'identifiants détectée!")

        # Vérifier que verifier_rappels_imminents récupère et notifie TOUS les 100 rappels d'un coup
        imminents = reminders.verifier_rappels_imminents()
        self.assertEqual(len(imminents), 100, "Des rappels à la même seconde n'ont pas été notifiés!")

        # Un deuxième appel immédiat doit renvoyer 0 rappel (tous notifiés)
        imminents_2 = reminders.verifier_rappels_imminents()
        self.assertEqual(len(imminents_2), 0)

    def test_persistance_atomique_crash_simule(self):
        """Simule un crash disque / OS pendant l'écriture pour valider l'atomicité."""
        reminders.creer_rappel("Rappel initial A", delai_minutes=10)
        reminders.creer_rappel("Rappel initial B", delai_minutes=20)
        self.assertTrue(os.path.exists(self.reminders_file))

        # Simuler un échec système brutal lors du remplacement du fichier atomique
        with patch('os.replace', side_effect=OSError("Crash I/O simulé")):
            succes = reminders._sauvegarder_rappels([{"id": "corrupted", "texte": "bad"}])
            self.assertFalse(succes)

        # Le fichier d'origine DOIT être strictement intact et non corrompu
        self.assertTrue(os.path.exists(self.reminders_file))
        rappels_restants = reminders._charger_rappels()
        self.assertEqual(len(rappels_restants), 2)
        self.assertEqual(rappels_restants[0]["texte"], "Rappel initial A")
        self.assertEqual(rappels_restants[1]["texte"], "Rappel initial B")

        # Le fichier .tmp doit avoir été nettoyé
        fichier_tmp = f"{self.reminders_file}.tmp"
        self.assertFalse(os.path.exists(fichier_tmp))

    def test_resilience_fichier_disque_corrompu(self):
        """Vérifie que le module gère un fichier JSON corrompu sur le disque."""
        with open(self.reminders_file, "w", encoding="utf-8") as f:
            f.write('{"id": "incomplete_json... [CORRUPTED DATA]')

        charge = reminders._charger_rappels()
        self.assertEqual(charge, [])

        res = reminders.creer_rappel("Nouveau rappel sain", delai_minutes=5)
        self.assertIn("Rappel programmé avec succès", res)
        rappels_repares = reminders._charger_rappels()
        self.assertEqual(len(rappels_repares), 1)
        self.assertEqual(rappels_repares[0]["texte"], "Nouveau rappel sain")

    def test_caracteres_speciaux_et_unicode_rappels(self):
        """Vérifie le stockage fidèle d'Unicode complexe, emojis et caractères d'échappement."""
        texte_complexe = "💊 Prendre pilule à 20h30 — « Canopée & Ambre » 🔥\n\tLigne 2: RTL \u202eعربي\u202c & CJK: 提醒 & Quotes: '\"`"
        res = reminders.creer_rappel(texte_complexe, delai_minutes=15)
        self.assertIn("Rappel programmé avec succès", res)

        rappels = reminders._charger_rappels()
        self.assertEqual(rappels[0]["texte"], texte_complexe)

        liste = reminders.lister_rappels()
        self.assertIn("Canopée & Ambre", liste)
        self.assertIn("🔥", liste)

    def test_concurrence_ecriture_rappels(self):
        """Éprouve la robustesse face à des écritures concurrentes multithread sur reminders.json."""
        from concurrent.futures import ThreadPoolExecutor

        def creer_concurrent(i):
            return reminders.creer_rappel(f"Rappel multithread {i}", delai_minutes=10)

        with ThreadPoolExecutor(max_workers=4) as pool:
            resultats = list(pool.map(creer_concurrent, range(10)))

        rappels = reminders._charger_rappels()
        # En l'absence de verrou de synchronisation, les écritures concurrentes provoquent WinError 32 ou des pertes de données
        self.assertEqual(
            len(rappels),
            10,
            f"Perte de rappels sous accès concurrent : {len(rappels)}/10 sauvegardés !"
        )


class TestAdversarialNotes(unittest.TestCase):
    """Stress tests et attaques par injection sur la gestion des notes rapides."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="alyx_adv_notes_")
        self.notes_dir = os.path.join(self.temp_dir, "notes")
        self.index_file = os.path.join(self.temp_dir, "notes.json")
        os.makedirs(self.notes_dir, exist_ok=True)
        self.patcher = patch(
            'function.notes._obtenir_chemins_notes',
            return_value=(self.notes_dir, self.index_file)
        )
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_injection_chemin_relatif_et_absolu_dans_titre(self):
        """Tente d'injecter des chemins relatifs (path traversal) et absolus dans le titre de note."""
        injections = [
            "../../../../Windows/System32/calc.exe",
            "..\\..\\system_override.bat",
            "C:\\Windows\\malicious.md",
            "/etc/shadow",
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
        ]

        for inject in injections:
            res = notes.ajouter_note_rapide(titre=inject, contenu=f"Contenu malveillant pour {inject}")
            self.assertIn("Note enregistrée avec succès", res)

        # Vérifier que TOUS les fichiers Markdown créés sont strictement situés dans self.notes_dir
        fichiers_crees = os.listdir(self.notes_dir)
        self.assertEqual(len(fichiers_crees), len(injections))

        for nom in fichiers_crees:
            chemin_absolu = os.path.join(self.notes_dir, nom)
            self.assertTrue(os.path.commonpath([self.notes_dir, chemin_absolu]) == self.notes_dir)
            self.assertTrue(nom.endswith(".md"))

        index = notes._charger_index_notes()
        self.assertEqual(len(index), len(injections))

    def test_caracteres_speciaux_emojis_unicode_extreme_notes(self):
        """Vérifie l'enregistrement de notes avec emojis seuls, caractères multilingues et symboles."""
        res_emojis = notes.ajouter_note_rapide(titre="🔥🚀💡🎉", contenu="Corps de note emojis")
        self.assertIn("Note enregistrée avec succès", res_emojis)

        titre_cjk = "Alyx 桌面助手 - 自动化测试"
        res_cjk = notes.ajouter_note_rapide(titre=titre_cjk, contenu="测试内容 - 100% 本地离线", etiquette="cjk")
        self.assertIn("Note enregistrée avec succès", res_cjk)

        titre_arabe = "ملاحظة اختبار آمنة"
        res_ar = notes.ajouter_note_rapide(titre=titre_arabe, contenu="محتوى باللغة العربية", etiquette="ar")
        self.assertIn("Note enregistrée avec succès", res_ar)

        lecture_cjk = notes.lire_note_rapide(titre_cjk)
        self.assertIn("100% 本地离线", lecture_cjk)

        lecture_ar = notes.lire_note_rapide(titre_arabe)
        self.assertIn("محتوى باللغة العربية", lecture_ar)

    def test_injection_markdown_et_injection_titre_sur_plusieurs_lignes(self):
        """Vérifie le comportement si le titre contient des sauts de ligne ou balises Markdown."""
        titre_multiligne = "Titre Ligne 1\n# Injection Titre H1\nLigne 3"
        contenu = "Contenu classique"
        res = notes.ajouter_note_rapide(titre=titre_multiligne, contenu=contenu)
        self.assertIn("Note enregistrée avec succès", res)

        index = notes._charger_index_notes()
        self.assertEqual(index[0]["titre"], titre_multiligne)

        lecture = notes.lire_note_rapide(index[0]["id"])
        self.assertIn("Contenu classique", lecture)

    def test_persistance_atomique_index_notes_crash_simule(self):
        """Simule un crash I/O lors de la sauvegarde de l'index notes.json."""
        notes.ajouter_note_rapide("Note A", "Contenu A")
        index_initial = notes._charger_index_notes()
        self.assertEqual(len(index_initial), 1)

        with patch('os.replace', side_effect=OSError("Panne disque simulée")):
            succes = notes._sauvegarder_index_notes([{"id": "bad", "titre": "corrompu"}])
            self.assertFalse(succes)

        index_apres = notes._charger_index_notes()
        self.assertEqual(len(index_apres), 1)
        self.assertEqual(index_apres[0]["titre"], "Note A")

    def test_resilience_fichier_markdown_orphelin_ou_manquant(self):
        """Vérifie la robustesse si un fichier Markdown physique est supprimé manuellement."""
        notes.ajouter_note_rapide("Note Orpheline", "Ce fichier va disparaître")
        index = notes._charger_index_notes()
        note_id = index[0]["id"]
        fichier_md = os.path.join(self.notes_dir, index[0]["fichier"])
        self.assertTrue(os.path.exists(fichier_md))

        os.remove(fichier_md)

        res_lecture = notes.lire_note_rapide(note_id)
        self.assertIn("introuvable", res_lecture)

        res_suppr = notes.supprimer_note_rapide(note_id)
        self.assertIn("supprimée avec succès", res_suppr)
        self.assertEqual(len(notes._charger_index_notes()), 0)

    def test_concurrence_ecriture_notes(self):
        """Éprouve la robustesse face à des ajouts concurrents de notes multithread sur notes.json."""
        from concurrent.futures import ThreadPoolExecutor

        def creer_note_concurrent(i):
            return notes.ajouter_note_rapide(f"Note multithread {i}", f"Contenu concurrent {i}")

        with ThreadPoolExecutor(max_workers=4) as pool:
            resultats = list(pool.map(creer_note_concurrent, range(10)))

        index = notes._charger_index_notes()
        self.assertEqual(
            len(index),
            10,
            f"Perte de notes dans l'index sous accès concurrent : {len(index)}/10 enregistrées !"
        )


class TestAdversarialFocusGaming(unittest.TestCase):
    """Stress tests sur la détection géométrique, multi-écrans et charge CPU/FPS."""

    def setUp(self):
        with focus_gaming._lock:
            focus_gaming._focus_gaming_actif = False
            focus_gaming._dernier_processus_detecte = None

    def tearDown(self):
        with focus_gaming._lock:
            focus_gaming._focus_gaming_actif = False
            focus_gaming._dernier_processus_detecte = None

    def test_fenetre_sans_titre_windows(self):
        """Vérifie qu'une fenêtre sans titre est détectée sans planter."""
        with patch('sys.platform', 'win32'), \
             patch('ctypes.windll.user32.GetForegroundWindow', return_value=12345), \
             patch('ctypes.windll.user32.GetClassNameW') as mock_classe, \
             patch('ctypes.windll.user32.GetWindowRect') as mock_rect, \
             patch('ctypes.windll.user32.MonitorFromWindow', return_value=999), \
             patch('ctypes.windll.user32.GetMonitorInfoW') as mock_mon, \
             patch('ctypes.windll.user32.GetWindowThreadProcessId') as mock_pid, \
             patch('psutil.Process') as mock_proc:

            def side_classe(hwnd, buf, size):
                buf.value = "UnrealWindow"
                return 1
            mock_classe.side_effect = side_classe

            def side_rect(hwnd, rect_ptr):
                rect = rect_ptr._obj
                rect.left = 0
                rect.top = 0
                rect.right = 1920
                rect.bottom = 1080
                return 1
            mock_rect.side_effect = side_rect

            def side_mon(hmon, mi_ptr):
                mi = mi_ptr._obj
                mi.rcMonitor.left = 0
                mi.rcMonitor.top = 0
                mi.rcMonitor.right = 1920
                mi.rcMonitor.bottom = 1080
                return 1
            mock_mon.side_effect = side_mon

            def side_pid(hwnd, pid_ptr):
                pid_ptr._obj.value = 5432
                return 1
            mock_pid.side_effect = side_pid

            proc_instance = MagicMock()
            proc_instance.name.return_value = "GameWithoutTitle.exe"
            mock_proc.return_value = proc_instance

            actif, nom_proc, meta = focus_gaming.detecter_mode_focus_gaming()
            self.assertTrue(actif)
            self.assertEqual(nom_proc, "GameWithoutTitle.exe")
            self.assertEqual(meta.get("class"), "UnrealWindow")

    def test_multi_ecrans_coordonnees_negatives(self):
        """Vérifie la détection d'une fenêtre plein écran sur un écran secondaire situé à gauche (coords négatives)."""
        with patch('sys.platform', 'win32'), \
             patch('ctypes.windll.user32.GetForegroundWindow', return_value=12345), \
             patch('ctypes.windll.user32.GetClassNameW') as mock_classe, \
             patch('ctypes.windll.user32.GetWindowRect') as mock_rect, \
             patch('ctypes.windll.user32.MonitorFromWindow', return_value=888), \
             patch('ctypes.windll.user32.GetMonitorInfoW') as mock_mon, \
             patch('ctypes.windll.user32.GetWindowThreadProcessId') as mock_pid, \
             patch('psutil.Process') as mock_proc:

            def side_classe(hwnd, buf, size):
                buf.value = "GameWindow"
                return 1
            mock_classe.side_effect = side_classe

            def side_pid(hwnd, pid_ptr):
                pid_ptr._obj.value = 7777
                return 1
            mock_pid.side_effect = side_pid

            proc_instance = MagicMock()
            proc_instance.name.return_value = "Cyberpunk2077.exe"
            mock_proc.return_value = proc_instance

            # Écran secondaire à gauche : [-1920, 0] à [0, 1080]
            def side_mon(hmon, mi_ptr):
                mi = mi_ptr._obj
                mi.rcMonitor.left = -1920
                mi.rcMonitor.top = 0
                mi.rcMonitor.right = 0
                mi.rcMonitor.bottom = 1080
                return 1
            mock_mon.side_effect = side_mon

            # Cas 1 : Fenêtre parfaitement plein écran sur l'écran secondaire
            def side_rect_fullscreen(hwnd, rect_ptr):
                rect = rect_ptr._obj
                rect.left = -1920
                rect.top = 0
                rect.right = 0
                rect.bottom = 1080
                return 1
            mock_rect.side_effect = side_rect_fullscreen

            actif, nom_proc, meta = focus_gaming.detecter_mode_focus_gaming()
            self.assertTrue(actif, "Écran secondaire avec coordonnées négatives non détecté en plein écran !")
            self.assertEqual(nom_proc, "Cyberpunk2077.exe")

            # Cas 2 : Fenêtre fenêtrée sur l'écran secondaire (10 pixels de marge) -> DOIT renvoyer False
            def side_rect_windowed(hwnd, rect_ptr):
                rect = rect_ptr._obj
                rect.left = -1910  # 10px de marge à gauche
                rect.top = 10
                rect.right = -10
                rect.bottom = 1070
                return 1
            mock_rect.side_effect = side_rect_windowed

            actif_w, nom_proc_w, _ = focus_gaming.detecter_mode_focus_gaming()
            self.assertFalse(actif_w, "Fenêtre fenêtrée incorrectement détectée comme plein écran !")

    def test_multi_ecrans_secondaire_droite(self):
        """Vérifie la détection d'une fenêtre plein écran sur un écran secondaire situé à droite (coords positives)."""
        with patch('sys.platform', 'win32'), \
             patch('ctypes.windll.user32.GetForegroundWindow', return_value=12345), \
             patch('ctypes.windll.user32.GetClassNameW') as mock_classe, \
             patch('ctypes.windll.user32.GetWindowRect') as mock_rect, \
             patch('ctypes.windll.user32.MonitorFromWindow', return_value=888), \
             patch('ctypes.windll.user32.GetMonitorInfoW') as mock_mon, \
             patch('ctypes.windll.user32.GetWindowThreadProcessId') as mock_pid, \
             patch('psutil.Process') as mock_proc:

            mock_classe.side_effect = lambda h, b, s: setattr(b, 'value', 'GameWindow') or 1
            mock_pid.side_effect = lambda h, p: setattr(p._obj, 'value', 7777) or 1

            proc_instance = MagicMock()
            proc_instance.name.return_value = "DoomEternal.exe"
            mock_proc.return_value = proc_instance

            # Écran secondaire à droite : [1920, 0] à [3840, 1080]
            def side_mon(hmon, mi_ptr):
                mi = mi_ptr._obj
                mi.rcMonitor.left = 1920
                mi.rcMonitor.top = 0
                mi.rcMonitor.right = 3840
                mi.rcMonitor.bottom = 1080
                return 1
            mock_mon.side_effect = side_mon

            def side_rect(hwnd, rect_ptr):
                rect = rect_ptr._obj
                rect.left = 1920
                rect.top = 0
                rect.right = 3840
                rect.bottom = 1080
                return 1
            mock_rect.side_effect = side_rect

            actif, nom_proc, meta = focus_gaming.detecter_mode_focus_gaming()
            self.assertTrue(actif)
            self.assertEqual(nom_proc, "DoomEternal.exe")

    def test_fenetre_maximisee_avec_barre_des_taches_non_detectee(self):
        """Vérifie qu'une fenêtre maximisée classique (avec barre des tâches visible) n'est PAS détectée plein écran."""
        with patch('sys.platform', 'win32'), \
             patch('ctypes.windll.user32.GetForegroundWindow', return_value=12345), \
             patch('ctypes.windll.user32.GetClassNameW') as mock_classe, \
             patch('ctypes.windll.user32.GetWindowRect') as mock_rect, \
             patch('ctypes.windll.user32.MonitorFromWindow', return_value=888), \
             patch('ctypes.windll.user32.GetMonitorInfoW') as mock_mon, \
             patch('ctypes.windll.user32.GetWindowThreadProcessId') as mock_pid, \
             patch('psutil.Process') as mock_proc:

            mock_classe.side_effect = lambda h, b, s: setattr(b, 'value', 'Chrome_WidgetWin_1') or 1
            mock_pid.side_effect = lambda h, p: setattr(p._obj, 'value', 3333) or 1

            proc_instance = MagicMock()
            proc_instance.name.return_value = "chrome.exe"
            mock_proc.return_value = proc_instance

            def side_mon(hmon, mi_ptr):
                mi = mi_ptr._obj
                mi.rcMonitor.left = 0
                mi.rcMonitor.top = 0
                mi.rcMonitor.right = 1920
                mi.rcMonitor.bottom = 1080
                return 1
            mock_mon.side_effect = side_mon

            # Fenêtre maximisée standard Windows : barre des tâches en bas (hauteur 1040 au lieu de 1080)
            def side_rect(hwnd, rect_ptr):
                rect = rect_ptr._obj
                rect.left = -8
                rect.top = -8
                rect.right = 1928
                rect.bottom = 1040  # Réduit par la barre des tâches
                return 1
            mock_rect.side_effect = side_rect

            actif, nom_proc, _ = focus_gaming.detecter_mode_focus_gaming()
            self.assertFalse(actif, "Une fenêtre normale avec barre des tâches visible ne doit pas être plein écran !")

    def test_processus_introuvable_ou_acces_refuse(self):
        """Vérifie la robustesse si le PID n'existe plus ou est inaccessible (AccessDenied / NoSuchProcess)."""
        import psutil
        with patch('sys.platform', 'win32'), \
             patch('ctypes.windll.user32.GetForegroundWindow', return_value=12345), \
             patch('ctypes.windll.user32.GetClassNameW') as mock_classe, \
             patch('ctypes.windll.user32.GetWindowRect') as mock_rect, \
             patch('ctypes.windll.user32.MonitorFromWindow', return_value=888), \
             patch('ctypes.windll.user32.GetMonitorInfoW') as mock_mon, \
             patch('ctypes.windll.user32.GetWindowThreadProcessId') as mock_pid, \
             patch('psutil.Process', side_effect=psutil.NoSuchProcess(pid=99999)):

            mock_classe.side_effect = lambda h, b, s: setattr(b, 'value', 'GameWindow') or 1
            mock_pid.side_effect = lambda h, p: setattr(p._obj, 'value', 99999) or 1

            def side_rect(hwnd, rect_ptr):
                rect = rect_ptr._obj
                rect.left = 0
                rect.top = 0
                rect.right = 1920
                rect.bottom = 1080
                return 1
            mock_rect.side_effect = side_rect

            def side_mon(hmon, mi_ptr):
                mi = mi_ptr._obj
                mi.rcMonitor.left = 0
                mi.rcMonitor.top = 0
                mi.rcMonitor.right = 1920
                mi.rcMonitor.bottom = 1080
                return 1
            mock_mon.side_effect = side_mon

            actif, nom_proc, meta = focus_gaming.detecter_mode_focus_gaming()
            self.assertTrue(actif)
            self.assertIsNone(nom_proc)
            self.assertIsNone(meta.get("process"))

    def test_exclusion_stricte_processus_alyx(self):
        """Vérifie que si la fenêtre Alyx elle-même est en plein écran, le mode n'est pas activé."""
        with patch('sys.platform', 'win32'), \
             patch('ctypes.windll.user32.GetForegroundWindow', return_value=12345), \
             patch('ctypes.windll.user32.GetClassNameW') as mock_classe, \
             patch('ctypes.windll.user32.GetWindowRect') as mock_rect, \
             patch('ctypes.windll.user32.MonitorFromWindow', return_value=888), \
             patch('ctypes.windll.user32.GetMonitorInfoW') as mock_mon, \
             patch('ctypes.windll.user32.GetWindowThreadProcessId') as mock_pid, \
             patch('psutil.Process') as mock_proc:

            mock_classe.side_effect = lambda h, b, s: setattr(b, 'value', 'AvaloniaWindow') or 1
            mock_pid.side_effect = lambda h, p: setattr(p._obj, 'value', 1234) or 1

            def side_rect(hwnd, rect_ptr):
                rect = rect_ptr._obj
                rect.left = 0
                rect.top = 0
                rect.right = 1920
                rect.bottom = 1080
                return 1
            mock_rect.side_effect = side_rect

            def side_mon(hmon, mi_ptr):
                mi = mi_ptr._obj
                mi.rcMonitor.left = 0
                mi.rcMonitor.top = 0
                mi.rcMonitor.right = 1920
                mi.rcMonitor.bottom = 1080
                return 1
            mock_mon.side_effect = side_mon

            proc_instance = MagicMock()
            proc_instance.name.return_value = "AlyxDesktop.exe"
            mock_proc.return_value = proc_instance

            actif, nom_proc, _ = focus_gaming.detecter_mode_focus_gaming()
            self.assertFalse(actif, "Alyx s'est auto-détecté comme jeu plein écran !")

    def test_performance_cpu_et_impact_fps_benchmark(self):
        """Mesure empirique du temps d'exécution et de l'empreinte CPU sur 1 000 itérations."""
        nb_iterations = 1000
        t_debut = time.perf_counter()
        cpu_debut = time.process_time()

        for _ in range(nb_iterations):
            focus_gaming.detecter_mode_focus_gaming()

        t_fin = time.perf_counter()
        cpu_fin = time.process_time()

        temps_total_sec = t_fin - t_debut
        temps_cpu_sec = cpu_fin - cpu_debut
        temps_moyen_ms = (temps_total_sec / nb_iterations) * 1000

        self.assertLess(
            temps_moyen_ms,
            1.5,
            f"La détection plein écran est trop lente ({temps_moyen_ms:.3f} ms par appel)!"
        )

        ratio_cpu_pct = ((temps_cpu_sec / nb_iterations) / 5.0) * 100

        self.assertLess(
            ratio_cpu_pct,
            0.05,
            f"Empreinte CPU estimée excessive ({ratio_cpu_pct:.4f}%)!"
        )


if __name__ == '__main__':
    unittest.main()
