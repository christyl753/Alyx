from datetime import datetime
from functools import lru_cache
from pathlib import Path
import platform
import re
import sys
from typing import Callable
from core.logger import get_logger
from core.exceptions import PermissionRequiredException

logger = get_logger('alyx.ai')
from function import (
    creer_fichier,
    creer_dossier,
    lister_fichiers,
    renommer_fichier,
    deplacer_fichier,
    supprimer_fichier,
    lire_fichier_securise,
    ecrire_fichier_securise,
    generer_pdf,
    trouver_doublons,
    annuler_derniere_action,
    rechercher_web,
    executer_avec_permission,
    faire_parler,
    ecouter,
    ouvrir_explorateur,
    ouvrir_application,
    lister_apps_actives,
    fermer_application,
    controler_media,
    redemarrer_pc,
    rechercher_processus,
    lister_services,
    gerer_service,
    lister_taches_planifiees,
    gerer_tache_planifiee,
    lister_apps_demarrage,
    gerer_app_demarrage,
    desactiver_telemetrie_pc,
    executer_commande_systeme,
    rechercher_ou_jouer_media,
    lire_presse_papiers,
    copier_presse_papiers,
    diagnostiquer_reseau,
    reparer_reseau,
    nettoyer_caches,
    analyser_telechargements,
    mettre_a_jour_logiciels,
    analyser_journaux_crash,
    creer_rappel,
    lister_rappels,
    supprimer_rappel,
    ajouter_note_rapide,
    lister_notes_rapides,
    lire_note_rapide,
    supprimer_note_rapide,
)
from core.context import obtenir_fenetre_active

from core.llm_provider import (
    chat_with_provider,
    load_config,
    preload_models,
)

# --- 1. DÉFINITION DES OUTILS LOCAUX ---
outils_disponibles = {
    'ouvrir_explorateur': ouvrir_explorateur,
    'ouvrir_application': ouvrir_application,
    'lister_apps_actives': lister_apps_actives,
    'fermer_application': fermer_application,
    'rechercher_ou_jouer_media': rechercher_ou_jouer_media,
    'lire_presse_papiers': lire_presse_papiers,
    'copier_presse_papiers': copier_presse_papiers,
    'creer_rappel': creer_rappel,
    'lister_rappels': lister_rappels,
    'supprimer_rappel': supprimer_rappel,
    'ajouter_note_rapide': ajouter_note_rapide,
    'lister_notes_rapides': lister_notes_rapides,
    'lire_note_rapide': lire_note_rapide,
    'supprimer_note_rapide': supprimer_note_rapide,
    'obtenir_fenetre_active': obtenir_fenetre_active,
    'rechercher_processus': rechercher_processus,
    'lister_services': lister_services,
    'gerer_service': gerer_service,
    'lister_taches_planifiees': lister_taches_planifiees,
    'gerer_tache_planifiee': gerer_tache_planifiee,
    'lister_apps_demarrage': lister_apps_demarrage,
    'gerer_app_demarrage': gerer_app_demarrage,
    'desactiver_telemetrie_pc': desactiver_telemetrie_pc,
    'executer_commande_systeme': executer_commande_systeme,
    'creer_fichier': creer_fichier,
    'creer_dossier': creer_dossier,
    'lister_fichiers': lister_fichiers,
    'renommer_fichier': renommer_fichier,
    'deplacer_fichier': deplacer_fichier,
    'supprimer_fichier': supprimer_fichier,
    'lire_fichier_securise': lire_fichier_securise,
    'ecrire_fichier_securise': ecrire_fichier_securise,
    'generer_pdf': generer_pdf,
    'trouver_doublons': trouver_doublons,
    'annuler_derniere_action': annuler_derniere_action,
    'rechercher_web': rechercher_web,
    'diagnostiquer_reseau': diagnostiquer_reseau,
    'reparer_reseau': reparer_reseau,
    'nettoyer_caches': nettoyer_caches,
    'analyser_telechargements': analyser_telechargements,
    'mettre_a_jour_logiciels': mettre_a_jour_logiciels,
    'analyser_journaux_crash': analyser_journaux_crash,
    'controler_media': controler_media,
    'redemarrer_pc': redemarrer_pc,
}

LISTE_FONCTIONS = list(outils_disponibles.values())

# --- 1.1 ALIAS D'OUTILS & NORMALISATION D'ARGUMENTS ---
ALIAS_OUTILS: dict[str, str] = {
    # Fichiers & dossiers
    'move_file': 'deplacer_fichier',
    'move_files': 'deplacer_fichier',
    'move': 'deplacer_fichier',
    'mv': 'deplacer_fichier',
    'deplacer_fichiers': 'deplacer_fichier',
    'deplacer': 'deplacer_fichier',
    'deplacement_fichier': 'deplacer_fichier',
    'ranger_fichier': 'deplacer_fichier',
    'ranger_fichiers': 'deplacer_fichier',

    'list_files': 'lister_fichiers',
    'list_file': 'lister_fichiers',
    'list_dir': 'lister_fichiers',
    'listdir': 'lister_fichiers',
    'ls': 'lister_fichiers',
    'dir': 'lister_fichiers',
    'lister_fichier': 'lister_fichiers',
    'lister_dossier': 'lister_fichiers',
    'lister_repertoire': 'lister_fichiers',
    'liste_fichiers': 'lister_fichiers',
    'liste_dossier': 'lister_fichiers',

    'read_file': 'lire_fichier_securise',
    'cat': 'lire_fichier_securise',
    'view_file': 'lire_fichier_securise',
    'lire_fichier': 'lire_fichier_securise',
    'lire_contenu_fichier': 'lire_fichier_securise',

    'write_file': 'ecrire_fichier_securise',
    'ecrire_fichier': 'ecrire_fichier_securise',
    'enregistrer_fichier': 'ecrire_fichier_securise',

    'delete_file': 'supprimer_fichier',
    'delete_files': 'supprimer_fichier',
    'remove_file': 'supprimer_fichier',
    'rm': 'supprimer_fichier',
    'trash_file': 'supprimer_fichier',
    'supprimer_fichiers': 'supprimer_fichier',
    'supprimer': 'supprimer_fichier',
    'effacer_fichier': 'supprimer_fichier',

    'create_file': 'creer_fichier',
    'touch': 'creer_fichier',
    'new_file': 'creer_fichier',
    'creer_fichiers': 'creer_fichier',

    'create_folder': 'creer_dossier',
    'create_directory': 'creer_dossier',
    'mkdir': 'creer_dossier',
    'new_folder': 'creer_dossier',
    'creer_repertoire': 'creer_dossier',
    'creer_dossiers': 'creer_dossier',

    'rename_file': 'renommer_fichier',
    'rename': 'renommer_fichier',
    'renommer_fichiers': 'renommer_fichier',
    'renommer': 'renommer_fichier',

    'find_duplicates': 'trouver_doublons',
    'scan_duplicates': 'trouver_doublons',
    'detecter_doublons': 'trouver_doublons',

    'undo': 'annuler_derniere_action',
    'revert': 'annuler_derniere_action',
    'annuler': 'annuler_derniere_action',

    # Applications & Système
    'open_app': 'ouvrir_application',
    'launch_app': 'ouvrir_application',
    'start_app': 'ouvrir_application',
    'lancer_application': 'ouvrir_application',

    'close_app': 'fermer_application',
    'kill_app': 'fermer_application',
    'quit_app': 'fermer_application',
    'arreter_application': 'fermer_application',

    'list_apps': 'lister_apps_actives',
    'get_running_apps': 'lister_apps_actives',
    'lister_applications': 'lister_apps_actives',

    'open_explorer': 'ouvrir_explorateur',
    'open_folder': 'ouvrir_explorateur',
    'explorer': 'ouvrir_explorateur',

    'read_clipboard': 'lire_presse_papiers',
    'get_clipboard': 'lire_presse_papiers',
    'clipboard': 'lire_presse_papiers',

    'find_process': 'rechercher_processus',
    'search_process': 'rechercher_processus',
    'ps': 'rechercher_processus',

    'media_control': 'controler_media',
    'control_media': 'controler_media',

    'restart_pc': 'redemarrer_pc',
    'reboot': 'redemarrer_pc',

    'run_command': 'executer_commande_systeme',
    'exec_command': 'executer_commande_systeme',
    'cmd': 'executer_commande_systeme',

    'web_search': 'rechercher_web',
    'search_web': 'rechercher_web',

    # Rappels & Notes (B.8.3)
    'create_reminder': 'creer_rappel',
    'add_reminder': 'creer_rappel',
    'rappel': 'creer_rappel',
    'nouveau_rappel': 'creer_rappel',
    'list_reminders': 'lister_rappels',
    'get_reminders': 'lister_rappels',
    'rappels': 'lister_rappels',
    'delete_reminder': 'supprimer_rappel',
    'remove_reminder': 'supprimer_rappel',

    'add_note': 'ajouter_note_rapide',
    'create_note': 'ajouter_note_rapide',
    'quick_note': 'ajouter_note_rapide',
    'nouvelle_note': 'ajouter_note_rapide',
    'note': 'ajouter_note_rapide',
    'list_notes': 'lister_notes_rapides',
    'get_notes': 'lister_notes_rapides',
    'notes': 'lister_notes_rapides',
    'read_note': 'lire_note_rapide',
    'get_note': 'lire_note_rapide',
    'view_note': 'lire_note_rapide',
    'delete_note': 'supprimer_note_rapide',
    'remove_note': 'supprimer_note_rapide',

    'copy_clipboard': 'copier_presse_papiers',
    'set_clipboard': 'copier_presse_papiers',
    'copier': 'copier_presse_papiers',
    'get_active_window': 'obtenir_fenetre_active',
}

ARG_ALIASES: dict[str, dict[str, str]] = {
    'deplacer_fichier': {
        'source': 'chemin_source',
        'src': 'chemin_source',
        'file': 'chemin_source',
        'file_path': 'chemin_source',
        'source_path': 'chemin_source',
        'chemin': 'chemin_source',
        'destination': 'dossier_destination',
        'dst': 'dossier_destination',
        'target': 'dossier_destination',
        'target_dir': 'dossier_destination',
        'target_folder': 'dossier_destination',
        'destination_folder': 'dossier_destination',
        'dossier': 'dossier_destination',
    },
    'lister_fichiers': {
        'path': 'dossier',
        'folder': 'dossier',
        'directory': 'dossier',
        'dir': 'dossier',
        'chemin': 'dossier',
    },
    'lire_fichier_securise': {
        'file': 'chemin',
        'file_path': 'chemin',
        'path': 'chemin',
    },
    'supprimer_fichier': {
        'file': 'chemin',
        'file_path': 'chemin',
        'path': 'chemin',
    },
    'creer_fichier': {
        'file': 'chemin',
        'file_path': 'chemin',
        'path': 'chemin',
    },
    'creer_dossier': {
        'folder': 'chemin',
        'folder_path': 'chemin',
        'directory': 'chemin',
        'path': 'chemin',
        'dossier': 'chemin',
    },
    'ecrire_fichier_securise': {
        'file': 'chemin',
        'file_path': 'chemin',
        'path': 'chemin',
        'text': 'contenu',
        'content': 'contenu',
    },
    'renommer_fichier': {
        'chemin': 'chemin_actuel',
        'source': 'chemin_actuel',
        'file': 'chemin_actuel',
        'nouveau': 'nouveau_nom',
        'new_name': 'nouveau_nom',
        'name': 'nouveau_nom',
    },
    'creer_rappel': {
        'message': 'texte',
        'rappel': 'texte',
        'content': 'texte',
        'delai': 'delai_minutes',
        'minutes': 'delai_minutes',
        'time': 'date_heure',
        'date': 'date_heure',
    },
    'supprimer_rappel': {
        'id': 'rappel_id',
        'id_rappel': 'rappel_id',
    },
    'ajouter_note_rapide': {
        'title': 'titre',
        'text': 'contenu',
        'content': 'contenu',
        'body': 'contenu',
        'tag': 'etiquette',
        'category': 'etiquette',
    },
    'lister_notes_rapides': {
        'tag': 'etiquette',
        'category': 'etiquette',
        'count': 'limite',
        'max': 'limite',
    },
    'lire_note_rapide': {
        'id': 'titre_ou_id',
        'title': 'titre_ou_id',
        'name': 'titre_ou_id',
    },
    'supprimer_note_rapide': {
        'id': 'titre_ou_id',
        'title': 'titre_ou_id',
    },
    'copier_presse_papiers': {
        'text': 'texte',
        'content': 'texte',
        'valeur': 'texte',
    },
}


def resoudre_outil(nom_fonction: str, arguments: dict | None = None) -> tuple[Callable | None, str, dict]:
    """Résout un nom d'outil (canonique ou alias) et normalise ses arguments."""
    if not isinstance(nom_fonction, str):
        nom_nettoye = str(nom_fonction or "").strip().lower().replace('-', '_')
    else:
        nom_nettoye = nom_fonction.strip().lower().replace('-', '_')

    if nom_nettoye in outils_disponibles:
        nom_canonique = nom_nettoye
    elif nom_nettoye in ALIAS_OUTILS:
        nom_canonique = ALIAS_OUTILS[nom_nettoye]
    else:
        nom_canonique = nom_nettoye

    fonction = outils_disponibles.get(nom_canonique)

    args_entrants = dict(arguments) if arguments else {}
    alias_map = ARG_ALIASES.get(nom_canonique, {})
    args_normalises = dict(args_entrants)

    if alias_map:
        for k, v in list(args_entrants.items()):
            k_clean = k.strip().lower().replace('-', '_') if isinstance(k, str) else k
            if k_clean in alias_map:
                canon_k = alias_map[k_clean]
                if canon_k not in args_normalises or args_normalises[canon_k] is None:
                    args_normalises[canon_k] = v
                if k != canon_k:
                    args_normalises.pop(k, None)

    return fonction, nom_canonique, args_normalises

# --- ROUTAGE DYNAMIQUE D'OUTILS (< 1 ms) & DÉTECTION CONTEXTE MATÉRIEL ---
_DOMAINES_OUTILS = (
    # Médias & Volume (Audio / Streaming)
    (
        re.compile(
            r'\b(?:spotify|deezer|youtube|yt|soundcloud|'
            r'musiques?|chansons?|titres?|morceaux?|pistes?|'
            r'music|songs?|tracks?|albums?|artist(?:es?|s)?|playlists?|'
            r'm[uú]si[ck][a-z]*|canci[oó]n(?:es)?|temas?|[aá]lbum(?:es)?|'
            r'lied(?:er)?|titel|spuren?|k(?:[uü]|ue)nstler|wiedergabeliste(?:n)?|'
            r'joue[rzs]?|lance[rzs]?|play|pause|stop|arr[eê]te[rzs]?|coupe[rzs]?|'
            r'reproduc[eir][a-z]*|toca[rn]?|para[rn]?|deten[a-z]*|'
            r'spiel[a-z]*|abspiel[a-z]*|stopp[a-z]*|anhalten|pausier[a-z]*|'
            r'suivante?s?|pr[eé]c[eé]dente?s?|next|previous|prev|skip|'
            r'siguiente[s]?|anterior(?:es)?|pasa[rn]?|'
            r'n(?:[aä]|ae)chste[a-z]*|vorherige[a-z]*|weiter|zur(?:[uü]|ue)ck|(?:[uü]|ue)berspringen|'
            r'volume|volumen|lautst(?:[aä]|ae)rke[a-z]*|lautstärkeregelung|lautstärkeeinstellung|lautstärkeregler|'
            r'son|audio|sonido|ton|sound|'
            r'sourdine|muet|mute|unmute|silencio|stumm[a-z]*|'
            r'[eé]coute[rzs]?|listen|escuch[a-z]*|h(?:[oö]|oe)r[a-z]*|'
            r'medias?|m[eé]dias?|medien|medios?)\b',
            re.IGNORECASE,
        ),
        (controler_media, rechercher_ou_jouer_media, ouvrir_application, fermer_application),
    ),
    # Presse-papiers (lecture & copie - B.8.3)
    (
        re.compile(
            r'\b(?:presse[- ]papiers?|clipboard|portapapeles|zwischenablage|'
            r'copi[eé][es]?|copier|copy|copia[rn]?|kopier[a-z]*|'
            r'colle[rzs]?|paste|pega[rn]?|einf(?:[uü]|ue)g[a-z]*)\b',
            re.IGNORECASE,
        ),
        (copier_presse_papiers, lire_presse_papiers),
    ),
    # Rappels programmés (B.8.3)
    (
        re.compile(
            r'\b(?:rappels?|reminders?|recordatorios?|erinnerung(?:en)?|'
            r'rappelle[rzs]?|remind|recu[eé]rda[rn]?|erinner[a-z]*|'
            r'alarme?s?|alarm(?:en)?|minuteur|timer|compte [aà] rebours)\b',
            re.IGNORECASE,
        ),
        (creer_rappel, lister_rappels, supprimer_rappel),
    ),
    # Notes rapides (B.8.3)
    (
        re.compile(
            r'\b(?:notes? rapides?|quick\s*notes?|notas? r[aá]pidas?|kurze\s*notizen?|m[eé]mo[s]?|pense[- ]b[eê]te|carnet)\b|'
            r'(?<!bloc[- ])(?<!bloc de )(?<!bloc )\b(?:notes?|notizen?|note[rzs]?|noter|apunt[a-z]*|notier[a-z]*|aufschreib[a-z]*)\b|'
            r'(?<!bloc de )\bnotas?\b',
            re.IGNORECASE,
        ),
        (ajouter_note_rapide, lister_notes_rapides, lire_note_rapide, supprimer_note_rapide),
    ),
    # Contexte & Fenêtre active (B.8.6)
    (
        re.compile(
            r'\b(?:fen[eê]tre active|active window|foreground window|'
            r'application active|programme actif|sur quoi je travaille)\b',
            re.IGNORECASE,
        ),
        (obtenir_fenetre_active, lister_apps_actives),
    ),
    # Télémétrie
    (
        re.compile(
            r'\b(?:t[eé]l[eé]m[eé]trie|telemetry|telemetr[ií]a|telemetrie|diagtrack)\b',
            re.IGNORECASE,
        ),
        (desactiver_telemetrie_pc,),
    ),
    # Réseau & Connexion
    (
        re.compile(
            r'\b(?:r[eé]seau|network|red|netzwerk[a-z]*|netzwerkdiagnose|ping|dns|flushdns|'
            r'connexion|conexi[oó]n|verbindung[a-z]*|wifi|wi-fi|ethernet|ip|ssid|diagnos[a-z]*|diagnosti[a-z]*)\b',
            re.IGNORECASE,
        ),
        (diagnostiquer_reseau, reparer_reseau, executer_commande_systeme),
    ),
    # Services système
    (
        re.compile(
            r'\b(?:services?|systemd|servicios?|dienst(?:e)?)\b',
            re.IGNORECASE,
        ),
        (lister_services, gerer_service),
    ),
    # Journaux système et recherche de sources de crash
    (
        re.compile(
            r'\b(?:journaux?|logs?|event\s*viewer|observateur d[’\']év[eé]nements|'
            r'crash(?:es)?|plantages?|pannes?|coredumps?|core dumps?|journalctl|'
            r'identifier.*(?:erreur|crash|plantage)|(?:erreur|crash|plantage).*(?:source|cause))\b',
            re.IGNORECASE,
        ),
        (analyser_journaux_crash, executer_commande_systeme),
    ),
    # Tâches planifiées
    (
        re.compile(
            r'\b(?:t[aâ]ches?|tasks?|tareas?|aufgabe(?:n)?|planifi[a-z]*|scheduled|programadas?|zeitplan|cron|timers?)\b',
            re.IGNORECASE,
        ),
        (lister_taches_planifiees, gerer_tache_planifiee),
    ),
    # Applications au démarrage
    (
        re.compile(
            r'\b(?:d[eé]marr[a-z]*|startup[a-z]*|autostart[a-z]*|autostartprogramme|boot|inicio)\b',
            re.IGNORECASE,
        ),
        (lister_apps_demarrage, gerer_app_demarrage),
    ),
    # Mises à jour logicielles
    (
        re.compile(
            r'\b(?:mises? [aà] jour|updates?|upgrade|actualiz[a-z]*|aktualisier[a-z]*|winget|pacman|apt|dnf)\b',
            re.IGNORECASE,
        ),
        (mettre_a_jour_logiciels, executer_commande_systeme),
    ),
    # Redémarrage PC
    (
        re.compile(
            r'\b(?:red[eé]marre[rzs]?|reboot|restart|reinicia[rn]?|neustart[a-z]*)\b',
            re.IGNORECASE,
        ),
        (redemarrer_pc,),
    ),
    # Nettoyage & Caches (Maintenance)
    (
        re.compile(
            r'\b(?:netto[iy][a-z]*|clean[a-z]*|limpi[a-z]*|(?:[a-z]+)?bereinig[a-z]*|s(?:[aä]|ae)uber[a-z]*|'
            r'purger?|purge|purga[rn]?|leeren|vide[rzs]?|empty|vacia[rn]?|'
            r'caches?|cach[eé]s?|temp(?:oraire)?s?|temporales?|tempor(?:[aä]|ae)r[a-z]*|'
            r'inutiles?|junk|basura|m(?:[uü]|ue)ll|datenm(?:[uü]|ue)ll|'
            r'lib[eé]rer|free(?: up)?|liberar|freigeben|'
            r'optimis[a-z]*|optimi[sz][a-z]*|optimier[a-z]*|'
            r'maintenance|mantenimiento|(?:[a-z]+)?wartung[a-z]*|'
            r'festplattenbereinigung|speicherbereinigung|systemwartung)\b',
            re.IGNORECASE,
        ),
        (nettoyer_caches, supprimer_fichier, trouver_doublons, analyser_telechargements),
    ),
    # Applications actives & Gestion fenêtres
    (
        re.compile(
            r'\b(?:(?:apps?|applis?|applications?|fen[eê]tres?|windows?|ventanas?|fenster)\s+(?:actives?|ouvertes?)|running\s+apps?|fen[eê]tres?\s+ouvertes?|laufende[n]?\s+anwendungen)\b',
            re.IGNORECASE,
        ),
        (lister_apps_actives, ouvrir_application, fermer_application),
    ),
    # Explorateur de fichiers
    (
        re.compile(
            r'\b(?:explorateur|explorer|explorador|dateimanager)\b',
            re.IGNORECASE,
        ),
        (ouvrir_explorateur, lister_fichiers),
    ),
    # Organisation, Déplacement et Rangement de fichiers
    (
        re.compile(
            r'\b(?:d[eé]place[rzs]?|move|muev[a-z]*|mover|traslada[rn]?|verschieb[a-z]*|'
            r'range[rzs]?|trie[rzs]?|organis[a-z]*|class[a-z]*)\b',
            re.IGNORECASE,
        ),
        (deplacer_fichier, lister_fichiers, creer_dossier, renommer_fichier),
    ),
    # Recherche de doublons
    (
        re.compile(
            r'\b(?:doublons?|duplicates?|duplicados?|(?:datei)?duplikat[a-z]*|dateiduplikate|doppelte)\b',
            re.IGNORECASE,
        ),
        (trouver_doublons, lister_fichiers, supprimer_fichier),
    ),
    # Génération et manipulation PDF
    (
        re.compile(
            r'\b(?:pdf|pdfs?)\b',
            re.IGNORECASE,
        ),
        (generer_pdf, lire_fichier_securise, lister_fichiers),
    ),
    # Analyse des téléchargements
    (
        re.compile(
            r'\b(?:analy[sz][a-z]*|examine[rzs]?|scan[a-z]*)\b.*\b(?:t[eé]l[eé]chargements?|downloads?|descargas?|heruntergeladen)\b|\b(?:t[eé]l[eé]chargements?|downloads?|descargas?|heruntergeladen)\b.*\b(?:analy[sz][a-z]*|examine[rzs]?|scan[a-z]*)\b',
            re.IGNORECASE,
        ),
        (analyser_telechargements, lister_fichiers, ouvrir_explorateur),
    ),


    # Annulation d'action / Revert
    (
        re.compile(
            r'\b(?:undo|annule[rzs]?|restaure[rzs]?|revert|deshaz|deshacer|r(?:[uü]|ue)ckg(?:[aä]|ae)ngig)\b',
            re.IGNORECASE,
        ),
        (annuler_derniere_action, lister_fichiers),
    ),
    # Suppression / Corbeille
    (
        re.compile(
            r'\b(?:supprime[rzs]?|efface[rzs]?|delete|remove|erase|'
            r'borra[rn]?|elimina[rn]?|suprim[a-z]*|l(?:[oö]|oe)sch[a-z]*|entfern[a-z]*|'
            r'corbeille|trash|recycle bin|papelera|papierkorb)\b',
            re.IGNORECASE,
        ),
        (supprimer_fichier, lister_fichiers, annuler_derniere_action),
    ),
    # Renommage de fichiers
    (
        re.compile(
            r'\b(?:renomme[rzs]?|rename|renombra[rn]?|umbenenn[a-z]*)\b',
            re.IGNORECASE,
        ),
        (renommer_fichier, lister_fichiers),
    ),
    # Lecture de fichiers
    (
        re.compile(
            r'\b(?:lis|lit|lisons|lisez|lisent|lire|lecture|read|reading|leer|le[ey][a-z]*|lesen|liest|gelesen|consulte[rzs]?|dateiinhalt)\b',
            re.IGNORECASE,
        ),
        (lire_fichier_securise, ecrire_fichier_securise, lister_fichiers),
    ),

    # Écriture dans les fichiers
    (
        re.compile(
            r'\b(?:[eé]cri[stve][a-z]*|write|escrib[a-z]*|schreib[a-z]*)\b',
            re.IGNORECASE,
        ),
        (ecrire_fichier_securise, creer_fichier, lire_fichier_securise, lister_fichiers),
    ),
    # Création de fichiers ou dossiers
    (
        re.compile(
            r'\b(?:cr[eé]e[rzs]?|create|make|crea[rn]?|erstell[a-z]*|anleg[a-z]*)\b',
            re.IGNORECASE,
        ),
        (creer_fichier, creer_dossier, lister_fichiers),
    ),
    # Recherche Web
    (
        re.compile(
            r'\b(?:google|web|internet|en ligne|online|en l[ií]nea|'
            r'infos?|nouvelles?|actualit[eé]s?|news|noticias|nachrichten|'
            r'm[eé]t[eé]o|weather|clima|wetter|'
            r'qui est|qu est ce|who is|what is|qui[eé]n es|qu[eé] es|wer ist|was ist|'
            r'site|website|webseite|p[aá]gina|wikipedia|wiki)\b|'
            r'\b(?:recherche[rzs]?|cherche[rzs]?|search|lookup)\b.*\b(?:web|internet|en ligne|online|google)\b',
            re.IGNORECASE,
        ),
        (rechercher_web, lire_presse_papiers),
    ),

    # Applications & Cycle de vie fenêtres
    (
        re.compile(
            r'\b(?:ouvr[eir][a-z]*|open|lance[rzs]?|launch|start|d[eé]marre[rzs]?|'
            r'abr[eir][a-z]*|inicia[rn]?|ejecuta[rn]?|(?:[oö]|oe)ffn[a-z]*|ausf(?:[uü]|ue)hr[a-z]*|'
            r'ferme[rzs]?|close|quitte[rzs]?|quit|exit|kill|arr[eê]te[rzs]?|terminate|'
            r'cierra[rn]?|quita[rn]?|mata[rn]?|schlie(?:[sß]|ss)[a-z]*|beend[a-z]*|t(?:[oö]|oe)t[a-z]*|'
            r'apps?|applis?|applications?|programmes?|logiciels?|software|'
            r'aplicaci[oó]n(?:es)?|anwendun[a-z]*|programme?|'
            r'fen[eê]tres?|windows?|ventanas?|fenster)\b',
            re.IGNORECASE,
        ),
        (ouvrir_application, fermer_application, lister_apps_actives, ouvrir_explorateur),
    ),
    # Matériel & Processus système
    (
        re.compile(
            r'\b(?:cpu|processeur|processor|procesador|prozessor[a-z]*|prozessorauslastung|hintergrundprozess|coeurs?|cores?|'
            r'ram|m[eé]moire|memory|memoria|arbeitsspeicher|speicher[a-z]*|'
            r'gpu|vram|carte graphique|tarjeta gr[aá]fica|grafikkarte[a-z]*|nvidia|radeon|'
            r'disques?|stockage|disk(?:s)?|storage|drives?|ssd|hdd|discos?|almacenamiento|festplatte[a-z]*|speicherplatz|'
            r'batterie|battery|bater[ií]a|akku(?:stand)?|autonomie|charge|'
            r'temp[eé]rature|temperature|temperatura|chauffe|surchauffe|calienta|heiss|heiß|(?:[uü]|ue)berhitzung|'
            r'mat[eé]riel|hardware|ventilateur|fan(?:s)?|l(?:[uü]|ue)fter|'
            r'processus|process(?:es)?|procesos?|prozess[a-z]*|pids?|'
            r'horloge|clock|reloj|uhrzeit|fuseau|timezone|zeitzone|'
            r'lent|lenteurs?|slow|lento|rame[rzs]?|lag|freeze|'
            r'performances?|rendimiento|leistung|auslastung)\b',
            re.IGNORECASE,
        ),
        (rechercher_processus, fermer_application, executer_commande_systeme),
    ),
    # Fichiers générique / Navigation / Dateiverwaltung
    (
        re.compile(
            r'\b(?:fichiers?|files?|dossiers?|folders?|r[eé]pertoires?|director(?:y|ies)|'
            r'archivos?|ficheros?|carpetas?|directorios?|'
            r'datei[a-z]*|ordner|verzeichnis(?:se)?|dateiverwaltung|'
            r'documents?|docs?|notes?|textes?|texts?|notas?|notizen?|'
            r'bureau|desktop|escritorio|schreibtisch)\b',
            re.IGNORECASE,
        ),
        (lister_fichiers, deplacer_fichier, creer_dossier, ouvrir_explorateur, lire_presse_papiers),
    ),

    # Commandes système / Terminal
    (
        re.compile(
            r'\b(?:commandes?|commands?|comandos?|befehle?|powershell|terminal|bash|cmd|registre|registry|'
            r'admin|administrateur|administrator|administrador|syst[eé]me|system|sistema)\b',
            re.IGNORECASE,
        ),
        (executer_commande_systeme,),
    ),
)


_KIT_BASE_POLYVALENT = [
    ouvrir_application,
    lister_fichiers,
    lire_presse_papiers,
    rechercher_processus,
]

def _charger_tools_config() -> dict:
    try:
        from core.preferences import get_tools_config
        return get_tools_config()
    except Exception:
        return {
            'budget_max_outils': 1000,
            'max_outils_routage': 6,
        }

_tools_init = _charger_tools_config()
MAX_OUTILS_ROUTAGE = _tools_init['max_outils_routage']
BUDGET_MAX_OUTILS = _tools_init['budget_max_outils']

_REGEX_BESOIN_ETAT_SYSTEME = re.compile(
    r'\b(?:cpu|processeur|processor|procesador|prozessor[a-z]*|coeurs?|cores?|'
    r'ram|m[eé]moire|memory|memoria|arbeitsspeicher|speicher[a-z]*|'
    r'gpu|vram|carte graphique|tarjeta gr[aá]fica|grafikkarte[a-z]*|nvidia|radeon|'
    r'disques?|stockage|disk(?:s)?|storage|drives?|ssd|hdd|discos?|almacenamiento|festplatte[a-z]*|speicherplatz|'
    r'batterie|battery|bater[ií]a|akku(?:stand)?|autonomie|charge|'
    r'temp[eé]rature|temperature|temperatura|chauffe|surchauffe|calienta|heiss|heiß|(?:[uü]|ue)berhitzung|'
    r'mat[eé]riel|hardware|ventilateur|fan(?:s)?|l(?:[uü]|ue)fter|'
    r'r[eé]seau|network|red|netzwerk[a-z]*|wifi|wi-fi|ssid|internet|ip|d[eé]bit|speed|velocidad|geschwindigkeit|'
    r'lent|lenteurs?|slow|lento|rame[rzs]?|lag|freeze|'
    r'performances?|rendement|rendimiento|leistung|auslastung|'
    r'processus|process(?:es)?|procesos?|prozess[a-z]*|consomme[a-z]*|consuming|consume|verbraucht|gourmand[es]?|heavy|'
    r'utilisation|usage|uso|nutzung|[eé]tat|state|status|estado|zustand|sant[eé]|health|salud|'
    r'config|configuration|machine|pc|ordinateur|computer|computadora|rechner|'
    r'horloge|clock|reloj|uhrzeit|fuseau|timezone|zeitzone)\b',
    re.IGNORECASE,
)


@lru_cache(maxsize=1)
def _load_cached_config():
    return load_config()


def selectionner_outils_pertinents(user_input: str) -> list:
    """Selectionne le sous-ensemble d'outils pertinent pour la requete utilisateur."""
    cfg = _load_cached_config()
    if not cfg.get('llm_provider', {}).get('dynamic_tool_routing', True):
        return LISTE_FONCTIONS

    tools_cfg = cfg.get('tools', {})
    max_outils = int(tools_cfg.get('max_outils_routage', MAX_OUTILS_ROUTAGE))
    budget_max = int(tools_cfg.get('budget_max_outils', BUDGET_MAX_OUTILS))

    texte = str(user_input or "")
    selection = []
    vus = set()
    for regex, outils_domaine in _DOMAINES_OUTILS:
        if regex.search(texte):
            for fn in outils_domaine:
                if fn not in vus:
                    vus.add(fn)
                    selection.append(fn)
                    if len(selection) >= max_outils:
                        break
        if len(selection) >= max_outils:
            break

    if not selection:
        selection = list(_KIT_BASE_POLYVALENT)

    from core.token_counter import estimer_tokens_outils
    while len(selection) > 1 and estimer_tokens_outils(selection) > budget_max:
        selection.pop()

    return selection


def besoin_etat_systeme(user_input: str) -> bool:
    """Détermine si le snapshot matériel en direct (CPU/RAM/GPU/processus) est utile à la requête."""
    return bool(_REGEX_BESOIN_ETAT_SYSTEME.search(str(user_input or "")))


def _detecter_os_nom() -> str:
    """Détecte le nom du système d'exploitation hôte pour l'ancrage contextuel."""
    if sys.platform == 'win32':
        return 'Windows'
    if sys.platform.startswith('linux'):
        return 'Linux'
    if sys.platform == 'darwin':
        return 'macOS'
    return platform.system() or 'Inconnu'


# --- 2. INITIALISATION DE L'AGENT ---
PROMPT_BASE = """# Identité & Mission
Tu es Alyx, assistant système de bureau souverain et 100% hors-ligne (air-gapped).
- Système d'exploitation : {os_nom}
- Répertoire utilisateur : {user_home}
- Langue active : {langue_label}

# Contexte temporel
- Date et Heure locales : {date_heure}

# Directives Opérationnelles
- **Air-gapped local** : Zéro fuite réseau. Aucun appel externe ni service cloud.
- **Ancrage factuel** : Fonde les réponses sur les faits et retours d'outils. Si une info manque, indique expressément [Information manquante].
- **Concision** : Réponses directes, sans politesses, excuses ni phrases d'introduction.
- **Honnêteté** : Si une action est impossible ou partielle, signale la limite technique. Ne simule jamais une exécution.

# Utilisation des Outils
- **Appel impératif** : Toute action ou consultation système requiert l'appel de fonction JSON idoine. Jamais de texte narratif sans outil.
- **Multi-outils** : Pour plusieurs actions, émets tous les outils requis dans le même tour.
- **Périmètre** : Respecte les schémas et le bac à sable ({user_home}).
- **Modèle Yield/Resume (HITL)** : Actions critiques soumises à confirmation (PermissionRequiredException). Suspends et attends la décision utilisateur.
- **Retours d'outils** : Transmets les résultats réels et erreurs techniques sans les masquer.

# Tâches par Lots & Manipulation de Fichiers
- **Méthode** : 1) `lister_fichiers` sans wildcard `*` pour identifier les cibles. 2) Émettre chaque `deplacer_fichier` dans le même tour sans s'arrêter au premier.
- **Exemple** : Ranger des fichiers -> lister le dossier puis déplacer tous les éléments ciblés.

# Format de Réponse
- **Style Néo-brutaliste** : Ton direct, percutant et sans fioritures.
- **Structure Markdown** : Utilise le format Markdown (listes, gras, code, tableaux) selon besoin.
- **Formules LaTeX** : Écris les maths inline en $...$ et en bloc en $$...$$ pour la synthèse vocale.
- **Langue** : {consigne_langue} Réponds toujours dans la langue de l'utilisateur."""



def prompt_systeme(langue: str = 'fr', timestamp: str | None = None) -> str:
    """Prompt système complet structuré en Markdown avec ancrage contextuel dynamique."""
    from core.preferences import LANGUES, consigne_langue

    os_nom = _detecter_os_nom()
    user_home = str(Path.home())
    date_heure = timestamp if timestamp is not None else datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    langue_info = LANGUES.get(langue, LANGUES.get('fr', ('Français', 'Réponds toujours en français.')))
    langue_label = langue_info[0]
    consigne = consigne_langue(langue)

    return PROMPT_BASE.format(
        os_nom=os_nom,
        user_home=user_home,
        langue_label=langue_label,
        date_heure=date_heure,
        consigne_langue=consigne,
    )


generer_prompt_systeme = prompt_systeme

messages: list[dict] = [{'role': 'system', 'content': prompt_systeme('fr')}]

# Modèle courant (peut être changé dynamiquement via l'API).
# Le pré-chargement est lancé par le point d'entrée (api.py ou lancer_cli), pas à l'import.
MODEL = 'Aucun modèle'


def tronquer_sortie_outil(resultat, max_chars: int = 4000) -> str:
    """Sanitiseur défensif : tronque les sorties volumineuses d'outils avant injection dans le contexte."""
    if resultat is None:
        return ""
    resultat_str = str(resultat)
    if len(resultat_str) > max_chars:
        return resultat_str[:max_chars] + f"\n[Sortie tronquée : affichage des {max_chars} premiers caractères sur {len(resultat_str)}]"
    return resultat_str


def _executer_outil_cli(nom_fonction, arguments):
    fonction, nom_canonique, args_normalises = resoudre_outil(nom_fonction, arguments)
    if fonction is None:
        return f"Erreur: Outil {nom_fonction} introuvable."
    try:
        res = fonction(**args_normalises)
    except PermissionRequiredException as e:
        reponse = input(f"     [Permission requise : {e.action} -> {e.cible}. Autoriser ? (o/N)] ").strip().lower()
        if reponse not in ('o', 'oui', 'y', 'yes'):
            return "L'utilisateur a refusé cette action."
        res = executer_avec_permission(fonction, args_normalises)
    except TypeError as e:
        return f"Erreur: arguments invalides pour {nom_canonique} ({e})."
    return tronquer_sortie_outil(res)


def lancer_cli():
    global MODEL
    MODEL = preload_models()
    logger.info("Alyx (Local): Agent Système en ligne.")
    print("---> Alyx (Local): Bonjour Maître Christ, l'Agent Système est en ligne.")
    print("     (Tape 'bye' pour quitter, ou 'vocal' pour activer/désactiver le micro)")

    mode_vocal = False

    # --- BOUCLE AGENTIQUE ---
    while True:
        if mode_vocal:
            user_input = ecouter()
            if not user_input:
                continue
        else:
            user_input = input("\n----> ")

        user_input_lower = user_input.strip().lower()

        if user_input_lower in ['bye', 'out', 'tu peux disposer']:
            print("---> Alyx: Déconnexion locale. À bientôt !")
            faire_parler("Déconnexion de l'Agent. À bientôt.")
            break

        if user_input_lower == 'vocal':
            mode_vocal = not mode_vocal
            etat = "activé" if mode_vocal else "désactivé"
            print(f"---> Alyx: Mode vocal {etat}.")
            faire_parler(f"Mode vocal {etat}")
            continue

        if not user_input_lower:
            continue

        if MODEL == 'Aucun modèle':
            print("\n---> Alyx: Aucun modèle n'est sélectionné ou disponible. Lancez Ollama ou LM Studio.")
            continue

        messages.append({'role': 'user', 'content': user_input})
        outils_tour = selectionner_outils_pertinents(user_input)

        try:
            response = chat_with_provider(model_name=MODEL, messages_list=messages, tools=outils_tour)
            message_ia = response['message']
            messages.append(message_ia)

            # Boucle multi-tool : continuer tant que le modèle demande des outils
            max_iterations = load_config().get('llm_provider', {}).get('max_tool_iterations', 10)
            iteration = 0
            while message_ia.get('tool_calls') and iteration < max_iterations:
                for tool_call in message_ia['tool_calls']:
                    nom_fonction = tool_call['function']['name']
                    arguments = tool_call['function'].get('arguments') or {}
                    logger.info(f"Action système détectée : exécution de {nom_fonction}({arguments})...")
                    print(f"     [Action système détectée : exécution de {nom_fonction}({arguments})...]")

                    resultat_execution = _executer_outil_cli(nom_fonction, arguments)
                    messages.append({
                        'role': 'tool',
                        'content': tronquer_sortie_outil(resultat_execution),
                        'name': nom_fonction,
                        'tool_name': nom_fonction,
                        'tool_call_id': tool_call['id']
                    })

                iteration += 1
                outils = outils_tour if iteration < max_iterations else None
                response = chat_with_provider(model_name=MODEL, messages_list=messages, tools=outils)
                message_ia = response['message']
                messages.append(message_ia)

            print(f"\n---> Alyx: {message_ia['content']}")
            faire_parler(message_ia['content'])

        except Exception as e:
            logger.error(f"Erreur système LLM : {e}", exc_info=True)
            print(f"\n---> Erreur système LLM : {e}")


if __name__ == "__main__":
    lancer_cli()
