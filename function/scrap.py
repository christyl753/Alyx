# Fichier : function/scrap.py
import os
import sys

def construire_dictionnaire_applications() -> dict:
    """
    Scanne les répertoires Linux standards pour trouver les applications installées
    et crée un dictionnaire : {'nom gui': 'commande système'}.
    """
    app_dict = {}

    if sys.platform == "win32":
        # Scanning simple du Menu Démarrer (raccourcis .lnk) sur Windows
        paths = [
            os.path.join(os.environ.get('PROGRAMDATA', 'C:\\ProgramData'), 'Microsoft', 'Windows', 'Start Menu', 'Programs'),
            os.path.join(os.environ.get('APPDATA', ''), 'Microsoft', 'Windows', 'Start Menu', 'Programs')
        ]
        for p in paths:
            if not os.path.exists(p):
                continue
            for root, _, files in os.walk(p):
                for f in files:
                    if f.endswith('.lnk') or f.endswith('.exe'):
                        app_name = os.path.splitext(f)[0].lower()
                        # Sur Windows, utiliser os.startfile sur le raccourci fonctionne bien
                        app_dict[app_name] = f'start "" "{os.path.join(root, f)}"'
                        mot_cle = app_name.split()[0]
                        if mot_cle not in app_dict:
                            app_dict[mot_cle] = f'start "" "{os.path.join(root, f)}"'
        return app_dict

    # Les dossiers où Linux (et Flatpak) stockent les raccourcis d'applications (.desktop)
    repertoires_a_scanner = [
        "/usr/share/applications/",
        os.path.expanduser("~/.local/share/applications/"),
        "/var/lib/flatpak/exports/share/applications/"
    ]

    for dossier in repertoires_a_scanner:
        if not os.path.exists(dossier):
            continue

        for fichier in os.listdir(dossier):
            if fichier.endswith(".desktop"):
                chemin_complet = os.path.join(dossier, fichier)

                try:
                    nom_gui = None
                    commande_exec = None

                    with open(chemin_complet, 'r', encoding='utf-8', errors='ignore') as f:
                        for ligne in f:
                            if ligne.startswith("Name=") and not nom_gui:
                                nom_gui = ligne.split("=", 1)[1].strip().lower()

                            elif ligne.startswith("Exec=") and not commande_exec:
                                raw_exec = ligne.split("=", 1)[1].strip()
                                commande_exec = raw_exec.split()[0].replace('"', '').replace("'", "")

                    if nom_gui and commande_exec:
                        # Sauvegarde le nom complet (ex: "brave web browser")
                        app_dict[nom_gui] = commande_exec

                        # Sauvegarde le premier mot pour plus de flexibilité (ex: "brave")
                        mot_cle_simple = nom_gui.split()[0]
                        if mot_cle_simple not in app_dict:
                            app_dict[mot_cle_simple] = commande_exec

                except Exception:
                    pass

    return app_dict
