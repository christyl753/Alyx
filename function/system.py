import base64
import ctypes
import os
import re
import sys
import shlex
import shutil
import subprocess
import tempfile
import threading
import psutil
from .scrap import construire_dictionnaire_applications
from .files import _demander_permission
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

# Services système critiques que le LLM ne doit jamais arrêter ou désactiver
SERVICES_PROTEGES = {
    # Windows
    'rpcss', 'dcomlaunch', 'plugplay', 'lsass', 'samss', 'winmgmt',
    'mpssvc', 'windefend', 'bfe', 'dhcp', 'dnscache', 'nsi',
    'eventlog', 'schedule', 'profsvc', 'cryptsvc', 'lsm', 'trustedinstaller',
    'power', 'gpsvc', 'systemeventsbroker', 'wscsvc',
    # Linux
    'systemd-journald', 'systemd-logind', 'systemd-udevd', 'systemd-resolved',
    'dbus', 'dbus-broker', 'networkmanager', 'polkit', 'sddm', 'gdm',
    'display-manager', 'firewalld',
}

# Expressions régulières bloquant les commandes destructrices dans executer_commande_systeme
COMMANDES_INTERDITES_REGEX = [
    re.compile(p, re.IGNORECASE) for p in (
        r'(?:^|[;&|]\s*)format(?:\.com)?\s+[a-z]:',
        r'\b(?:format-volume|clear-disk|diskpart|bcdedit)\b',
        r'\bcipher(?:\.exe)?\s+/w',
        r'\b(?:remove-item|ri|rm|del|erase|rd|rmdir)\b[^\n;|&]*(?:-r\b|-recurse\b|/s\b)[^\n;|&]*\b[a-z]:\\(?:\s|$|\*|["\'])',
        r'\b(?:remove-item|ri|rm|del|erase|rd|rmdir)\b[^\n;|&]*\b[a-z]:\\(?:\s|\*|["\'])[^\n;|&]*(?:-r\b|-recurse\b|/s\b)',
        r'\brm\s+[^\n;|&]*-[a-z]*r[a-z]*\s+[^\n;|&]*(?:/\s*$|/\*|~)',
        r'\bdd\s+[^\n;|&]*\bof=/dev/',
        r'\bmkfs(?:\.[a-z0-9]+)?\b',
    )
]

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

    # Sous Windows 64-bit, NtQuerySystemInformation via _lister_windows prend ~5 ms contre ~7.5 s avec psutil en non-admin
    utilise_fast_win = False
    if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
        try:
            from core.system_monitor import _lister_windows
            for pid, _, nom_brut, _, _ in _lister_windows():
                if pid == 0:
                    continue
                nom = (nom_brut or '').lower()
                if nom in compteurs:
                    compteurs[nom] += 1
            utilise_fast_win = True
        except Exception:
            compteurs = {app: 0 for app in apps_courantes}

    if not utilise_fast_win:
        for proc in psutil.process_iter(['name', 'status']):
            try:
                nom = (proc.info.get('name') or '').lower()
                if nom in compteurs and proc.info.get('status') != psutil.STATUS_ZOMBIE:
                    compteurs[nom] += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

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
    _demander_permission("REDEMARRER le PC", "Système d'exploitation")

    try:
        if sys.platform == "win32":
            subprocess.Popen(["shutdown", "/r", "/t", "0"])
        else:
            subprocess.Popen(["systemctl", "reboot"])
        return "Le redémarrage du système a été initié."
    except Exception as e:
        return f"Erreur lors de la tentative de redémarrage : {e}"


# --- EXÉCUTION POWERSHELL & ÉLÉVATION UAC ---
def _est_admin() -> bool:
    """Vérifie si le processus courant dispose des privilèges administrateur."""
    if sys.platform == "win32":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0 if hasattr(os, 'geteuid') else False


def _run_ps(script: str, timeout: int = 15, extra_env: dict | None = None) -> tuple[int, str]:
    """Exécute un script PowerShell sans fenêtre console et retourne (returncode, sortie)."""
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    cmd_script = f"[Console]::OutputEncoding = [System.Text.Encoding]::UTF8; {script}"
    env = {**os.environ, **{k: str(v) for k, v in extra_env.items()}} if extra_env else None
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", cmd_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=flags,
            env=env,
        )
        sortie = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        if err:
            sortie = f"{sortie}\n{err}".strip()
        return res.returncode, sortie
    except subprocess.TimeoutExpired:
        return -1, f"Erreur : Délai d'attente dépassé ({timeout}s)."
    except Exception as e:
        return -1, f"Erreur PowerShell : {e}"


def _run_ps_admin(script: str, timeout: int = 30, extra_env: dict | None = None) -> tuple[int, str]:
    """Exécute un script PowerShell avec élévation UAC via -EncodedCommand (sans fichier .ps1, gère les espaces dans %TEMP%)."""
    if _est_admin():
        return _run_ps(script, timeout=timeout, extra_env=extra_env)

    fd, out_path = tempfile.mkstemp(prefix="alyx_admin_", suffix=".out")
    os.close(fd)

    env_lines = []
    for k, v in (extra_env or {}).items():
        if re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', k):
            b64_val = base64.b64encode(str(v).encode('utf-8')).decode('ascii')
            env_lines.append(f"$env:{k} = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{b64_val}'))")

    b64_out = base64.b64encode(out_path.encode('utf-8')).decode('ascii')
    env_header = "\n".join(env_lines)
    wrapper = (
        "$ErrorActionPreference = 'Continue'\n"
        f"$__alyx_out = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{b64_out}'))\n"
        f"{env_header}\n"
        "$__alyx_code = 0\n"
        "& {\n"
        "    try {\n"
        f"{script}\n"
        "    } catch {\n"
        "        Write-Output $_.Exception.Message\n"
        "        $script:__alyx_code = 1\n"
        "    }\n"
        "} *>&1 | Out-File -FilePath $__alyx_out -Encoding utf8\n"
        "if ($LASTEXITCODE -and $__alyx_code -eq 0) { $__alyx_code = $LASTEXITCODE }\n"
        "exit $__alyx_code\n"
    )
    encoded_cmd = base64.b64encode(wrapper.encode('utf-16-le')).decode('ascii')
    try:
        elevate_cmd = (
            f"$p = Start-Process powershell -ArgumentList '-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-EncodedCommand','{encoded_cmd}' "
            f"-Verb RunAs -Wait -WindowStyle Hidden -PassThru; exit $p.ExitCode"
        )
        code, err = _run_ps(elevate_cmd, timeout=timeout)
        sortie = ""
        if os.path.exists(out_path):
            with open(out_path, "r", encoding="utf-8-sig", errors="replace") as f:
                sortie = f.read().strip()
        if code != 0 and not sortie:
            return code, err or "Élévation administrateur (UAC) refusée ou annulée."
        return code, sortie
    finally:
        try:
            if os.path.exists(out_path):
                os.remove(out_path)
        except OSError:
            pass


# --- ADMINISTRATION AVANCÉE (PROCESSUS, SERVICES, TÂCHES, DÉMARRAGE, TÉLÉMÉTRIE) ---
def rechercher_processus(filtre: str = "") -> str:
    """Recherche parmi tous les processus actifs du PC (triés par consommation RAM décroissante).

    Args:
        filtre: Sous-chaîne optionnelle pour filtrer par nom de processus (ex: 'telemetry', 'compat', 'chrome'). Vide pour lister les 50 processus les plus gourmands.
    """
    f_low = str(filtre or "").lower().strip()
    items = []
    utilise_fast_win = False
    if sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8:
        try:
            from core.system_monitor import _lister_windows
            for pid, _, nom_brut, _, working_set in _lister_windows():
                if pid == 0:
                    continue
                nom = nom_brut or 'inconnu'
                if f_low and f_low not in nom.lower():
                    continue
                items.append((working_set, pid, nom))
            utilise_fast_win = True
        except Exception:
            items = []

    if not utilise_fast_win:
        for proc in psutil.process_iter(['pid', 'name', 'memory_info', 'status']):
            try:
                info = proc.info
                if info.get('status') == psutil.STATUS_ZOMBIE:
                    continue
                nom = info.get('name') or 'inconnu'
                if f_low and f_low not in nom.lower():
                    continue
                mem = getattr(info.get('memory_info'), 'rss', 0) or 0
                items.append((mem, info.get('pid'), nom))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    if not items:
        return f"Aucun processus actif trouvé pour le filtre '{filtre}'." if f_low else "Aucun processus actif trouvé."

    items.sort(key=lambda x: x[0], reverse=True)
    lignes = [f"- {nom} (PID: {pid}, RAM: {mem / (1024 * 1024):.1f} MB)" for mem, pid, nom in items[:50]]
    entete = f"Processus actifs correspondant à '{filtre}' ({len(items)} trouvés) :" if f_low else f"Top {len(lignes)} processus actifs (sur {len(items)}) :"
    return entete + "\n" + "\n".join(lignes)


def lister_services(filtre: str = "") -> str:
    """Liste les services système (Windows ou Linux) et leur état de fonctionnement et de démarrage.

    Args:
        filtre: Mot-clé optionnel pour filtrer par nom ou description (ex: 'diagtrack', 'telemetry', 'xbox'). Vide pour afficher les services de télémétrie/diagnostic connus et les services actifs.
    """
    f_low = str(filtre or "").lower().strip()
    if sys.platform == "win32":
        telemetrie_connus = {
            'diagtrack', 'dmwappushservice', 'diagnosticshub.standardcollector.service',
            'diagsvc', 'wersvc', 'wercplsupport', 'pcaasvc', 'dps', 'wdiservicehost', 'wdisystemhost',
        }
        prioritaires = []
        autres = []
        try:
            for svc in psutil.win_service_iter():
                try:
                    name = svc.name()
                    display = svc.display_name()
                    status = svc.status()
                    start_type = svc.start_type()
                except Exception:
                    continue
                n_low = name.lower()
                d_low = display.lower()
                ligne = f"- {name} ({display}) [État: {status}, Démarrage: {start_type}]"
                if f_low:
                    if f_low in n_low or f_low in d_low:
                        prioritaires.append(ligne)
                else:
                    if n_low in telemetrie_connus or 'telemetr' in d_low or 'télémétr' in d_low or 'diagnostic' in d_low:
                        prioritaires.append(ligne)
                    elif status == 'running' and len(autres) < 40:
                        autres.append(ligne)
        except Exception as e:
            return f"Erreur lors de la lecture des services Windows : {e}"

        selection = (prioritaires + autres)[:50]
        if not selection:
            return f"Aucun service trouvé pour le filtre '{filtre}'."
        return f"Services trouvés ({len(selection)} affichés) :\n" + "\n".join(selection)
    else:
        try:
            res = subprocess.run(
                ["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"],
                capture_output=True, text=True, errors="replace", timeout=10
            )
            lignes = [l.strip() for l in (res.stdout or "").splitlines() if l.strip()]
            if f_low:
                lignes = [l for l in lignes if f_low in l.lower()]
            if not lignes:
                return f"Aucun service Linux trouvé pour '{filtre}'."
            return "Services Linux :\n" + "\n".join(f"- {l}" for l in lignes[:50])
        except Exception as e:
            return f"Erreur systemctl : {e}"


def gerer_service(nom_service: str, action: str) -> str:
    """Arrête, démarre, active ou désactive un service système (permission requise).

    Args:
        nom_service: Nom technique du service (ex: 'DiagTrack', 'dmwappushservice').
        action: Action à effectuer : 'arreter', 'demarrer', 'desactiver' (arrête et désactive au démarrage) ou 'activer'.
    """
    nom = str(nom_service or "").strip()
    if not nom or not re.match(r'^[A-Za-z0-9_.\$][A-Za-z0-9_.\-@\$ ]*$', nom):
        return f"Erreur : Nom de service invalide '{nom_service}'."

    if nom.lower().removesuffix('.service') in SERVICES_PROTEGES:
        return f"Erreur : Le service '{nom}' est un service système critique protégé et ne peut pas être modifié."

    act_map = {
        'arreter': 'arreter', 'arrêter': 'arreter', 'stop': 'arreter',
        'demarrer': 'demarrer', 'démarrer': 'demarrer', 'start': 'demarrer',
        'desactiver': 'desactiver', 'désactiver': 'desactiver', 'disable': 'desactiver',
        'activer': 'activer', 'enable': 'activer',
    }
    act = act_map.get(str(action or "").lower().strip())
    if not act:
        return "Erreur : action invalide (utilise 'arreter', 'demarrer', 'desactiver' ou 'activer')."

    _demander_permission(f"SERVICE ({act.upper()})", nom)

    if sys.platform == "win32":
        if act == 'arreter':
            ps = 'Stop-Service -Name $env:ALYX_SVC -Force -ErrorAction Stop; Write-Output "Succès : Service \'$($env:ALYX_SVC)\' arrêté."'
        elif act == 'demarrer':
            ps = 'Start-Service -Name $env:ALYX_SVC -ErrorAction Stop; Write-Output "Succès : Service \'$($env:ALYX_SVC)\' démarré."'
        elif act == 'desactiver':
            ps = (
                'Stop-Service -Name $env:ALYX_SVC -Force -ErrorAction SilentlyContinue; '
                'Set-Service -Name $env:ALYX_SVC -StartupType Disabled -ErrorAction Stop; '
                'Write-Output "Succès : Service \'$($env:ALYX_SVC)\' arrêté et désactivé au démarrage."'
            )
        else:
            ps = (
                'Set-Service -Name $env:ALYX_SVC -StartupType Manual -ErrorAction Stop; '
                'Start-Service -Name $env:ALYX_SVC -ErrorAction SilentlyContinue; '
                'Write-Output "Succès : Service \'$($env:ALYX_SVC)\' réactivé (démarrage manuel) et démarré."'
            )
        code, sortie = _run_ps_admin(ps, extra_env={'ALYX_SVC': nom})
        if code != 0:
            return f"Erreur lors de l'action '{act}' sur le service '{nom}' : {sortie}"
        return sortie or f"Succès : Action '{act}' appliquée au service '{nom}'."
    else:
        cmd_map = {'arreter': ['stop'], 'demarrer': ['start'], 'desactiver': ['disable', '--now'], 'activer': ['enable', '--now']}
        prefix = [] if _est_admin() else ["pkexec"]
        try:
            res = subprocess.run(prefix + ["systemctl"] + cmd_map[act] + ["--", nom], capture_output=True, text=True, errors="replace", timeout=30)
            if res.returncode == 0:
                return f"Succès : Action '{act}' appliquée au service '{nom}'."
            return f"Erreur systemctl : {(res.stderr or res.stdout).strip()}"
        except Exception as e:
            return f"Erreur lors de la gestion du service '{nom}' : {e}"


def lister_taches_planifiees(filtre: str = "") -> str:
    """Liste les tâches planifiées du système (Planificateur de tâches Windows ou timers systemd Linux).

    Args:
        filtre: Mot-clé optionnel pour filtrer par nom ou chemin de tâche (ex: 'Application Experience', 'Customer Experience', 'telemetry'). Vide pour lister les tâches actives.
    """
    f_raw = str(filtre or "").strip()
    if sys.platform == "win32":
        if f_raw:
            ps = (
                "$f = $env:ALYX_FILTER\n"
                "$all = @(Get-ScheduledTask | Where-Object { "
                "$_.TaskName.IndexOf($f, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 -or "
                "$_.TaskPath.IndexOf($f, [System.StringComparison]::OrdinalIgnoreCase) -ge 0 })\n"
                "$total = $all.Count\n"
                "$all | Select-Object -First 50 | ForEach-Object { \"- $($_.TaskPath)$($_.TaskName) [État: $($_.State)]\" }\n"
                "if ($total -gt 50) { Write-Output \"[... $($total - 50) autres tâches masquées, précisez le filtre]\" }"
            )
        else:
            ps = (
                "$all = @(Get-ScheduledTask | Where-Object { $_.State -ne 'Disabled' })\n"
                "$total = $all.Count\n"
                "$all | Select-Object -First 50 | ForEach-Object { \"- $($_.TaskPath)$($_.TaskName) [État: $($_.State)]\" }\n"
                "if ($total -gt 50) { Write-Output \"[... $($total - 50) autres tâches masquées, précisez le filtre]\" }"
            )
        code, sortie = _run_ps(ps, timeout=20, extra_env={'ALYX_FILTER': f_raw})
        if code != 0:
            return f"Erreur lors de la lecture des tâches planifiées : {sortie}"
        if not sortie:
            return f"Aucune tâche planifiée trouvée pour '{filtre}'." if f_raw else "Aucune tâche planifiée active trouvée."
        return f"Tâches planifiées ({'filtre: ' + f_raw if f_raw else 'actives'}) :\n{sortie}"
    else:
        try:
            res = subprocess.run(["systemctl", "list-timers", "--all", "--no-pager", "--no-legend"], capture_output=True, text=True, errors="replace", timeout=10)
            if res.returncode != 0:
                return f"Erreur systemctl list-timers : {(res.stderr or res.stdout).strip()}"
            lignes = [l.strip() for l in (res.stdout or "").splitlines() if l.strip()]
            if f_raw:
                f_low = f_raw.lower()
                lignes = [l for l in lignes if f_low in l.lower()]
            if not lignes:
                return f"Aucun timer systemd trouvé pour '{f_raw}'." if f_raw else "Aucun timer systemd trouvé."
            out = "\n".join(f"- {l}" for l in lignes[:50])
            if len(lignes) > 50:
                out += f"\n[... {len(lignes) - 50} autres timers masqués, précisez le filtre]"
            return f"Timers systemd :\n{out}"
        except Exception as e:
            return f"Erreur lors du listage des timers : {e}"


def gerer_tache_planifiee(nom_ou_chemin: str, action: str) -> str:
    """Active, désactive ou arrête une tâche planifiée du système (permission requise).

    Args:
        nom_ou_chemin: Nom de la tâche (ex: 'Consolidator') ou chemin complet (ex: '\\Microsoft\\Windows\\Application Experience\\Microsoft Compatibility Appraiser').
        action: Action à effectuer : 'desactiver', 'activer' ou 'arreter'.
    """
    cible = str(nom_ou_chemin or "").strip()
    if not cible:
        return "Erreur : Nom ou chemin de tâche manquant."

    act_map = {
        'desactiver': 'desactiver', 'désactiver': 'desactiver', 'disable': 'desactiver',
        'activer': 'activer', 'enable': 'activer',
        'arreter': 'arreter', 'arrêter': 'arreter', 'stop': 'arreter',
    }
    act = act_map.get(str(action or "").lower().strip())
    if not act:
        return "Erreur : action invalide (utilise 'desactiver', 'activer' ou 'arreter')."

    _demander_permission(f"TACHE PLANIFIEE ({act.upper()})", cible)

    if sys.platform == "win32":
        cmd_action = {
            'desactiver': "$t | Stop-ScheduledTask -ErrorAction SilentlyContinue; $t | Disable-ScheduledTask -ErrorAction Stop | Out-Null",
            'activer': "$t | Enable-ScheduledTask -ErrorAction Stop | Out-Null",
            'arreter': "$t | Stop-ScheduledTask -ErrorAction Stop | Out-Null",
        }[act]
        ps = (
            "$cible = $env:ALYX_TASK\n"
            "$t = @(Get-ScheduledTask | Where-Object { ($_.TaskPath + $_.TaskName) -eq $cible -or $_.TaskName -eq $cible })\n"
            "if ($t.Count -eq 0) { throw \"Introuvable : Aucune tâche ne correspond à '$cible'.\" }\n"
            f"{cmd_action}\n"
            "Write-Output \"Succès : Action '$($env:ALYX_ACT)' appliquée sur $($t.Count) tâche(s) ($cible).\""
        )
        code, sortie = _run_ps_admin(ps, extra_env={'ALYX_TASK': cible, 'ALYX_ACT': act})
        if code != 0:
            return f"Erreur sur la tâche planifiée '{cible}' : {sortie}"
        return sortie
    else:
        if not re.match(r'^[A-Za-z0-9_.\$][A-Za-z0-9_.\-@\$]*$', cible):
            return f"Erreur : Nom de timer invalide '{cible}'."
        cible_unit = cible if cible.endswith(('.timer', '.service')) else f"{cible}.timer"
        cmd_map = {'desactiver': ['disable', '--now'], 'activer': ['enable', '--now'], 'arreter': ['stop']}
        prefix = [] if _est_admin() else ["pkexec"]
        try:
            res = subprocess.run(prefix + ["systemctl"] + cmd_map[act] + ["--", cible_unit], capture_output=True, text=True, errors="replace", timeout=30)
            if res.returncode == 0:
                return f"Succès : Action '{act}' appliquée au timer '{cible_unit}'."
            return f"Erreur systemctl : {(res.stderr or res.stdout).strip()}"
        except Exception as e:
            return f"Erreur lors de la gestion de la tâche '{cible}' : {e}"


def lister_apps_demarrage() -> str:
    """Liste les applications configurées pour se lancer automatiquement au démarrage du PC."""
    if sys.platform == "win32":
        import winreg
        statut_approbation = {}
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for sub in (
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run",
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder",
            ):
                try:
                    with winreg.OpenKey(hive, sub, 0, winreg.KEY_READ) as k:
                        i = 0
                        while True:
                            try:
                                vname, vdata, _ = winreg.EnumValue(k, i)
                                i += 1
                                if isinstance(vdata, (bytes, bytearray)) and len(vdata) > 0:
                                    # Octet 0 pair (0x02, 0x06) = Activé ; impair (0x03) = Désactivé
                                    statut_approbation[vname.lower()] = "Activé" if (vdata[0] % 2 == 0) else "Désactivé"
                            except OSError:
                                break
                except OSError:
                    pass

        entrees = []
        for label, hive in (("HKCU", winreg.HKEY_CURRENT_USER), ("HKLM", winreg.HKEY_LOCAL_MACHINE)):
            try:
                with winreg.OpenKey(hive, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as k:
                    i = 0
                    while True:
                        try:
                            vname, vdata, _ = winreg.EnumValue(k, i)
                            i += 1
                            etat = statut_approbation.get(vname.lower(), "Activé")
                            entrees.append(f"- {vname} [{label}, État: {etat}] -> {vdata}")
                        except OSError:
                            break
            except OSError:
                pass

        appdata = os.environ.get('APPDATA')
        if appdata:
            startup_dir = os.path.join(appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
            if os.path.isdir(startup_dir):
                for fname in os.listdir(startup_dir):
                    if fname.lower() == 'desktop.ini':
                        continue
                    etat = statut_approbation.get(fname.lower(), "Activé")
                    entrees.append(f"- {fname} [Dossier Startup, État: {etat}]")

        if not entrees:
            return "Aucune application au démarrage trouvée."
        return "Applications au démarrage :\n" + "\n".join(entrees)
    else:
        autostart = os.path.expanduser("~/.config/autostart")
        if not os.path.isdir(autostart):
            return "Aucune entrée dans ~/.config/autostart."
        lignes = []
        for fname in sorted(os.listdir(autostart)):
            if not fname.endswith(".desktop"):
                continue
            fpath = os.path.join(autostart, fname)
            hidden = False
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.strip().lower().startswith("hidden=true"):
                            hidden = True
                            break
            except OSError:
                pass
            lignes.append(f"- {fname} [État: {'Désactivé' if hidden else 'Activé'}]")
        return "Applications au démarrage (Linux) :\n" + "\n".join(lignes) if lignes else "Aucune application au démarrage trouvée."


def gerer_app_demarrage(nom_entree: str, action: str) -> str:
    """Active ou désactive une application au démarrage automatique du PC (permission requise).

    Args:
        nom_entree: Nom exact de l'entrée au démarrage (tel qu'affiché par lister_apps_demarrage).
        action: Action à effectuer : 'desactiver' ou 'activer'.
    """
    nom = str(nom_entree or "").strip()
    if not nom:
        return "Erreur : Nom de l'entrée au démarrage manquant."

    act_map = {
        'desactiver': 'desactiver', 'désactiver': 'desactiver', 'disable': 'desactiver',
        'activer': 'activer', 'enable': 'activer',
    }
    act = act_map.get(str(action or "").lower().strip())
    if not act:
        return "Erreur : action invalide (utilise 'desactiver' ou 'activer')."

    _demander_permission(f"APPLICATION AU DEMARRAGE ({act.upper()})", nom)

    if sys.platform == "win32":
        import winreg
        data_bytes = b'\x03\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00' if act == 'desactiver' else b'\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        # Chercher si l'entrée existe dans HKCU\Run, StartupFolder ou HKLM\Run
        cible_sub = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
        est_hklm = False
        nom_reel = nom

        trouve = False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as k:
                i = 0
                while True:
                    try:
                        vname, _, _ = winreg.EnumValue(k, i)
                        i += 1
                        if vname.lower() == nom.lower():
                            nom_reel = vname
                            trouve = True
                            break
                    except OSError:
                        break
        except OSError:
            pass

        if not trouve:
            appdata = os.environ.get('APPDATA')
            if appdata:
                startup_dir = os.path.join(appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup')
                if os.path.isdir(startup_dir):
                    for fname in os.listdir(startup_dir):
                        if fname.lower() == nom.lower():
                            nom_reel = fname
                            cible_sub = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"
                            trouve = True
                            break

        if not trouve:
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ) as k:
                    i = 0
                    while True:
                        try:
                            vname, _, _ = winreg.EnumValue(k, i)
                            i += 1
                            if vname.lower() == nom.lower():
                                nom_reel = vname
                                est_hklm = True
                                trouve = True
                                break
                        except OSError:
                            break
            except OSError:
                pass

        if not trouve:
            return f"Erreur : Aucune entrée de démarrage nommée '{nom}' n'a été trouvée."

        if not est_hklm:
            try:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, cible_sub, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, nom_reel, 0, winreg.REG_BINARY, data_bytes)
                etat_txt = "désactivée" if act == 'desactiver' else "activée"
                return f"Succès : L'application au démarrage '{nom_reel}' a été {etat_txt}."
            except OSError as e:
                return f"Erreur lors de la modification du registre HKCU : {e}"
        else:
            octet_str = "0x03,0,0,0,0,0,0,0,0,0,0,0" if act == 'desactiver' else "0x02,0,0,0,0,0,0,0,0,0,0,0"
            ps = (
                "$path = 'HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run'\n"
                "if (-not (Test-Path $path)) { New-Item -Path $path -Force | Out-Null }\n"
                f"Set-ItemProperty -Path $path -Name $env:ALYX_ENTRY -Value ([byte[]]({octet_str})) -Type Binary -ErrorAction Stop\n"
                "Write-Output \"Succès : Entrée HKLM '$($env:ALYX_ENTRY)' modifiée ($($env:ALYX_ACT)).\""
            )
            code, sortie = _run_ps_admin(ps, extra_env={'ALYX_ENTRY': nom_reel, 'ALYX_ACT': act})
            if code != 0:
                return f"Erreur lors de la modification HKLM de '{nom_reel}' : {sortie}"
            return sortie
    else:
        autostart = os.path.expanduser("~/.config/autostart")
        fname = nom if nom.endswith(".desktop") else f"{nom}.desktop"
        fpath = os.path.join(autostart, os.path.basename(fname))
        if not os.path.isfile(fpath):
            return f"Erreur : Fichier '{fpath}' introuvable."
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lignes = f.readlines()
            val_hidden = "true" if act == 'desactiver' else "false"
            nouvelles = [l for l in lignes if not l.strip().lower().startswith("hidden=")]
            nouvelles.append(f"Hidden={val_hidden}\n")
            with open(fpath, "w", encoding="utf-8") as f:
                f.writelines(nouvelles)
            return f"Succès : Entrée autostart '{fname}' {'désactivée' if act == 'desactiver' else 'activée'}."
        except OSError as e:
            return f"Erreur lors de la modification de '{fpath}' : {e}"


def desactiver_telemetrie_pc() -> str:
    """Désactive intégralement la télémétrie sur le PC : arrête les processus de télémétrie actifs, coupe et désactive les services de télémétrie, désactive les tâches planifiées de collecte et bloque la télémétrie système (permission requise)."""
    if sys.platform == "win32":
        _demander_permission(
            "DESACTIVER LA TELEMETRIE WINDOWS (Processus, Services, Planificateur de tâches, Registre)",
            "DiagTrack, dmwappushservice, CompatTelRunner, CEIP, Application Experience, SustainabilityTelemetry"
        )
    else:
        _demander_permission(
            "DESACTIVER LA TELEMETRIE LINUX (Services de rapport d'erreurs)",
            "whoopsie, apport, abrtd"
        )

    rapport = []
    if sys.platform == "win32":
        # 1. Terminer les processus de télémétrie actifs accessibles
        procs_telemetrie = {'compattelrunner.exe', 'devicecensus.exe', 'diagtrackrunner.exe', 'wermgr.exe'}
        tues = []
        pids_cibles = []
        if ctypes.sizeof(ctypes.c_void_p) == 8:
            try:
                from core.system_monitor import _lister_windows
                for pid, _, nom_brut, _, _ in _lister_windows():
                    if pid and (nom_brut or '').lower() in procs_telemetrie:
                        pids_cibles.append((pid, (nom_brut or '').lower()))
            except Exception:
                pids_cibles = []
        if pids_cibles:
            for pid, nom in pids_cibles:
                try:
                    psutil.Process(pid).kill()
                    tues.append(f"{nom} (PID {pid})")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        else:
            # Aucun trouvé via NtQuerySystemInformation (ou fallback 32-bit)
            if ctypes.sizeof(ctypes.c_void_p) != 8:
                for proc in psutil.process_iter(['pid', 'name']):
                    try:
                        nom = (proc.info.get('name') or '').lower()
                        if nom in procs_telemetrie:
                            proc.kill()
                            tues.append(f"{nom} (PID {proc.pid})")
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass

        if tues:
            rapport.append("[Processus arrêtés] : " + ", ".join(tues))
        else:
            rapport.append("[Processus] : Aucun processus de télémétrie (CompatTelRunner, DeviceCensus, DiagTrackRunner) actif en mémoire.")

        # 2. Exécution groupée en une seule élévation UAC (Processus élevés, Services, Tâches planifiées, Registre)
        ps_script = r"""
$procs = @('CompatTelRunner', 'DeviceCensus', 'DiagTrackRunner')
foreach ($p in $procs) {
    $running = Get-Process -Name $p -ErrorAction SilentlyContinue
    if ($running) {
        Stop-Process -Name $p -Force -ErrorAction SilentlyContinue
        Write-Output "[Processus (Admin)] : $p terminé."
    }
}

$services = @('DiagTrack', 'dmwappushservice', 'diagnosticshub.standardcollector.service')
foreach ($s in $services) {
    $svc = Get-Service -Name $s -ErrorAction SilentlyContinue
    if ($svc) {
        Stop-Service -Name $s -Force -ErrorAction SilentlyContinue
        Set-Service -Name $s -StartupType Disabled -ErrorAction SilentlyContinue
        $svcAfter = Get-Service -Name $s -ErrorAction SilentlyContinue
        Write-Output "[Service] : $s -> État=$($svcAfter.Status), Démarrage=$($svcAfter.StartType)"
    } else {
        Write-Output "[Service] : $s non présent sur ce système."
    }
}

$taskFolders = @(
    '\Microsoft\Windows\Application Experience\',
    '\Microsoft\Windows\Customer Experience Improvement Program\'
)
foreach ($folder in $taskFolders) {
    $folderTasks = @(Get-ScheduledTask -TaskPath $folder -ErrorAction SilentlyContinue)
    foreach ($ft in $folderTasks) {
        Stop-ScheduledTask -TaskPath $ft.TaskPath -TaskName $ft.TaskName -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskPath $ft.TaskPath -TaskName $ft.TaskName -ErrorAction SilentlyContinue | Out-Null
        Write-Output "[Tâche planifiée] : $($ft.TaskPath)$($ft.TaskName) -> Désactivée"
    }
}

$tasks = @(
    '\Microsoft\Windows\Sustainability\SustainabilityTelemetry',
    '\Microsoft\Windows\Autochk\Proxy',
    '\Microsoft\Windows\DiskDiagnostic\Microsoft-Windows-DiskDiagnosticDataCollector',
    '\Microsoft\Windows\Feedback\Siuf\DmClient',
    '\Microsoft\Windows\Feedback\Siuf\DmClientOnScenarioDownload'
)
foreach ($tpath in $tasks) {
    $splitIdx = $tpath.LastIndexOf('\')
    $folder = $tpath.Substring(0, $splitIdx + 1)
    $name = $tpath.Substring($splitIdx + 1)
    $t = Get-ScheduledTask -TaskPath $folder -TaskName $name -ErrorAction SilentlyContinue
    if ($t) {
        Stop-ScheduledTask -TaskPath $folder -TaskName $name -ErrorAction SilentlyContinue
        Disable-ScheduledTask -TaskPath $folder -TaskName $name -ErrorAction SilentlyContinue | Out-Null
        Write-Output "[Tâche planifiée] : $name -> Désactivée"
    }
}

$regPath = 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\DataCollection'
if (-not (Test-Path $regPath)) {
    New-Item -Path $regPath -Force | Out-Null
}
Set-ItemProperty -Path $regPath -Name 'AllowTelemetry' -Value 0 -Type DWord -Force
Set-ItemProperty -Path $regPath -Name 'MaxTelemetryAllowed' -Value 0 -Type DWord -Force
Write-Output "[Registre] : AllowTelemetry = 0 configuré dans $regPath"
"""
        code, sortie = _run_ps_admin(ps_script, timeout=45)
        if sortie:
            rapport.append(sortie)
        if code != 0 and not sortie:
            rapport.append(f"[Erreur Admin] : L'élévation UAC a échoué ou a été refusée ({code}).")
        return "Rapport de désactivation de la télémétrie :\n" + "\n".join(rapport)
    else:
        sh_script = (
            'for s in whoopsie apport abrtd; do '
            'if systemctl list-unit-files "$s.service" 2>/dev/null | grep -q "$s.service"; then '
            'systemctl disable --now "$s.service" >/dev/null 2>&1 && echo "[Service] : $s désactivé." || echo "[Service] : $s (échec ou déjà inactif)."; '
            'else echo "[Service] : $s non présent sur ce système."; fi; '
            'done'
        )
        prefix = [] if _est_admin() else ["pkexec"]
        try:
            res = subprocess.run(
                prefix + ["sh", "-c", sh_script],
                capture_output=True, text=True, errors="replace", timeout=30
            )
            sortie = (res.stdout or res.stderr or "Terminé").strip()
            return f"Rapport de désactivation de la télémétrie (Linux) :\n{sortie}"
        except Exception as e:
            return f"Erreur lors de la désactivation de la télémétrie sous Linux : {e}"


def executer_commande_systeme(commande: str, admin: bool = False) -> str:
    """Exécute une commande système PowerShell (Windows) ou Bash (Linux) pour l'administration avancée du PC (permission requise).

    Args:
        commande: La commande PowerShell ou Bash à exécuter.
        admin: True si la commande nécessite les privilèges Administrateur (UAC/pkexec), False sinon.
    """
    cmd = str(commande or "").strip()
    if not cmd:
        return "Erreur : La commande est vide."

    est_admin_req = admin.strip().lower() in ('true', '1', 'yes', 'oui') if isinstance(admin, str) else bool(admin)

    for rx in COMMANDES_INTERDITES_REGEX:
        if rx.search(cmd):
            logger.warning(f"Commande système destructrice bloquée : {cmd}")
            return "Erreur : Commande refusée pour des raisons de sécurité (opération destructrice interdite)."

    _demander_permission("EXECUTER UNE COMMANDE SYSTEME" + (" (ADMIN)" if est_admin_req else ""), cmd)

    if sys.platform == "win32":
        code, sortie = _run_ps_admin(cmd, timeout=30) if est_admin_req else _run_ps(cmd, timeout=30)
    else:
        try:
            if est_admin_req and not _est_admin():
                full_cmd = ["pkexec", "bash", "-c", cmd]
            else:
                full_cmd = ["bash", "-c", cmd]
            res = subprocess.run(full_cmd, capture_output=True, text=True, errors="replace", timeout=30)
            code = res.returncode
            sortie = ((res.stdout or "") + ("\n" + res.stderr if res.stderr else "")).strip()
        except Exception as e:
            return f"Erreur d'exécution : {e}"

    if len(sortie) > 4000:
        sortie = sortie[:4000] + "\n...[Sortie tronquée à 4000 caractères]"
    if not sortie:
        sortie = f"Commande exécutée (code retour: {code}, aucune sortie texte)."
    return sortie

