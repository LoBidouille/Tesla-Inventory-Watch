# Changelog

## 0.3.1

- Explique les refus HTTP 429 dans l’état de l’intégration et affiche la date/heure du prochain appel autorisé dans le fuseau Home Assistant.
- Distingue les nouveaux essais de configuration locaux des appels réseau Tesla, sans modifier la limite de trois contrôles par jour.
- Conserve les échéances et reconnaît les erreurs 429 déjà enregistrées par la version 0.3.0.
- Vérifie qu’un refus 429, les essais de configuration suivants et un rechargement ne produisent qu’un seul appel Tesla pendant l’attente.
- Cette version améliore le diagnostic ; elle ne supprime pas une limitation imposée par Tesla.

## 0.3.0

- Remplace le client HTTP standard par `curl-cffi==0.16.3` avec empreinte TLS/HTTP Chrome et en-têtes cohérents, sans désactiver TLS.
- Charge la dépendance native dans un exécuteur au démarrage de l’entrée, sans import natif lors de la découverte du formulaire.
- Fixe la cadence à huit heures, soit au maximum trois recherches complètes par 24 heures et par entrée. Les anciens intervalles sont ignorés.
- Enregistre la prochaine tentative avant l’appel réseau, y compris en cas d’erreur ou d’annulation ; respecte aussi un délai Tesla plus long.
- Conserve cette échéance et le dernier résultat après redémarrage/rechargement. Le bouton ne contourne pas la cadence et ne rejoue pas les alertes.
- Supprime les requêtes Tesla à la validation des formulaires : le premier contrôle est réalisé en arrière-plan après enregistrement.
- Ajoute les attributs `last_checked` et `next_check` et des tests de cadence, redémarrage, concurrence et transport Chrome.
- Vérifie les tests avec Home Assistant 2026.3.0 et 2026.10.2. L’empreinte Chrome ne garantit pas la levée d’un refus Tesla 403.

## 0.2.5

- Corrige la pagination au-delà de 96 véhicules et les totaux Tesla renvoyés sous forme de texte.
- Refuse les réponses invalides, les pages répétées et les inventaires incomplets au lieu de publier un état trompeur.
- Déduplique les véhicules par VIN.
- Respecte les délais `Retry-After`, y compris les dates HTTP et les délais supérieurs à une heure.
- Évite un appel API supplémentaire si la page Tesla renvoie déjà HTTP 429.
- Prend en charge les proxys HTTP configurés dans l’environnement.
- Permet de modifier notifications, tri et intervalle sans appel Tesla si les filtres restent identiques.
- Ne réinitialise plus les VIN lorsque seul le tri ou l’ordre des sélections change.
- Valide coordonnées, code postal français et format du service de notification.
- Préserve la référence en mémoire si son enregistrement échoue.
- Ajoute une suite de tests de régression et son exécution dans GitHub Actions.

La première synchronisation après mise à jour rétablit silencieusement la référence des VIN, car le calcul de signature a changé.

## 0.2.4

- Corrige le crash « 500 Internal Server Error » du Config Flow.
- Supprime la dépendance externe `curl-cffi` afin que Home Assistant puisse charger le flux sans installation binaire.
- Utilise uniquement le client `aiohttp` natif de Home Assistant.
- Crée une session dédiée avec cookies pour reproduire la navigation Tesla.
- Conserve `count=24`, `super_region = north america` et les en-têtes navigateur.

## 0.2.3

- Ajoute un repli automatique entre les empreintes Chrome, Safari iOS et Chrome Android en cas de HTTP 403 Tesla.
- Conserve la session et les cookies Tesla entre les tentatives.
- Améliore la robustesse face aux protections anti-bot variables de Tesla.

## 0.2.2

- Corrige les refus HTTP 403 de Tesla avec une empreinte navigateur Chrome au niveau HTTP/TLS.
- Établit une session sur la page d'inventaire avant l'appel API afin de conserver les cookies.
- Corrige `super_region` en `north america`, conformément à la requête navigateur Tesla.
- Utilise `curl-cffi==0.16.3` pour l'impersonation navigateur.
- Conserve la pagination Tesla par blocs de 24 résultats.

## 0.2.1

- Requête Tesla alignée sur le site officiel avec `count=24`.
- Pagination par blocs de 24 véhicules.
- Messages dédiés pour les réponses HTTP 403 et 429.
- Diagnostic amélioré des réponses Tesla non JSON.
- Liens GitHub du manifeste corrigés pour LoBidouille/Tesla-Inventory-Watch.

## 0.2.0

- Structure de dépôt compatible HACS.
- Ajout d'un logo et d'une icône locale Home Assistant (`brand/`).
- Configuration graphique des filtres Tesla.
- Intervalle de vérification configurable.
- Notifications Home Assistant configurables.
- Détection des nouveaux véhicules par VIN.
- Réinitialisation silencieuse de la référence après modification des filtres.
- Bouton d'actualisation manuelle.

## 0.1.0

- Première version fonctionnelle.
