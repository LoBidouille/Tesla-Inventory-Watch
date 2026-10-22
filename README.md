# Tesla Inventory Watch

Intégration **non officielle** pour Home Assistant permettant de surveiller l'inventaire Tesla et d'être averti lorsqu'un nouveau véhicule correspondant aux critères configurés apparaît.

> Cette intégration n'est ni développée, ni approuvée, ni supportée par Tesla. Elle utilise l'endpoint d'inventaire utilisé par le site Tesla ; cet endpoint n'est pas une API publique documentée et peut changer.

## Fonctions

- Configuration entièrement depuis l'interface Home Assistant.
- Model 3, Model Y, Model S et Model X.
- Véhicules neufs ou d'occasion.
- Filtres : années, codes de versions Tesla, couleurs, prix, kilométrage, code postal, rayon et coordonnées.
- Intervalle de vérification configurable.
- Notifications activables/désactivables avec choix du service `notify.*`.
- Détection par VIN : seules les nouvelles annonces déclenchent une alerte.
- Lorsqu'un filtre est modifié, la nouvelle liste devient silencieusement la référence afin d'éviter les fausses notifications.
- Capteurs `Véhicules disponibles` et `Nouveaux véhicules`.
- Bouton `Actualiser maintenant`.
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
- Intervalle de 5 minutes

Tout est modifiable depuis les options de l'intégration.

## Installation avec HACS

HACS installe une intégration depuis un **dépôt GitHub public**. Ce dossier est prêt à être placé tel quel à la racine d'un dépôt GitHub.

1. Créer un dépôt GitHub, par exemple `tesla-inventory-watch`.
2. Envoyer tout le contenu de ce dossier à la racine du dépôt.
3. Dans HACS : menu `⋮` → **Dépôts personnalisés**.
4. Ajouter `https://github.com/LoBidouille/Tesla-Inventory-Watch` et sélectionner la catégorie **Intégration**.
5. Installer **Tesla Inventory Watch** puis redémarrer Home Assistant.
6. Aller dans **Paramètres → Appareils et services → Ajouter une intégration** et rechercher **Tesla Inventory Watch**.

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

Les tests ne contactent pas Tesla et n’envoient aucune notification réelle. Ils couvrent notamment les formulaires Home Assistant, la pagination, les erreurs réseau, la limitation HTTP 429, la persistance et la détection des nouveaux VIN.

Pour vérifier l’intégration en fonctionnement, utiliser une instance Home Assistant de développement, placer ce dossier `custom_components/tesla_inventory_watch` dans son répertoire `custom_components`, puis ajouter l’intégration depuis les paramètres. Après une mise à jour via HACS, redémarrer Home Assistant.

## Limites et diagnostic

- Tesla peut refuser les clients automatisés (HTTP 403). Les cookies et en-têtes ne garantissent pas l’accès ; cette intégration ne contourne pas les restrictions Tesla.
- Si un proxy est requis, les variables standard `HTTPS_PROXY`, `HTTP_PROXY` et `NO_PROXY` sont prises en compte. La vérification TLS reste activée.
- Une réponse invalide ou incomplète conserve la référence des VIN et rend la mise à jour indisponible ; elle n’est pas interprétée comme un inventaire vide.
- La pagination est limitée à 100 pages de 24 résultats par actualisation. Une recherche dépassant cette limite échoue explicitement : affiner alors les filtres.
- Les modifications du tri, des notifications et de l’intervalle ne réinitialisent pas la référence des VIN. Les changements de filtres le font silencieusement.
- Lors du premier passage à la version 0.2.5, la nouvelle signature réinitialise silencieusement la référence une fois.
