"""core/token_counter.py
Estimation déterministe et ultra-rapide (<0.1ms) des tokens pour les modèles LLM locaux.
100% Python pur, zéro dépendance, conforme aux contraintes air-gap et Python 3.14 (BLOC B.1).
"""
import json
import re

_RE_TOKENS = re.compile(r"""\w+|[^\w\s]|\n""")

# Constantes de budget de contexte Alyx (BLOC B.7, PROJECT.md)
CONTEXT_LENGTH = 4096
HEADROOM_TOKENS = 800
MAX_INPUT_TOKENS = CONTEXT_LENGTH - HEADROOM_TOKENS  # 3296


def estimer_tokens_texte(texte: str) -> int:
    """Estime le nombre de tokens d'un texte de manière conservatrice et rapide (<0.1ms).

    Args:
        texte: Chaîne textuelle (français, code, JSON, logs).

    Returns:
        int: Nombre estimé de tokens BPE.
    """
    if not texte:
        return 0
    n = len(texte)
    if n <= 3:
        return 1

    matches = _RE_TOKENS.findall(texte)
    total = 0

    for w in matches:
        lw = len(w)
        if lw == 1:
            total += 1
        elif w.isascii():
            if lw <= 4:
                total += 1
            elif lw <= 8:
                total += 2
            else:
                total += 1 + (lw - 1) // 3
        else:
            # Caractères non-ASCII (accents français, symboles internationaux)
            total += 1 + lw // 3

    # Garde-fou pour séquences ultra-denses sans espaces (hashes, base64)
    min_tokens = (n + 3) // 4
    return max(total, min_tokens)


def estimer_tokens_message(msg: dict) -> int:
    """Estime les tokens consommés par un message de chat (rôle, contenu, métadonnées, tool_calls).

    Args:
        msg: Dictionnaire représentant un message OpenAI / Ollama.

    Returns:
        int: Nombre total de tokens consommés.
    """
    if not isinstance(msg, dict):
        return 0

    # Cadrage ChatML / Llama 3 header + rôle + délimiteur (<|start_header_id|>...<|eot_id|>)
    total = 4

    contenu = msg.get('content')
    if isinstance(contenu, str) and contenu:
        total += estimer_tokens_texte(contenu)

    for champ in ('name', 'tool_name', 'tool_call_id'):
        val = msg.get(champ)
        if isinstance(val, str) and val:
            total += 1 + estimer_tokens_texte(val)

    tool_calls = msg.get('tool_calls')
    if tool_calls and isinstance(tool_calls, list):
        for tc in tool_calls:
            total += 4  # Overhead de délimitation d'appel d'outil
            if isinstance(tc, dict):
                fn = tc.get('function') or {}
                if isinstance(fn, dict):
                    nom = fn.get('name')
                    if isinstance(nom, str) and nom:
                        total += estimer_tokens_texte(nom)
                    args = fn.get('arguments')
                    if isinstance(args, str):
                        total += estimer_tokens_texte(args)
                    elif isinstance(args, dict):
                        total += estimer_tokens_texte(json.dumps(args, ensure_ascii=False))

    return total


def estimer_tokens_outils(tools: list | None) -> int:
    """Estime les tokens consommés par les définitions et schémas JSON d'outils."""
    if not tools:
        return 0
    from core.llm_provider import _tools_to_schemas
    schemas = _tools_to_schemas(tools)
    if not schemas:
        return 0
    texte_schemas = json.dumps(schemas, ensure_ascii=False)
    return 10 + estimer_tokens_texte(texte_schemas)


estimer_tokens_tools = estimer_tokens_outils
