import contextvars

class PermissionRequiredException(Exception):
    """Exception levée lorsqu'une action critique requiert l'autorisation de l'utilisateur."""
    def __init__(self, action: str, cible: str):
        self.action = action
        self.cible = cible
        super().__init__(f"Permission requise pour l'action '{action}' sur '{cible}'.")


# Bascule Human-in-the-Loop : le LLM appelle toujours la même fonction (ex.
# supprimer_fichier) qu'il s'agisse du premier essai (permission à demander) ou de la
# reprise après validation utilisateur (permission déjà accordée, à exécuter pour de
# vrai cette fois). Une ContextVar isole proprement cette bascule par tâche asyncio :
# deux conversations WebSocket concurrentes ne peuvent jamais se marcher dessus, chacune
# tournant dans sa propre Task avec son propre contexte.
permission_deja_accordee = contextvars.ContextVar('permission_deja_accordee', default=False)
