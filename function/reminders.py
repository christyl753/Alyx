"""Module de gestion des rappels locaux d'Alyx (Conformité BLOC B.8.3).

Persistance locale 100% hors-ligne dans %APPDATA%/Alyx/daily/reminders.json
ou ~/.config/alyx/daily/reminders.json.
"""
from datetime import datetime, timedelta
import json
import os
import sys
import threading
import uuid
from core.logger import get_logger

logger = get_logger('alyx.reminders')

_lock = threading.RLock()

def _obtenir_fichier_rappels() -> str:
    """Résout le chemin du fichier reminders.json selon l'OS hôte."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        dossier = os.path.join(base, "Alyx", "daily")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        dossier = os.path.join(base, "alyx", "daily")
    os.makedirs(dossier, exist_ok=True)
    return os.path.join(dossier, "reminders.json")

def _charger_rappels() -> list[dict]:
    """Charge la liste des rappels depuis le stockage local persistant."""
    with _lock:
        fichier = _obtenir_fichier_rappels()
        if not os.path.exists(fichier):
            return []
        try:
            with open(fichier, "r", encoding="utf-8") as f:
                donnees = json.load(f)
                return donnees if isinstance(donnees, list) else []
        except Exception as e:
            logger.warning(f"Erreur lors du chargement des rappels: {e}")
            return []

def _sauvegarder_rappels(rappels: list[dict]) -> bool:
    """Sauvegarde la liste des rappels de manière atomique."""
    with _lock:
        fichier = _obtenir_fichier_rappels()
        fichier_tmp = f"{fichier}.{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(fichier_tmp, "w", encoding="utf-8") as f:
                json.dump(rappels, f, indent=2, ensure_ascii=False)
            os.replace(fichier_tmp, fichier)
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde des rappels: {e}")
            if os.path.exists(fichier_tmp):
                try:
                    os.remove(fichier_tmp)
                except OSError:
                    pass
            return False

def creer_rappel(texte: str, delai_minutes: int = 0, date_heure: str = "") -> str:
    """Crée un rappel local programmé pour une échéance donnée ou un délai en minutes.

    Args:
        texte: Message ou sujet du rappel (ex: 'Prendre mes médicaments', 'Réunion budget').
        delai_minutes: Délai en minutes à compter de maintenant (ex: 15 pour dans un quart d'heure).
        date_heure: Date et heure précises d'échéance au format 'YYYY-MM-DD HH:MM:SS' ou 'HH:MM'.
    """
    if not texte or not str(texte).strip():
        return "Erreur : Le texte du rappel ne peut pas être vide."
    texte_propre = str(texte).strip()

    maintenant = datetime.now()
    echeance = None

    try:
        delai = int(delai_minutes)
    except (ValueError, TypeError):
        delai = 10

    if delai > 0:
        echeance = maintenant + timedelta(minutes=delai)
    elif date_heure and str(date_heure).strip():
        dh = str(date_heure).strip()
        formats = [
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%H:%M:%S",
            "%H:%M",
        ]
        for fmt in formats:
            try:
                dt_parsed = datetime.strptime(dh, fmt)
                if fmt in ("%H:%M:%S", "%H:%M"):
                    dt_parsed = maintenant.replace(
                        hour=dt_parsed.hour,
                        minute=dt_parsed.minute,
                        second=dt_parsed.second,
                        microsecond=0
                    )
                    if dt_parsed <= maintenant:
                        dt_parsed += timedelta(days=1)
                echeance = dt_parsed
                break
            except ValueError:
                continue

    if echeance is None:
        echeance = maintenant + timedelta(minutes=10)

    rappel_id = uuid.uuid4().hex[:8]
    nouveau_rappel = {
        "id": rappel_id,
        "texte": texte_propre,
        "cree_le": maintenant.strftime("%Y-%m-%d %H:%M:%S"),
        "echeance": echeance.strftime("%Y-%m-%d %H:%M:%S"),
        "delai_minutes": delai if delai > 0 else 0,
        "statut": "en_attente",
        "notifie": False,
    }

    with _lock:
        rappels = _charger_rappels()
        rappels.append(nouveau_rappel)
        if _sauvegarder_rappels(rappels):
            return f"Rappel programmé avec succès [ID: {rappel_id}] pour le {nouveau_rappel['echeance']} : « {texte_propre} »."
        return "Erreur : Impossible d'enregistrer le rappel sur le disque."

def lister_rappels(inclure_passes: bool = False) -> str:
    """Liste tous les rappels programmés enregistrés.

    Args:
        inclure_passes: Si True, inclut également les rappels déjà déclenchés ou annulés.
    """
    with _lock:
        rappels = _charger_rappels()
        if not inclure_passes:
            rappels = [r for r in rappels if r.get("statut") == "en_attente"]

        if not rappels:
            return "Aucun rappel en attente." if not inclure_passes else "Aucun rappel enregistré."

        rappels.sort(key=lambda x: x.get("echeance", ""))
        lignes = [f"Rappels {'enregistrés' if inclure_passes else 'en attente'} ({len(rappels)}) :"]
        for r in rappels:
            statut_label = f" [{r.get('statut')}]" if inclure_passes else ""
            lignes.append(f"• [ID: {r.get('id')}] Échéance: {r.get('echeance')}{statut_label} — « {r.get('texte')} »")
        return "\n".join(lignes)

def supprimer_rappel(rappel_id: str) -> str:
    """Supprime ou annule un rappel programmé existant via son identifiant.

    Args:
        rappel_id: Identifiant unique ou préfixe de l'identifiant du rappel (ex: 'e4f8a1b2').
    """
    if not rappel_id or not str(rappel_id).strip():
        return "Erreur : Identifiant de rappel requis."
    cible = str(rappel_id).strip().lower()

    with _lock:
        rappels = _charger_rappels()
        trouve = None
        for r in rappels:
            r_id = str(r.get("id", "")).lower()
            if r_id == cible or r_id.startswith(cible):
                trouve = r
                break

        if not trouve:
            return f"Erreur : Aucun rappel correspondant à l'identifiant '{rappel_id}'."

        rappels.remove(trouve)
        if _sauvegarder_rappels(rappels):
            return f"Rappel [ID: {trouve.get('id')}] supprimé : « {trouve.get('texte')} »."
        return "Erreur : Impossible de mettre à jour le fichier des rappels."

def verifier_rappels_imminents() -> list[dict]:
    """Vérifie les rappels échus et renvoie la liste de ceux à notifier (appelé périodiquement)."""
    with _lock:
        rappels = _charger_rappels()
        maintenant_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        a_notifier = []
        modifie = False

        for r in rappels:
            if r.get("statut") == "en_attente" and not r.get("notifie", False):
                if r.get("echeance", "") <= maintenant_str:
                    r["statut"] = "declenche"
                    r["notifie"] = True
                    a_notifier.append(dict(r))
                    modifie = True

        if modifie:
            _sauvegarder_rappels(rappels)
        return a_notifier
