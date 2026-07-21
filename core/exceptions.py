class PermissionRequiredException(Exception):
    """Exception levée lorsqu'une action critique requiert l'autorisation de l'utilisateur."""
    def __init__(self, action: str, cible: str):
        self.action = action
        self.cible = cible
        super().__init__(f"Permission requise pour l'action '{action}' sur '{cible}'.")
