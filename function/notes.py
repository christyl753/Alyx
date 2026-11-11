"""Module de prise de notes rapides pour Alyx (Conformité BLOC B.8.3).

Persistance locale dans %APPDATA%/Alyx/daily/notes/ ou ~/.config/alyx/daily/notes/.
Chaque note dispose d'une entrée indexée dans notes.json et d'un fichier Markdown dédié.
"""
from datetime import datetime
import json
import os
import re
import sys
import threading
import uuid
from core.logger import get_logger

logger = get_logger('alyx.notes')
_lock = threading.RLock()

def _obtenir_chemins_notes() -> tuple[str, str]:
    """Résout le dossier de notes et le fichier d'index notes.json selon l'OS."""
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        dossier = os.path.join(base, "Alyx", "daily", "notes")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        dossier = os.path.join(base, "alyx", "daily", "notes")
    os.makedirs(dossier, exist_ok=True)
    fichier_index = os.path.join(os.path.dirname(dossier), "notes.json")
    return dossier, fichier_index

def _charger_index_notes() -> list[dict]:
    with _lock:
        _, fichier_index = _obtenir_chemins_notes()
        if not os.path.exists(fichier_index):
            return []
        try:
            with open(fichier_index, "r", encoding="utf-8") as f:
                donnees = json.load(f)
                return donnees if isinstance(donnees, list) else []
        except Exception as e:
            logger.warning(f"Erreur lors du chargement des notes: {e}")
            return []

def _sauvegarder_index_notes(notes: list[dict]) -> bool:
    with _lock:
        _, fichier_index = _obtenir_chemins_notes()
        fichier_tmp = f"{fichier_index}.{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(fichier_tmp, "w", encoding="utf-8") as f:
                json.dump(notes, f, indent=2, ensure_ascii=False)
            os.replace(fichier_tmp, fichier_index)
            return True
        except Exception as e:
            logger.error(f"Erreur lors de la sauvegarde de l'index des notes: {e}")
            if os.path.exists(fichier_tmp):
                try:
                    os.remove(fichier_tmp)
                except OSError:
                    pass
            return False

def _slugifier(texte: str) -> str:
    s = re.sub(r'[^\w\s-]', '', texte.strip().lower())
    return re.sub(r'[-\s]+', '_', s)[:30] or "note"

def ajouter_note_rapide(titre: str, contenu: str, etiquette: str = "") -> str:
    """Ajoute une nouvelle note rapide enregistrée localement en Markdown.

    Args:
        titre: Titre court de la note (ex: 'Liste de courses', 'Idée projet').
        contenu: Contenu textuel ou Markdown de la note.
        etiquette: Catégorie optionnelle pour classer la note (ex: 'todo', 'perso', 'travail').
    """
    if not titre or not str(titre).strip():
        return "Erreur : Le titre de la note ne peut pas être vide."
    if not contenu or not str(contenu).strip():
        return "Erreur : Le contenu de la note ne peut pas être vide."

    with _lock:
        titre_propre = str(titre).strip()
        contenu_propre = str(contenu).strip()
        etiquette_propre = str(etiquette or "").strip().lower()

        dossier_notes, _ = _obtenir_chemins_notes()
        note_id = uuid.uuid4().hex[:8]
        slug = _slugifier(titre_propre)
        nom_fichier = f"{note_id}_{slug}.md"
        chemin_complet = os.path.join(dossier_notes, nom_fichier)

        maintenant = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        entete_md = [
            f"# {titre_propre}",
            f"*Créé le : {maintenant}* | *Étiquette : {etiquette_propre or 'général'}*",
            "",
            contenu_propre,
            ""
        ]
        try:
            with open(chemin_complet, "w", encoding="utf-8") as f:
                f.write("\n".join(entete_md))
        except Exception as e:
            return f"Erreur lors de l'écriture du fichier note : {e}"

        entree = {
            "id": note_id,
            "titre": titre_propre,
            "apercu": contenu_propre[:120] + ("..." if len(contenu_propre) > 120 else ""),
            "etiquette": etiquette_propre,
            "cree_le": maintenant,
            "modifie_le": maintenant,
            "fichier": nom_fichier,
        }
        notes = _charger_index_notes()
        notes.insert(0, entree)
        succes = _sauvegarder_index_notes(notes)
        if not succes:
            if os.path.exists(chemin_complet):
                try:
                    os.remove(chemin_complet)
                except OSError:
                    pass
            return "Erreur : Impossible de sauvegarder l'index des notes. La note n'a pas été enregistrée."

        return f"Note enregistrée avec succès [ID: {note_id}] : « {titre_propre} »."

def lister_notes_rapides(etiquette: str = "", limite: int = 20) -> str:
    """Liste les notes rapides récentes enregistrées.

    Args:
        etiquette: Filtrer par étiquette (ex: 'todo', 'travail'). Si vide, affiche toutes les notes.
        limite: Nombre maximal de notes à renvoyer (défaut: 20).
    """
    with _lock:
        notes = _charger_index_notes()
        if etiquette and str(etiquette).strip():
            filtre = str(etiquette).strip().lower()
            notes = [n for n in notes if n.get("etiquette") == filtre]

        if not notes:
            msg = f" avec l'étiquette '{etiquette}'" if etiquette else ""
            return f"Aucune note rapide trouvée{msg}."

        notes_retenues = notes[:limite]
        lignes = [f"Notes rapides ({len(notes_retenues)}) :"]
        for n in notes_retenues:
            etiq = f" [{n.get('etiquette')}]" if n.get("etiquette") else ""
            lignes.append(f"• [ID: {n.get('id')}] {n.get('cree_le')} | {n.get('titre')}{etiq}")
            lignes.append(f"   Aperçu : {n.get('apercu')}")
        return "\n".join(lignes)

def lire_note_rapide(titre_ou_id: str) -> str:
    """Lit le contenu intégral d'une note rapide par son titre ou son identifiant.

    Args:
        titre_ou_id: Identifiant unique ou partie du titre de la note recherchée.
    """
    if not titre_ou_id or not str(titre_ou_id).strip():
        return "Erreur : Identifiant ou titre requis."
    cible = str(titre_ou_id).strip().lower()

    with _lock:
        notes = _charger_index_notes()
        trouvee = None
        for n in notes:
            n_id = str(n.get("id", "")).lower()
            n_titre = str(n.get("titre", "")).lower()
            if n_id == cible or n_id.startswith(cible) or cible in n_titre:
                trouvee = n
                break

        if not trouvee:
            return f"Erreur : Aucune note correspondant à '{titre_ou_id}'."

        dossier_notes, _ = _obtenir_chemins_notes()
        chemin_fichier = os.path.join(dossier_notes, trouvee.get("fichier", ""))
        if not os.path.exists(chemin_fichier):
            return f"Note trouvée dans l'index [ID: {trouvee.get('id')}], mais le fichier Markdown associé est introuvable."

        try:
            with open(chemin_fichier, "r", encoding="utf-8") as f:
                contenu = f.read()
            return contenu
        except Exception as e:
            return f"Erreur lors de la lecture du fichier note : {e}"

def supprimer_note_rapide(titre_ou_id: str) -> str:
    """Supprime définitivement une note rapide et son fichier Markdown associé.

    Args:
        titre_ou_id: Identifiant ou titre de la note à supprimer.
    """
    if not titre_ou_id or not str(titre_ou_id).strip():
        return "Erreur : Identifiant ou titre requis."
    cible = str(titre_ou_id).strip().lower()

    with _lock:
        notes = _charger_index_notes()
        trouvee = None
        for n in notes:
            n_id = str(n.get("id", "")).lower()
            n_titre = str(n.get("titre", "")).lower()
            if n_id == cible or n_id.startswith(cible) or cible in n_titre:
                trouvee = n
                break

        if not trouvee:
            return f"Erreur : Aucune note correspondant à '{titre_ou_id}'."

        notes.remove(trouvee)
        succes = _sauvegarder_index_notes(notes)
        if not succes:
            return "Erreur : Impossible de sauvegarder l'index des notes. La note n'a pas été supprimée."

        dossier_notes, _ = _obtenir_chemins_notes()
        chemin_fichier = os.path.join(dossier_notes, trouvee.get("fichier", ""))
        if os.path.exists(chemin_fichier):
            try:
                os.remove(chemin_fichier)
            except OSError:
                pass

        return f"Note [ID: {trouvee.get('id')}] « {trouvee.get('titre')} » supprimée avec succès."
