# Tesla Inventory Watch

Intégration **non officielle** pour Home Assistant permettant de surveiller l'inventaire Tesla et d'être averti lorsqu'un nouveau véhicule correspondant aux critères configurés apparaît.

> Cette intégration n'est ni développée, ni approuvée, ni supportée par Tesla. Elle utilise l'endpoint d'inventaire utilisé par le site Tesla ; cet endpoint n'est pas une API publique documentée et peut changer.

## Fonctions

- Configuration entièrement depuis l'interface Home Assistant.
- Model 3, Model Y, Model S et Model X.
- Véhicules neufs ou d'occasion.
- Filtres : années, codes de versions Tesla, couleurs, prix, kilométrage, code postal, rayon et coordonnées.
- Au maximum trois recherches par période de 24 heures, espacées d’au moins huit heures pour chaque recherche configurée.
- Notifications activables/désactivables avec choix du service `notify.*`.
- Détection par VIN : seules les nouvelles annonces déclenchent une alerte.
- Lorsqu'un filtre est modifié, la nouvelle liste devient silencieusement la référence afin d'éviter les fausses notifications.
- Capteurs `Véhicules disponibles` et `Nouveaux véhicules`.
- Bouton d’actualisation respectant le même délai de huit heures.
- Événement Home Assistant `tesla_inventory_watch_new_vehicle` pour les automatisations avancées.

## Valeurs préconfigurées

La configuration initiale reprend la recherche fournie :

- Model 3 d'occasion
- `LRRWD`, `PRRWD`, `LRAWD`
- Années 2021 à 2025
- Noir et gris
- 25 000 à 45 000 €
- 9 000 à 107 000 km
- Code postal 13220
- Contrôle toutes les huit heures (trois fois par jour)

Les filtres et les notifications sont modifiables depuis les options. La cadence de huit heures est fixe, y compris pour les anciennes installations.

## Installation avec HACS

HACS installe cette intégration depuis son dépôt GitHub public.

1. Dans HACS : menu `⋮` → **Dépôts personnalisés**.
2. Ajouter `https://github.com/LoBidouille/Tesla-Inventory-Watch` et sélectionner **Intégration**.
3. Installer **Tesla Inventory Watch**, puis redémarrer Home Assistant. Pour une mise à jour, utiliser **Retélécharger** dans HACS.
4. Aller dans **Paramètres → Appareils et services → Ajouter une intégration** et rechercher **Tesla Inventory Watch**.
5. Enregistrer les critères. Le premier appel Tesla est effectué en arrière-plan après l’enregistrement, sans doubler les appels à la validation du formulaire.

Home Assistant installe automatiquement `curl-cffi==0.16.3`, qui reproduit l’empreinte TLS/HTTP de Chrome avec ses en-têtes cohérents et conserve les cookies pendant une recherche. Aucun Chrome, Selenium ou service externe n’est à installer. Le chargement natif est différé pour ne pas bloquer la découverte du formulaire de configuration. Si la dépendance ne peut pas être installée sur votre architecture, consulter les journaux Home Assistant ; ne pas désactiver la vérification des certificats.

## Cadence de trois recherches par jour

- La première recherche part au démarrage initial ; les suivantes sont espacées d’au moins huit heures. Exemple : installation à 08 h, contrôles vers 08 h, 16 h et minuit. Ce sont des intervalles écoulés, pas des heures locales fixes.
- La limite est appliquée **par recherche configurée**. Deux recherches indépendantes peuvent donc produire six contrôles par jour.
- Une recherche complète peut contenir plusieurs requêtes HTTP : visite de la page d’inventaire pour les cookies, puis une ou plusieurs pages de résultats. Il ne s’agit pas d’une limite de trois paquets HTTP.
- Les échecs 403/429 et les interruptions consomment une tentative. Aucun changement de navigateur ni nouvel essai immédiat après un refus. Un `Retry-After` supérieur à huit heures prolonge l’attente.
- L’échéance est enregistrée **avant** l’appel réseau : redémarrer Home Assistant, recharger l’intégration ou modifier les filtres ne réinitialise pas l’attente.
- Pendant l’attente, le bouton affiche les données conservées sans contacter Tesla ni renvoyer les anciennes notifications. Après un échec, l’intégration reste indisponible jusqu’à un contrôle réussi ; les journaux indiquent la cause.
- Les attributs `last_checked` et `next_check` du capteur de véhicules disponibles indiquent les horodatages Unix du dernier contrôle réussi et du prochain contrôle autorisé.
- Une annonce ajoutée puis retirée entre deux contrôles peut être manquée. La première recherche et un changement de filtres établissent une référence silencieuse.

## Logo

À partir de Home Assistant 2026.3, les intégrations personnalisées peuvent embarquer leurs propres images de marque dans `custom_components/<domain>/brand/`. Ce dépôt contient `icon.png`, `logo.png` et leurs versions haute résolution/dark mode.

## Remarques techniques

- L'état des VIN est enregistré dans le stockage Home Assistant de l'intégration.
- Une première synchronisation sert uniquement à établir la référence ; elle ne déclenche pas d'alerte.
- Un retour vide temporaire de Tesla ne supprime pas immédiatement la référence des VIN précédents.
- Les réponses HTTP 429 utilisent le mécanisme `retry_after` du `DataUpdateCoordinator` de Home Assistant.

## Licence

MIT.

## Développement et tests

Utiliser Python 3.14 et Home Assistant 2026.3.0 (version minimale annoncée par cette intégration) :

```sh
python3.14 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

Les tests ne contactent pas Tesla et n’envoient aucune notification réelle. Ils sont vérifiés avec Home Assistant 2026.3.0 et 2026.10.2. Ils couvrent notamment les formulaires Home Assistant, la pagination, les erreurs réseau, la limitation HTTP 429, la persistance et la détection des nouveaux VIN.

Pour vérifier l’intégration en fonctionnement, utiliser une instance Home Assistant de développement, placer ce dossier `custom_components/tesla_inventory_watch` dans son répertoire `custom_components`, puis ajouter l’intégration depuis les paramètres. Après une mise à jour via HACS, redémarrer Home Assistant.

## Limites et diagnostic

- L’empreinte Chrome ne lance pas un navigateur complet et n’exécute ni JavaScript ni CAPTCHA. Tesla peut encore refuser l’accès (HTTP 403) : un succès sur un autre réseau ne garantit pas le fonctionnement chez vous.
- Si un proxy est requis, les variables standard `HTTPS_PROXY`, `HTTP_PROXY` et `NO_PROXY` sont prises en compte. La vérification TLS reste activée.
- Une réponse invalide ou incomplète conserve la référence des VIN et rend la mise à jour indisponible ; elle n’est pas interprétée comme un inventaire vide.
- La pagination est limitée à 100 pages de 24 résultats par actualisation. Une recherche dépassant cette limite échoue explicitement : affiner alors les filtres.
- Les modifications du tri et des notifications ne réinitialisent pas la référence des VIN. Les changements de filtres le font silencieusement.
- Lors du premier passage à la version 0.2.5, la nouvelle signature réinitialise silencieusement la référence une fois.

### « Tesla rate limit reached » après enregistrement

Le formulaire enregistre les critères avant le premier accès Tesla. Un échec ensuite signifie que les critères sont conservés mais que l’inventaire n’a pas pu être chargé. Le message `Tesla rate limit reached` correspond au refus HTTP 429 de Tesla ; il ne prouve pas que cette intégration a envoyé trop de requêtes, car la limitation peut aussi dépendre de l’adresse IP ou du client.

À partir de la version 0.3.1, l’état de l’intégration indique la date/heure du prochain appel autorisé, dans le fuseau configuré dans Home Assistant. Les « nouveaux essais » de configuration Home Assistant relisent l’échéance locale sans contacter Tesla avant ce moment. Attendre au moins huit heures après la tentative refusée, ou davantage si Tesla a demandé un délai supérieur. Ne pas supprimer/recréer l’entrée : cela effacerait sa propre échéance. Une mise à jour ou un redémarrage conserve l’attente enregistrée.

La compatibilité Chrome ne garantit pas l’accès : si le premier contrôle autorisé après l’attente renvoie encore 429, il faut considérer la collecte directe comme bloquée sur cette installation. Aucun test depuis un autre réseau ne permet de garantir la levée du blocage.
