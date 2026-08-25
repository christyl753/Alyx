# Fichier : function/tasks.py
"""Rappels locaux et prise de notes rapide (README V2 : "Daily Tasks").

Stockage 100% local dans data/ à la racine du projet (comme logs/, run/, models/ :
état applicatif propre à cette installation, jamais suivi par git). Pas de
dépendance nouvelle : JSON de la stdlib, cohérent avec le reste du projet.
"""
import json
import os
import threading
from datetime import datetime
from core.logger import get_logger

logger = get_logger('alyx.tasks')

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DATA_DIR = os.path.join(_PROJECT_ROOT, 'data')
_RAPPELS_PATH = os.path.join(_DATA_DIR, 'rappels.json')
_NOTES_PATH = os.path.join(_DATA_DIR, 'notes.json')

_verrou = threading.Lock()  # deux tool_calls (voire CLI + UI) ne doivent jamais écrire en même temps


def _charger(chemin: str, defaut):
    if not os.path.exists(chemin):
        return defaut
    try:
        with open(chemin, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Fichier de données corrompu ou illisible ({chemin}) : {e}. Repart d'un état vide.")
        return defaut


def _sauvegarder(chemin: str, donnees) -> None:
    os.makedirs(_DATA_DIR, exist_ok=True)
    # Écriture atomique (fichier temporaire + remplacement) : une coupure de courant ou
    # un crash pendant l'écriture ne doit jamais corrompre les rappels/notes existants.
    chemin_temp = chemin + '.tmp'
    with open(chemin_temp, 'w', encoding='utf-8') as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
    os.replace(chemin_temp, chemin)


def _charger_rappels() -> dict:
    """{'prochain_numero': int, 'actifs': [...]}.

    'prochain_numero' est un compteur qui ne recule JAMAIS, même après suppression :
    sans ça, terminer le rappel #1 puis en créer un nouveau lui redonnerait le numéro
    #1, alors qu'un utilisateur peut encore faire référence à l'ancien #1 de mémoire
    dans la conversation. Un numéro déjà attribué ne doit jamais désigner autre chose.
    """
    return _charger(_RAPPELS_PATH, {'prochain_numero': 1, 'actifs': []})


def creer_rappel(texte: str, quand: str = "") -> str:
    """Ajoute un rappel local. 'quand' est un texte libre (ex: 'demain 14h', 'ce soir') non interprété comme une date exacte — Alyx ne déclenche pas d'alerte automatique, il garde la liste consultable."""
    texte = texte.strip()
    if not texte:
        return "Erreur : le rappel ne peut pas être vide."
    with _verrou:
        etat = _charger_rappels()
        numero = etat['prochain_numero']
        etat['prochain_numero'] = numero + 1
        etat['actifs'].append({
            'numero': numero,
            'texte': texte,
            'quand': quand.strip(),
            'cree_le': datetime.now().isoformat(timespec='minutes'),
        })
        _sauvegarder(_RAPPELS_PATH, etat)
    suffixe = f" ({quand.strip()})" if quand.strip() else ""
    return f"Rappel #{numero} enregistré : « {texte} »{suffixe}."


def lister_rappels() -> str:
    """Liste tous les rappels actifs, avec leur numéro (nécessaire pour terminer_rappel)."""
    with _verrou:
        actifs = _charger_rappels()['actifs']
    if not actifs:
        return "Aucun rappel actif."
    lignes = []
    for r in sorted(actifs, key=lambda r: r['numero']):
        suffixe = f" — {r['quand']}" if r.get('quand') else ""
        lignes.append(f"#{r['numero']} : {r['texte']}{suffixe}")
    return "\n".join(lignes)


def terminer_rappel(numero: int) -> str:
    """Marque un rappel comme terminé et le retire de la liste active (numéro donné par lister_rappels)."""
    with _verrou:
        etat = _charger_rappels()
        restants = [r for r in etat['actifs'] if r['numero'] != numero]
        if len(restants) == len(etat['actifs']):
            return f"Erreur : aucun rappel actif portant le numéro #{numero}."
        etat['actifs'] = restants
        _sauvegarder(_RAPPELS_PATH, etat)
    return f"Rappel #{numero} marqué comme terminé."


def prendre_note(texte: str) -> str:
    """Ajoute une note horodatée au journal de notes rapides."""
    texte = texte.strip()
    if not texte:
        return "Erreur : la note ne peut pas être vide."
    with _verrou:
        notes = _charger(_NOTES_PATH, [])
        notes.append({'texte': texte, 'horodatage': datetime.now().isoformat(timespec='seconds')})
        _sauvegarder(_NOTES_PATH, notes)
    return "Note enregistrée."


def lister_notes(nombre: int = 10) -> str:
    """Affiche les dernières notes prises, les plus récentes en premier."""
    with _verrou:
        notes = _charger(_NOTES_PATH, [])
    if not notes:
        return "Aucune note enregistrée."
    recentes = list(reversed(notes))[:max(1, nombre)]
    lignes = []
    for n in recentes:
        horodatage = n['horodatage'].replace('T', ' ')
        lignes.append(f"[{horodatage}] {n['texte']}")
    return "\n".join(lignes)
