from datetime import datetime
from functools import lru_cache
from pathlib import Path
import platform
import re
import sys
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
    diagnostiquer_reseau,
    reparer_reseau,
    nettoyer_caches,
    analyser_telechargements,
    mettre_a_jour_logiciels,
)

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
    'controler_media': controler_media,
    'redemarrer_pc': redemarrer_pc,
}

LISTE_FONCTIONS = list(outils_disponibles.values())

# --- ROUTAGE DYNAMIQUE D'OUTILS (< 1 ms) & DÉTECTION CONTEXTE MATÉRIEL ---
_DOMAINES_OUTILS = (
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
            r'volume|volumen|lautst(?:[aä]|ae)rke[a-z]*|son|audio|sonido|ton|sound|'
            r'sourdine|muet|mute|unmute|silencio|stumm|'
            r'[eé]coute[rzs]?|listen|escuch[a-z]*|h(?:[oö]|oe)r[a-z]*|'
            r'medias?|m[eé]dias?|medien|medios?)\b',
            re.IGNORECASE,
        ),
        (rechercher_ou_jouer_media, controler_media, ouvrir_application, fermer_application),
    ),
    (
        re.compile(
            r'\b(?:ouvr[eir][a-z]*|open|lance[rzs]?|launch|start|d[eé]marre[rzs]?|'
            r'abr[eir][a-z]*|inicia[rn]?|ejecuta[rn]?|(?:[oö]|oe)ffn[a-z]*|ausf(?:[uü]|ue)hr[a-z]*|'
            r'ferme[rzs]?|close|quitte[rzs]?|quit|exit|kill|arr[eê]te[rzs]?|terminate|'
            r'cierra[rn]?|quita[rn]?|mata[rn]?|schlie(?:[sß]|ss)[a-z]*|beend[a-z]*|t(?:[oö]|oe)t[a-z]*|'
            r'apps?|applis?|applications?|programmes?|logiciels?|software|'
            r'aplicaci[oó]n(?:es)?|anwendun[a-z]*|programme?|'
            r'fen[eê]tres?|windows?|ventanas?|fenster|'
            r'explorateur|explorer|explorador|dateimanager|'
            r'copi[eé][es]?|copier|copy|copia[rn]?|kopier[a-z]*|'
            r'colle[rzs]?|paste|pega[rn]?|einf(?:[uü]|ue)g[a-z]*|'
            r'presse[- ]papiers?|clipboard|portapapeles|zwischenablage)\b',
            re.IGNORECASE,
        ),
        (ouvrir_application, fermer_application, lister_apps_actives, ouvrir_explorateur, rechercher_ou_jouer_media, lire_presse_papiers),
    ),
    (
        re.compile(
            r'\b(?:fichiers?|files?|dossiers?|folders?|r[eé]pertoires?|director(?:y|ies)|'
            r'archivos?|ficheros?|carpetas?|directorios?|'
            r'datei[a-z]*|ordner|verzeichnis(?:se)?|'
            r'documents?|docs?|pdfs?|notes?|textes?|texts?|notas?|notizen?|'
            r'bureau|desktop|escritorio|schreibtisch|'
            r't[eé]l[eé]chargements?|downloads?|descargas?|heruntergeladen|'
            r'cr[eé]e[rzs]?|create|make|crea[rn]?|erstell[a-z]*|anleg[a-z]*|'
            r'[eé]cri[stve][a-z]*|write|escrib[a-z]*|schreib[a-z]*|'
            r'li[st][a-z]*|lire|read|le[aer][a-z]*|les[a-z]*|'
            r'supprime[rzs]?|efface[rzs]?|delete|remove|erase|'
            r'borra[rn]?|elimina[rn]?|suprim[a-z]*|l(?:[oö]|oe)sch[a-z]*|entfern[a-z]*|'
            r'corbeille|trash|recycle bin|papelera|papierkorb|'
            r'renomme[rzs]?|rename|renombra[rn]?|umbenenn[a-z]*|'
            r'd[eé]place[rzs]?|move|muev[a-z]*|mover|traslada[rn]?|verschieb[a-z]*|'
            r'liste[rzs]?|list|mostrar|auflist[a-z]*|'
            r'doublons?|duplicates?|duplicados?|(?:datei)?duplikat[a-z]*|doppelte|'
            r'undo|annule[rzs]?|restaure[rzs]?|revert|deshaz|deshacer|r(?:[uü]|ue)ckg(?:[aä]|ae)ngig|'
            r'sauvegarde[rzs]?|save|guarda[rn]?|speicher[nt]?)\b',
            re.IGNORECASE,
        ),
        (
            creer_fichier, creer_dossier, lister_fichiers, renommer_fichier, deplacer_fichier,
            supprimer_fichier, lire_fichier_securise, ecrire_fichier_securise, generer_pdf,
            trouver_doublons, annuler_derniere_action, analyser_telechargements,
            ouvrir_explorateur, lire_presse_papiers,
        ),
    ),
    (
        re.compile(
            r'\b(?:recherche[rzs]?|cherche[rzs]?|trouve[rzs]?|search|lookup|find|'
            r'busc[aoe][a-z]*|buscar|encuentr[a-z]*|such[a-z]*|recherchier[a-z]*|'
            r'google|web|internet|en ligne|online|en l[ií]nea|'
            r'infos?|nouvelles?|actualit[eé]s?|news|noticias|nachrichten|'
            r'm[eé]t[eé]o|weather|clima|wetter|'
            r'qui est|qu est ce|who is|what is|qui[eé]n es|qu[eé] es|wer ist|was ist|'
            r'site|page|website|webseite|p[aá]gina)\b',
            re.IGNORECASE,
        ),
        (rechercher_web, lire_presse_papiers),
    ),
    (
        re.compile(
            r'\b(?:cpu|processeur|processor|procesador|prozessor[a-z]*|coeurs?|cores?|'
            r'ram|m[eé]moire|memory|memoria|arbeitsspeicher|speicher[a-z]*|'
            r'gpu|vram|carte graphique|tarjeta gr[aá]fica|grafikkarte[a-z]*|nvidia|radeon|'
            r'disques?|stockage|disk(?:s)?|storage|drives?|ssd|hdd|discos?|almacenamiento|festplatte[a-z]*|speicherplatz|'
            r'batterie|battery|bater[ií]a|akku(?:stand)?|autonomie|charge|'
            r'temp[eé]rature|temperature|temperatura|chauffe|surchauffe|calienta|heiss|heiß|(?:[uü]|ue)berhitzung|'
            r'mat[eé]riel|hardware|ventilateur|fan(?:s)?|l(?:[uü]|ue)fter|'
            r'processus|process(?:es)?|procesos?|prozess[a-z]*|pids?|'
            r'services?|systemd|servicios?|dienst(?:e)?|'
            r't[aâ]ches?|tasks?|tareas?|aufgabe(?:n)?|planifi[a-z]*|scheduled|zeitplan|cron|timers?|'
            r'd[eé]marr[a-z]*|startup[a-z]*|autostart[a-z]*|boot|inicio|'
            r'commandes?|commands?|comandos?|befehle?|powershell|terminal|bash|cmd|registre|registry|'
            r'red[eé]marre[rzs]?|reboot|restart|reinicia[rn]?|neustart[a-z]*|'
            r'admin|administrateur|administrator|administrador|syst[eé]me|system|sistema|'
            r'mises? [aà] jour|updates?|upgrade|actualiz[a-z]*|aktualisier[a-z]*|winget|pacman|apt|dnf|'
            r'r[eé]seau|network|red|netzwerk[a-z]*|ping|dns|flushdns|connexion|conexi[oó]n|verbindung[a-z]*|wifi|wi-fi|ethernet|ip|ssid|diagnos[a-z]*|diagnosti[a-z]*|'
            r't[eé]l[eé]m[eé]trie|telemetry|telemetr[ií]a|telemetrie|diagtrack|'
            r'horloge|clock|reloj|uhrzeit|fuseau|timezone|zeitzone|'
            r'lent|lenteurs?|slow|lento|rame[rzs]?|lag|freeze|'
            r'performances?|rendimiento|leistung|auslastung)\b',
            re.IGNORECASE,
        ),
        (
            desactiver_telemetrie_pc, rechercher_processus, lister_services, gerer_service,
            lister_taches_planifiees, gerer_tache_planifiee, lister_apps_demarrage,
            gerer_app_demarrage, executer_commande_systeme, fermer_application, redemarrer_pc,
            mettre_a_jour_logiciels, nettoyer_caches, reparer_reseau, diagnostiquer_reseau,
        ),
    ),
    (
        re.compile(
            r'\b(?:netto[iy][a-z]*|clean[a-z]*|limpi[a-z]*|(?:[a-z]+)?bereinig[a-z]*|s(?:[aä]|ae)uber[a-z]*|'
            r'purger?|purge|purga[rn]?|leeren|vide[rzs]?|empty|vacia[rn]?|'
            r'caches?|cach[eé]s?|temp(?:oraire)?s?|temporales?|tempor(?:[aä]|ae)r[a-z]*|'
            r'inutiles?|junk|basura|m(?:[uü]|ue)ll|datenm(?:[uü]|ue)ll|'
            r'lib[eé]rer|free(?: up)?|liberar|freigeben|'
            r'optimis[a-z]*|optimi[sz][a-z]*|optimier[a-z]*|'
            r'maintenance|mantenimiento|(?:[a-z]+)?wartung[a-z]*)\b',
            re.IGNORECASE,
        ),
        (
            nettoyer_caches,
            desactiver_telemetrie_pc,
            supprimer_fichier,
            trouver_doublons,
            analyser_telechargements,
            lister_fichiers,
            deplacer_fichier,
            lister_apps_demarrage,
            gerer_app_demarrage,
            mettre_a_jour_logiciels,
            executer_commande_systeme,
            rechercher_processus,
            fermer_application,
            reparer_reseau,
            diagnostiquer_reseau,
            gerer_service,
        ),
    ),
)

_KIT_BASE_POLYVALENT = [
    ouvrir_application,
    rechercher_ou_jouer_media,
    controler_media,
    rechercher_processus,
    lister_fichiers,
    lire_presse_papiers,
    executer_commande_systeme,
]

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
    """Sélectionne en < 1 ms le sous-ensemble d'outils pertinent pour la requête utilisateur."""
    if not _load_cached_config().get('llm_provider', {}).get('dynamic_tool_routing', True):
        return LISTE_FONCTIONS

    texte = str(user_input or "")
    selection = []
    vus = set()
    for regex, outils_domaine in _DOMAINES_OUTILS:
        if regex.search(texte):
            for fn in outils_domaine:
                if fn not in vus:
                    vus.add(fn)
                    selection.append(fn)

    return selection if selection else list(_KIT_BASE_POLYVALENT)


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
Tu es Alyx, un assistant système de bureau intelligent, efficace, souverain et 100% hors-ligne (air-gapped).
- Système d'exploitation : {os_nom}
- Répertoire utilisateur : {user_home}
- Langue active : {langue_label}

# Contexte temporel
- Date et Heure locales : {date_heure}

# Directives Opérationnelles
- **Exécution 100% locale (Air-gapped)** : Aucune donnée ne quitte cette machine. N'effectue aucun appel réseau externe et ne fais référence à aucun service cloud distant. Tu fonctionnes exclusivement en environnement local déconnecté.
- **Ancrage factuel & Zéro hallucination** : Fonde chaque réponse uniquement sur l'état vérifié du système et les retours d'outils. Si une information est manquante ou incertaine, indique expressément [Information manquante] au lieu de supposer ou d'inventer.
- **Concision stricte** : Formule des réponses directes, denses et sans bavardage. Élimine les formules de politesse, excuses, flatteries et phrases d'introduction superflues. Moins tu parles, plus tu es efficace.
- **Honnêteté opérationnelle** : Si une action demandée n'est pas automatisable ou ne réussit que partiellement, signale immédiatement la limite technique exacte en une phrase au lieu de prétendre que tout est accompli. Ne simule jamais une exécution d'action.

# Utilisation des Outils
- **Action système = Appel d'outil JSON impératif** : Si l'utilisateur demande une action ou consultation sur le système (fichiers, applications, processus, médias, réseau), appelle IMPÉRATIVEMENT la fonction JSON correspondante. Ne réponds JAMAIS par du texte narratif (ex: « Ouverture en cours... », « Je ferme l'application ») sans avoir appelé l'outil.
- **Exécution multi-outils simultanée** : Lorsque la demande comporte plusieurs actions (ex: « ferme Firefox et ouvre Discord »), appelle TOUS les outils requis en même temps dans le même tour.
- **Paramètres précis & Périmètre autorisé** : Renseigne scrupuleusement les arguments requis selon les schémas d'outils. Respecte le bac à sable du répertoire utilisateur ({user_home}) ; ne cible aucun chemin sensible ou interdit hors périmètre.
- **Modèle Yield/Resume (HITL)** : Les actions critiques ou destructrices (supprimer un fichier, fermer un processus protégé, redémarrer l'ordinateur) déclenchent une demande de confirmation utilisateur (PermissionRequiredException). Suspends l'action et attends la décision explicite de l'utilisateur sans chercher à contourner ce contrôle.
- **Exploitation des retours d'outils** : Utilise le contenu retourné par le rôle `tool` pour formuler ta réponse finale. En cas d'erreur ou d'échec rapporté par un outil, transmets le constat technique exact sans le masquer.

# Format de Réponse
- **Style Néo-brutaliste** : Ton direct, percutant, factuel et sans fioritures. Réponds sans phrase d'introduction ni conclusion cérémonieuse.
- **Mise en forme Markdown** : Structure tes réponses en Markdown quand c'est utile (titres ##, listes à puces, **gras**, `code` pour commandes/chemins/processus, tableaux comparatifs).
- **Formules mathématiques en LaTeX** : Écris obligatoirement les formules inline entre $...$ et les formules bloc entre $$...$$ afin de garantir la compatibilité avec la synthèse vocale (TTS).
- **Préservation linguistique absolue** : {consigne_langue} Conserve TOUJOURS cette langue de réponse, même après l'exécution d'un outil ayant retourné des logs ou messages en anglais. Ne bascule jamais vers une autre langue sans consigne explicite."""


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


def _executer_outil_cli(nom_fonction, arguments):
    fonction = outils_disponibles.get(nom_fonction)
    if fonction is None:
        return f"Erreur: Outil {nom_fonction} introuvable."
    try:
        return fonction(**arguments)
    except PermissionRequiredException as e:
        reponse = input(f"     [Permission requise : {e.action} -> {e.cible}. Autoriser ? (o/N)] ").strip().lower()
        if reponse not in ('o', 'oui', 'y', 'yes'):
            return "L'utilisateur a refusé cette action."
        return executer_avec_permission(fonction, arguments)
    except TypeError as e:
        return f"Erreur: arguments invalides pour {nom_fonction} ({e})."


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
                        'content': str(resultat_execution),
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
