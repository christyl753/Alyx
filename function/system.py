import os
import sys
import subprocess
import psutil
import time
from .scrap import construire_dictionnaire_applications
from core.logger import get_logger

logger = get_logger('alyx.system')

logger.info("Scan des applications installées...")
print("     [Initialisation : Scan des applications installées...]")
ALIAS_DYNAMIQUES = construire_dictionnaire_applications()
logger.info(f"{len(ALIAS_DYNAMIQUES)} alias d'applications générés.")
print(f"     [Succès : {len(ALIAS_DYNAMIQUES)} alias d'applications générés !]")

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
    """Lance une application via son nom système."""
    nom_propre = nom_commande.lower().strip()
    commande_reelle = ALIAS_DYNAMIQUES.get(nom_propre, nom_propre)
    try:
        subprocess.Popen(commande_reelle.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"L'application a été lancée via la commande système '{commande_reelle}'."
    except FileNotFoundError:
        return f"Erreur: la commande système '{commande_reelle}' est introuvable."

def lister_apps_actives() -> str:
    """Liste les applications courantes en cours d'exécution."""
    if sys.platform == "win32":
        apps_courantes = ['explorer.exe', 'notepad.exe', 'firefox.exe', 'chrome.exe', 'brave.exe', 'discord.exe']
    else:
        apps_courantes = ['dolphin', 'kate', 'firefox', 'brave', 'brave-browser', 'discord', 'konsole', 'steam']
    resultat = ""
    for app in apps_courantes:
        count = 0
        for proc in psutil.process_iter(['name', 'status']):
            if proc.info['name'] and proc.info['name'].lower() == app.lower():
                if proc.info['status'] != psutil.STATUS_ZOMBIE:
                    count += 1
        if count == 1:
            resultat += f"- {app} (1 instance)\n"
        elif count > 1:
            resultat += f"- {app} ({count} instances en cours)\n"
    return resultat if resultat else "Aucune application surveillée n'est actuellement ouverte."

def fermer_application(nom_app: str) -> str:
    """Ferme (tue le processus) une application via son nom."""
    nom_propre = nom_app.lower().strip().replace('.desktop', '')
    if sys.platform == "win32" and not nom_propre.endswith('.exe'):
        nom_propre += '.exe'
        
    processus_cibles = []
    for proc in psutil.process_iter(['name', 'status']):
        try:
            if proc.info.get('status') == psutil.STATUS_ZOMBIE:
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
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
                
    if instances_fermees > 0:
        return f"Le processus de l'application '{nom_propre}' a été terminé avec succès ({instances_fermees} instances fermées)."
    return f"Erreur : Impossible de terminer l'application '{nom_app}'."

def redemarrer_pc() -> str:
    """Redémarre l'ordinateur."""
    from function.files import _demander_permission
    _demander_permission("REDEMARRER le PC", "Système d'exploitation")
    
    try:
        if sys.platform == "win32":
            os.system("shutdown /r /t 0")
        else:
            os.system("reboot")
        return "Le redémarrage du système a été initié."
    except Exception as e:
        return f"Erreur lors de la tentative de redémarrage : {e}"
