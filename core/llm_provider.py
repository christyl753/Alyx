import threading
import time
import requests
import ollama
import json
import yaml
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.logger import get_logger

logger = get_logger('alyx.llm_provider')

# --- CONFIGURATION ---
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}

config = load_config()
llm_config = config.get('llm_provider', {})

CACHE_TTL = llm_config.get('cache_ttl', 60)
SCAN_TIMEOUT = llm_config.get('scan_timeout', 1.5)
CB_MAX_FAILURES = llm_config.get('circuit_breaker_max_failures', 3)
CB_COOLDOWN = llm_config.get('circuit_breaker_cooldown', 30)

PROVIDERS = {p['name']: p for p in config.get('providers', [])}
if not PROVIDERS:
    PROVIDERS = {
        'ollama': {'name': 'ollama', 'api_base': 'http://127.0.0.1:11434', 'priority': 1},
        'lmstudio': {'name': 'lmstudio', 'api_base': 'http://127.0.0.1:1234', 'priority': 2},
        'nvidia': {'name': 'nvidia', 'api_base': 'http://127.0.0.1:8000', 'priority': 3}
    }

# --- CACHE & CIRCUIT BREAKER ---
_models_cache = {}           
_model_to_provider = {}      
_cache_timestamp = 0.0       
_cache_lock = threading.Lock()
_models_ready = threading.Event()

# { 'provider_name': {'failures': int, 'last_failure': timestamp, 'latency': float, 'status': str} }
_provider_stats = {name: {'failures': 0, 'last_failure': 0.0, 'latency': 0.0, 'status': 'unknown'} for name in PROVIDERS}

def _is_provider_available(provider_name: str) -> bool:
    stats = _provider_stats[provider_name]
    if stats['failures'] >= CB_MAX_FAILURES:
        if time.time() - stats['last_failure'] < CB_COOLDOWN:
            return False
        else:
            # Demi-ouvert
            stats['failures'] = CB_MAX_FAILURES - 1 
    return True

def _record_success(provider_name: str, latency: float):
    _provider_stats[provider_name]['failures'] = 0
    _provider_stats[provider_name]['latency'] = latency
    _provider_stats[provider_name]['status'] = 'online'

def _record_failure(provider_name: str):
    _provider_stats[provider_name]['failures'] += 1
    _provider_stats[provider_name]['last_failure'] = time.time()
    _provider_stats[provider_name]['status'] = 'offline'

# --- SCAN ---
def _scan_ollama():
    provider_name = 'ollama'
    if not _is_provider_available(provider_name):
        return provider_name, []
    try:
        t0 = time.time()
        response = ollama.list()
        latency = time.time() - t0
        models = response.get('models', []) if isinstance(response, dict) else getattr(response, 'models', response)
        formatted = []
        for m in models:
            if hasattr(m, 'model'):
                name = m.model
                size_gb = getattr(m, 'size', 0) / (1024**3)
            else:
                name = m.get('name', m.get('model', 'inconnu'))
                size_gb = m.get('size', 0) / (1024**3)
            formatted.append({'name': name, 'size': f"{size_gb:.1f} GB", 'provider': provider_name})
        _record_success(provider_name, latency)
        return provider_name, formatted
    except Exception as e:
        _record_failure(provider_name)
    return provider_name, []

def _scan_generic(provider_name: str, endpoint: str):
    if not _is_provider_available(provider_name):
        return provider_name, []
    try:
        t0 = time.time()
        resp = requests.get(f"{PROVIDERS[provider_name]['api_base']}{endpoint}", timeout=SCAN_TIMEOUT)
        if resp.status_code == 200:
            latency = time.time() - t0
            data = resp.json()
            models = data.get('data', [])
            formatted = [{'name': m.get('id', 'inconnu'), 'size': '--', 'provider': provider_name} for m in models]
            _record_success(provider_name, latency)
            return provider_name, formatted
    except Exception:
        pass
    _record_failure(provider_name)
    return provider_name, []

def _refresh_models_cache():
    global _models_cache, _model_to_provider, _cache_timestamp
    
    resultats = {}
    provider_map = {}
    
    with ThreadPoolExecutor(max_workers=len(PROVIDERS)) as executor:
        futures = []
        if 'ollama' in PROVIDERS:
            futures.append(executor.submit(_scan_ollama))
        if 'lmstudio' in PROVIDERS:
            futures.append(executor.submit(_scan_generic, 'lmstudio', '/v1/models'))
        if 'nvidia' in PROVIDERS:
            futures.append(executor.submit(_scan_generic, 'nvidia', '/v1/models'))
            
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

def get_provider_status() -> dict:
    with _cache_lock:
        return _provider_stats

def get_default_model():
    with _cache_lock:
        models = _models_cache
    
    sorted_providers = sorted(PROVIDERS.values(), key=lambda x: x.get('priority', 99))
    for p in sorted_providers:
        p_name = p['name']
        if p_name in models and len(models[p_name]) > 0:
            return models[p_name][0]['name']
            
    return 'Aucun modèle'

def get_model_provider(model_name: str) -> str:
    with _cache_lock:
        provider = _model_to_provider.get(model_name)
    if provider:
        return provider
    return 'ollama'

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

