# Fichier : function/files.py
import os
import shutil
from datetime import datetime
import tkinter as tk
from tkinter import messagebox
from fpdf import FPDF

def _resoudre_chemin(chemin: str) -> str:
    """Résout un chemin utilisateur (~, relatif) en chemin absolu propre."""
    return os.path.abspath(os.path.expanduser(chemin.strip()))

def creer_fichier(chemin: str) -> str:
    """Crée un fichier texte vide au chemin spécifié (ex: '~/Bureau/note.txt')."""
    chemin_absolu = _resoudre_chemin(chemin)
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
    """Crée un nouveau dossier au chemin spécifié (ex: '~/Documents/Projet')."""
    chemin_absolu = _resoudre_chemin(chemin)
    try:
        os.makedirs(chemin_absolu, exist_ok=True)
        return f"Succès : Le dossier '{chemin}' a été créé."
    except Exception as e:
        return f"Erreur lors de la création du dossier '{chemin}': {str(e)}"

def lister_fichiers(dossier: str = "~") -> str:
    """Liste les fichiers et dossiers présents dans un répertoire donné."""
    chemin = _resoudre_chemin(dossier)
    if not os.path.isdir(chemin):
        return f"Erreur: '{chemin}' n'est pas un dossier valide ou n'existe pas."
    try:
        elements = os.listdir(chemin)
        if not elements:
            return f"Le dossier '{chemin}' est vide."
        resultat = f"Contenu de '{chemin}':\n"
        for e in sorted(elements):
            chemin_complet = os.path.join(chemin, e)
            type_e = "📁" if os.path.isdir(chemin_complet) else "📄"
            resultat += f"{type_e} {e}\n"
        return resultat
    except PermissionError:
        return f"Erreur: permission refusée pour lire '{chemin}'."

def renommer_fichier(chemin_actuel: str, nouveau_nom: str) -> str:
    """Renomme un fichier ou dossier."""
    source = _resoudre_chemin(chemin_actuel)
    if not os.path.exists(source):
        return f"Erreur: '{source}' n'existe pas."

    dossier_parent = os.path.dirname(source)
    destination = os.path.join(dossier_parent, nouveau_nom.strip())

    if os.path.exists(destination):
        return f"Erreur: un fichier nommé '{nouveau_nom}' existe déjà dans ce dossier."

    try:
        os.rename(source, destination)
        return f"'{os.path.basename(source)}' a été renommé en '{nouveau_nom}' avec succès."
    except Exception as e:
        return f"Erreur lors du renommage : {str(e)}"

def deplacer_fichier(chemin_source: str, dossier_destination: str) -> str:
    """Déplace un fichier ou dossier vers un autre dossier."""
    source = _resoudre_chemin(chemin_source)
    destination_dossier = _resoudre_chemin(dossier_destination)

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
    """Déplace un fichier vers la corbeille système de l'OS (XDG/Windows/Mac)."""
    chemin_absolu = _resoudre_chemin(chemin)

    if not os.path.exists(chemin_absolu):
        return f"Erreur : L'élément '{chemin}' est introuvable."

    dossiers_proteges = ["/", os.path.expanduser("~"), "/home", "/usr", "/etc", "/bin", "/boot", "C:\\", "C:\\Windows", "C:\\Program Files"]
    if chemin_absolu in dossiers_proteges:
        return f"Erreur : '{chemin_absolu}' est un dossier système protégé, action refusée."

    try:
        from send2trash import send2trash
        send2trash(chemin_absolu)
        return f"Succès : '{os.path.basename(chemin_absolu)}' a été placé dans la corbeille du système."
    except Exception as e:
        return f"Erreur lors de la mise en corbeille : {str(e)}"

def _demander_permission(action: str, cible: str) -> bool:
    """Affiche une popup pour demander la permission à l'utilisateur via un sous-processus."""
    import subprocess
    import sys
    
    script = f'''
import tkinter as tk
from tkinter import messagebox
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
rep = messagebox.askyesno("Permission requise", """Alyx demande l'autorisation pour l'action suivante:\\n\\n{action}\\n\\nCible : {cible}\\n\\nAutoriser ?""")
print("YES" if rep else "NO")
    '''
    try:
        res = subprocess.check_output([sys.executable, "-c", script], text=True, stderr=subprocess.DEVNULL)
        return "YES" in res
    except Exception as e:
        print(f"Erreur popup tkinter via subprocess : {e}")
        # Fallback console si pas d'interface
        reponse = input(f"Alyx demande la permission de {action} sur {cible}. (o/N): ")
        return reponse.lower().strip() == 'o'

def lire_fichier_securise(chemin: str) -> str:
    """Lit le contenu d'un fichier après avoir demandé la permission."""
    chemin_absolu = _resoudre_chemin(chemin)
    if not os.path.isfile(chemin_absolu):
        return f"Erreur : Le fichier '{chemin}' n'existe pas."
    
    if _demander_permission("LIRE un fichier", chemin_absolu):
        try:
            with open(chemin_absolu, 'r', encoding='utf-8') as f:
                contenu = f.read()
            return f"Contenu de {chemin} :\n{contenu}"
        except Exception as e:
            return f"Erreur lors de la lecture : {str(e)}"
    else:
        return "Erreur : L'utilisateur a refusé la permission de lire ce fichier."

def ecrire_fichier_securise(chemin: str, contenu: str) -> str:
    """Écrit du contenu dans un fichier après avoir demandé la permission."""
    chemin_absolu = _resoudre_chemin(chemin)
    
    if _demander_permission("ECRIRE dans un fichier (ou le créer)", chemin_absolu):
        try:
            dossier_parent = os.path.dirname(chemin_absolu)
            if dossier_parent:
                os.makedirs(dossier_parent, exist_ok=True)
            with open(chemin_absolu, 'w', encoding='utf-8') as f:
                f.write(contenu)
            return f"Succès : Le contenu a été écrit dans '{chemin}'."
        except Exception as e:
            return f"Erreur lors de l'écriture : {str(e)}"
    else:
        return "Erreur : L'utilisateur a refusé la permission d'écrire dans ce fichier."

def generer_pdf(chemin: str, contenu: str) -> str:
    """Génère un fichier PDF avec le contenu spécifié (permission requise)."""
    if not chemin.lower().endswith(".pdf"):
        chemin += ".pdf"
    
    chemin_absolu = _resoudre_chemin(chemin)
    
    if _demander_permission("GENERER UN PDF", chemin_absolu):
        try:
            dossier_parent = os.path.dirname(chemin_absolu)
            if dossier_parent:
                os.makedirs(dossier_parent, exist_ok=True)
                
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            
            # Gestion du texte multi-lignes pour fpdf2
            pdf.multi_cell(0, 10, txt=contenu)
            
            pdf.output(chemin_absolu)
            return f"Succès : Le PDF a été généré dans '{chemin}'."
        except Exception as e:
            return f"Erreur lors de la génération du PDF : {str(e)}"
    else:
        return "Erreur : L'utilisateur a refusé la génération de ce PDF."
