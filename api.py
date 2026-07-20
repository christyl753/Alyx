import flask
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os
import signal
import threading
import requests as py_requests

import ollama

# pyrefly: ignore [missing-import]
from ai import messages, LISTE_FONCTIONS, outils_disponibles, faire_parler, ecouter, lister_modeles_disponibles
import ai

app = Flask(__name__)
CORS(app)

# Désactivation des logs serveur de développement Werkzeug
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

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
    return [system_prompt] + recents

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
            'message': final_text,
            'actions': system_actions,
            'user_input': user_input
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ========== Model Management ==========

@app.route('/api/models', methods=['GET'])
def get_models():
    """Liste tous les modèles disponibles sur tous les providers."""
    try:
        resultats = lister_modeles_disponibles()
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
