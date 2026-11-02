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
    trouver_doublons,
    annuler_derniere_action,
    executer_avec_permission
)
from .web import rechercher_web
from .voice import faire_parler, ecouter, arreter_parole
from .system import (
    ouvrir_explorateur,
    ouvrir_application,
    lister_apps_actives,
    fermer_application,
    controler_media,
    redemarrer_pc,
    rechercher_processus,
    lister_services,
    gerer_service,
    lister_taches_planifiees,
    gerer_tache_planifiee,
    lister_apps_demarrage,
    gerer_app_demarrage,
    desactiver_telemetrie_pc,
    executer_commande_systeme,
    rechercher_ou_jouer_media,
    lire_presse_papiers,
    diagnostiquer_reseau,
    reparer_reseau,
    nettoyer_caches,
    analyser_telechargements,
    mettre_a_jour_logiciels,
)
