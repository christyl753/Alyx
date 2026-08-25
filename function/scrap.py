# Fichier : function/scrap.py
import os
import re
import sys
import unicodedata


def normaliser_texte(texte: str) -> str:
    """Minuscules sans accents : 'Surveillance du système' -> 'surveillance du systeme'.

    L'utilisateur tape rarement les accents ("gestionnaire de tache"), alors que les
    fichiers .desktop les portent toujours. On aligne les deux.
    """
    texte = unicodedata.normalize('NFKD', texte.lower().strip())
    return ''.join(c for c in texte if not unicodedata.combining(c))


# Mots sans valeur discriminante pour identifier une application.
MOTS_IGNORES = {'app', 'application', 'appli', 'logiciel', 'programme',
                'le', 'la', 'les', 'l', 'de', 'du', 'des', 'd', 'a', 'au', 'aux',
                'et', 'ou', 'en', 'pour', 'sur', 'to', 'the', 'of', 'for'}


def racine(token: str) -> str:
    """Rapproche singulier et pluriel ('taches' -> 'tache').

    Appliquée des deux côtés de la comparaison, elle reste sûre même quand elle se
    trompe : 'processus' devient 'processu' dans la requête comme dans l'index.
    """
    return token[:-1] if len(token) > 3 and token.endswith('s') else token


def tokeniser(texte: str) -> list:
    """Découpe un nom en mots significatifs, sans accents ni séparateurs."""
    texte = normaliser_texte(texte)
    texte = re.sub(r'\.(desktop|exe|app)$', '', texte)
    tokens = [t for t in re.split(r'[\s\-_./]+', texte) if t]
    significatifs = [t for t in tokens if t not in MOTS_IGNORES]
    # Si l'utilisateur n'a tapé que des mots vides, on garde les tokens bruts.
    return significatifs or tokens


def _locales_preferees() -> list:
    """Codes de langue à privilégier pour lire les champs traduits des .desktop."""
    codes = []
    for variable in ('LC_ALL', 'LC_MESSAGES', 'LANG'):
        valeur = os.environ.get(variable)
        if valeur and valeur not in ('C', 'POSIX'):
            base = valeur.split('.')[0]          # fr_FR.utf8 -> fr_FR
            codes.extend([base, base.split('_')[0]])
            break
    codes.append('fr')  # Alyx s'adresse à un utilisateur francophone.
    return list(dict.fromkeys(codes))


# Champs du standard freedesktop qui décrivent une application en langage humain.
# 'keywords' existe précisément pour que « gestionnaire de tâches » trouve
# « System Monitor » : c'est la métadonnée prévue pour la recherche.
_CHAMPS_NOMS = ('name', 'genericname')
_CHAMP_MOTS_CLES = 'keywords'
_LIGNE_DESKTOP = re.compile(r'^([A-Za-z][A-Za-z0-9-]*)(?:\[([^\]]+)\])?\s*=\s*(.*)$')


def _lire_desktop(chemin: str, locales: list) -> tuple:
    """Extrait (commande, noms, mots_cles) d'un fichier .desktop.

    Seul le groupe [Desktop Entry] est lu : les groupes [Desktop Action ...] ont
    leurs propres Name=/Exec= qui désigneraient une action, pas l'application.
    """
    commande = None
    noms, mots_cles = [], []
    masque = False
    dans_entry = False

    with open(chemin, 'r', encoding='utf-8', errors='ignore') as f:
        for ligne in f:
            ligne = ligne.strip()
            if ligne.startswith('['):
                dans_entry = (ligne == '[Desktop Entry]')
                continue
            if not dans_entry or not ligne or ligne.startswith('#'):
                continue

            correspondance = _LIGNE_DESKTOP.match(ligne)
            if not correspondance:
                continue
            champ, langue, valeur = correspondance.groups()
            champ = champ.lower()
            valeur = valeur.strip()
            if not valeur:
                continue

            if champ in ('nodisplay', 'hidden') and valeur.lower() == 'true':
                masque = True
            elif champ == 'exec' and not commande:
                commande = valeur.split()[0].replace('"', '').replace("'", "")
            elif champ in _CHAMPS_NOMS and (langue is None or langue in locales):
                noms.append(valeur)
            elif champ == _CHAMP_MOTS_CLES and (langue is None or langue in locales):
                # "tâche ; gestionnaire ; processus ;" -> mots individuels
                mots_cles.extend(m.strip() for m in valeur.split(';') if m.strip())

    if masque:
        return None, [], []
    return commande, noms, mots_cles


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

    locales = _locales_preferees()
    applications = []

    for dossier in repertoires_a_scanner:
        if not os.path.exists(dossier):
            continue

        for fichier in os.listdir(dossier):
            if not fichier.endswith(".desktop"):
                continue
            try:
                commande, noms, mots_cles = _lire_desktop(
                    os.path.join(dossier, fichier), locales
                )
                if commande and noms:
                    applications.append((commande, noms, mots_cles))
            except Exception:
                pass

    # Passe 1 : les noms réels (Name, GenericName, y compris traduits). Ils sont
    # prioritaires et peuvent s'écraser entre eux sans dommage.
    for commande, noms, _ in applications:
        for nom in noms:
            nom_normalise = normaliser_texte(nom)
            if nom_normalise:
                app_dict[nom_normalise] = commande

    # Passe 2 : premier mot du nom (« brave » pour « brave web browser »), sans
    # jamais écraser un nom complet déjà enregistré.
    for commande, noms, _ in applications:
        for nom in noms:
            mots = normaliser_texte(nom).split()
            if mots:
                app_dict.setdefault(mots[0], commande)

    # Passe 3 : les mots-clés de recherche (« gestionnaire », « tâche »). Volontairement
    # en dernier : ce sont des termes génériques, ils ne doivent jamais masquer le nom
    # d'une application réellement installée.
    for commande, _, mots_cles in applications:
        for mot_cle in mots_cles:
            mot_normalise = normaliser_texte(mot_cle)
            if mot_normalise:
                app_dict.setdefault(mot_normalise, commande)

    return app_dict


def construire_index_recherche() -> list:
    """Index sémantique : [(commande, {termes}, {termes_de_nom}), ...].

    Contrairement au dictionnaire nom -> commande, cet index ne perd rien : une même
    application conserve TOUS ses termes. C'est indispensable quand deux applications
    partagent un mot-clé — « gestionnaire » appartient au gestionnaire de fichiers
    comme au gestionnaire de tâches, seul le décompte global permet de trancher.
    """
    if sys.platform == "win32":
        return [
            (commande, set(tokeniser(nom)), set(tokeniser(nom)))
            for nom, commande in construire_dictionnaire_applications().items()
        ]

    repertoires_a_scanner = [
        "/usr/share/applications/",
        os.path.expanduser("~/.local/share/applications/"),
        "/var/lib/flatpak/exports/share/applications/"
    ]

    index = []
    locales = _locales_preferees()
    for dossier in repertoires_a_scanner:
        if not os.path.exists(dossier):
            continue
        for fichier in os.listdir(dossier):
            if not fichier.endswith(".desktop"):
                continue
            try:
                commande, noms, mots_cles = _lire_desktop(
                    os.path.join(dossier, fichier), locales
                )
                if not (commande and noms):
                    continue
                termes_nom = set()
                for nom in noms:
                    termes_nom.update(racine(t) for t in tokeniser(nom))
                termes = set(termes_nom)
                for mot_cle in mots_cles:
                    termes.update(racine(t) for t in tokeniser(mot_cle))
                # Le nom de l'exécutable est lui aussi un terme de recherche valide.
                termes.add(racine(normaliser_texte(os.path.basename(commande))))
                index.append((commande, termes, termes_nom))
            except Exception:
                pass

    return index
