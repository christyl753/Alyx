# Fichier : function/__init__.py
from .scrap import construire_dictionnaire_applications
from .files import (
    creer_fichier,
    creer_dossier,
    lister_fichiers,
    renommer_fichier,
    deplacer_fichier,
    supprimer_fichier,
    lire_fichier_securise,
    ecrire_fichier_securise,
    generer_pdf
)
from .voice import faire_parler, ecouter   # <-- Ajout des modules vocaux
