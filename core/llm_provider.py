import threading
import time
import requests
import json
import yaml
import os
import re
import uuid
import socket
import inspect
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor, as_completed
from ollama import Client as OllamaClient
from core.logger import get_logger

logger = get_logger('alyx.llm_provider')

# --- CONFIGURATION ---
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yaml')

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    return {}

config = load_config()
llm_config = config.get('llm_provider', {})

CACHE_TTL = llm_config.get('cache_ttl', 60)
SCAN_TIMEOUT = llm_config.get('scan_timeout', 1.5)
CHAT_TIMEOUT = llm_config.get('chat_timeout', 120)
CB_MAX_FAILURES = llm_config.get('circuit_breaker_max_failures', 3)
CB_COOLDOWN = llm_config.get('circuit_breaker_cooldown', 30)

PROVIDERS = {p['name']: p for p in config.get('providers', [])}
if not PROVIDERS:
    PROVIDERS = {
        'ollama': {'name': 'ollama', 'api_base': 'http://127.0.0.1:11434', 'priority': 1},
        'lmstudio': {'name': 'lmstudio', 'api_base': 'http://127.0.0.1:1234', 'priority': 2},
        'nvidia': {'name': 'nvidia', 'api_base': 'http://127.0.0.1:8000', 'priority': 3}
    }

# --- CLIENTS HTTP PARTAGÉS (keep-alive, pas de reconnexion à chaque requête) ---
_http = requests.Session()
_ollama_scan_client = None
_clients_lock = threading.Lock()

def _ollama_client():
    global _ollama_scan_client
    with _clients_lock:
        if _ollama_scan_client is None:
            _ollama_scan_client = OllamaClient(host=PROVIDERS['ollama']['api_base'], timeout=SCAN_TIMEOUT)
        return _ollama_scan_client

# --- CACHE & CIRCUIT BREAKER ---
_models_cache = {}
_model_to_provider = {}
_cache_timestamp = 0.0
_cache_lock = threading.Lock()
_stats_lock = threading.Lock()
_models_ready = threading.Event()

# { 'provider_name': {'failures': int, 'last_failure': timestamp, 'latency': float, 'status': str} }
_provider_stats = {name: {'failures': 0, 'last_failure': 0.0, 'latency': 0.0, 'status': 'unknown'} for name in PROVIDERS}

def _is_provider_available(provider_name: str) -> bool:
    with _stats_lock:
        stats = _provider_stats[provider_name]
        if stats['failures'] >= CB_MAX_FAILURES:
            if time.time() - stats['last_failure'] < CB_COOLDOWN:
                return False
            # Demi-ouvert
            stats['failures'] = CB_MAX_FAILURES - 1
    return True

def _record_success(provider_name: str, latency: float):
    with _stats_lock:
        _provider_stats[provider_name]['failures'] = 0
        _provider_stats[provider_name]['latency'] = latency
        _provider_stats[provider_name]['status'] = 'online'

def _record_failure(provider_name: str):
    with _stats_lock:
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
        response = _ollama_client().list()
        latency = time.time() - t0
        models = response.get('models', []) if isinstance(response, dict) else getattr(response, 'models', response)
        formatted = []
        for m in models:
            if hasattr(m, 'model'):
                name = m.model
                m_size = getattr(m, 'size', 0)
            else:
                name = m.get('name', m.get('model', 'inconnu'))
                m_size = m.get('size', 0)
            size_gb = (m_size / (1024**3)) if m_size else 0
            formatted.append({'name': name, 'size': f"{size_gb:.1f} GB", 'provider': provider_name})
        _record_success(provider_name, latency)
        return provider_name, formatted
    except Exception as e:
        logger.debug(f"Scan ollama échoué: {e}")
        _record_failure(provider_name)
    return provider_name, []

def _scan_generic(provider_name: str, endpoint: str):
    if not _is_provider_available(provider_name):
        return provider_name, []
    try:
        t0 = time.time()
        resp = _http.get(f"{PROVIDERS[provider_name]['api_base']}{endpoint}", timeout=SCAN_TIMEOUT)
        if resp.status_code == 200:
            latency = time.time() - t0
            data = resp.json()
            models = data.get('data', [])
            formatted = [{'name': m.get('id', 'inconnu'), 'size': '--', 'provider': provider_name} for m in models]
            _record_success(provider_name, latency)
            return provider_name, formatted
    except Exception as e:
        logger.debug(f"Scan {provider_name} échoué: {e}")
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
        # Un fournisseur momentanément injoignable garde son routage : sinon ses modèles
        # seraient envoyés par défaut à Ollama avec une erreur trompeuse.
        for name, provider in _model_to_provider.items():
            if provider not in resultats:
                provider_map.setdefault(name, provider)
        _models_cache = resultats
        _model_to_provider = provider_map
        _cache_timestamp = time.time()

    _models_ready.set()
    return resultats

def lister_modeles_disponibles(force_refresh=False) -> dict:
    if force_refresh:
        # Reset circuit breaker on forced refresh
        with _stats_lock:
            for p in _provider_stats:
                _provider_stats[p]['failures'] = 0
                _provider_stats[p]['status'] = 'unknown'

    with _cache_lock:
        cache_age = time.time() - _cache_timestamp
        if not force_refresh and _models_cache and cache_age < CACHE_TTL:
            return _models_cache
    return _refresh_models_cache()

def is_models_ready() -> bool:
    return _models_ready.is_set()

def wait_models_ready(timeout: float) -> bool:
    return _models_ready.wait(timeout)

def get_provider_status() -> dict:
    with _stats_lock:
        return {name: dict(stats) for name, stats in _provider_stats.items()}

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

# --- SCHÉMAS D'OUTILS (format JSON strict commun à tous les fournisseurs) ---
def _parse_docstring(doc: str):
    """Sépare la description et la section 'Args:' (style Google) d'une docstring."""
    description, params = [], {}
    dans_args, courant = False, None
    for ligne in doc.splitlines():
        s = ligne.strip()
        if s.lower() in ('args:', 'arguments:', 'parameters:'):
            dans_args = True
            continue
        if not dans_args:
            if s:
                description.append(s)
            continue
        m = re.match(r'^(\w+)\s*(?:\([^)]*\))?\s*:\s*(.*)$', s)
        if m:
            courant = m.group(1)
            params[courant] = m.group(2)
        elif s and courant:
            params[courant] += ' ' + s
    return ' '.join(description), params

@lru_cache(maxsize=None)
def _function_to_json_schema(func):
    sig = inspect.signature(func)
    description, docs_params = _parse_docstring(inspect.getdoc(func) or "")

    schema = {
        "type": "function",
        "function": {
            "name": func.__name__,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }

    for name, param in sig.parameters.items():
        if name == 'self':
            continue
        param_type = "string"
        if param.annotation is int:
            param_type = "integer"
        elif param.annotation is bool:
            param_type = "boolean"
        elif param.annotation is float:
            param_type = "number"

        schema["function"]["parameters"]["properties"][name] = {
            "type": param_type,
            "description": docs_params.get(name, f"Paramètre {name}")
        }
        if param.default is inspect.Parameter.empty:
            schema["function"]["parameters"]["required"].append(name)

    return schema

def _tools_to_schemas(tools):
    schemas = []
    for tool in tools or []:
        if callable(tool):
            schemas.append(_function_to_json_schema(tool))
        elif isinstance(tool, dict):
            schemas.append(tool if 'type' in tool else {'type': 'function', 'function': tool})
    return schemas

# --- NORMALISATION DES MESSAGES ---
def normaliser_tool_calls(tool_calls) -> list:
    """Convertit des tool_calls (objets Ollama ou dicts OpenAI) en dicts uniformes avec id et arguments dict."""
    resultat = []
    for tc in tool_calls or []:
        if hasattr(tc, 'model_dump'):
            tc = tc.model_dump()
        fn = tc.get('function') or {}
        if hasattr(fn, 'model_dump'):
            fn = fn.model_dump()
        args = fn.get('arguments') or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        resultat.append({
            'id': tc.get('id') or f"call_{uuid.uuid4().hex[:12]}",
            'type': 'function',
            'function': {'name': fn.get('name', ''), 'arguments': args}
        })
    return resultat

def _to_openai_messages(messages_list):
    """Format OpenAI strict : tool_call_id sur les messages 'tool', arguments sérialisés en chaîne JSON."""
    clean_messages = []
    for msg in messages_list:
        clean_msg = {'role': msg['role'], 'content': msg.get('content') or ''}
        if msg.get('tool_calls'):
            clean_msg['tool_calls'] = [
                {
                    'id': tc['id'],
                    'type': 'function',
                    'function': {
                        'name': tc['function']['name'],
                        'arguments': json.dumps(tc['function'].get('arguments') or {}, ensure_ascii=False)
                    }
                }
                for tc in normaliser_tool_calls(msg['tool_calls'])
            ]
        if msg['role'] == 'tool':
            if msg.get('tool_call_id'):
                clean_msg['tool_call_id'] = msg['tool_call_id']
            if msg.get('name'):
                clean_msg['name'] = msg['name']
        clean_messages.append(clean_msg)
    return clean_messages

def _to_ollama_messages(messages_list):
    """Format natif /api/chat d'Ollama : arguments en objet JSON, 'tool_name' sur les messages 'tool'."""
    clean_messages = []
    for msg in messages_list:
        clean_msg = {'role': msg['role'], 'content': msg.get('content') or ''}
        if msg.get('tool_calls'):
            clean_msg['tool_calls'] = [
                {'function': {'name': tc['function']['name'], 'arguments': tc['function'].get('arguments') or {}}}
                for tc in normaliser_tool_calls(msg['tool_calls'])
            ]
        if msg['role'] == 'tool' and (msg.get('tool_name') or msg.get('name')):
            clean_msg['tool_name'] = msg.get('tool_name') or msg.get('name')
        clean_messages.append(clean_msg)
    return clean_messages

# --- CHAT ---
def _fermeture_socket(resp):
    """
    Coupe une réponse HTTP streamée depuis n'importe quel thread, sans bloquer.
    (resp.close() appelé depuis un autre thread attend la fin de la lecture en cours.)
    """
    # Socket portée par le flux de la réponse (toujours présente pendant le streaming,
    # même si http.client l'a détachée de la connexion), sinon celle de la connexion keep-alive
    fp = getattr(getattr(getattr(resp.raw, '_fp', None), 'fp', None), 'raw', None)
    sock = getattr(fp, '_sock', None) or getattr(getattr(resp.raw, '_connection', None), 'sock', None)
    if sock is None:
        logger.debug("Socket introuvable : le kill switch attendra le prochain token.")
    def fermer():
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    return fermer

def _post_stream(provider, url, payload, enregistrer_fermeture):
    try:
        resp = _http.post(url, json=payload, stream=True, timeout=(SCAN_TIMEOUT * 2, CHAT_TIMEOUT))
    except requests.RequestException as e:
        raise Exception(f"Erreur {provider}: {e}") from e
    if resp.status_code >= 400:
        detail = resp.text[:300]
        resp.close()
        raise Exception(f"Erreur {provider} (HTTP {resp.status_code}): {detail}")
    if enregistrer_fermeture is not None:
        enregistrer_fermeture(_fermeture_socket(resp))
    return resp

def _stream_ollama(model_name, messages_list, tools, enregistrer_fermeture=None):
    payload = {
        "model": model_name,
        "messages": _to_ollama_messages(messages_list),
        "stream": True,
        "keep_alive": "1h"
    }
    schemas = _tools_to_schemas(tools)
    if schemas:
        payload['tools'] = schemas

    resp = _post_stream('ollama', f"{PROVIDERS['ollama']['api_base']}/api/chat", payload, enregistrer_fermeture)
    tool_calls = []
    try:
        for line in resp.iter_lines():
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
            if data.get('error'):
                raise Exception(f"Erreur ollama: {data['error']}")
            msg = data.get('message') or {}
            if msg.get('content'):
                yield {'content': msg['content']}
            if msg.get('tool_calls'):
                tool_calls.extend(msg['tool_calls'])
            if data.get('done'):
                if data.get('eval_count') and data.get('eval_duration'):
                    yield {'stats': {'tps': round(data['eval_count'] / (data['eval_duration'] / 1e9), 1)}}
                break
    finally:
        # Ferme la connexion HTTP : Ollama interrompt la génération (kill switch)
        resp.close()
    if tool_calls:
        yield {'tool_calls': normaliser_tool_calls(tool_calls)}

def _stream_openai(provider, model_name, messages_list, tools, enregistrer_fermeture=None):
    api_base = PROVIDERS[provider]['api_base']
    payload = {
        "model": model_name,
        "messages": _to_openai_messages(messages_list),
        "temperature": 0.7,
        "stream": True
    }
    schemas = _tools_to_schemas(tools)
    if schemas:
        payload['tools'] = schemas

    resp = _post_stream(provider, f"{api_base}/v1/chat/completions", payload, enregistrer_fermeture)

    accumulateur = {}  # index -> {'id', 'name', 'arguments'}
    try:
        for line in resp.iter_lines():
            if not line:
                continue
            decoded_line = line.decode('utf-8', errors='replace')
            if not decoded_line.startswith('data:'):
                continue
            data_str = decoded_line[5:].strip()
            if data_str == '[DONE]':
                break
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                continue
            choices = data.get('choices') or []
            if not choices:
                continue
            delta = choices[0].get('delta') or {}
            if delta.get('content'):
                yield {'content': delta['content']}
            # Les tool_calls arrivent en fragments indexés à recoller
            for tc in delta.get('tool_calls') or []:
                slot = accumulateur.setdefault(tc.get('index', 0), {'id': None, 'name': '', 'arguments': ''})
                if tc.get('id'):
                    slot['id'] = tc['id']
                fn = tc.get('function') or {}
                if fn.get('name') and not slot['name']:
                    slot['name'] = fn['name']
                if fn.get('arguments'):
                    args = fn['arguments']
                    slot['arguments'] += args if isinstance(args, str) else json.dumps(args)
    finally:
        # Ferme la connexion HTTP : le serveur interrompt la génération (kill switch)
        resp.close()
    if accumulateur:
        yield {'tool_calls': normaliser_tool_calls([
            {'id': s['id'], 'function': {'name': s['name'], 'arguments': s['arguments']}}
            for _, s in sorted(accumulateur.items())
        ])}

def stream_chat(model_name, messages_list, tools=None, enregistrer_fermeture=None):
    """
    Génère la réponse en streaming, outils compris (un seul appel LLM par tour).
    Produit des dicts {'content': str} au fil de l'eau, puis {'tool_calls': [...]} si le modèle appelle des outils.
    Fermer le générateur (close()) coupe la connexion et interrompt la génération côté fournisseur.
    `enregistrer_fermeture(fn)` reçoit une fonction appelable depuis un autre thread pour couper
    la connexion immédiatement (kill switch), même pendant l'attente du premier token.
    """
    provider = get_model_provider(model_name)
    if provider == 'ollama':
        return _stream_ollama(model_name, messages_list, tools, enregistrer_fermeture)
    if provider in ('lmstudio', 'nvidia'):
        return _stream_openai(provider, model_name, messages_list, tools, enregistrer_fermeture)
    raise Exception(f"Fournisseur non supporté: {provider}")

def chat_with_provider(model_name, messages_list, tools=None):
    """Version non streamée : renvoie {'message': {'role', 'content', 'tool_calls'}}."""
    content, tool_calls = [], []
    for event in stream_chat(model_name, messages_list, tools):
        if 'content' in event:
            content.append(event['content'])
        elif 'tool_calls' in event:
            tool_calls.extend(event['tool_calls'])
    return {'message': {'role': 'assistant', 'content': ''.join(content), 'tool_calls': tool_calls}}

# --- GESTION DES MODÈLES (onglet Modèles du widget) ---
def modeles_charges() -> dict:
    """Modèles Ollama présents en mémoire : {nom: {'vram_gb', 'ctx'}} (vide si non supporté)."""
    if 'ollama' not in PROVIDERS:
        return {}
    try:
        resp = _http.get(f"{PROVIDERS['ollama']['api_base']}/api/ps", timeout=SCAN_TIMEOUT)
        if resp.status_code != 200:
            return {}
        return {
            m.get('name') or m.get('model'): {
                'vram_gb': round((m.get('size_vram') or 0) / 1024**3, 1),
                'ctx': m.get('context_length'),
            }
            for m in resp.json().get('models', [])
        }
    except (requests.RequestException, ValueError):
        return {}

def charger_modele(model_name: str) -> bool:
    """Précharge le modèle en mémoire (Ollama). LM Studio charge à la première requête : rien à faire."""
    if get_model_provider(model_name) != 'ollama':
        return False
    resp = _http.post(f"{PROVIDERS['ollama']['api_base']}/api/generate",
                      json={"model": model_name, "keep_alive": "1h", "stream": False},
                      timeout=(SCAN_TIMEOUT * 2, max(CHAT_TIMEOUT, 300)))
    if resp.status_code >= 400:
        raise Exception(f"Erreur ollama (HTTP {resp.status_code}): {resp.text[:200]}")
    return True

def decharger_modele(model_name: str):
    """Libère la VRAM occupée par le modèle (Ollama uniquement)."""
    if get_model_provider(model_name) != 'ollama':
        raise Exception("Le déchargement n'est possible que pour les modèles Ollama (utilisez LM Studio pour les siens).")
    resp = _http.post(f"{PROVIDERS['ollama']['api_base']}/api/generate",
                      json={"model": model_name, "keep_alive": 0, "stream": False},
                      timeout=(SCAN_TIMEOUT * 2, 60))
    if resp.status_code >= 400:
        raise Exception(f"Erreur ollama (HTTP {resp.status_code}): {resp.text[:200]}")

def preload_models():
    """Thread de pré-chargement : scan les modèles puis sélectionne le défaut."""
    logger.info("Détection des modèles IA en cours...")
    _refresh_models_cache()
    model = get_default_model()
    with _cache_lock:
        total = sum(len(v) for v in _models_cache.values())
    logger.info(f"{total} modèle(s) détecté(s), modèle par défaut: {model}")
    return model
