import threading
import sys
from core.logger import get_logger

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
    faire_parler,
    ecouter,
    ouvrir_explorateur,
    ouvrir_application,
    lister_apps_actives,
    fermer_application,
    redemarrer_pc
)

from core.llm_provider import (
    chat_with_provider,
    preload_models,
    lister_modeles_disponibles,
    is_models_ready,
    get_default_model
)

# --- 1. DÉFINITION DES OUTILS LOCAUX ---
outils_disponibles = {
    'ouvrir_explorateur': ouvrir_explorateur,
    'ouvrir_application': ouvrir_application,
    'lister_apps_actives': lister_apps_actives,
    'fermer_application': fermer_application,
    'creer_fichier': creer_fichier,
    'creer_dossier': creer_dossier,
    'lister_fichiers': lister_fichiers,
    'renommer_fichier': renommer_fichier,
    'deplacer_fichier': deplacer_fichier,
    'supprimer_fichier': supprimer_fichier,
    'lire_fichier_securise': lire_fichier_securise,
    'ecrire_fichier_securise': ecrire_fichier_securise,
    'generer_pdf': generer_pdf,
    'redemarrer_pc': redemarrer_pc
}

LISTE_FONCTIONS = list(outils_disponibles.values())

# --- 2. INITIALISATION DE L'AGENT ---
messages = [{'role': 'system', 'content': (
    "Tu es Alyx, un assistant système intelligent et efficace. "
    "RÈGLE ABSOLUE : Si l'utilisateur te demande d'effectuer une action système (ouvrir/fermer une application, créer un fichier, etc.), "
    "tu DOIS IMPÉRATIVEMENT utiliser l'outil/la fonction JSON correspondant. "
    "Ne réponds JAMAIS par du texte comme 'Ouverture en cours...' ou 'Je ferme l'application' sans avoir appelé l'outil. "
    "IMPORTANT: Quand l'utilisateur te demande de réaliser PLUSIEURS actions dans une même requête "
    "(par exemple 'ferme Firefox et ouvre Discord'), tu DOIS appeler TOUS les outils nécessaires en même temps. "
    "Tu as accès aux outils pour : ouvrir/fermer des applications, lister les processus, gérer les fichiers "
    "(lister, créer, renommer, déplacer, lire, écrire, et supprimer), générer des PDF, et redémarrer le PC. "
    "Réponds toujours en français, de façon très concise. Moins tu parles, mieux c'est."
)}]

# Modèle courant (peut être changé dynamiquement via l'API)
MODEL = 'Aucun modèle'
_preload_thread = None

# --- PRÉ-CHARGEMENT ASYNCHRONE AU DÉMARRAGE ---
def _preload_and_set():
    global MODEL
    MODEL = preload_models()

_preload_thread = threading.Thread(target=_preload_and_set, daemon=True)
_preload_thread.start()


def lancer_cli():
    global messages, MODEL
    # Attendre que le pré-chargement des modèles soit terminé
    _preload_thread.join(timeout=10)
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

        messages.append({'role': 'user', 'content': user_input})

        try:
            if MODEL == 'Aucun modèle':
                print("\n---> Alyx: Aucun modèle n'est sélectionné ou disponible. Lancez Ollama ou LM Studio.")
                continue

            response = chat_with_provider(
                model_name=MODEL,
                messages_list=messages,
                tools=LISTE_FONCTIONS
            )
            message_ia = response['message']
            messages.append(message_ia)

            # Boucle multi-tool : continuer tant que le modèle demande des outils
            max_iterations = 5
            iteration = 0
            while message_ia.get('tool_calls') and iteration < max_iterations:
                for tool_call in message_ia['tool_calls']:
                    nom_fonction = tool_call['function']['name']
                    arguments = tool_call['function'].get('arguments', {})
                    logger.info(f"Action système détectée : exécution de {nom_fonction}({arguments})...")
                    print(f"     [Action système détectée : exécution de {nom_fonction}({arguments})...]")

                    if nom_fonction in outils_disponibles:
                        try:
                            resultat_execution = outils_disponibles[nom_fonction](**arguments)
                        except TypeError:
                            resultat_execution = outils_disponibles[nom_fonction]()
                    else:
                        resultat_execution = f"Erreur: Outil {nom_fonction} introuvable."

                    messages.append({
                        'role': 'tool',
                        'content': resultat_execution,
                        'name': nom_fonction
                    })

                response = chat_with_provider(model_name=MODEL, messages_list=messages, tools=LISTE_FONCTIONS)
                message_ia = response['message']
                messages.append(message_ia)
                iteration += 1

            print(f"\n---> Alyx: {message_ia['content']}")
            faire_parler(message_ia['content'])

        except Exception as e:
            logger.error(f"Erreur système LLM : {e}", exc_info=True)
            print(f"\n---> Erreur système LLM : {e}")

if __name__ == "__main__":
    lancer_cli()
