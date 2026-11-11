"""Module de détection du Mode Focus / Gaming et régulation des ressources (Conformité BLOC B.8.5).

Détecte les fenêtres actives en plein écran (Windows & Linux) ou les processus de jeux vidéo.
Suspend les routines de télémétrie lourdes et décharge la VRAM pour garantir un impact FPS strictement nul.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import threading
import time
import psutil
from core.logger import get_logger

logger = get_logger('alyx.focus_gaming')

# Processus ou signatures de jeux vidéo / moteurs sous Linux et Windows
PROCESSUS_JEUX_SIGNATURES = {
    "steam", "steamwebhelper", "gamescope", "wine-preloader", "wineserver",
    "proton", "gamemoded", "mangohud", "lutris", "heroic", "epicgameslauncher",
    "unrealengine", "unitycrashhandler64", "directx", "vulkan"
}

_focus_gaming_actif = False
_dernier_processus_detecte = None
_modele_precedemment_decharge = None
_lock = threading.Lock()

def est_focus_gaming_actif() -> bool:
    """Indique si le mode Focus/Gaming est actuellement actif."""
    with _lock:
        return _focus_gaming_actif

def dernier_processus_focus() -> str | None:
    """Nom du processus ayant déclenché le mode Focus/Gaming."""
    with _lock:
        return _dernier_processus_detecte

def _detecter_plein_ecran_windows() -> tuple[bool, str | None, dict]:
    """Détecte sous Windows si la fenêtre au premier plan est en plein écran."""
    if sys.platform != "win32":
        return False, None, {}
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return False, None, {}

        # Ignorer le bureau et la barre des tâches
        buffer_classe = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buffer_classe, 256)
        nom_classe = buffer_classe.value
        if nom_classe in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False, None, {}

        # Coordonnées de la fenêtre
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                        ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

        rect = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return False, None, {}

        largeur_fenetre = rect.right - rect.left
        hauteur_fenetre = rect.bottom - rect.top

        # Coordonnées du moniteur associé
        MONITOR_DEFAULTTONEAREST = 2
        hmonitor = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("rcMonitor", RECT),
                ("rcWork", RECT),
                ("dwFlags", ctypes.c_ulong),
            ]

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if user32.GetMonitorInfoW(hmonitor, ctypes.byref(mi)):
            mon_w = mi.rcMonitor.right - mi.rcMonitor.left
            mon_h = mi.rcMonitor.bottom - mi.rcMonitor.top
            mon_left = mi.rcMonitor.left
            mon_top = mi.rcMonitor.top
        else:
            mon_w = user32.GetSystemMetrics(0)
            mon_h = user32.GetSystemMetrics(1)
            mon_left = 0
            mon_top = 0

        est_plein_ecran = (
            rect.left <= mon_left and
            rect.top <= mon_top and
            largeur_fenetre >= mon_w and
            hauteur_fenetre >= mon_h
        )

        if not est_plein_ecran:
            return False, None, {}

        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        nom_proc = None
        try:
            proc = psutil.Process(pid.value)
            nom_proc = proc.name()
            if nom_proc.lower().startswith("alyx"):
                return False, None, {}
        except Exception:
            pass

        return True, nom_proc, {"hwnd": hwnd, "class": nom_classe, "pid": pid.value, "process": nom_proc}
    except Exception as e:
        logger.debug(f"Erreur détection plein écran Windows: {e}")
        return False, None, {}

def _detecter_plein_ecran_linux() -> tuple[bool, str | None, dict]:
    """Détecte sous Linux si une fenêtre plein écran est active ou un jeu Steam/Proton est lancé."""
    if not sys.platform.startswith("linux"):
        return False, None, {}

    # 1. Détection via xprop (X11)
    if shutil.which("xprop"):
        try:
            res_root = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, timeout=1)
            if res_root.returncode == 0 and "window id #" in res_root.stdout:
                win_id = res_root.stdout.split()[-1]
                res_state = subprocess.run(["xprop", "-id", win_id, "_NET_WM_STATE"], capture_output=True, text=True, timeout=1)
                if "_NET_WM_STATE_FULLSCREEN" in res_state.stdout:
                    res_pid = subprocess.run(["xprop", "-id", win_id, "_NET_WM_PID"], capture_output=True, text=True, timeout=1)
                    nom_proc = None
                    if res_pid.returncode == 0:
                        pid_str = res_pid.stdout.split()[-1]
                        if pid_str.isdigit():
                            try:
                                nom_proc = psutil.Process(int(pid_str)).name()
                            except Exception:
                                pass
                    return True, nom_proc, {"win_id": win_id, "process": nom_proc}
        except Exception:
            pass

    # 2. Détection de processus de jeux vidéo sous Linux (Proton/Steam/Gamescope)
    try:
        for p in psutil.process_iter(['name']):
            p_name = (p.info.get('name') or '').lower()
            if p_name in PROCESSUS_JEUX_SIGNATURES:
                return True, p_name, {"process": p_name, "type": "gaming_runtime"}
    except Exception:
        pass

    return False, None, {}

def detecter_mode_focus_gaming() -> tuple[bool, str | None, dict]:
    """Détecte si une application plein écran ou un jeu vidéo est actif."""
    if sys.platform == "win32":
        return _detecter_plein_ecran_windows()
    elif sys.platform.startswith("linux"):
        return _detecter_plein_ecran_linux()
    return False, None, {}

def evaluer_changement_focus(auto_unload_vram: bool = True) -> tuple[bool, bool, str | None]:
    """Évalue l'état actuel et gère les transitions d'état.
    
    Renvoie: (changement_detecte, nouvel_etat_actif, nom_processus)
    """
    global _focus_gaming_actif, _dernier_processus_detecte, _modele_precedemment_decharge
    actif, nom_proc, _ = detecter_mode_focus_gaming()

    changement = False
    with _lock:
        if actif and not _focus_gaming_actif:
            _focus_gaming_actif = True
            _dernier_processus_detecte = nom_proc or "Application plein écran"
            changement = True
            logger.info(f"Mode Focus/Gaming ACTIVÉ (détecté : {_dernier_processus_detecte}).")

            if auto_unload_vram:
                try:
                    from core.llm_provider import decharger_modele
                    import ai
                    if ai.MODEL and ai.MODEL != 'Aucun modèle':
                        _modele_precedemment_decharge = ai.MODEL
                        decharger_modele(ai.MODEL)
                        logger.info(f"VRAM libérée pour le jeu : modèle '{ai.MODEL}' déchargé.")
                except Exception as e:
                    logger.warning(f"Impossible de décharger la VRAM automatiquement: {e}")

        elif not actif and _focus_gaming_actif:
            _focus_gaming_actif = False
            ancien_proc = _dernier_processus_detecte
            _dernier_processus_detecte = None
            changement = True
            logger.info(f"Mode Focus/Gaming DÉSACTIVÉ (fin de {ancien_proc}).")

        etat_actuel = _focus_gaming_actif
        proc_actuel = _dernier_processus_detecte

    return changement, etat_actuel, proc_actuel
