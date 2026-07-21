import flask
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import os
import signal
import threading
import requests as py_requests

import ollama

from core.exceptions import PermissionRequiredException

# pyrefly: ignore [missing-import]
from ai import messages, LISTE_FONCTIONS, outils_disponibles
from core.llm_provider import lister_modeles_disponibles, is_models_ready
from function import faire_parler, ecouter
import ai
from core.logger import get_logger

logger = get_logger('alyx.api')

app = Flask(__name__)
CORS(app)

import logging
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.setLevel(logging.ERROR)

# Limite de contexte : garder le system prompt + les N derniers messages
MAX_CONTEXT_MESSAGES = 40

def _messages_avec_fenetre():
    """Retourne le system prompt + les N derniers messages pour éviter de dépasser le contexte."""
    if len(messages) <= 1:
        return messages
    system_prompt = messages[0]
    recents = messages[1:]
    if len(recents) > MAX_CONTEXT_MESSAGES:
        recents = recents[-MAX_CONTEXT_MESSAGES:]
        
    # Optimisation (Prompt Caching): Nettoyer les vieux appels d'outils de l'historique
    last_user_idx = len(recents) - 1
    while last_user_idx >= 0 and recents[last_user_idx].get('role') != 'user':
        last_user_idx -= 1
        
    optimized = [system_prompt]
    for i, msg in enumerate(recents):
        if i < last_user_idx:
            # Historique passé : on ne garde que les textes finaux (user/assistant)
            if msg.get('role') in ['user', 'assistant'] and msg.get('content'):
                optimized.append({'role': msg['role'], 'content': msg['content']})
        else:
            # Contexte actuel : on conserve tout (y compris les tool_calls et role: tool)
            optimized.append(msg)
            
    return optimized

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid or missing JSON body'}), 400
    
    user_input = data.get('message', '')
    mode_vocal = data.get('vocal', False)
    
    if not user_input and not mode_vocal:
        return jsonify({'error': 'Message empty'}), 400
        
    if mode_vocal and not user_input:
        user_input = ecouter()
        if not user_input:
            return jsonify({'message': 'Je n\'ai rien entendu...', 'vocal_input': '', 'actions': []}), 200

    messages.append({'role': 'user', 'content': user_input})
    
    try:
        current_model = ai.MODEL
        if current_model == 'Aucun modèle':
            return jsonify({
                'message': "Aucun modèle n'est sélectionné ou disponible. Veuillez lancer un modèle via Ollama ou LM Studio.",
                'actions': [],
                'user_input': user_input
            })
            
        contexte = _messages_avec_fenetre()
        response = ai.chat_with_provider(
            model_name=current_model,
            messages_list=contexte,
            tools=LISTE_FONCTIONS
        )
        message_ia = response['message']
        messages.append(message_ia)
        
        system_actions = []

        # Boucle multi-tool : continuer tant que le modèle demande des outils
        max_iterations = 5
        iteration = 0
        while message_ia.get('tool_calls') and iteration < max_iterations:
            for tool_call in message_ia['tool_calls']:
                nom_fonction = tool_call['function']['name']
                arguments = tool_call['function'].get('arguments', {})
                if nom_fonction in outils_disponibles:
                    try:
                        resultat_execution = outils_disponibles[nom_fonction](**arguments)
                    except TypeError:
                        resultat_execution = outils_disponibles[nom_fonction]()
                    except PermissionRequiredException as e:
                        logger.warning(f"Permission requise pour l'outil {nom_fonction}.")
                        return jsonify({
                            'status': 'ACTION_REQUIRED',
                            'action': e.action,
                            'cible': e.cible,
                            'tool_call': tool_call
                        }), 403
                else:
                    resultat_execution = f"Erreur: Outil {nom_fonction} introuvable."

                system_actions.append(resultat_execution)

                messages.append({
                    'role': 'tool',
                    'content': resultat_execution,
                    'name': nom_fonction
                })

            contexte = _messages_avec_fenetre()
            response = ai.chat_with_provider(
                model_name=current_model,
                messages_list=contexte,
                tools=LISTE_FONCTIONS
            )
            message_ia = response['message']
            messages.append(message_ia)
            iteration += 1

        final_text = message_ia['content']
        
        if mode_vocal:
            def _safe_tts(text):
                try:
                    faire_parler(text)
                except Exception:
                    pass
            threading.Thread(target=_safe_tts, args=(final_text,), daemon=True).start()
            
        return jsonify({
            'message': message_ia.get('content', ''),
            'vocal_input': user_input if mode_vocal else '',
            'actions': system_actions
        })
    except Exception as e:
        logger.error(f"Erreur API LLM : {e}", exc_info=True)
        return jsonify({'error': str(e)}), 500

import json

@app.route('/api/chat_stream', methods=['POST'])
def chat_stream():
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid or missing JSON body'}), 400
    
    user_input = data.get('message', '')
    mode_vocal = data.get('vocal', False)
    
    if not user_input and not mode_vocal:
        return jsonify({'error': 'Message empty'}), 400
        
    if mode_vocal and not user_input:
        user_input = ecouter()
        if not user_input:
            return jsonify({'message': 'Je n\'ai rien entendu...', 'vocal_input': '', 'actions': []}), 200

    messages.append({'role': 'user', 'content': user_input})
    
    def generate():
        current_model = ai.MODEL
        if current_model == 'Aucun modèle':
            yield f"data: {json.dumps({'error': 'Aucun modèle'})}\n\n"
            return
            
        contexte = _messages_avec_fenetre()
        
        # Pour simplifier, on désactive les outils en mode streaming pour l'instant,
        # car la gestion des tool_calls en streaming asynchrone est complexe.
        # Si des outils sont nécessaires, il est préférable d'utiliser /api/chat.
        try:
            generator = ai.chat_with_provider(
                model_name=current_model,
                messages_list=contexte,
                tools=None,
                stream=True
            )
            
            full_content = ""
            tts_buffer = ""
            
            for chunk in generator:
                content = chunk.get('message', {}).get('content', '')
                if content:
                    full_content += content
                    yield f"data: {json.dumps({'chunk': content})}\n\n"
                    
                    if mode_vocal:
                        tts_buffer += content
                        if any(punct in tts_buffer for punct in ['.', '!', '?', '\n']):
                            # Simple split sur la première ponctuation trouvée pour envoyer au TTS
                            for punct in ['.', '!', '?', '\n']:
                                if punct in tts_buffer:
                                    parts = tts_buffer.split(punct, 1)
                                    sentence = parts[0] + punct
                                    if sentence.strip():
                                        faire_parler(sentence.strip())
                                    tts_buffer = parts[1] if len(parts) > 1 else ""
                                    break
            
            # Envoyer le reste du buffer s'il y a du texte résiduel
            if mode_vocal and tts_buffer.strip():
                faire_parler(tts_buffer.strip())
            
            messages.append({'role': 'assistant', 'content': full_content})
            yield f"data: {json.dumps({'done': True, 'vocal_input': user_input if mode_vocal else ''})}\n\n"
            
        except Exception as e:
            logger.error(f"Erreur stream: {e}", exc_info=True)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


# ========== Model Management ==========

@app.route('/api/models/ready', methods=['GET'])
def models_ready():
    """Endpoint rapide pour vérifier si les modèles sont chargés (polling au démarrage)."""
    return jsonify({
        'ready': is_models_ready(),
        'current_model': ai.MODEL
    })

@app.route('/api/models', methods=['GET'])
def get_models():
    """Liste tous les modèles disponibles sur tous les providers."""
    try:
        force = request.args.get('refresh', 'false').lower() == 'true'
        resultats = lister_modeles_disponibles(force_refresh=force)
        return jsonify({
            'current_model': ai.MODEL,
            'providers': resultats
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/models/select', methods=['POST'])
def select_model():
    """Change le modèle courant."""
    data = request.json
    if not data:
        return jsonify({'error': 'Invalid JSON body'}), 400
    
    new_model = data.get('model', '')
    if not new_model:
        return jsonify({'error': 'No model specified'}), 400
    
    ai.MODEL = new_model
    return jsonify({
        'success': True,
        'current_model': ai.MODEL,
        'message': f"Modèle changé vers '{new_model}'"
    })


@app.route('/api/vocal/listen', methods=['POST'])
def listen_vocal():
    text = ecouter()
    return jsonify({'text': text})


@app.route('/api/shutdown', methods=['POST'])
def shutdown():
    """Stops the Flask server gracefully."""
    import signal
    os.kill(os.getpid(), signal.SIGINT)
    return jsonify({'message': 'Server shutting down...'}), 200

if __name__ == '__main__':
    app.run(port=5000, debug=False)
