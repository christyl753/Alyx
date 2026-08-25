import asyncio
import http
import websockets
import json
import os
import signal
import socket
import sys
import threading
from urllib.parse import urlparse, parse_qs

from core.exceptions import PermissionRequiredException
import ai
from ai import messages, LISTE_FONCTIONS, outils_disponibles
from core.llm_provider import lister_modeles_disponibles, get_provider_status, load_config
from core.pairing import obtenir_token, regenerer_token, obtenir_ip_locale
from function import faire_parler
from core.logger import get_logger
import urllib.request
import urllib.error
import time

logger = get_logger('alyx.ws_api')

config = load_config()
MAX_CONTEXT_MESSAGES = config.get('llm_provider', {}).get('max_context_messages', 40)
_server_config = config.get('server', {})
PORT = _server_config.get('port', 8765)
MOBILE_PORT = _server_config.get('mobile_port', 8766)
# Ouvre l'API au réseau Wi-Fi local (app mobile) : toute connexion NON locale doit
# passer le jeton de jumelage (voir _verifier_origine_connexion). Mettre à false
# revient au comportement historique 100% local (aucune écoute réseau).
ALLOW_LAN = _server_config.get('allow_lan', True)
BIND_ADDRESS = "0.0.0.0" if ALLOW_LAN else "localhost"

_stt_config = config.get('stt', {})
STT_PORT = _stt_config.get('port', 5001)
STT_TIMEOUT = _stt_config.get('request_timeout', 20)

# Gestion du Kill Switch
_cancel_events = {}
# Dernier mode_vocal utilisé par connexion : permet à la reprise après validation
# Human-in-the-Loop (_reprendre_apres_permission) de savoir si la réponse doit être
# aussi lue à voix haute, sans que le client ait besoin de le retransmettre.
_last_mode_vocal = {}


def _tool_call_vers_dict(tool_call) -> dict:
    """Normalise un tool_call en dict JSON-sérialisable.

    Selon le fournisseur, tool_call est soit un objet pydantic 'ollama.ToolCall' (non
    JSON-sérialisable tel quel : json.dumps() plantait ici, faisant crasher toute
    demande de permission — cf. tests/test_pairing.py découvert en testant le
    compagnon mobile), soit déjà un dict plat construit à la main (LM Studio/NVIDIA,
    voir core/llm_provider.py). Les deux cas sont couverts.
    """
    if hasattr(tool_call, 'model_dump'):
        return tool_call.model_dump()
    return dict(tool_call)


def _verifier_origine_connexion(connection, request):
    """Porte d'entrée unique du serveur : exécutée avant l'upgrade WebSocket.

    La machine locale (127.0.0.1/::1) est TOUJOURS autorisée sans jeton — c'est le
    chemin emprunté par l'UI C# elle-même, aucune friction pour l'usage principal.
    Toute autre origine (le téléphone sur le Wi-Fi local, ou n'importe quel autre
    appareil du réseau) doit présenter le jeton de jumelage en paramètre d'URL
    (?token=...), sans quoi la connexion est rejetée avant même d'atteindre
    handler_client. C'est ce qui rend l'ouverture au réseau (ALLOW_LAN) sûre.
    """
    if not ALLOW_LAN:
        return None  # BIND_ADDRESS vaut déjà "localhost" dans ce cas ; rien à faire ici

    ip_distante = connection.remote_address[0] if connection.remote_address else None
    if ip_distante in ('127.0.0.1', '::1', None):
        return None

    query = parse_qs(urlparse(request.path).query)
    token_fourni = (query.get('token') or [''])[0]

    if not token_fourni or token_fourni != obtenir_token():
        logger.warning(f"Connexion refusée depuis {ip_distante} : jeton de jumelage invalide ou absent.")
        return connection.respond(http.HTTPStatus.UNAUTHORIZED, "Jeton de jumelage invalide ou manquant.\n")

    return None

def _messages_avec_fenetre():
    if len(messages) <= 1:
        return messages
    system_prompt = messages[0]
    recents = messages[1:]
    
    if len(recents) > MAX_CONTEXT_MESSAGES:
        # Trouver un point de coupure sûr
        start_idx = len(recents) - MAX_CONTEXT_MESSAGES
        
        # On recule si on coupe au milieu d'une paire tool_call/tool
        while start_idx > 0:
            msg = recents[start_idx]
            prev_msg = recents[start_idx - 1]
            if msg.get('role') == 'tool' or prev_msg.get('tool_calls'):
                start_idx -= 1
            else:
                break
                
        recents = recents[start_idx:]
        
    last_user_idx = len(recents) - 1
    while last_user_idx >= 0 and recents[last_user_idx].get('role') != 'user':
        last_user_idx -= 1
        
    optimized = [system_prompt]
    for i, msg in enumerate(recents):
        if i < last_user_idx:
            if msg.get('role') in ['user', 'assistant'] and msg.get('content'):
                optimized.append({'role': msg['role'], 'content': msg['content']})
        else:
            optimized.append(msg)
            
    return optimized

async def handle_chat(websocket, data):
    user_input = data.get('prompt', '')
    mode_vocal = data.get('vocal', False)

    if mode_vocal and not user_input:
        # "listening" est un statut distinct de "system_action" : il permet à l'UI
        # d'afficher un indicateur micro-actif différent de "l'IA réfléchit", ce qui
        # évite la confusion "pourquoi ça ne répond pas" pendant l'enregistrement.
        await websocket.send(json.dumps({"type": "listening"}))

        def _appeler_stt():
            req = urllib.request.Request(f"http://127.0.0.1:{STT_PORT}/listen", method="POST")
            with urllib.request.urlopen(req, timeout=STT_TIMEOUT) as response:
                return json.loads(response.read().decode('utf-8'))

        # L'appel STT est poussé dans un thread (jamais d'appel bloquant dans la boucle
        # asyncio, cf. AGENTS.md B.3) et couru contre le Kill Switch : un clic sur
        # "annuler" pendant l'écoute rend la main immédiatement, sans attendre la fin
        # de l'enregistrement/transcription côté micro-service.
        cancel_event = _cancel_events.get(websocket)
        stt_task = asyncio.ensure_future(asyncio.to_thread(_appeler_stt))
        a_attendre = {stt_task}
        cancel_task = asyncio.ensure_future(cancel_event.wait()) if cancel_event else None
        if cancel_task:
            a_attendre.add(cancel_task)

        done, _ = await asyncio.wait(a_attendre, return_when=asyncio.FIRST_COMPLETED)

        if cancel_task and cancel_task in done:
            logger.info("Écoute annulée via Kill Switch.")
            await websocket.send(json.dumps({"type": "done"}))
            return
        if cancel_task:
            cancel_task.cancel()

        try:
            res_data = stt_task.result()
            user_input = res_data.get('text', '')
            raison = res_data.get('reason', 'ok')
        except Exception as e:
            logger.error(f"Erreur STT: {e}")
            user_input = ""
            raison = "erreur_micro"

        if not user_input:
            messages_par_raison = {
                'silence': "Je n'ai rien entendu.",
                'modele_indisponible': "La reconnaissance vocale n'est pas disponible sur cet environnement.",
                'erreur_micro': "Erreur du microphone ou du service de reconnaissance vocale.",
            }
            # 'reason' permet au client de distinguer un silence normal (à réessayer
            # sans pénalité) d'une vraie panne (à compter dans son compteur d'échecs).
            await websocket.send(json.dumps({
                "type": "error",
                "reason": raison,
                "message": messages_par_raison.get(raison, "Je n'ai rien entendu (ou erreur STT)...")
            }))
            await websocket.send(json.dumps({"type": "done"}))
            return

    if not user_input:
        return

    messages.append({'role': 'user', 'content': user_input})
    _last_mode_vocal[websocket] = mode_vocal

    current_model = ai.MODEL
    if current_model == 'Aucun modèle':
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Aucun modèle n'est sélectionné ou disponible."
        }))
        await websocket.send(json.dumps({"type": "done"}))
        return

    await _continuer_conversation(websocket, current_model, mode_vocal)


async def _continuer_conversation(websocket, current_model, mode_vocal):
    """
    Corps de la boucle agentique (appel LLM -> outils -> réponse), partagé par deux
    points d'entrée :
    - handle_chat() : nouveau message utilisateur (texte ou vocal transcrit).
    - _reprendre_apres_permission() : reprise après décision Human-in-the-Loop, où le
      dernier message de `messages` est déjà le résultat d'un outil (pas un nouveau
      prompt utilisateur) — extraire cette fonction évite de dupliquer toute la logique
      de streaming/TTS/kill-switch entre les deux chemins.
    """
    # PHASE 1: Outils (Appel non-streamé)
    contexte = _messages_avec_fenetre()
    response = await asyncio.to_thread(
        ai.chat_with_provider,
        model_name=current_model,
        messages_list=contexte,
        tools=LISTE_FONCTIONS,
        stream=False
    )
    
    message_ia = response['message']
    
    # Boucle d'outils
    iteration = 0
    while message_ia.get('tool_calls') and iteration < 5:
        messages.append(message_ia)
        
        for tool_call in message_ia['tool_calls']:
            nom_fonction = tool_call['function']['name']
            arguments = tool_call['function'].get('arguments', {})
            
            await websocket.send(json.dumps({
                "type": "system_action",
                "content": f"Exécution de {nom_fonction}..."
            }))
            
            if nom_fonction in outils_disponibles:
                try:
                    # Executer l'outil dans un thread séparé
                    def run_tool():
                        try:
                            return outils_disponibles[nom_fonction](**arguments)
                        except TypeError:
                            return outils_disponibles[nom_fonction]()
                    
                    resultat_execution = await asyncio.to_thread(run_tool)
                except PermissionRequiredException as e:
                    logger.warning(f"Permission requise pour l'outil {nom_fonction}.")
                    await websocket.send(json.dumps({
                        "type": "action_required",
                        "action": e.action,
                        "cible": e.cible,
                        "tool_call": _tool_call_vers_dict(tool_call)
                    }))
                    # On suspend ce tour : le client devra renvoyer permission_granted
                    # ou permission_denied (voir _reprendre_apres_permission) pour
                    # reprendre la conversation là où elle s'est arrêtée.
                    return
            else:
                resultat_execution = f"Erreur: Outil {nom_fonction} introuvable."
                
            tool_call_id = tool_call.get('id')
            
            tool_msg = {
                'role': 'tool',
                'content': str(resultat_execution),
                'name': nom_fonction
            }
            if tool_call_id:
                tool_msg['tool_call_id'] = tool_call_id
                
            messages.append(tool_msg)
            
        contexte = _messages_avec_fenetre()
        response = await asyncio.to_thread(
            ai.chat_with_provider,
            model_name=current_model,
            messages_list=contexte,
            tools=LISTE_FONCTIONS,
            stream=False
        )
        message_ia = response['message']
        iteration += 1

    # Le dernier appel non-streamé (détection d'outils ou fin de boucle d'outils)
    # a déjà produit la réponse finale : on l'utilise directement plutôt que de
    # relancer une 2e inférence complète juste pour la re-streamer (latence x2).
    contenu_deja_genere = (message_ia.get('content') or '').strip()
    if not message_ia.get('tool_calls') and contenu_deja_genere:
        await websocket.send(json.dumps({
            "type": "token",
            "content": contenu_deja_genere
        }))
        if mode_vocal:
            faire_parler(contenu_deja_genere)
        messages.append({'role': 'assistant', 'content': contenu_deja_genere})
        await websocket.send(json.dumps({"type": "done"}))
        return

    # PHASE 2: Réponse textuelle (Appel streamé) — filet de sécurité si le
    # dernier appel n'a produit aucun contenu exploitable.
    contexte = _messages_avec_fenetre()
    try:
        # Pousser l'appel bloquant dans un thread séparé
        generator = await asyncio.to_thread(
            ai.chat_with_provider,
            model_name=current_model,
            messages_list=contexte,
            tools=None,
            stream=True
        )
        
        full_content = ""
        tts_buffer = ""

        # Un seul thread draine tout le générateur bloquant vers une queue asyncio,
        # au lieu d'un aller-retour ThreadPool par token (latence/jitter par token).
        loop = asyncio.get_running_loop()
        token_queue: asyncio.Queue = asyncio.Queue()
        _STREAM_DONE = object()

        def _drain_generator():
            try:
                for chunk in generator:
                    loop.call_soon_threadsafe(token_queue.put_nowait, chunk)
            except Exception as e:
                loop.call_soon_threadsafe(token_queue.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(token_queue.put_nowait, _STREAM_DONE)

        threading.Thread(target=_drain_generator, daemon=True).start()

        cancel_event = _cancel_events.get(websocket)

        while True:
            if cancel_event and cancel_event.is_set():
                logger.info("Génération annulée via Kill Switch.")
                full_content += "\n[Génération interrompue par l'utilisateur]"
                break

            try:
                chunk = await token_queue.get()
                if chunk is _STREAM_DONE:
                    break
                if isinstance(chunk, Exception):
                    raise chunk

                content = chunk.get('message', {}).get('content', '')
                if content:
                    full_content += content
                    await websocket.send(json.dumps({
                        "type": "token",
                        "content": content
                    }))
                    
                    if mode_vocal:
                        tts_buffer += content
                        if any(punct in tts_buffer for punct in ['.', '!', '?', '\n']):
                            for punct in ['.', '!', '?', '\n']:
                                if punct in tts_buffer:
                                    parts = tts_buffer.split(punct, 1)
                                    sentence = parts[0] + punct
                                    if sentence.strip():
                                        faire_parler(sentence.strip())
                                    tts_buffer = parts[1] if len(parts) > 1 else ""
                                    break
            except Exception as e:
                logger.error(f"Erreur chunk: {e}")
                break
                
        if mode_vocal and tts_buffer.strip():
            faire_parler(tts_buffer.strip())
            
        messages.append({'role': 'assistant', 'content': full_content})
        await websocket.send(json.dumps({"type": "done"}))
        
    except Exception as e:
        logger.error(f"Erreur stream: {e}", exc_info=True)
        await websocket.send(json.dumps({
            "type": "error",
            "message": str(e)
        }))
        await websocket.send(json.dumps({"type": "done"}))


async def _reprendre_apres_permission(websocket, tool_call: dict, autorise: bool):
    """
    Reprend une conversation suspendue par une demande Human-in-the-Loop
    (voir 'action_required' dans _continuer_conversation).

    Si autorisé : réexécute EXACTEMENT le même outil, mais cette fois avec
    permission_deja_accordee positionnée (core/exceptions.py) pour que
    _demander_permission() (function/files.py) laisse l'action passer au lieu de
    relever une nouvelle PermissionRequiredException.
    Si refusé : n'exécute rien, enregistre le refus comme résultat de l'outil.

    Dans les deux cas, le résultat est ajouté à l'historique puis la conversation
    reprend normalement (nouvel appel LLM, qui peut streamer une réponse ou demander
    une nouvelle permission si une autre action critique s'enchaîne).
    """
    from core.exceptions import permission_deja_accordee

    nom_fonction = tool_call.get('function', {}).get('name', '')
    arguments = tool_call.get('function', {}).get('arguments', {}) or {}

    if not autorise:
        resultat_execution = "Action refusée par l'utilisateur."
    elif nom_fonction not in outils_disponibles:
        resultat_execution = f"Erreur: Outil {nom_fonction} introuvable."
    else:
        await websocket.send(json.dumps({
            "type": "system_action",
            "content": f"Exécution de {nom_fonction} (autorisée par l'utilisateur)..."
        }))

        def run_tool_autorise():
            token = permission_deja_accordee.set(True)
            try:
                try:
                    return outils_disponibles[nom_fonction](**arguments)
                except TypeError:
                    return outils_disponibles[nom_fonction]()
            finally:
                permission_deja_accordee.reset(token)

        try:
            resultat_execution = await asyncio.to_thread(run_tool_autorise)
        except Exception as e:
            logger.error(f"Erreur lors de l'exécution autorisée de {nom_fonction} : {e}")
            resultat_execution = f"Erreur lors de l'exécution : {e}"

    tool_call_id = tool_call.get('id')
    tool_msg = {'role': 'tool', 'content': str(resultat_execution), 'name': nom_fonction}
    if tool_call_id:
        tool_msg['tool_call_id'] = tool_call_id
    messages.append(tool_msg)

    current_model = ai.MODEL
    if current_model == 'Aucun modèle':
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Aucun modèle n'est sélectionné ou disponible."
        }))
        await websocket.send(json.dumps({"type": "done"}))
        return

    mode_vocal = _last_mode_vocal.get(websocket, False)
    await _continuer_conversation(websocket, current_model, mode_vocal)


async def handler_client(websocket):
    logger.info("Interface C# connectée.")
    # Désactive l'algorithme de Nagle : évite jusqu'à ~40ms de délai par frame
    # WS sur la boucle locale (latence perçue GUI <-> agent).
    sock = websocket.transport.get_extra_info('socket')
    if sock is not None:
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
    _cancel_events[websocket] = asyncio.Event()
    
    try:
        async for message_brut in websocket:
            try:
                data = json.loads(message_brut)
                msg_type = data.get('type', 'chat')
                
                if msg_type == 'chat':
                    _cancel_events[websocket].clear()
                    await handle_chat(websocket, data)
                    
                elif msg_type == 'cancel':
                    logger.info("Kill Switch activé.")
                    _cancel_events[websocket].set()
                    
                elif msg_type == 'get_models':
                    force = data.get('refresh', False)
                    resultats = await asyncio.to_thread(lister_modeles_disponibles, force)
                    await websocket.send(json.dumps({
                        "type": "models_list",
                        "current_model": ai.MODEL,
                        "providers": resultats
                    }))
                    
                elif msg_type == 'get_status':
                    status = await asyncio.to_thread(get_provider_status)
                    await websocket.send(json.dumps({
                        "type": "provider_status",
                        "status": status
                    }))
                    
                elif msg_type == 'select_model':
                    new_model = data.get('model', '')
                    if new_model:
                        ai.MODEL = new_model
                        await websocket.send(json.dumps({
                            "type": "model_selected",
                            "model": ai.MODEL
                        }))

                elif msg_type in ('permission_granted', 'permission_denied'):
                    tool_call = data.get('tool_call') or {}
                    await _reprendre_apres_permission(
                        websocket, tool_call, autorise=(msg_type == 'permission_granted')
                    )

                elif msg_type == 'get_mobile_info':
                    # N'importe quel client déjà connecté peut demander ceci sans
                    # nouvelle vérification : _verifier_origine_connexion a déjà
                    # filtré à l'entrée (loopback, ou jeton valide) avant même
                    # d'atteindre ce code — donc ce client est déjà de confiance.
                    await websocket.send(json.dumps({
                        "type": "mobile_info",
                        "allow_lan": ALLOW_LAN,
                        "lan_ip": obtenir_ip_locale(),
                        "port": PORT,
                        "mobile_port": MOBILE_PORT,
                        "token": obtenir_token(),
                    }))

                elif msg_type == 'regenerate_pairing_token':
                    nouveau_token = await asyncio.to_thread(regenerer_token)
                    logger.info("Jeton de jumelage régénéré : les appareils mobiles déjà connectés devront se rejumeler.")
                    await websocket.send(json.dumps({
                        "type": "pairing_token_regenerated",
                        "token": nouveau_token
                    }))

                elif msg_type == 'shutdown':
                    logger.info("Signal de fermeture reçu du C#.")
                    await websocket.send(json.dumps({"type": "shutting_down"}))
                    
                    import subprocess
                    base_dir = os.path.dirname(os.path.abspath(__file__))
                    if sys.platform == "win32":
                        script_path = os.path.join(base_dir, 'stop.bat')
                        if os.path.exists(script_path):
                            subprocess.Popen(['cmd.exe', '/c', script_path], creationflags=subprocess.CREATE_NO_WINDOW)
                    else:
                        script_path = os.path.join(base_dir, 'stop.sh')
                        if os.path.exists(script_path):
                            subprocess.Popen(['/bin/bash', script_path])

                    os.kill(os.getpid(), signal.SIGINT)
                    
            except json.JSONDecodeError:
                logger.error("Message JSON invalide reçu.")
                
    except websockets.exceptions.ConnectionClosed:
        logger.info("Interface C# déconnectée.")
    finally:
        _cancel_events.pop(websocket, None)

async def demarrer_serveur_alyx():
    port = PORT
    
    # Précharger les modèles en arrière-plan
    def _preload():
        from core.llm_provider import preload_models
        ai.MODEL = preload_models()
        logger.info(f"Modèles préchargés, modèle par défaut: {ai.MODEL}")
        
        # Handshake STT
        logger.info("Attente du service STT (Handshake)...")
        for _ in range(10):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{STT_PORT}/health", timeout=1)
                logger.info("Service STT prêt.")
                break
            except Exception:
                time.sleep(1)
        
    threading.Thread(target=_preload, daemon=True).start()

    logger.info(f"---> Serveur WebSocket Alyx démarré sur ws://{BIND_ADDRESS}:{port} (LAN: {'ouvert' if ALLOW_LAN else 'désactivé'})")
    print(f"---> Serveur WebSocket Alyx démarré sur ws://{BIND_ADDRESS}:{port}")
    if ALLOW_LAN:
        ip_locale = obtenir_ip_locale()
        if ip_locale:
            print(f"     [Accès mobile (Wi-Fi local) : ws://{ip_locale}:{port} — jeton requis, voir l'UI]")
    # compression=None : évite le coût CPU de la compression deflate pour des
    # messages JSON courts échangés en local (pas de gain bande passante à attendre).
    # process_request : porte d'entrée du jumelage mobile (voir _verifier_origine_connexion).
    async with websockets.serve(
        handler_client, BIND_ADDRESS, port,
        compression=None, process_request=_verifier_origine_connexion
    ):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(demarrer_serveur_alyx())
    except KeyboardInterrupt:
        print("Serveur arrêté proprement.")
