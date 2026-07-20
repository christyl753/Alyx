# Fichier : ai.py
import subprocess
import ollama
import requests
import sys
import os
import psutil

# --- 1. IMPORTS DE TES MODULES CUSTOM ---
from function import (
    construire_dictionnaire_applications,
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
    ecouter
)

# --- 2. INITIALISATION DU SYSTÈME ---
print("     [Initialisation : Scan des applications installées...]")
ALIAS_DYNAMIQUES = construire_dictionnaire_applications()
print(f"     [Succès : {len(ALIAS_DYNAMIQUES)} alias d'applications générés !]")

# --- 3. DÉFINITION DES OUTILS LOCAUX ---
def ouvrir_explorateur() -> str:
    """Ouvre l'explorateur de fichiers."""
    if sys.platform == "win32":
        os.startfile('.')
    elif sys.platform == "darwin":
        subprocess.Popen(['open', '.'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.Popen(['xdg-open', '.'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "L'explorateur a été ouvert avec succès."

def ouvrir_application(nom_commande: str) -> str:
    """Lance une application via son nom système."""
    nom_propre = nom_commande.lower().strip()
    commande_reelle = ALIAS_DYNAMIQUES.get(nom_propre, nom_propre)
    try:
        subprocess.Popen(commande_reelle.split(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return f"L'application a été lancée via la commande système '{commande_reelle}'."
    except FileNotFoundError:
        return f"Erreur: la commande système '{commande_reelle}' est introuvable."

def lister_apps_actives() -> str:
    """Liste les applications courantes en cours d'exécution."""
    if sys.platform == "win32":
        apps_courantes = ['explorer.exe', 'notepad.exe', 'firefox.exe', 'chrome.exe', 'brave.exe', 'discord.exe']
    else:
        apps_courantes = ['dolphin', 'kate', 'firefox', 'brave', 'brave-browser', 'discord', 'konsole', 'steam']
    resultat = ""
    for app in apps_courantes:
        count = sum(1 for proc in psutil.process_iter(['name']) if proc.info['name'] and proc.info['name'].lower() == app.lower())
        if count == 1:
            resultat += f"- {app} (1 instance)\n"
        elif count > 1:
            resultat += f"- {app} ({count} instances en cours)\n"
    return resultat if resultat else "Aucune application surveillée n'est actuellement ouverte."

def fermer_application(nom_app: str) -> str:
    """Ferme (tue le processus) une application via son nom."""
    nom_propre = nom_app.lower().strip().replace('.desktop', '')
    if sys.platform == "win32" and not nom_propre.endswith('.exe'):
        nom_propre += '.exe'
        
    fermee = False
    for proc in psutil.process_iter(['name']):
        if proc.info['name'] and proc.info['name'].lower() == nom_propre:
            try:
                proc.kill()
                fermee = True
            except Exception:
                pass
                
    if fermee:
        return f"Le processus de l'application '{nom_propre}' a été terminé avec succès."
    return f"Erreur : Impossible de trouver ou de fermer l'application '{nom_app}'."

def redemarrer_pc() -> str:
    """Redémarre l'ordinateur."""
    try:
        if sys.platform == "win32":
            os.system("shutdown /r /t 0")
        else:
            os.system("reboot")
        return "Le redémarrage du système a été initié."
    except Exception as e:
        return f"Erreur lors de la tentative de redémarrage : {e}"

# --- 4. ROUTAGE DES OUTILS ---
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

LISTE_FONCTIONS = [
    ouvrir_explorateur, ouvrir_application, lister_apps_actives,
    fermer_application, creer_fichier, creer_dossier,
    lister_fichiers, renommer_fichier, deplacer_fichier, supprimer_fichier,
    lire_fichier_securise, ecrire_fichier_securise, generer_pdf,
    redemarrer_pc
]

# --- 5. INITIALISATION DE L'AGENT ---
messages = [{'role': 'system', 'content': (
    "Tu es Alyx, un assistant système intelligent et efficace. "
    "IMPORTANT: Quand l'utilisateur te demande de réaliser PLUSIEURS actions dans une même requête "
    "(par exemple 'ferme Firefox et ouvre Discord'), tu DOIS appeler TOUS les outils nécessaires "
    "dans ta réponse. N'appelle pas un seul outil si la requête en nécessite plusieurs. "
    "Tu peux ouvrir/fermer des applications, lister les processus, gérer les fichiers "
    "(lister, créer, renommer, déplacer, lire et écrire, et supprimer via la corbeille), générer des PDF, et redémarrer le PC. "
    "Les fonctions lire_fichier_securise, ecrire_fichier_securise, et generer_pdf déclenchent une demande de permission "
    "qui te permet de le faire de manière sécurisée si l'utilisateur l'accepte. "
    "Réponds toujours en français, de façon concise."
)}]

# Modèle courant (peut être changé dynamiquement via l'API)
MODEL = 'Aucun modèle'

# --- 6. PROVIDERS DE MODÈLES ---
# Configuration des différents fournisseurs de modèles
PROVIDERS = {
    'ollama': {
        'name': 'Ollama',
        'api_base': 'http://localhost:11434',
        'list_endpoint': '/api/tags'
    },
    'lmstudio': {
        'name': 'LM Studio',
        'api_base': 'http://127.0.0.1:1234',
        'list_endpoint': '/v1/models'
    },
    'nvidia': {
        'name': 'NVIDIA NIM',
        'api_base': 'http://127.0.0.1:8000',
        'list_endpoint': '/v1/models'
    }
}

def lister_modeles_disponibles() -> dict:
    """Liste les modèles disponibles sur tous les fournisseurs détectés."""
    resultats = {}
    
    # 1. Ollama
    try:
        resp = requests.get(f"{PROVIDERS['ollama']['api_base']}/api/tags", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('models', [])
            resultats['ollama'] = [
                {
                    'name': m.get('name', m.get('model', 'inconnu')),
                    'size': f"{m.get('size', 0) / (1024**3):.1f} GB",
                    'provider': 'ollama'
                }
                for m in models
            ]
    except Exception:
        pass

    # 2. LM Studio (OpenAI-compatible API)
    try:
        resp = requests.get(f"{PROVIDERS['lmstudio']['api_base']}/v1/models", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('data', [])
            resultats['lmstudio'] = [
                {
                    'name': m.get('id', 'inconnu'),
                    'size': '--',
                    'provider': 'lmstudio'
                }
                for m in models
            ]
    except Exception:
        pass

    # 3. NVIDIA NIM (also OpenAI-compatible)
    try:
        resp = requests.get(f"{PROVIDERS['nvidia']['api_base']}/v1/models", timeout=3)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('data', [])
            resultats['nvidia'] = [
                {
                    'name': m.get('id', 'inconnu'),
                    'size': '--',
                    'provider': 'nvidia'
                }
                for m in models
            ]
    except Exception:
        pass

    return resultats

def get_default_model():
    models = lister_modeles_disponibles()
    if 'ollama' in models and len(models['ollama']) > 0:
        return models['ollama'][0]['name']
    if 'lmstudio' in models and len(models['lmstudio']) > 0:
        return models['lmstudio'][0]['name']
    return 'Aucun modèle'

# On met à jour le modèle par défaut avec le premier modèle trouvé
MODEL = get_default_model()

def get_model_provider(model_name: str) -> str:
    models = lister_modeles_disponibles()
    for provider, model_list in models.items():
        for m in model_list:
            if m['name'] == model_name:
                return provider
    return 'ollama' # fallback

def chat_with_provider(model_name, messages_list, tools=None):
    provider = get_model_provider(model_name)
    if provider == 'ollama':
        return ollama.chat(
            model=model_name,
            messages=messages_list,
            tools=tools,
            keep_alive='1h'
        )
    elif provider in ['lmstudio', 'nvidia']:
        # Fallback HTTP request to OpenAI-compatible endpoint (no tools support yet)
        api_base = PROVIDERS[provider]['api_base']
        payload = {
            "model": model_name,
            "messages": messages_list,
            "temperature": 0.7
        }
        try:
            resp = requests.post(f"{api_base}/v1/chat/completions", json=payload, timeout=120)
            resp.raise_for_status()
            data = resp.json()
            content = data['choices'][0]['message'].get('content', '')
            return {
                'message': {
                    'role': 'assistant',
                    'content': content,
                    'tool_calls': []
                }
            }
        except Exception as e:
            raise Exception(f"Erreur {provider}: {e}")
    else:
        raise Exception(f"Fournisseur non supporté: {provider}")


def lancer_cli():
    global messages
    print("---> Alyx (Local via Ollama): Bonjour Maître Christ, l'Agent Système est en ligne.")
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
            print(f"\n---> Erreur système Ollama : {e}")

if __name__ == "__main__":
    lancer_cli()
