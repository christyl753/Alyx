import os
import sys
import shlex
import shutil
import subprocess
import threading
import psutil
from .scrap import construire_dictionnaire_applications
from core.logger import get_logger

logger = get_logger('alyx.system')

# Processus que le LLM ne doit jamais pouvoir tuer
PROCESSUS_PROTEGES = {
    # Windows
    'system', 'smss.exe', 'csrss.exe', 'wininit.exe', 'winlogon.exe', 'services.exe',
    'lsass.exe', 'svchost.exe', 'dwm.exe', 'fontdrvhost.exe', 'alyxdesktop.exe',
    # Linux
    'systemd', 'init', 'xorg', 'xwayland', 'gnome-shell', 'plasmashell', 'kwin_x11',
    'kwin_wayland', 'sddm', 'gdm', 'pipewire', 'dbus-daemon', 'alyxdesktop',
}

# --- ALIAS D'APPLICATIONS (scan en arrière-plan, non bloquant au démarrage) ---
_alias_lock = threading.Lock()
_alias_dynamiques = None

def _get_alias() -> dict:
    global _alias_dynamiques
    with _alias_lock:
        if _alias_dynamiques is None:
            logger.info("Scan des applications installées...")
            _alias_dynamiques = construire_dictionnaire_applications()
            logger.info(f"{len(_alias_dynamiques)} alias d'applications générés.")
        return _alias_dynamiques

threading.Thread(target=_get_alias, daemon=True).start()

def _pids_proteges() -> set:
    """PID d'Alyx lui-même et de ses parents (lanceur venv, cmd...)."""
    pids = {os.getpid()}
    try:
        for parent in psutil.Process().parents():
            pids.add(parent.pid)
    except psutil.Error:
        pass
    return pids

def ouvrir_explorateur() -> str:
    """Ouvre l'explorateur de fichiers."""
    if sys.platform == "win32":
        os.startfile('.')
    elif sys.platform == "darwin":
        subprocess.Popen(['open', '.'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(['xdg-open', '.'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "L'explorateur a été ouvert avec succès."

def ouvrir_application(nom_commande: str) -> str:
    """Lance une application installée.

    Args:
        nom_commande: Nom de l'application (ex: 'firefox', 'discord', 'notepad').
    """
    nom_propre = str(nom_commande).lower().strip()
    alias = _get_alias()
    cible = alias.get(nom_propre) or alias.get(nom_propre.removesuffix('.exe'))

    try:
        if cible:
            if sys.platform == "win32":
                os.startfile(cible)
            else:
                # Commande issue du fichier .desktop du système (pas du LLM)
                subprocess.Popen(shlex.split(cible), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return f"L'application '{nom_propre}' a été lancée."

        # Hors alias : uniquement un nom d'exécutable simple présent dans le PATH, sans arguments
        if not nom_propre or os.path.basename(nom_propre) != nom_propre or any(c in nom_propre for c in ' \t/\\'):
            return f"Erreur: '{nom_commande}' n'est pas un nom d'application valide."
        executable = shutil.which(nom_propre)
        if not executable:
            return f"Erreur: l'application '{nom_propre}' est introuvable."
        subprocess.Popen([executable], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=(sys.platform != "win32"))
        return f"L'application a été lancée via '{executable}'."
    except (OSError, ValueError) as e:
        return f"Erreur lors du lancement de '{nom_propre}': {e}"

def lister_apps_actives() -> str:
    """Liste les applications courantes en cours d'exécution."""
    if sys.platform == "win32":
        apps_courantes = ['explorer.exe', 'notepad.exe', 'firefox.exe', 'chrome.exe', 'brave.exe', 'discord.exe']
    else:
        apps_courantes = ['dolphin', 'kate', 'firefox', 'brave', 'brave-browser', 'discord', 'konsole', 'steam']
    compteurs = {app: 0 for app in apps_courantes}
    # Un seul parcours de la table des processus
    for proc in psutil.process_iter(['name', 'status']):
        nom = (proc.info.get('name') or '').lower()
        if nom in compteurs and proc.info.get('status') != psutil.STATUS_ZOMBIE:
            compteurs[nom] += 1
    resultat = ""
    for app, count in compteurs.items():
        if count == 1:
            resultat += f"- {app} (1 instance)\n"
        elif count > 1:
            resultat += f"- {app} ({count} instances en cours)\n"
    return resultat if resultat else "Aucune application surveillée n'est actuellement ouverte."

def fermer_application(nom_app: str) -> str:
    """Ferme une application (termine ses processus).

    Args:
        nom_app: Nom du processus de l'application (ex: 'firefox', 'discord').
    """
    nom_propre = str(nom_app).lower().strip().replace('.desktop', '')
    if sys.platform == "win32" and not nom_propre.endswith('.exe'):
        nom_propre += '.exe'

    if nom_propre in PROCESSUS_PROTEGES:
        return f"Erreur : '{nom_propre}' est un processus protégé, fermeture refusée."

    pids_proteges = _pids_proteges()
    processus_cibles = []
    for proc in psutil.process_iter(['name', 'status']):
        try:
            if proc.info.get('status') == psutil.STATUS_ZOMBIE or proc.pid in pids_proteges:
                continue
            if proc.info.get('name') and proc.info['name'].lower() == nom_propre:
                processus_cibles.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not processus_cibles:
        return f"Aucune instance active de '{nom_propre}' n'a été trouvée."

    instances_fermees = 0

    # Tentative de fermeture propre (SIGTERM)
    for proc in processus_cibles:
        try:
            logger.info(f"Tentative de fermeture (SIGTERM) du processus {proc.pid} ({nom_propre})")
            proc.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Attente maximale de 3 secondes pour libérer la mémoire proprement
    gone, alive = psutil.wait_procs(processus_cibles, timeout=3.0)
    instances_fermees += len(gone)

    # Forçage (SIGKILL) des processus récalcitrants
    if alive:
        logger.warning(f"Processus {len(alive)} instance(s) de {nom_propre} résistent, utilisation de SIGKILL")
        for proc in alive:
            try:
                proc.kill()
                proc.wait(timeout=1.0)
                instances_fermees += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                pass

    if instances_fermees > 0:
        return f"Le processus de l'application '{nom_propre}' a été terminé avec succès ({instances_fermees} instances fermées)."
    return f"Erreur : Impossible de terminer l'application '{nom_app}'."

_TOUCHES_MEDIA = {'lecture_pause': (0xB3, 'play-pause'), 'suivant': (0xB0, 'next'), 'precedent': (0xB1, 'previous')}

def controler_media(action: str) -> str:
    """Contrôle la lecture multimédia en cours (Spotify, navigateur, lecteur vidéo...).

    Args:
        action: 'lecture_pause' (lecture ou pause), 'suivant' ou 'precedent'.
    """
    cle = str(action).lower().strip().replace('-', '_').replace(' ', '_')
    cle = {'pause': 'lecture_pause', 'play': 'lecture_pause', 'lecture': 'lecture_pause', 'next': 'suivant',
           'previous': 'precedent', 'précédent': 'precedent'}.get(cle, cle)
    if cle not in _TOUCHES_MEDIA:
        return "Erreur: action inconnue (utilise 'lecture_pause', 'suivant' ou 'precedent')."
    code_touche, commande_playerctl = _TOUCHES_MEDIA[cle]
    try:
        if sys.platform == "win32":
            import ctypes
            # Touche multimédia virtuelle : comprise par tous les lecteurs Windows
            ctypes.windll.user32.keybd_event(code_touche, 0, 0, 0)
            ctypes.windll.user32.keybd_event(code_touche, 0, 2, 0)  # KEYEVENTF_KEYUP
        else:
            subprocess.run(["playerctl", commande_playerctl], check=True, timeout=3,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"Commande multimédia '{cle}' envoyée."
    except (OSError, subprocess.SubprocessError) as e:
        return f"Erreur lors du contrôle multimédia : {e}"

def redemarrer_pc() -> str:
    """Redémarre l'ordinateur (permission requise)."""
    from function.files import _demander_permission
    _demander_permission("REDEMARRER le PC", "Système d'exploitation")

    try:
        if sys.platform == "win32":
            subprocess.Popen(["shutdown", "/r", "/t", "0"])
        else:
            subprocess.Popen(["systemctl", "reboot"])
        return "Le redémarrage du système a été initié."
    except Exception as e:
        return f"Erreur lors de la tentative de redémarrage : {e}"
