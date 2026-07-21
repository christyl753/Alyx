import asyncio
import websockets
import json
import os
import signal
import sys
import concurrent.futures

from core.exceptions import PermissionRequiredException
import ai
from ai import messages, LISTE_FONCTIONS, outils_disponibles
from core.llm_provider import lister_modeles_disponibles, is_models_ready
from function import faire_parler, ecouter
from core.logger import get_logger

logger = get_logger('alyx.ws_api')

MAX_CONTEXT_MESSAGES = 40

def _messages_avec_fenetre():
    if len(messages) <= 1:
        return messages
    system_prompt = messages[0]
    recents = messages[1:]
    if len(recents) > MAX_CONTEXT_MESSAGES:
        recents = recents[-MAX_CONTEXT_MESSAGES:]
        
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
        # Run synchronous voice recognition in thread
        user_input = await asyncio.to_thread(ecouter)
        if not user_input:
            await websocket.send(json.dumps({
                "type": "error",
                "message": "Je n'ai rien entendu..."
            }))
            await websocket.send(json.dumps({"type": "done"}))
            return

    if not user_input:
        return

    messages.append({'role': 'user', 'content': user_input})
    
    current_model = ai.MODEL
    if current_model == 'Aucun modèle':
        await websocket.send(json.dumps({
            "type": "error",
            "message": "Aucun modèle n'est sélectionné ou disponible."
        }))
        await websocket.send(json.dumps({"type": "done"}))
        return

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
                        "tool_call": tool_call
                    }))
                    # On arrête le traitement de ce chat, le C# devra relancer avec permission_granted
                    return 
            else:
                resultat_execution = f"Erreur: Outil {nom_fonction} introuvable."
                
            messages.append({
                'role': 'tool',
                'content': resultat_execution,
                'name': nom_fonction
            })
            
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

    # PHASE 2: Réponse textuelle (Appel streamé)
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
        
        # Pour lire le générateur asynchrone depuis un générateur synchrone bloquant :
        # On lit chunk par chunk via un ThreadPool
        loop = asyncio.get_running_loop()
        while True:
            try:
                # `next()` est bloquant, on le passe à to_thread
                chunk = await asyncio.to_thread(next, generator)
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
            except StopIteration:
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


async def handler_client(websocket):
    logger.info("Interface C# connectée.")
    try:
        async for message_brut in websocket:
            try:
                data = json.loads(message_brut)
                msg_type = data.get('type', 'chat')
                
                if msg_type == 'chat':
                    await handle_chat(websocket, data)
                    
                elif msg_type == 'get_models':
                    force = data.get('refresh', False)
                    resultats = await asyncio.to_thread(lister_modeles_disponibles, force)
                    await websocket.send(json.dumps({
                        "type": "models_list",
                        "current_model": ai.MODEL,
                        "providers": resultats
                    }))
                    
                elif msg_type == 'select_model':
                    new_model = data.get('model', '')
                    if new_model:
                        ai.MODEL = new_model
                        await websocket.send(json.dumps({
                            "type": "model_selected",
                            "model": ai.MODEL
                        }))
                        
                elif msg_type == 'shutdown':
                    logger.info("Signal de fermeture reçu du C#.")
                    await websocket.send(json.dumps({"type": "shutting_down"}))
                    os.kill(os.getpid(), signal.SIGINT)
                    
            except json.JSONDecodeError:
                logger.error("Message JSON invalide reçu.")
                
    except websockets.exceptions.ConnectionClosed:
        logger.info("Interface C# déconnectée.")


async def demarrer_serveur_alyx():
    port = 8765
    logger.info(f"---> Serveur WebSocket Alyx démarré sur ws://localhost:{port}")
    print(f"---> Serveur WebSocket Alyx démarré sur ws://localhost:{port}")
    async with websockets.serve(handler_client, "localhost", port):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(demarrer_serveur_alyx())
    except KeyboardInterrupt:
        print("Serveur arrêté proprement.")
