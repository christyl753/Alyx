# Fichier : function/files.py
import os
import shutil
import threading
from fpdf import FPDF
from core.logger import get_logger
from core.exceptions import PermissionRequiredException

logger = get_logger('alyx.files')

# Taille maximale lue par lire_fichier_securise (le contenu part dans le contexte du LLM)
TAILLE_MAX_LECTURE = 100 * 1024

# Permission accordée par l'utilisateur pour l'appel d'outil en cours (par thread)
_permission_ctx = threading.local()

# Nombre maximal d'entrées renvoyées par lister_fichiers (le résultat part dans le contexte du LLM)
MAX_ENTREES_LISTE = 200

def _normaliser(chemin: str) -> str:
    return os.path.normcase(os.path.realpath(chemin))

def _est_dans(chemin_reel: str, dossier_reel: str) -> bool:
    try:
        return os.path.commonpath([chemin_reel, dossier_reel]) == dossier_reel
    except ValueError:  # lecteurs différents sous Windows
        return False

def _zones_sensibles() -> list:
    """Emplacements où une écriture permettrait d'exécuter du code ou de voler des clés."""
    home = os.path.expanduser("~")
    zones = [
        os.path.join(home, '.ssh'),
        os.path.join(home, '.gnupg'),
        os.path.join(home, '.config', 'autostart'),
        os.path.join(home, '.config', 'systemd'),
        os.path.join(home, '.bashrc'),
        os.path.join(home, '.bash_profile'),
        os.path.join(home, '.profile'),
        os.path.join(home, '.zshrc'),
    ]
    appdata = os.environ.get('APPDATA')
    if appdata:
        zones.append(os.path.join(appdata, 'Microsoft', 'Windows', 'Start Menu', 'Programs', 'Startup'))
    return [_normaliser(z) for z in zones]

def _resoudre_chemin(chemin: str, ecriture: bool = False) -> str:
    """Résout un chemin utilisateur (~, relatif) en chemin absolu propre et applique le sandboxing."""
    chemin_absolu = os.path.abspath(os.path.expanduser(str(chemin).strip()))
    home_dir = _normaliser(os.path.expanduser("~"))

    # Sandboxing: le chemin réel (liens symboliques résolus) doit être dans le dossier utilisateur
    chemin_reel = _normaliser(chemin_absolu)
    if not _est_dans(chemin_reel, home_dir):
        logger.warning(f"Tentative d'accès hors sandbox bloquée: {chemin_absolu}")
        raise PermissionError(f"Accès refusé : Le chemin '{chemin_absolu}' est en dehors de votre répertoire utilisateur autorisé.")

    if ecriture and any(_est_dans(chemin_reel, zone) for zone in _zones_sensibles()):
        logger.warning(f"Écriture dans une zone sensible bloquée: {chemin_absolu}")
        raise PermissionError(f"Accès refusé : '{chemin_absolu}' est un emplacement système sensible (démarrage automatique, clés...).")

    return chemin_absolu

def executer_avec_permission(fonction, arguments: dict):
    """Exécute un outil après validation explicite de l'utilisateur (Human-in-the-Loop)."""
    _permission_ctx.accordee = True
    try:
        return fonction(**arguments)
    finally:
        _permission_ctx.accordee = False

def _demander_permission(action: str, cible: str) -> bool:
    """
    Demande la permission d'effectuer une action critique.
    Si l'utilisateur ne l'a pas encore accordée pour cet appel, lève une PermissionRequiredException
    interceptée par le handler WebSocket (api.py), qui suspend l'exécution et envoie une demande
    de validation au frontend C# (Human-in-the-Loop). L'outil est ré-exécuté via
    executer_avec_permission() une fois l'action autorisée.
    """
    if getattr(_permission_ctx, 'accordee', False):
        return True
    raise PermissionRequiredException(action, cible)

def creer_fichier(chemin: str) -> str:
    """Crée un fichier texte vide.

    Args:
        chemin: Chemin du fichier à créer (ex: '~/Bureau/note.txt').
    """
    try:
        chemin_absolu = _resoudre_chemin(chemin, ecriture=True)
    except PermissionError as e:
        return str(e)
    try:
        dossier_parent = os.path.dirname(chemin_absolu)
        if dossier_parent:
            os.makedirs(dossier_parent, exist_ok=True)
        with open(chemin_absolu, 'a'):
            pass
        return f"Succès : Le fichier '{chemin}' a été créé."
    except Exception as e:
        return f"Erreur lors de la création du fichier '{chemin}': {str(e)}"

def creer_dossier(chemin: str) -> str:
    """Crée un nouveau dossier.

    Args:
        chemin: Chemin du dossier à créer (ex: '~/Documents/Projet').
    """
    try:
        chemin_absolu = _resoudre_chemin(chemin, ecriture=True)
    except PermissionError as e:
        return str(e)
    try:
        os.makedirs(chemin_absolu, exist_ok=True)
        return f"Succès : Le dossier '{chemin}' a été créé."
    except Exception as e:
        return f"Erreur lors de la création du dossier '{chemin}': {str(e)}"

def lister_fichiers(dossier: str = "~") -> str:
    """Liste les fichiers et dossiers présents dans un répertoire.

    Args:
        dossier: Chemin du dossier à lister (ex: '~/Documents'). Par défaut le dossier utilisateur.
    """
    try:
        chemin = _resoudre_chemin(dossier)
    except PermissionError as e:
        return str(e)
    if not os.path.isdir(chemin):
        return f"Erreur: '{chemin}' n'est pas un dossier valide ou n'existe pas."
    try:
        with os.scandir(chemin) as it:
            elements = sorted(it, key=lambda e: e.name)
        if not elements:
            return f"Le dossier '{chemin}' est vide."
        lignes = [f"Contenu de '{chemin}' ({len(elements)} éléments):"]
        for e in elements[:MAX_ENTREES_LISTE]:
            try:
                type_e = "📁" if e.is_dir() else "📄"
            except OSError:
                type_e = "📄"
            lignes.append(f"{type_e} {e.name}")
        if len(elements) > MAX_ENTREES_LISTE:
            lignes.append(f"[... {len(elements) - MAX_ENTREES_LISTE} éléments non affichés]")
        return "\n".join(lignes) + "\n"
    except PermissionError:
        return f"Erreur: permission refusée pour lire '{chemin}'."

def renommer_fichier(chemin_actuel: str, nouveau_nom: str) -> str:
    """Renomme un fichier ou dossier (sans le déplacer).

    Args:
        chemin_actuel: Chemin actuel du fichier ou dossier (ex: '~/Bureau/note.txt').
        nouveau_nom: Nouveau nom seul, sans chemin (ex: 'notes.txt').
    """
    try:
        source = _resoudre_chemin(chemin_actuel, ecriture=True)
    except PermissionError as e:
        return str(e)
    if not os.path.exists(source):
        return f"Erreur: '{source}' n'existe pas."

    nom = str(nouveau_nom).strip()
    if not nom or nom in ('.', '..') or os.path.basename(nom) != nom or '/' in nom or '\\' in nom:
        return "Erreur: le nouveau nom doit être un simple nom de fichier, sans chemin."

    destination = os.path.join(os.path.dirname(source), nom)
    try:
        _resoudre_chemin(destination, ecriture=True)
    except PermissionError as e:
        return str(e)

    if os.path.exists(destination):
        return f"Erreur: un fichier nommé '{nom}' existe déjà dans ce dossier."

    try:
        os.rename(source, destination)
        return f"'{os.path.basename(source)}' a été renommé en '{nom}' avec succès."
    except Exception as e:
        return f"Erreur lors du renommage : {str(e)}"

def deplacer_fichier(chemin_source: str, dossier_destination: str) -> str:
    """Déplace un fichier ou dossier vers un autre dossier.

    Args:
        chemin_source: Chemin du fichier ou dossier à déplacer.
        dossier_destination: Dossier de destination existant.
    """
    try:
        source = _resoudre_chemin(chemin_source, ecriture=True)
        destination_dossier = _resoudre_chemin(dossier_destination, ecriture=True)
    except PermissionError as e:
        return str(e)

    if not os.path.exists(source):
        return f"Erreur: '{source}' n'existe pas."
    if not os.path.isdir(destination_dossier):
        return f"Erreur: le dossier de destination '{destination_dossier}' n'existe pas."

    try:
        destination_finale = os.path.join(destination_dossier, os.path.basename(source))
        if os.path.exists(destination_finale):
            return f"Erreur: un fichier du même nom existe déjà dans '{destination_dossier}'."
        shutil.move(source, destination_finale)
        return f"'{os.path.basename(source)}' a été déplacé vers '{destination_dossier}' avec succès."
    except Exception as e:
        return f"Erreur lors du déplacement : {str(e)}"

def supprimer_fichier(chemin: str) -> str:
    """Déplace un fichier ou dossier vers la corbeille du système (permission requise).

    Args:
        chemin: Chemin du fichier ou dossier à supprimer.
    """
    try:
        chemin_absolu = _resoudre_chemin(chemin)
    except PermissionError as e:
        return str(e)

    if not os.path.exists(chemin_absolu):
        return f"Erreur : L'élément '{chemin}' est introuvable."

    if _normaliser(chemin_absolu) == _normaliser(os.path.expanduser("~")):
        return f"Erreur : '{chemin_absolu}' est un dossier protégé, action refusée."

    _demander_permission("SUPPRIMER un fichier", chemin_absolu)

    try:
        from send2trash import send2trash
        send2trash(chemin_absolu)
        return f"Succès : '{os.path.basename(chemin_absolu)}' a été placé dans la corbeille du système."
    except Exception as e:
        return f"Erreur lors de la mise en corbeille : {str(e)}"

def lire_fichier_securise(chemin: str) -> str:
    """Lit le contenu d'un fichier texte (permission requise).

    Args:
        chemin: Chemin du fichier à lire.
    """
    try:
        chemin_absolu = _resoudre_chemin(chemin)
    except PermissionError as e:
        return str(e)
    if not os.path.isfile(chemin_absolu):
        return f"Erreur : Le fichier '{chemin}' n'existe pas."

    _demander_permission("LIRE un fichier", chemin_absolu)
    try:
        taille = os.path.getsize(chemin_absolu)
        with open(chemin_absolu, 'rb') as f:
            brut = f.read(TAILLE_MAX_LECTURE)
        if b'\x00' in brut[:8192]:
            return f"Erreur : '{chemin}' semble être un fichier binaire, lecture refusée."
        contenu = brut.decode('utf-8', errors='replace')
        if taille > TAILLE_MAX_LECTURE:
            contenu += f"\n[... contenu tronqué : {TAILLE_MAX_LECTURE // 1024} Ko lus sur {taille // 1024} Ko]"
        return f"Contenu de {chemin} :\n{contenu}"
    except Exception as e:
        return f"Erreur lors de la lecture : {str(e)}"

def ecrire_fichier_securise(chemin: str, contenu: str) -> str:
    """Écrit du texte dans un fichier, en le créant ou en l'écrasant (permission requise).

    Args:
        chemin: Chemin du fichier à écrire.
        contenu: Texte à écrire dans le fichier.
    """
    try:
        chemin_absolu = _resoudre_chemin(chemin, ecriture=True)
    except PermissionError as e:
        return str(e)

    _demander_permission("ECRIRE dans un fichier (ou le créer)", chemin_absolu)
    try:
        dossier_parent = os.path.dirname(chemin_absolu)
        if dossier_parent:
            os.makedirs(dossier_parent, exist_ok=True)
        with open(chemin_absolu, 'w', encoding='utf-8') as f:
            f.write(contenu)
        return f"Succès : Le contenu a été écrit dans '{chemin}'."
    except Exception as e:
        return f"Erreur lors de l'écriture : {str(e)}"

# Les polices PDF standard (Helvetica) ne couvrent que le Latin-1
_REMPLACEMENTS_PDF = str.maketrans({
    '‘': "'", '’': "'", '“': '"', '”': '"', '«': '"', '»': '"',
    '–': '-', '—': '-', '…': '...', '•': '-', ' ': ' ', ' ': ' ',
    'œ': 'oe', 'Œ': 'OE',
})

def _texte_latin1(texte: str) -> str:
    return str(texte).translate(_REMPLACEMENTS_PDF).encode('latin-1', errors='replace').decode('latin-1')

def generer_pdf(chemin: str, contenu: str) -> str:
    """Génère un fichier PDF contenant le texte donné (permission requise).

    Args:
        chemin: Chemin du PDF à créer (ex: '~/Documents/rapport.pdf').
        contenu: Texte à écrire dans le PDF.
    """
    if not chemin.lower().endswith(".pdf"):
        chemin += ".pdf"

    try:
        chemin_absolu = _resoudre_chemin(chemin, ecriture=True)
    except PermissionError as e:
        return str(e)

    _demander_permission("GENERER UN PDF", chemin_absolu)
    try:
        dossier_parent = os.path.dirname(chemin_absolu)
        if dossier_parent:
            os.makedirs(dossier_parent, exist_ok=True)

        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)

        # Gestion du texte multi-lignes pour fpdf2
        pdf.multi_cell(0, 10, _texte_latin1(contenu))

        pdf.output(chemin_absolu)
        return f"Succès : Le PDF a été généré dans '{chemin}'."
    except Exception as e:
        return f"Erreur lors de la génération du PDF : {str(e)}"
