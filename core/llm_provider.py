import threading
import time
import requests
import ollama
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.logger import get_logger

logger = get_logger('alyx.llm_provider')

# --- CACHE DES MODÈLES ---
_models_cache = {}           # Résultats mis en cache
_model_to_provider = {}      # Map rapide nom -> provider
_cache_timestamp = 0.0       # Quand le cache a été mis à jour
_cache_lock = threading.Lock()
_models_ready = threading.Event()  # Signale que le premier scan est terminé
CACHE_TTL = 60               # Durée de vie du cache en secondes

# --- PROVIDERS DE MODÈLES ---
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

# --- Fonctions internes de scan par provider ---

def _scan_ollama():
    try:
        resp = requests.get(f"{PROVIDERS['ollama']['api_base']}/api/tags", timeout=1.5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('models', [])
            return 'ollama', [
                {
                    'name': m.get('name', m.get('model', 'inconnu')),
                    'size': f"{m.get('size', 0) / (1024**3):.1f} GB",
                    'provider': 'ollama'
                }
                for m in models
            ]
    except Exception:
        pass
    return 'ollama', []

def _scan_lmstudio():
    try:
        resp = requests.get(f"{PROVIDERS['lmstudio']['api_base']}/v1/models", timeout=1.5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('data', [])
            return 'lmstudio', [
                {
                    'name': m.get('id', 'inconnu'),
                    'size': '--',
                    'provider': 'lmstudio'
                }
                for m in models
            ]
    except Exception:
        pass
    return 'lmstudio', []

def _scan_nvidia():
    try:
        resp = requests.get(f"{PROVIDERS['nvidia']['api_base']}/v1/models", timeout=1.5)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get('data', [])
            return 'nvidia', [
                {
                    'name': m.get('id', 'inconnu'),
                    'size': '--',
                    'provider': 'nvidia'
                }
                for m in models
            ]
    except Exception:
        pass
    return 'nvidia', []

def _refresh_models_cache():
    global _models_cache, _model_to_provider, _cache_timestamp
    
    resultats = {}
    provider_map = {}
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [
            executor.submit(_scan_ollama),
            executor.submit(_scan_lmstudio),
            executor.submit(_scan_nvidia),
        ]
        for future in as_completed(futures):
            try:
                provider_name, models_list = future.result()
                if models_list:
                    resultats[provider_name] = models_list
                    for m in models_list:
                        provider_map[m['name']] = provider_name
            except Exception:
                pass
    
    with _cache_lock:
        _models_cache = resultats
        _model_to_provider = provider_map
        _cache_timestamp = time.time()
    
    _models_ready.set()
    return resultats

def lister_modeles_disponibles(force_refresh=False) -> dict:
    global _cache_timestamp
    with _cache_lock:
        cache_age = time.time() - _cache_timestamp
        if not force_refresh and _models_cache and cache_age < CACHE_TTL:
            return _models_cache
    return _refresh_models_cache()

def is_models_ready() -> bool:
    return _models_ready.is_set()

def get_default_model():
    with _cache_lock:
        models = _models_cache
    if 'ollama' in models and len(models['ollama']) > 0:
        return models['ollama'][0]['name']
    if 'lmstudio' in models and len(models['lmstudio']) > 0:
        return models['lmstudio'][0]['name']
    if 'nvidia' in models and len(models['nvidia']) > 0:
        return models['nvidia'][0]['name']
    return 'Aucun modèle'

def get_model_provider(model_name: str) -> str:
    with _cache_lock:
        provider = _model_to_provider.get(model_name)
    if provider:
        return provider
    return 'ollama'

import json

def chat_with_provider(model_name, messages_list, tools=None, stream=False):
    provider = get_model_provider(model_name)
    if provider == 'ollama':
        return ollama.chat(
            model=model_name,
            messages=messages_list,
            tools=tools,
            stream=stream,
            keep_alive='1h'
        )
    elif provider in ['lmstudio', 'nvidia']:
        api_base = PROVIDERS[provider]['api_base']
        
        clean_messages = []
        for msg in messages_list:
            clean_msg = {'role': msg['role'], 'content': msg.get('content', '')}
            if 'tool_calls' in msg and msg['tool_calls']:
                clean_msg['tool_calls'] = msg['tool_calls']
            clean_messages.append(clean_msg)
        
        payload = {
            "model": model_name,
            "messages": clean_messages,
            "temperature": 0.7,
            "stream": stream
        }
        try:
            if stream:
                resp = requests.post(f"{api_base}/v1/chat/completions", json=payload, stream=True, timeout=120)
                resp.raise_for_status()
                def generate():
                    for line in resp.iter_lines():
                        if line:
                            decoded_line = line.decode('utf-8')
                            if decoded_line.startswith('data: '):
                                data_str = decoded_line[6:]
                                if data_str == '[DONE]':
                                    break
                                try:
                                    data = json.loads(data_str)
                                    if data['choices'][0]['delta'].get('content'):
                                        yield {'message': {'content': data['choices'][0]['delta']['content']}}
                                except json.JSONDecodeError:
                                    pass
                return generate()
            else:
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
            }
        except Exception as e:
            raise Exception(f"Erreur {provider}: {e}")
    else:
        raise Exception(f"Fournisseur non supporté: {provider}")

def preload_models():
    """Thread de pré-chargement : scan les modèles puis sélectionne le défaut."""
    logger.info("Détection des modèles IA en cours...")
    print("     [Initialisation : Détection des modèles IA en cours...]")
    _refresh_models_cache()
    model = get_default_model()
    with _cache_lock:
        total = sum(len(v) for v in _models_cache.values())
    logger.info(f"{total} modèle(s) détecté(s), modèle par défaut: {model}")
    print(f"     [Succès : {total} modèle(s) détecté(s), modèle par défaut: {model}]")
    return model
