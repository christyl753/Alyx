# Fichier : core/history.py
import json
import os
import sys
import time
from datetime import datetime, timedelta
from core.logger import get_logger

logger = get_logger('alyx.history')

RETENTION_JOURS = 90

def _dossier_historique() -> str:
    if sys.platform == "win32":
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    else:
        base = os.path.expanduser('~/.config')
    dossier = os.path.join(base, 'Alyx', 'history')
    os.makedirs(dossier, exist_ok=True)
    return dossier

def purger_historique_ancien(retention_jours: int = RETENTION_JOURS) -> int:
    """Supprime les sessions antérieures à la durée de rétention (90 jours par défaut)."""
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

