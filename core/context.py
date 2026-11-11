"""Module de Conscience Contextuelle à l'Invocation (Conformité BLOC B.8.6).

Capture automatiquement la fenêtre active précédente et le presse-papiers
lors de l'ouverture du prompt pour enrichir le tour de conversation.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import psutil
from core.logger import get_logger

logger = get_logger('alyx.context')

def obtenir_fenetre_active() -> dict:
    """Identifie la fenêtre active au premier plan (titre et processus)."""
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return {}
            longueur = user32.GetWindowTextLengthW(hwnd)
            titre = ""
            if longueur > 0:
                buffer = ctypes.create_unicode_buffer(longueur + 1)
                user32.GetWindowTextW(hwnd, buffer, longueur + 1)
                titre = buffer.value

            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            nom_proc = ""
            try:
                proc = psutil.Process(pid.value)
                nom_proc = proc.name()
            except Exception:
                pass

            # Filtrer Alyx lui-même
            if nom_proc.lower().startswith("alyx"):
                return {}

            return {
                "titre": titre,
                "processus": nom_proc,
                "pid": pid.value,
                "os": "Windows"
            }
        except Exception as e:
            logger.debug(f"Erreur lecture fenêtre active Windows: {e}")
            return {}

    elif sys.platform.startswith("linux"):
        titre = ""
        nom_proc = ""
        if shutil.which("xdotool"):
            try:
                res = subprocess.run(["xdotool", "getactivewindow", "getwindowname"], capture_output=True, text=True, timeout=1)
                if res.returncode == 0:
                    titre = res.stdout.strip()
                res_pid = subprocess.run(["xdotool", "getactivewindow", "getwindowpid"], capture_output=True, text=True, timeout=1)
                if res_pid.returncode == 0 and res_pid.stdout.strip().isdigit():
                    nom_proc = psutil.Process(int(res_pid.stdout.strip())).name()
            except Exception:
                pass
        return {"titre": titre, "processus": nom_proc, "os": "Linux"} if titre or nom_proc else {}

    return {}

def obtenir_presse_papiers_invoque(max_chars: int = 1500) -> str | None:
    """Lit défensivement le texte copié sans lever d'exception bloquante."""
    texte = ""
    if sys.platform == "win32":
        try:
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", "Get-Clipboard -Raw"],
                capture_output=True,
                text=True,
                timeout=2
            )
            if res.returncode == 0:
                texte = res.stdout or ""
        except Exception:
            return None
    else:
        commandes = []
        if os.environ.get('WAYLAND_DISPLAY') and shutil.which('wl-paste'):
            commandes.append(['wl-paste', '--no-newline'])
        if shutil.which('xclip'):
            commandes.append(['xclip', '-o', '-selection', 'clipboard'])
        if shutil.which('xsel'):
            commandes.append(['xsel', '-ob'])
        for cmd in commandes:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                if res.returncode == 0:
                    texte = res.stdout or ""
                    break
            except Exception:
                continue

    texte_propre = texte.strip()
    if not texte_propre:
        return None
    if len(texte_propre) > max_chars:
        return texte_propre[:max_chars] + f"\n... [Presse-papiers tronqué à {max_chars} caractères]"
    return texte_propre

def capturer_contexte_invocation() -> dict:
    """Capture globale du contexte lors de l'ouverture du prompt Alyx."""
    fenetre = obtenir_fenetre_active()
    presse_papiers = obtenir_presse_papiers_invoque()
    return {
        "fenetre_active": fenetre,
        "presse_papiers": presse_papiers
    }
