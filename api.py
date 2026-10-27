import asyncio
import websockets
import json
import os
import re
import threading
import time
import urllib.request

import psutil

from core.exceptions import PermissionRequiredException
import ai
from ai import messages, LISTE_FONCTIONS, outils_disponibles
from core.llm_provider import (
    lister_modeles_disponibles,
    get_provider_status,
    load_config,
    stream_chat,
    get_default_model,
    wait_models_ready,
    preload_models,
    get_model_provider,
    modeles_charges,
    charger_modele,
    decharger_modele,
)
from core import system_monitor
from function import faire_parler, arreter_parole, executer_avec_permission
from function import tts
from core import preferences
from core.logger import get_logger

logger = get_logger('alyx.ws_api')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
config = load_config()
MAX_CONTEXT_MESSAGES = config.get('llm_provider', {}).get('max_context_messages', 40)
PORT = config.get('server', {}).get('port', 8765)
STT_URL = f"http://127.0.0.1:{config.get('server', {}).get('stt_port', 5001)}"
MAX_ITERATIONS_OUTILS = 5

# Fin de phrase pour le TTS : ponctuation suivie d'un blanc (évite "3.5" ou "note.txt")
FIN_DE_PHRASE = re.compile(r'[.!?…]+(?=\s)|\n')

_arret = None  # asyncio.Event, créé au démarrage du serveur


class Session:
    """État d'une connexion WebSocket (kill switch, tâche en cours, action en attente de validation)."""
    def __init__(self, websocket):
        self.ws = websocket
        self.cancel = threading.Event()
        self.task = None
        self.pending = None
        self.metrics_task = None
        self.tps = None  # débit du dernier tour (tokens/s)

    def occupee(self):
        return self.task is not None and not self.task.done()

    async def envoyer(self, payload):
        try:
            await self.ws.send(json.dumps(payload))
        except websockets.exceptions.ConnectionClosed:
            pass


# --- FENÊTRE DE CONTEXTE ---
def _index_coupure_sure(recents, max_messages):
    """Index de début qui ne sépare jamais une paire tool_call / réponse d'outil."""
    start_idx = max(0, len(recents) - max_messages)
    while start_idx > 0:
        msg = recents[start_idx]
        prev_msg = recents[start_idx - 1]
        if msg.get('role') == 'tool' or prev_msg.get('tool_calls'):
            start_idx -= 1
        else:
            break
    return start_idx

def _messages_avec_fenetre(etat_systeme=None):
    # Prompt système reconstruit à chaque tour : langue choisie dans les réglages + état du système
    contenu = ai.prompt_systeme(preferences.charger()['language'])
    if etat_systeme:
        contenu += "\n\n" + etat_systeme
    system_prompt = {'role': 'system', 'content': contenu}
    if len(messages) <= 1:
        return [system_prompt]
    recents = messages[1:]

    if len(recents) > MAX_CONTEXT_MESSAGES:
        recents = recents[_index_coupure_sure(recents, MAX_CONTEXT_MESSAGES):]

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

def _tronquer_historique():
    """Borne la mémoire : ne conserve que ~2 fenêtres de contexte."""
    recents = len(messages) - 1
    if recents > MAX_CONTEXT_MESSAGES * 2:
        debut = _index_coupure_sure(messages[1:], MAX_CONTEXT_MESSAGES)
        del messages[1:1 + debut]


# --- STT ---
def _appel_stt(chemin, corps=None, timeout=60):
    """Requête au micro-service STT ; renvoie le JSON, ou {'error': 'injoignable'}."""
    try:
        donnees = json.dumps(corps).encode('utf-8') if corps is not None else None
        req = urllib.request.Request(f"{STT_URL}{chemin}", data=donnees, method="POST" if corps is not None else "GET",
                                     headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        logger.error(f"Erreur STT ({chemin}): {e}")
        return {'error': 'injoignable'}

def _message_erreur_stt(resultat):
    micro = resultat.get('device') or 'par défaut'
    return {
        'injoignable': "Le service de reconnaissance vocale ne répond pas. Relance Alyx (alyx.bat).",
        'modele': "La reconnaissance vocale n'est pas disponible (faster-whisper absent ou en erreur). "
                  "Relance install.bat pour l'installer.",
        'aucun_micro': "Aucun micro n'est branché.",
        'micro': f"Impossible d'ouvrir le micro « {micro} ». Choisis-en un autre dans Réglages › Micro.",
        'muet': f"Le micro « {micro} » ne capte aucun son : il est sans doute coupé. "
                "Réactive-le, ou choisis un autre micro dans Réglages › Micro.",
        'occupe': "Une écoute est déjà en cours.",
    }.get(resultat.get('error') or '', "Je n'ai rien compris. Réessaie en parlant un peu plus fort, près du micro.")

def _ecouter_stt():
    prefs = preferences.charger()
    resultat = _appel_stt('/listen', {'device': prefs['microphone'], 'language': prefs['language']})
    return (resultat.get('text') or '').strip(), resultat


# --- STREAMING LLM ---
def _extraire_phrases(buffer):
    phrases = []
    while True:
        m = FIN_DE_PHRASE.search(buffer)
        if not m:
            return phrases, buffer
        phrase = buffer[:m.end()].strip()
        buffer = buffer[m.end():]
        if phrase:
            phrases.append(phrase)

async def _stream_llm(session, model, contexte, tools, vocal):
    """
    Exécute un appel LLM streamé dans un thread producteur unique (pas un aller-retour
    thread-pool par token) et relaie les tokens à l'UI. Renvoie (contenu, tool_calls, annulé).
    """
    loop = asyncio.get_running_loop()
    file_events = asyncio.Queue()
    fermetures = []  # coupe la connexion au fournisseur depuis la boucle (kill switch)

    def producteur():
        gen = None
        try:
            gen = stream_chat(model, contexte, tools, enregistrer_fermeture=fermetures.append)
            for event in gen:
                if session.cancel.is_set():
                    break
                loop.call_soon_threadsafe(file_events.put_nowait, ('event', event))
        except Exception as e:
            loop.call_soon_threadsafe(file_events.put_nowait, ('error', e))
        finally:
            if gen is not None:
                gen.close()  # coupe la connexion : le fournisseur arrête de générer
            loop.call_soon_threadsafe(file_events.put_nowait, ('end', None))

    threading.Thread(target=producteur, daemon=True).start()

    contenu, tool_calls, tts_buffer = [], [], ""
    debut_tokens, tps_fournisseur = None, None
    while True:
        if session.cancel.is_set():
            # Sans attendre le prochain token : le fournisseur libère tout de suite la requête
            for fermer in list(fermetures):
                try:
                    fermer()
                except Exception:
                    pass
            return ''.join(contenu), [], True
        try:
            genre, valeur = await asyncio.wait_for(file_events.get(), timeout=0.25)
        except asyncio.TimeoutError:
            continue
        if genre == 'end':
            break
        if genre == 'error':
            raise valeur
        if 'tool_calls' in valeur:
            tool_calls.extend(valeur['tool_calls'])
            continue
        if 'stats' in valeur:
            tps_fournisseur = valeur['stats'].get('tps')
            continue
        token = valeur.get('content', '')
        if not token:
            continue
        if debut_tokens is None:
            debut_tokens = time.time()
        contenu.append(token)
        await session.envoyer({"type": "token", "content": token})
        if vocal:
            phrases, tts_buffer = _extraire_phrases(tts_buffer + token)
            for phrase in phrases:
                faire_parler(phrase)

    if vocal and tts_buffer.strip():
        faire_parler(tts_buffer.strip())
    # Débit : valeur exacte d'Ollama, sinon estimation (1 fragment streamé ~ 1 token)
    duree = time.time() - debut_tokens if debut_tokens else 0
    if tps_fournisseur:
        session.tps = tps_fournisseur
    elif duree > 0.2 and len(contenu) > 4:
        session.tps = round(len(contenu) / duree, 1)
    return ''.join(contenu), tool_calls, False


# --- BOUCLE AGENTIQUE ---
def _ajouter_resultat(tool_call, resultat):
    nom = tool_call['function']['name']
    messages.append({
        'role': 'tool',
        'content': str(resultat),
        'name': nom,
        'tool_name': nom,
        'tool_call_id': tool_call['id'],
    })

async def _executer_outils(session, tool_calls, debut, vocal, iteration, index_autorise=None):
    """Exécute les tool_calls à partir de `debut`. Renvoie 'ok', 'suspendu' ou 'annule'."""
    for i in range(debut, len(tool_calls)):
        tool_call = tool_calls[i]
        if session.cancel.is_set():
            for restant in tool_calls[i:]:
                _ajouter_resultat(restant, "Action annulée par l'utilisateur.")
            return 'annule'

        nom_fonction = tool_call['function']['name']
        arguments = tool_call['function'].get('arguments') or {}
        await session.envoyer({"type": "system_action", "content": f"Exécution de {nom_fonction}..."})

        fonction = outils_disponibles.get(nom_fonction)
        if fonction is None:
            resultat = f"Erreur: Outil {nom_fonction} introuvable."
        else:
            try:
                if i == index_autorise:
                    resultat = await asyncio.to_thread(executer_avec_permission, fonction, arguments)
                else:
                    resultat = await asyncio.to_thread(fonction, **arguments)
            except PermissionRequiredException as e:
                logger.warning(f"Permission requise pour l'outil {nom_fonction}.")
                session.pending = {'tool_calls': tool_calls, 'index': i, 'vocal': vocal, 'iteration': iteration}
                await session.envoyer({
                    "type": "action_required",
                    "action": e.action,
                    "cible": e.cible,
                    "tool_call": tool_call
                })
                return 'suspendu'
            except TypeError as e:
                resultat = f"Erreur: arguments invalides pour {nom_fonction} ({e})."
            except Exception as e:
                logger.error(f"Erreur outil {nom_fonction}: {e}", exc_info=True)
                resultat = f"Erreur lors de l'exécution de {nom_fonction}: {e}"
        _ajouter_resultat(tool_call, resultat)
    return 'ok'

async def _terminer(session):
    _tronquer_historique()
    await session.envoyer({"type": "done", "tps": session.tps, "provider": get_model_provider(ai.MODEL)})

async def _etat_systeme():
    try:
        return await asyncio.to_thread(system_monitor.resume_pour_llm)
    except Exception as e:
        logger.debug(f"État système indisponible: {e}")
        return None

async def _executer_tour(session, vocal, iteration=0):
    """Un seul appel LLM streamé par étape : tokens relayés en direct, outils exécutés s'il y en a."""
    model = ai.MODEL
    while True:
        tools = LISTE_FONCTIONS if iteration < MAX_ITERATIONS_OUTILS else None
        contexte = _messages_avec_fenetre(await _etat_systeme())
        contenu, tool_calls, annule = await _stream_llm(session, model, contexte, tools, vocal)

        if annule:
            logger.info("Génération annulée via Kill Switch.")
            messages.append({'role': 'assistant', 'content': contenu + "\n[Génération interrompue par l'utilisateur]"})
            return await _terminer(session)
        if not tool_calls:
            messages.append({'role': 'assistant', 'content': contenu})
            return await _terminer(session)

        messages.append({'role': 'assistant', 'content': contenu, 'tool_calls': tool_calls})
        iteration += 1
        statut = await _executer_outils(session, tool_calls, 0, vocal, iteration)
        if statut == 'suspendu':
            return
        if statut == 'annule':
            return await _terminer(session)

def _abandonner_attente(session):
    """Une nouvelle requête arrive alors qu'une action attend validation : on la clôt proprement."""
    pending, session.pending = session.pending, None
    if pending:
        for tool_call in pending['tool_calls'][pending['index']:]:
            _ajouter_resultat(tool_call, "Action non validée par l'utilisateur (abandonnée).")

async def handle_chat(session, data):
    user_input = (data.get('prompt') or '').strip()
    mode_vocal = bool(data.get('vocal', False))

    if mode_vocal and not user_input:
        user_input, resultat = await asyncio.to_thread(_ecouter_stt)
        if not user_input:
            await session.envoyer({"type": "error", "message": _message_erreur_stt(resultat)})
            await session.envoyer({"type": "done"})
            return
        await session.envoyer({"type": "transcript", "content": user_input})

    if not user_input:
        await session.envoyer({"type": "done"})
        return

    _abandonner_attente(session)

    if ai.MODEL == 'Aucun modèle':
        await asyncio.to_thread(wait_models_ready, 5)
        ai.MODEL = get_default_model()
    if ai.MODEL == 'Aucun modèle':
        await session.envoyer({"type": "error", "message": "Aucun modèle n'est sélectionné ou disponible."})
        await session.envoyer({"type": "done"})
        return

    messages.append({'role': 'user', 'content': user_input})
    # « Lire toutes les réponses » : la voix parle aussi en mode texte
    await _executer_tour(session, mode_vocal or preferences.charger()['speak_all'])

async def reprendre_apres_permission(session, accordee):
    pending, session.pending = session.pending, None
    if not pending:
        await session.envoyer({"type": "error", "message": "Aucune action n'est en attente de validation."})
        await session.envoyer({"type": "done"})
        return

    tool_calls, index = pending['tool_calls'], pending['index']
    if accordee:
        statut = await _executer_outils(session, tool_calls, index, pending['vocal'], pending['iteration'], index_autorise=index)
    else:
        _ajouter_resultat(tool_calls[index], "L'utilisateur a refusé cette action.")
        statut = await _executer_outils(session, tool_calls, index + 1, pending['vocal'], pending['iteration'])

    if statut == 'suspendu':
        return
    if statut == 'annule':
        return await _terminer(session)
    await _executer_tour(session, pending['vocal'], pending['iteration'])

async def _executer_en_securite(session, coro):
    """Toute erreur (fournisseur arrêté, etc.) est renvoyée à l'UI au lieu de couper la connexion."""
    try:
        await coro
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.error(f"Erreur traitement: {e}", exc_info=True)
        await session.envoyer({"type": "error", "message": str(e)})
        await session.envoyer({"type": "done"})


# --- ARRÊT ---
def _arreter_stt():
    """Arrête le micro-service STT lancé par alyx.bat / alyx.sh (PID vérifié avant kill)."""
    pid_file = os.path.join(BASE_DIR, 'run', 'stt.pid')
    try:
        with open(pid_file, 'r') as f:
            pid = int(f.read().strip())
        proc = psutil.Process(pid)
        if 'stt_server.py' in ' '.join(proc.cmdline()):
            proc.terminate()
            proc.wait(timeout=3)
    except (OSError, ValueError, psutil.Error):
        pass
    for nom in ('stt.pid', 'api.pid'):
        try:
            os.remove(os.path.join(BASE_DIR, 'run', nom))
        except OSError:
            pass


# --- WIDGET : MÉTRIQUES, PROCESSUS, MODÈLES ---
async def _boucle_metriques(session):
    """Envoie les métriques système chaque seconde tant que le menu du widget est ouvert."""
    try:
        while True:
            snapshot = await asyncio.to_thread(system_monitor.snapshot)
            await session.envoyer({"type": "metrics", "generating": session.occupee(), **snapshot})
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Boucle de métriques arrêtée: {e}", exc_info=True)

async def _envoyer_liste_modeles(session, force=False):
    if not force:
        await asyncio.to_thread(wait_models_ready, 5)
    resultats = await asyncio.to_thread(lister_modeles_disponibles, force)
    noms = {m['name'] for liste in resultats.values() for m in liste}
    if ai.MODEL == 'Aucun modèle' or (force and ai.MODEL not in noms):
        ai.MODEL = get_default_model()
    await session.envoyer({
        "type": "models_list",
        "current_model": ai.MODEL,
        "providers": resultats,
        "loaded": await asyncio.to_thread(modeles_charges),
    })

async def _charger_modele(session, modele):
    await session.envoyer({"type": "model_loading", "model": modele})
    try:
        await asyncio.to_thread(charger_modele, modele)
        await session.envoyer({"type": "model_loaded", "model": modele})
    except Exception as e:
        logger.error(f"Chargement de {modele} échoué: {e}")
        await session.envoyer({"type": "model_error", "model": modele, "message": str(e)})
    await _envoyer_liste_modeles(session)

async def _decharger_modele(session, modele):
    try:
        await asyncio.to_thread(decharger_modele, modele)
        await session.envoyer({"type": "model_unloaded", "model": modele})
    except Exception as e:
        await session.envoyer({"type": "model_error", "model": modele, "message": str(e)})
    await _envoyer_liste_modeles(session)


# --- VOIX ET LANGUE ---
def _appliquer_voix(prefs, voix=None):
    """Configure la synthèse ; sans voix choisie (ou voix absente), prend la première de la langue."""
    voix = voix if voix is not None else tts.lister_voix()
    ids = {v['id'] for v in voix}
    voice_id = prefs['voice_id'] if prefs['voice_id'] in ids else None
    if voice_id is None:
        choix = tts.voix_pour_langue(voix, prefs['language'])
        voice_id = choix['id'] if choix else (voix[0]['id'] if voix else None)
    tts.configurer(voice_id, prefs['rate'], prefs['volume'])
    return voice_id

def _etat_voix(changements=None):
    voix = tts.lister_voix()
    if changements:
        ancienne_langue = preferences.charger()['language']
        if 'language' in changements and changements['language'] != ancienne_langue and 'voice_id' not in changements:
            # Nouvelle langue : on bascule sur une voix de cette langue si la voix actuelle n'en est pas
            actuelle = next((v for v in voix if v['id'] == preferences.charger()['voice_id']), None)
            if actuelle is None or not (actuelle.get('lang') or '').lower().startswith(changements['language']):
                changements = {**changements, 'voice_id': None}
        prefs = preferences.mettre_a_jour(changements)
    else:
        prefs = preferences.charger()
    voice_id = _appliquer_voix(prefs, voix)
    return {
        "type": "voice_settings",
        "voices": voix,
        "languages": preferences.langues(),
        "prefs": {**prefs, "voice_id": voice_id},
        "has_language_voice": tts.voix_pour_langue(voix, prefs['language']) is not None,
    }

def _etat_micros(choix=None):
    """Micros vus par le service STT + état de la reconnaissance vocale."""
    if choix is not None:
        preferences.mettre_a_jour({'microphone': choix or None})
    sante = _appel_stt('/health', timeout=2)
    liste = _appel_stt('/devices', timeout=10)
    if sante.get('error') == 'injoignable':
        stt = 'injoignable'
    elif sante.get('model_error'):
        stt = 'modele'
    else:
        stt = 'ok' if sante.get('model_ready') else 'chargement'
    return {
        "type": "microphones",
        "devices": liste.get('devices', []),
        "selected": preferences.charger()['microphone'] or "",
        "stt": stt,
    }

async def _envoyer_depuis_thread(session, fonction, *args):
    try:
        await session.envoyer(await asyncio.to_thread(fonction, *args))
    except Exception as e:
        logger.error(f"{fonction.__name__}: {e}", exc_info=True)

def _tester_micro():
    resultat = _appel_stt('/test', {'device': preferences.charger()['microphone']}, timeout=15)
    erreur = resultat.get('error') or ''
    return {
        "type": "microphone_test",
        "level": resultat.get('level', 0.0),
        "device": resultat.get('device', ''),
        "error": erreur,
        "message": _message_erreur_stt(resultat) if erreur else "",
    }


async def handler_client(websocket):
    logger.info("Interface C# connectée.")
    session = Session(websocket)

    try:
        async for message_brut in websocket:
            try:
                data = json.loads(message_brut)
            except json.JSONDecodeError:
                logger.error("Message JSON invalide reçu.")
                continue
            msg_type = data.get('type', 'chat')

            if msg_type in ('chat', 'permission_granted', 'permission_denied'):
                if session.occupee():
                    await session.envoyer({"type": "error", "message": "Une génération est déjà en cours."})
                    continue
                session.cancel.clear()
                if msg_type == 'chat':
                    coro = handle_chat(session, data)
                else:
                    coro = reprendre_apres_permission(session, msg_type == 'permission_granted')
                # Tâche séparée : la boucle continue de lire les messages (kill switch réactif)
                session.task = asyncio.create_task(_executer_en_securite(session, coro))

            elif msg_type == 'cancel':
                logger.info("Kill Switch activé.")
                session.cancel.set()
                arreter_parole()

            elif msg_type == 'clear_history':
                session.cancel.set()
                session.pending = None
                del messages[1:]
                await session.envoyer({"type": "history_cleared"})

            elif msg_type == 'get_models':
                asyncio.create_task(_envoyer_liste_modeles(session, bool(data.get('refresh', False))))

            elif msg_type == 'load_model':
                modele = data.get('model', '')
                if modele:
                    ai.MODEL = modele
                    await asyncio.to_thread(preferences.mettre_a_jour, {'model': modele})
                    await session.envoyer({"type": "model_selected", "model": ai.MODEL})
                    asyncio.create_task(_charger_modele(session, modele))

            elif msg_type == 'unload_model':
                asyncio.create_task(_decharger_modele(session, data.get('model') or ai.MODEL))

            elif msg_type == 'subscribe_metrics':
                actif = bool(data.get('on', True))
                if actif and (session.metrics_task is None or session.metrics_task.done()):
                    session.metrics_task = asyncio.create_task(_boucle_metriques(session))
                elif not actif and session.metrics_task is not None:
                    session.metrics_task.cancel()
                    session.metrics_task = None

            elif msg_type == 'get_processes':
                liste = await asyncio.to_thread(system_monitor.processus, int(data.get('limit', 40)))
                await session.envoyer({"type": "processes", **liste})

            elif msg_type == 'kill_process':
                ok, message = await asyncio.to_thread(system_monitor.terminer_processus, data.get('pid'))
                await session.envoyer({"type": "process_killed", "pid": data.get('pid'), "ok": ok, "message": message})

            elif msg_type == 'get_voice_settings':
                await session.envoyer(await asyncio.to_thread(_etat_voix))
                # La liste des micros rafraîchit PortAudio (~1 s) : sans bloquer la lecture des messages
                asyncio.create_task(_envoyer_depuis_thread(session, _etat_micros))

            elif msg_type == 'set_microphone':
                nom = data.get('name')
                asyncio.create_task(_envoyer_depuis_thread(session, _etat_micros, nom if isinstance(nom, str) else ""))

            elif msg_type == 'test_microphone':
                asyncio.create_task(_envoyer_depuis_thread(session, _tester_micro))

            elif msg_type == 'set_voice_settings':
                changements = {k: data[k] for k in ('voice_id', 'rate', 'volume', 'speak_all', 'language') if k in data}
                await session.envoyer(await asyncio.to_thread(_etat_voix, changements))

            elif msg_type == 'test_voice':
                arreter_parole()
                faire_parler(preferences.phrase_test(preferences.charger()['language']))

            elif msg_type == 'get_status':
                await session.envoyer({"type": "provider_status", "status": get_provider_status()})

            elif msg_type == 'select_model':
                new_model = data.get('model', '')
                if new_model:
                    ai.MODEL = new_model
                    await asyncio.to_thread(preferences.mettre_a_jour, {'model': new_model})
                    await session.envoyer({"type": "model_selected", "model": ai.MODEL})

            elif msg_type == 'shutdown':
                logger.info("Signal de fermeture reçu du C#.")
                await session.envoyer({"type": "shutting_down"})
                await asyncio.to_thread(_arreter_stt)
                if _arret is not None:
                    _arret.set()

    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        logger.info("Interface C# déconnectée.")
        session.cancel.set()
        if session.occupee():
            session.task.cancel()
        if session.metrics_task is not None:
            session.metrics_task.cancel()
        # Pas de tool_call orphelin dans l'historique (sinon erreur 400 des API OpenAI-compatibles)
        _abandonner_attente(session)

async def demarrer_serveur_alyx():
    global _arret
    _arret = asyncio.Event()

    # Précharger les modèles en arrière-plan
    def _preload():
        try:
            _appliquer_voix(preferences.charger())  # voix et vitesse enregistrées
        except Exception as e:
            logger.warning(f"Configuration de la voix impossible: {e}")
        modele = preload_models()
        prefere = preferences.charger().get('model')
        if prefere and prefere in {m['name'] for liste in lister_modeles_disponibles().values() for m in liste}:
            modele = prefere
        if ai.MODEL == 'Aucun modèle':
            ai.MODEL = modele
        logger.info(f"Modèles préchargés, modèle par défaut: {ai.MODEL}")

        # Handshake STT (backoff court)
        logger.info("Attente du service STT (Handshake)...")
        delai = 0.25
        for _ in range(10):
            try:
                urllib.request.urlopen(f"{STT_URL}/health", timeout=1)
                logger.info("Service STT prêt.")
                return
            except Exception:
                time.sleep(delai)
                delai = min(delai * 2, 2)
        logger.warning("Service STT injoignable : le mode vocal sera indisponible.")

    threading.Thread(target=_preload, daemon=True).start()

    logger.info(f"---> Serveur WebSocket Alyx démarré sur ws://127.0.0.1:{PORT}")
    # origins=[None] : seuls les clients sans en-tête Origin (l'UI C#) sont acceptés.
    # Les navigateurs envoient toujours Origin, ce qui bloque le Cross-Site WebSocket Hijacking.
    async with websockets.serve(handler_client, "127.0.0.1", PORT, origins=[None]):
        await _arret.wait()

if __name__ == "__main__":
    try:
        asyncio.run(demarrer_serveur_alyx())
    except KeyboardInterrupt:
        pass
    print("Serveur arrêté proprement.")
