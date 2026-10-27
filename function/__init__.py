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
    generer_pdf,
    executer_avec_permission
)
from .voice import faire_parler, ecouter, arreter_parole
from .system import (
    ouvrir_explorateur,
    ouvrir_application,
    lister_apps_actives,
    fermer_application,
    controler_media,
    redemarrer_pc
)
