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
3. Dans `custom_components/tesla_inventory_watch/manifest.json`, remplacer `OWNER` dans les deux URL GitHub par le nom du compte ou de l'organisation qui héberge le dépôt.
4. Dans HACS : menu `⋮` → **Dépôts personnalisés**.
5. Ajouter l'URL du dépôt GitHub et sélectionner la catégorie **Intégration**.
6. Installer **Tesla Inventory Watch** puis redémarrer Home Assistant.
7. Aller dans **Paramètres → Appareils et services → Ajouter une intégration** et rechercher **Tesla Inventory Watch**.

## Logo

À partir de Home Assistant 2026.3, les intégrations personnalisées peuvent embarquer leurs propres images de marque dans `custom_components/<domain>/brand/`. Ce dépôt contient `icon.png`, `logo.png` et leurs versions haute résolution/dark mode.

## Remarques techniques

- L'état des VIN est enregistré dans le stockage Home Assistant de l'intégration.
- Une première synchronisation sert uniquement à établir la référence ; elle ne déclenche pas d'alerte.
- Un retour vide temporaire de Tesla ne supprime pas immédiatement la référence des VIN précédents.
- Les réponses HTTP 429 utilisent le mécanisme `retry_after` du `DataUpdateCoordinator` de Home Assistant.

## Licence

MIT.
