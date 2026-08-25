import os
import re
import sys
import subprocess
import psutil
from .scrap import construire_dictionnaire_applications
from core.logger import get_logger

logger = get_logger('alyx.system')

logger.info("Scan des applications installées...")
print("     [Initialisation : Scan des applications installées...]")
ALIAS_DYNAMIQUES = construire_dictionnaire_applications()
logger.info(f"{len(ALIAS_DYNAMIQUES)} alias d'applications générés.")
print(f"     [Succès : {len(ALIAS_DYNAMIQUES)} alias d'applications générés !]")

# --- RÉSOLUTION DE NOMS D'APPLICATIONS ---
# L'utilisateur parle en langage naturel ("ferme nobara welcome app") alors que le
# système raisonne en noms de processus ("nobara-welcome"). Ce module fait le pont,
# et sert AUSSI BIEN à l'ouverture qu'à la fermeture pour que les deux commandes
# comprennent exactement le même vocabulaire.

# Mots vides : sans valeur discriminante pour identifier une application.
_MOTS_IGNORES = {'app', 'application', 'appli', 'logiciel', 'programme',
                 'le', 'la', 'les', 'l', 'de', 'du', 'des', 'to', 'the'}

# Sous Linux, psutil lit le nom via /proc/<pid>/comm, tronqué à 15 caracteres
# (TASK_COMM_LEN). Une comparaison exacte échoue donc sur tout nom plus long.
_LONGUEUR_COMM_LINUX = 15


def _tokeniser(nom: str) -> list:
    """Découpe un nom d'application en mots significatifs, séparateurs normalisés."""
    nom = nom.lower().strip()
    nom = re.sub(r'\.(desktop|exe|app)$', '', nom)
    tokens = [t for t in re.split(r'[\s\-_.]+', nom) if t]
    significatifs = [t for t in tokens if t not in _MOTS_IGNORES]
    # Si l'utilisateur n'a tapé que des mots vides, on garde les tokens bruts.
    return significatifs or tokens


def _candidats_pour(nom_app: str) -> list:
    """
    Construit la liste des noms de processus plausibles pour une demande utilisateur.
    Ex: "nobara welcome app" -> ['nobara-welcome', 'nobarawelcome', 'nobara_welcome', ...]
    """
    tokens = _tokeniser(nom_app)
    if not tokens:
        return []

    candidats = []

    def ajouter(valeur):
        if not valeur:
            return
        valeur = valeur.lower()
        if valeur not in candidats:
            candidats.append(valeur)

    # 1. Recompositions directes des mots de l'utilisateur.
    for separateur in ('-', '', '_', ' '):
        ajouter(separateur.join(tokens))

    # 2. Résolution via le dictionnaire .desktop : on cherche une entrée dont les
    #    mots significatifs correspondent exactement à ceux demandés, quel que soit
    #    l'ordre ("nobara welcome" trouve "welcome to nobara").
    demande = set(tokens)
    for cle, commande in ALIAS_DYNAMIQUES.items():
        mots_cle = set(_tokeniser(cle))
        if demande == mots_cle or demande.issubset(mots_cle):
            # La commande peut être un chemin absolu (/usr/bin/nobara-welcome).
            ajouter(os.path.basename(commande))

    return candidats


def _noms_du_processus(proc) -> list:
    """Noms comparables d'un processus, en contournant la troncature de /proc/comm."""
    noms = []
    try:
        if proc.info.get('name'):
            noms.append(proc.info['name'].lower())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return noms

    # exe et cmdline ne sont pas tronqués : ils rattrapent les noms longs.
    for accesseur in ('exe', 'cmdline'):
        try:
            valeur = getattr(proc, accesseur)()
            if accesseur == 'cmdline':
                valeur = valeur[0] if valeur else None
            if valeur:
                noms.append(os.path.basename(valeur).lower())
        except (psutil.NoSuchProcess, psutil.AccessDenied, IndexError, OSError):
            continue

    return noms


def _correspond(candidat: str, noms_proc: list) -> bool:
    """Un candidat correspond-il à ce processus ? (tolère la troncature Linux)"""
    for nom in noms_proc:
        if nom == candidat:
            return True
        # Le nom lu est tronqué à 15 caracteres : on compare le préfixe.
        if len(nom) == _LONGUEUR_COMM_LINUX and candidat.startswith(nom):
            return True
        # Suffixe d'exécutable résiduel (ex: "firefox.exe" vs "firefox").
        if nom.rsplit('.', 1)[0] == candidat:
            return True
    return False


def trouver_processus(nom_app: str) -> tuple:
    """
    Cherche les processus actifs correspondant à une demande en langage naturel.
    Retourne (liste_de_processus, nom_reconnu) — nom_reconnu sert à l'utilisateur.
    """
    candidats = _candidats_pour(nom_app)
    if not candidats:
        return [], None

    pid_alyx = os.getpid()
    try:
        pids_proteges = {pid_alyx} | {p.pid for p in psutil.Process(pid_alyx).parents()}
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pids_proteges = {pid_alyx}

    # On teste les candidats par ordre de confiance décroissante et on s'arrête
    # au premier qui trouve quelque chose, pour ne jamais mélanger deux applications.
    for candidat in candidats:
        trouves = []
        for proc in psutil.process_iter(['name', 'status']):
            try:
                if proc.pid in pids_proteges:
                    continue
                if proc.info.get('status') == psutil.STATUS_ZOMBIE:
                    continue
                if _correspond(candidat, _noms_du_processus(proc)):
                    trouves.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        if trouves:
            return trouves, candidat

    return [], None

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
    commande_reelle = ALIAS_DYNAMIQUES.get(nom_propre)

    # Repli sur la résolution tolérante (mêmes règles que fermer_application) :
    # "nobara welcome app" doit lancer /usr/bin/nobara-welcome.
    if not commande_reelle:
        demande = set(_tokeniser(nom_commande))
        for cle, commande in ALIAS_DYNAMIQUES.items():
            if demande and demande.issubset(set(_tokeniser(cle))):
                commande_reelle = commande
                break

    if not commande_reelle:
        commande_reelle = nom_propre

    try:
        subprocess.Popen(commande_reelle.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"L'application a été lancée via la commande système '{commande_reelle}'."
    except FileNotFoundError:
        return (f"Erreur: la commande système '{commande_reelle}' est introuvable. "
                f"L'application '{nom_commande}' n'est peut-être pas installée.")

def lister_apps_actives() -> str:
    """Liste les applications réellement en cours d'exécution."""
    # Plutôt qu'une liste blanche figée (qui rendait invisible toute application non
    # prévue), on croise les processus actifs avec les applications réellement
    # installées (raccourcis .desktop / menu Démarrer). Le nom affiché est celui que
    # l'utilisateur connaît, suivi du nom de processus utilisable par fermer_application.
    executables_connus = {}
    # Index de repli : le lanceur déclaré dans le .desktop porte souvent un nom plus
    # long que le processus réel (brave-browser-stable -> brave). On indexe donc aussi
    # le préfixe, sans jamais écraser une correspondance exacte.
    prefixes_connus = {}
    for cle, commande in ALIAS_DYNAMIQUES.items():
        executable = os.path.basename(commande).lower()
        executables_connus.setdefault(executable, cle)
        racine = executable.split('-')[0]
        if racine != executable:
            prefixes_connus.setdefault(racine, cle)

    trouves = {}
    for proc in psutil.process_iter(['name', 'status']):
        try:
            if proc.info.get('status') == psutil.STATUS_ZOMBIE:
                continue
            noms = [n.rsplit('.', 1)[0] if n.endswith('.exe') else n
                    for n in _noms_du_processus(proc)]
            cible = next((n for n in noms if n in executables_connus), None)
            if cible is None:
                cible = next((n for n in noms if n in prefixes_connus), None)
                if cible is not None:
                    executables_connus.setdefault(cible, prefixes_connus[cible])
            if cible is not None:
                trouves[cible] = trouves.get(cible, 0) + 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if not trouves:
        return "Aucune application graphique connue n'est actuellement ouverte."

    lignes = []
    for executable in sorted(trouves):
        nom_convivial = executables_connus[executable]
        nombre = trouves[executable]
        suffixe = f" ({nombre} instances)" if nombre > 1 else ""
        lignes.append(f"- {nom_convivial} [processus: {executable}]{suffixe}")
    return "\n".join(lignes)

def fermer_application(nom_app: str) -> str:
    """Ferme (tue le processus) une application via son nom."""
    processus_cibles, nom_propre = trouver_processus(nom_app)

    if not processus_cibles:
        return (f"Aucune instance active de '{nom_app}' n'a été trouvée. "
                f"Utilise lister_apps_actives pour voir ce qui tourne réellement.")

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
        # On rappelle le processus réellement visé : l'utilisateur a dit
        # "nobara welcome app", il doit savoir que c'est "nobara-welcome" qui a été fermé.
        return (f"'{nom_app}' (processus '{nom_propre}') a été fermé avec succès "
                f"({instances_fermees} instance(s)).")
    return f"Erreur : Impossible de terminer l'application '{nom_app}' (processus '{nom_propre}')."

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
