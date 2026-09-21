# Changelog

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
