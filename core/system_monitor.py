"""Métriques système en direct pour le widget (CPU, RAM, GPU, réseau, batterie, processus).

Aucune dépendance supplémentaire : psutil + NVML chargé via ctypes s'il est présent.
"""
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time

import psutil

from core.logger import get_logger

logger = get_logger('alyx.monitor')

_lock = threading.Lock()


# --- GPU (NVIDIA via NVML, optionnel) ---
class _NvmlUtilization(ctypes.Structure):
    _fields_ = [('gpu', ctypes.c_uint), ('memory', ctypes.c_uint)]

class _NvmlMemory(ctypes.Structure):
    _fields_ = [('total', ctypes.c_ulonglong), ('free', ctypes.c_ulonglong), ('used', ctypes.c_ulonglong)]

class _Nvml:
    def __init__(self):
        self.handle = None
        self.lib = None
        self.name = ''
        try:
            nom = 'nvml.dll' if sys.platform == 'win32' else 'libnvidia-ml.so.1'
            self.lib = ctypes.CDLL(nom)
            if self.lib.nvmlInit_v2() != 0:
                raise OSError('nvmlInit échoué')
            handle = ctypes.c_void_p()
            if self.lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(handle)) != 0:
                raise OSError('aucun GPU NVIDIA')
            self.handle = handle
            buf = ctypes.create_string_buffer(96)
            if self.lib.nvmlDeviceGetName(handle, buf, 96) == 0:
                self.name = buf.value.decode(errors='replace')
        except (OSError, AttributeError) as e:
            logger.debug(f"NVML indisponible: {e}")
            self.handle = None

    def lire(self):
        if self.handle is None:
            return None
        util, mem, temp = _NvmlUtilization(), _NvmlMemory(), ctypes.c_uint()
        try:
            if self.lib.nvmlDeviceGetUtilizationRates(self.handle, ctypes.byref(util)) != 0:
                return None
            self.lib.nvmlDeviceGetMemoryInfo(self.handle, ctypes.byref(mem))
            self.lib.nvmlDeviceGetTemperature(self.handle, 0, ctypes.byref(temp))
        except OSError:
            return None
        return {
            'percent': float(util.gpu),
            'vram_used_gb': round(mem.used / 1024**3, 1),
            'vram_total_gb': round(mem.total / 1024**3, 1),
            'temp': int(temp.value) or None,
            'name': self.name,
        }

_nvml = None

def _gpu():
    global _nvml
    if _nvml is None:
        _nvml = _Nvml()
    return _nvml.lire()


# --- RÉSEAU ---
_net_precedent = None  # (timestamp, bytes_recv, bytes_sent)
_ssid_cache = (0.0, None)

def _ssid():
    """Nom du Wi-Fi courant (mis en cache 30 s : appel à un outil système)."""
    global _ssid_cache
    if time.time() - _ssid_cache[0] < 30:
        return _ssid_cache[1]
    ssid = None
    try:
        if sys.platform == 'win32':
            sortie = subprocess.run(['netsh', 'wlan', 'show', 'interfaces'], capture_output=True, text=True,
                                    timeout=3, creationflags=subprocess.CREATE_NO_WINDOW).stdout
            for ligne in sortie.splitlines():
                cle, _, valeur = ligne.partition(':')
                if cle.strip() == 'SSID' and valeur.strip():
                    ssid = valeur.strip()
                    break
        else:
            sortie = subprocess.run(['iwgetid', '-r'], capture_output=True, text=True, timeout=3).stdout.strip()
            ssid = sortie or None
    except (OSError, subprocess.SubprocessError):
        pass
    _ssid_cache = (time.time(), ssid)
    return ssid

def _ip_locale():
    # connect() sur une socket UDP choisit la route sans envoyer de paquet (compatible air-gapped)
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('10.254.254.254', 1))
            return s.getsockname()[0]
    except OSError:
        return None

def _reseau():
    global _net_precedent
    compteurs = psutil.net_io_counters()
    maintenant = time.time()
    down = up = 0.0
    if _net_precedent:
        dt = max(maintenant - _net_precedent[0], 1e-3)
        down = max(0.0, (compteurs.bytes_recv - _net_precedent[1]) / dt / 1024**2)
        up = max(0.0, (compteurs.bytes_sent - _net_precedent[2]) / dt / 1024**2)
    _net_precedent = (maintenant, compteurs.bytes_recv, compteurs.bytes_sent)
    return {'down_mbs': round(down, 2), 'up_mbs': round(up, 2), 'ssid': _ssid(), 'ip': _ip_locale()}


# --- INSTANTANÉ ---
def snapshot(reseau: bool = True) -> dict:
    """Métriques globales (appel ~1 Hz). Le premier appel renvoie un CPU à 0 (amorçage psutil)."""
    with _lock:
        mem = psutil.virtual_memory()
        freq = None
        try:
            f = psutil.cpu_freq()
            freq = round(f.current / 1000, 1) if f and f.current else None
        except (OSError, NotImplementedError):
            pass
        batterie = None
        try:
            b = psutil.sensors_battery()
            if b is not None:
                restant = b.secsleft if isinstance(b.secsleft, int) and b.secsleft >= 0 else None
                batterie = {'percent': round(b.percent), 'plugged': bool(b.power_plugged), 'secs_left': restant}
        except (OSError, NotImplementedError):
            pass
        return {
            'cpu': {'percent': psutil.cpu_percent(None), 'cores': psutil.cpu_count(logical=True), 'freq_ghz': freq},
            'ram': {'percent': mem.percent, 'used_gb': round(mem.used / 1024**3, 1), 'total_gb': round(mem.total / 1024**3, 1)},
            'gpu': _gpu(),
            'net': _reseau() if reseau else None,
            'battery': batterie,
        }


# --- PROCESSUS ---
def _lister_windows():
    """
    Tous les processus en UN appel NtQuerySystemInformation : [(pid, ppid, nom, temps_cpu_100ns, ram_octets)].
    psutil ouvre chaque processus et, sur refus d'accès, ré-énumère tout le système à chaque fois
    (O(n²) : ~2 s pour 450 processus) ; ici ~5 ms.
    """
    ntdll = ctypes.WinDLL('ntdll')
    taille = ctypes.c_ulong(1 << 20)
    while True:
        buf = ctypes.create_string_buffer(taille.value)
        statut = ntdll.NtQuerySystemInformation(5, buf, taille, ctypes.byref(taille))  # SystemProcessInformation
        if statut == 0:
            break
        if statut & 0xFFFFFFFF != 0xC0000004:  # STATUS_INFO_LENGTH_MISMATCH
            raise OSError(f"NtQuerySystemInformation: 0x{statut & 0xFFFFFFFF:08X}")
        taille = ctypes.c_ulong(taille.value + (1 << 16))
    brut = buf.raw
    base = ctypes.addressof(buf)
    resultat, offset = [], 0
    while True:
        suivant = int.from_bytes(brut[offset:offset + 4], 'little')
        user = int.from_bytes(brut[offset + 40:offset + 48], 'little')
        kernel = int.from_bytes(brut[offset + 48:offset + 56], 'little')
        longueur_nom = int.from_bytes(brut[offset + 56:offset + 58], 'little')
        ptr_nom = int.from_bytes(brut[offset + 64:offset + 72], 'little')
        pid = int.from_bytes(brut[offset + 80:offset + 88], 'little')
        ppid = int.from_bytes(brut[offset + 88:offset + 96], 'little')
        working_set = int.from_bytes(brut[offset + 144:offset + 152], 'little')
        if ptr_nom and longueur_nom:
            debut = ptr_nom - base
            nom = brut[debut:debut + longueur_nom].decode('utf-16-le', errors='replace')
        else:
            nom = 'System Idle Process' if pid == 0 else 'System'
        resultat.append((pid, ppid, nom, user + kernel, working_set))
        if suivant == 0:
            return resultat
        offset += suivant

_cpu_precedent = {}  # pid -> (horodatage, temps_cpu_100ns)

def _pids_alyx(parents, noms):
    """Processus d'Alyx : la chaîne Python de l'API (lanceur venv compris), le STT et l'UI."""
    pids = set()
    pid = os.getpid()
    while pid and pid not in pids and noms.get(pid, '').lower().startswith('python'):
        pids.add(pid)
        pid = parents.get(pid)
    try:
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(racine, 'run', 'stt.pid'), 'r') as f:
            stt = int(f.read().strip())
        pids.add(stt)
        pids.update(p for p, pp in parents.items() if pp == stt)  # interpréteur réel derrière le lanceur venv
    except (OSError, ValueError):
        pass
    pids.update(p for p, nom in noms.items() if nom.lower().startswith('alyxdesktop'))
    return pids

def _lister():
    """([(pid, nom, cpu_pourcent_normalisé, ram_mo)], pids_alyx) ; le CPU est calculé par différence entre deux appels."""
    global _cpu_precedent
    nb_coeurs = psutil.cpu_count(logical=True) or 1
    maintenant = time.time()
    liste, parents, noms = [], {}, {}
    if sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p) == 8:
        courant = {}
        for pid, ppid, nom, temps_cpu, ws in _lister_windows():
            if pid == 0:
                continue
            parents[pid], noms[pid] = ppid, nom
            courant[pid] = (maintenant, temps_cpu)
            cpu = 0.0
            if pid in _cpu_precedent:
                t0, c0 = _cpu_precedent[pid]
                if maintenant > t0:
                    cpu = (temps_cpu - c0) / 1e7 / (maintenant - t0) * 100 / nb_coeurs
            liste.append((pid, nom, max(0.0, cpu), ws / 1024**2))
        _cpu_precedent = courant
    else:
        for proc in psutil.process_iter(['name', 'ppid', 'cpu_percent', 'memory_info']):
            if proc.pid == 0:
                continue
            nom = proc.info.get('name') or '?'
            parents[proc.pid], noms[proc.pid] = proc.info.get('ppid'), nom
            mem = proc.info.get('memory_info')
            liste.append((proc.pid, nom, (proc.info.get('cpu_percent') or 0.0) / nb_coeurs,
                          mem.rss / 1024**2 if mem else 0))
    return liste, _pids_alyx(parents, noms)

def processus(limite: int = 40) -> dict:
    """Processus triés par CPU (normalisé sur tous les cœurs), puis par mémoire."""
    with _lock:
        liste, pids_alyx = _lister()
    items = [{
        'pid': pid,
        'name': nom,
        'cpu': round(cpu, 1),
        'mem_mb': round(ram),
        'alyx': pid in pids_alyx,
    } for pid, nom, cpu, ram in liste]
    items.sort(key=lambda p: (p['cpu'], p['mem_mb']), reverse=True)
    return {'total': len(items), 'items': items[:limite]}

def terminer_processus(pid: int) -> tuple:
    """Termine un processus depuis l'UI (SIGTERM puis SIGKILL). Refuse les processus protégés et Alyx."""
    from function.system import PROCESSUS_PROTEGES, _pids_proteges
    try:
        proc = psutil.Process(int(pid))
        nom = proc.name().lower()
        if nom in PROCESSUS_PROTEGES or proc.pid in _pids_proteges():
            return False, f"'{proc.name()}' est un processus protégé."
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except psutil.TimeoutExpired:
            proc.kill()
        return True, f"'{proc.name()}' a été terminé."
    except psutil.NoSuchProcess:
        return True, "Le processus n'existe plus."
    except psutil.AccessDenied:
        return False, "Accès refusé (processus système ou d'un autre utilisateur)."
    except (ValueError, TypeError):
        return False, "PID invalide."


def resume_pour_llm() -> str:
    """Contexte système compact injecté dans le prompt (« qu'est-ce qui mange ma RAM ? »)."""
    s = snapshot(reseau=False)
    top = processus(limite=5)['items']
    lignes = [
        f"CPU {s['cpu']['percent']:.0f} %",
        f"RAM {s['ram']['percent']:.0f} % ({s['ram']['used_gb']} / {s['ram']['total_gb']} Go)",
    ]
    if s['gpu']:
        lignes.append(f"GPU {s['gpu']['percent']:.0f} % (VRAM {s['gpu']['vram_used_gb']} / {s['gpu']['vram_total_gb']} Go)")
    if s['battery']:
        lignes.append(f"batterie {s['battery']['percent']} %{' (secteur)' if s['battery']['plugged'] else ''}")
    procs = ", ".join(f"{p['name']} ({p['cpu']} % CPU, {p['mem_mb']} Mo)" for p in top)
    return "État du système en direct : " + ", ".join(lignes) + f". Processus les plus actifs : {procs}."
