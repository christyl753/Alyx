# Fichier : core/history.py
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from core.logger import get_logger

logger = get_logger('alyx.history')

def _charger_retention_jours() -> int:
    try:
        from core.preferences import get_context_config
        return int(get_context_config().get('retention_jours', 90))
    except Exception:
        return 90

RETENTION_JOURS = _charger_retention_jours()
_session_lock = threading.RLock()

def _dossier_historique() -> str:
    """Résolution du répertoire selon l'OS (Multi-OS B.8).
    - Windows : %APPDATA%\\Alyx\\history
    - Linux   : ~/.config/Alyx/history (ou $XDG_CONFIG_HOME/Alyx/history)
    """
    if sys.platform == "win32":
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config')
    dossier = os.path.join(base, 'Alyx', 'history')
    os.makedirs(dossier, mode=0o700, exist_ok=True)
    return dossier

def purger_historique_ancien(retention_jours: int | None = None) -> int:
    """Supprime les sessions antérieures à la durée de rétention (90 jours par défaut, conformité B.4.1)."""
    if retention_jours is None:
        retention_jours = _charger_retention_jours()
    dossier = _dossier_historique()
    seuil = time.time() - (retention_jours * 86400)
    purges = 0
    try:
        for f in os.listdir(dossier):
            if f.endswith('.json'):
                p = os.path.join(dossier, f)
                try:
                    if os.path.getmtime(p) < seuil:
                        os.remove(p)
                        purges += 1
                except OSError:
                    continue
    except Exception as e:
        logger.warning(f"Erreur lors de la purge de l'historique : {e}")
    return purges

def enregistrer_session(session_id: str, prompt: str, reponse: str, outils: list | None = None) -> None:
    """Enregistre un tour de dialogue et ses actions dans l'historique JSON local (100% hors-ligne)."""
    try:
        purger_historique_ancien()
        dossier = _dossier_historique()
        chemin_fichier = os.path.join(dossier, f"{session_id}.json")
        entree = {
            "timestamp": datetime.now().isoformat(),
            "prompt": prompt,
            "reponse": reponse,
            "outils": outils or [],
        }
        donnees = []
        if os.path.isfile(chemin_fichier):
            try:
                with open(chemin_fichier, 'r', encoding='utf-8') as f:
                    donnees = json.load(f)
            except Exception:
                donnees = []
        donnees.append(entree)
        with open(chemin_fichier, 'w', encoding='utf-8') as f:
            json.dump(donnees, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Erreur enregistrement historique : {e}")

def consulter_historique(limite: int = 10) -> str:
    """Consulte les dernières sessions enregistrées dans l'historique local (Niveau 1)."""
    dossier = _dossier_historique()
    sessions = []
    try:
        for f in sorted(os.listdir(dossier), reverse=True):
            if f.endswith('.json'):
                p = os.path.join(dossier, f)
                try:
                    with open(p, 'r', encoding='utf-8') as fp:
                        tours = json.load(fp)
                    if tours and isinstance(tours, list):
                        premier = tours[0]
                        sessions.append({
                            "id": f.replace('.json', ''),
                            "date": premier.get("timestamp", ""),
                            "tours_count": len(tours),
                            "apercu": premier.get("prompt", "")[:80]
                        })
                except Exception:
                    continue
    except Exception as e:
        return f"Erreur lecture historique : {e}"

    if not sessions:
        return "Historique vide : aucune session enregistrée."

    lignes = [f"=== Historique local des sessions (rétention {RETENTION_JOURS} jours) ==="]
    for s in sessions[:limite]:
        lignes.append(f"• [{s['date'][:16]}] Session {s['id'][:8]}... ({s['tours_count']} tours) : « {s['apercu']} »")
    return "\n".join(lignes)

def supprimer_historique() -> str:
    """Supprime l'ensemble des fichiers d'historique de session locaux."""
    dossier = _dossier_historique()
    supprimes = 0
    try:
        for f in os.listdir(dossier):
            if f.endswith('.json'):
                os.remove(os.path.join(dossier, f))
                supprimes += 1
        return f"Succès : {supprimes} sessions d'historique supprimées."
    except Exception as e:
        return f"Erreur lors de la suppression de l'historique : {e}"


def _sanitiser_session_id(session_id: str) -> str:
    """Anti-traversée de répertoire stricte."""
    if not session_id or not isinstance(session_id, str):
        return "session_active"
    nom = os.path.basename(session_id.strip())
    nom_propre = "".join(c for c in nom if c.isalnum() or c in ("-", "_")).strip()
    return nom_propre or "session_active"


def _chemin_etat_session(session_id: str = "session_active") -> str:
    """Retourne le chemin absolu sécurisé du fichier d'état."""
    dossier = _dossier_historique()
    session_id_propre = _sanitiser_session_id(session_id)
    nom_fichier = "active_session_state.json" if session_id_propre == "session_active" else f"{session_id_propre}_state.json"
    chemin = os.path.abspath(os.path.join(dossier, nom_fichier))
    dossier_abs = os.path.abspath(dossier)
    if not chemin.startswith(dossier_abs):
        raise ValueError(f"Traversée de répertoire détectée : {chemin} hors de {dossier_abs}")
    return chemin


def sauvegarder_etat_session(messages: list[dict], session_id: str = "session_active") -> bool:
    """Sauvegarde atomique de l'état du contexte (M1 - R1)."""
    if not isinstance(messages, list):
        logger.warning(f"sauvegarder_etat_session : type invalide pour messages ({type(messages)})")
        return False

    with _session_lock:
        temp_path = None
        try:
            chemin_final = _chemin_etat_session(session_id)
            dossier = os.path.dirname(chemin_final)
            os.makedirs(dossier, mode=0o700, exist_ok=True)

            payload = {
                "version": 1,
                "session_id": session_id,
                "saved_at": time.time(),
                "saved_at_iso": datetime.now().isoformat(),
                "message_count": len(messages),
                "messages": messages,
            }

            fd, temp_path = tempfile.mkstemp(
                prefix="active_session_",
                suffix=".tmp",
                dir=dossier,
            )
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # Remplacement atomique avec retry loop (5 tentatives, 10ms backoff pour Windows)
            remplace = False
            derniere_err = None
            for tentative in range(5):
                try:
                    os.replace(temp_path, chemin_final)
                    remplace = True
                    temp_path = None
                    break
                except (PermissionError, OSError) as pe:
                    derniere_err = pe
                    time.sleep(0.01)

            if not remplace:
                raise derniere_err or OSError(f"Impossible de remplacer atomiquement {chemin_final}")

            return True
        except Exception as e:
            logger.warning(f"Erreur sauvegarde atomique session '{session_id}' : {e}")
            return False
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass


def charger_etat_session(session_id: str = "session_active", max_age_heures: int = 24) -> list[dict] | None:
    """Charge et restaure l'état du contexte depuis le disque (M1 - R1)."""
    with _session_lock:
        try:
            chemin = _chemin_etat_session(session_id)
            if not os.path.isfile(chemin):
                return None

            if max_age_heures > 0:
                mtime = os.path.getmtime(chemin)
                age_secondes = time.time() - mtime
                if age_secondes > (max_age_heures * 3600):
                    logger.info(f"Session '{session_id}' expirée ({age_secondes / 3600:.1f}h > {max_age_heures}h).")
                    return None

            data = None
            derniere_err = None
            for tentative in range(5):
                try:
                    with open(chemin, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    break
                except (PermissionError, OSError) as pe:
                    derniere_err = pe
                    time.sleep(0.01)

            if data is None and derniere_err is not None:
                raise derniere_err

            if isinstance(data, dict):
                saved_at = data.get("saved_at")
                if max_age_heures > 0 and isinstance(saved_at, (int, float)):
                    if (time.time() - saved_at) > (max_age_heures * 3600):
                        logger.info(f"Session '{session_id}' expirée selon timestamp payload.")
                        return None
                messages = data.get("messages")
            elif isinstance(data, list):
                messages = data
            else:
                raise ValueError(f"Payload JSON racine invalide ({type(data).__name__})")

            if not isinstance(messages, list):
                raise ValueError(f"Le champ 'messages' n'est pas une liste ({type(messages).__name__})")

            if not all(isinstance(m, dict) for m in messages):
                raise ValueError("La liste de messages contient des éléments non-dictionnaires")

            return messages
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
            logger.warning(f"Fichier d'état de session corrompu ({session_id}) : {e}")
            try:
                os.remove(_chemin_etat_session(session_id))
            except OSError:
                pass
            return None
        except Exception as e:
            logger.warning(f"Erreur lecture état session ({session_id}) : {e}")
            return None


def reinitialiser_etat_session(session_id: str = "session_active") -> None:
    """Supprime l'état persisté sur disque."""
    with _session_lock:
        try:
            chemin = _chemin_etat_session(session_id)
            if os.path.isfile(chemin):
                os.remove(chemin)
                logger.debug(f"État de session réinitialisé : {chemin}")
        except OSError as e:
            logger.warning(f"Erreur suppression état session ({session_id}) : {e}")


