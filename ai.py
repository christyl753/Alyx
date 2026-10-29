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
    'controler_media': controler_media,
    'redemarrer_pc': redemarrer_pc
}

LISTE_FONCTIONS = list(outils_disponibles.values())

# --- 2. INITIALISATION DE L'AGENT ---
PROMPT_BASE = (
    "Tu es Alyx, un assistant système intelligent et efficace. "
    "RÈGLE ABSOLUE : Si l'utilisateur te demande d'effectuer une action système (ouvrir/fermer une application, créer un fichier, etc.), "
    "tu DOIS IMPÉRATIVEMENT utiliser l'outil/la fonction JSON correspondant. "
    "Ne réponds JAMAIS par du texte comme 'Ouverture en cours...' ou 'Je ferme l'application' sans avoir appelé l'outil. "
    "IMPORTANT: Quand l'utilisateur te demande de réaliser PLUSIEURS actions dans une même requête "
    "(par exemple 'ferme Firefox et ouvre Discord'), tu DOIS appeler TOUS les outils nécessaires en même temps. "
    "Tu as accès aux outils pour : ouvrir/fermer des applications, rechercher et lister tous les processus actifs, "
    "lister et gérer les services système (arrêter, démarrer, désactiver), lister et gérer les tâches planifiées, "
    "lister et gérer les applications au démarrage automatique, désactiver intégralement la télémétrie du PC "
    "(utilise `desactiver_telemetrie_pc` dès qu'on te demande de couper ou désactiver la télémétrie partout), "
    "exécuter des commandes système PowerShell/Bash (`executer_commande_systeme`), gérer les fichiers "
    "(lister, créer, renommer, déplacer, lire, écrire, et supprimer), générer des PDF, contrôler la musique (lecture/pause, suivant, précédent) et redémarrer le PC. Un état du système en direct (CPU, RAM, GPU, processus) t'est fourni : utilise-le pour répondre aux questions sur la machine. "
    "Réponds de façon très concise. Moins tu parles, mieux c'est. "
    "Mets en forme tes réponses en Markdown quand c'est utile (titres ##, listes, **gras**, `code`, tableaux) ; "
    "écris les formules en LaTeX entre $...$, ou $$...$$ pour une formule seule sur sa ligne."
)


def prompt_systeme(langue: str = 'fr') -> str:
    """Prompt système complet pour la langue de réponse choisie dans les réglages."""
    from core.preferences import consigne_langue
    return f"{PROMPT_BASE} {consigne_langue(langue)}"


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

        try:
            response = chat_with_provider(model_name=MODEL, messages_list=messages, tools=LISTE_FONCTIONS)
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
                outils = LISTE_FONCTIONS if iteration < max_iterations else None
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
