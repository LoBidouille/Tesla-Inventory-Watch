# Inventory Watch — application web autonome

Une application de veille Tesla à héberger **sur un VPS OVH ou en local**, sans Home Assistant.

- Interface française adaptée au téléphone et à l’ordinateur.
- Recherche Tesla personnalisable : modèle, état, années, versions, couleurs, prix, kilométrage et localisation.
- Chromium réel avec profil et cookies conservés sur votre serveur.
- **Trois contrôles maximum par 24 heures**, espacés d’au moins huit heures. Les échecs, redémarrages et clics manuels ne remettent pas ce délai à zéro.
- Nouvelles annonces dans le tableau de bord et l’historique ; notifications du navigateur facultatives lorsque la page est ouverte. **Aucun service de messagerie externe.**
- Mot de passe privé, sessions protégées et données en SQLite.
- Installation Docker : le navigateur et les dépendances sont inclus.

> Tesla peut encore refuser un vrai navigateur, notamment depuis une adresse de centre de données OVH. Cette application ne garantit pas la disparition des erreurs 403/429, n’automatise pas de CAPTCHA et ne désactive pas la vérification TLS. Un import manuel est disponible si votre navigateur personnel accède au site et que le serveur est bloqué.

## Démarrage local avec Docker

Prérequis : Docker Engine avec Compose sur Linux, ou Docker Desktop sur Windows/macOS. Les commandes ci-dessous s’exécutent dans un terminal Bash. Sous PowerShell, remplacer `cp` par `Copy-Item` si nécessaire.

```sh
git clone https://github.com/LoBidouille/Tesla-Inventory-Watch.git
cd Tesla-Inventory-Watch/webapp
cp .env.example .env
docker compose up -d --build
```

Ouvrir `http://localhost:8080` dans votre navigateur. À la première visite, choisir un mot de passe d’au moins 12 caractères. Personnaliser **Ma recherche**, puis utiliser **Activer la surveillance** ou **Vérifier maintenant**.

L’application démarre **en pause** : aucun appel Tesla avant votre activation ou votre premier contrôle manuel. La première recherche constitue une référence silencieuse. Les nouveaux VIN observés ensuite créent des alertes. Une annonce retirée entre deux contrôles peut être manquée.

La première construction de l’image télécharge Chromium et peut prendre plusieurs minutes. Prévoir environ **2 Go de RAM** pour le serveur. Un seul processus applicatif est utilisé ; le verrou du répertoire de données empêche des travailleurs concurrents.

### Depuis un autre appareil de votre réseau

Dans `.env`, renseigner par exemple :

```dotenv
BIND_ADDRESS=0.0.0.0
ALLOWED_HOSTS=localhost,127.0.0.1,192.168.1.50
```

Remplacer l’adresse par celle de votre serveur, puis exécuter `docker compose up -d`. Ouvrir l’adresse IP du serveur sur le port 8080. Le tableau de bord et les alertes dans la page fonctionnent en HTTP sur le réseau local ; les notifications système du navigateur nécessitent HTTPS ou localhost. Pour un accès distant, utiliser la configuration HTTPS ci-dessous.

## Installation sur OVH avec HTTPS

Cette installation vise un **VPS ou serveur dédié Linux**, avec Docker et au moins 2 Go de RAM. Un hébergement web mutualisé PHP classique ne suffit pas pour Chromium et un processus Python permanent.

1. Cloner le dépôt et démarrer d’abord la configuration locale ci-dessus sur le VPS. Le port 8080 est lié uniquement à `127.0.0.1`.
2. Depuis votre ordinateur, ouvrir un tunnel :

   ```sh
   ssh -L 8080:127.0.0.1:8080 utilisateur@IP_DU_VPS
   ```

   Visiter `http://localhost:8080` et créer le mot de passe **avant** d’exposer l’application sur Internet. Les données seront réutilisées par la configuration HTTPS.
3. Créer un enregistrement DNS `A` de votre sous-domaine vers l’IPv4 du VPS. Ajouter `AAAA` uniquement si l’IPv6 correspondante fonctionne. Autoriser les ports TCP **80 et 443** dans le pare-feu OVH et celui du serveur.
4. Dans `.env`, remplacer `DOMAIN=tesla.example.com` par votre sous-domaine réel, par exemple `tesla.mondomaine.fr`.
5. Dans le dossier `webapp`, basculer vers la configuration HTTPS :

   ```sh
   docker compose down
   docker compose -f compose.ovh.yaml up -d --build
   ```

Caddy obtient et renouvelle automatiquement le certificat HTTPS. Se connecter à `https://VOTRE_SOUS_DOMAINE` avec le mot de passe créé précédemment. Le serveur Python n’expose aucun port public dans cette configuration ; l’accès passe par Caddy. Le volume de données et son nom sont communs aux deux configurations.

Pour vérifier le démarrage :

```sh
docker compose -f compose.ovh.yaml ps
docker compose -f compose.ovh.yaml logs --tail=80 app caddy
```

La connexion du navigateur aux critères et à l’historique est protégée par session ; les mutations vérifient l’origine. L’image tourne sans utilisateur root et son système de fichiers est en lecture seule, à l’exception des données et répertoires temporaires.

## Utilisation et notifications

- **Ma recherche** conserve vos critères. Un changement de filtres crée une nouvelle référence silencieuse au prochain contrôle autorisé et conserve l’attente en cours.
- **Activer la surveillance** lance le travail en arrière-plan sur le serveur. Laisser le serveur ou le conteneur allumé ; votre ordinateur de consultation peut être éteint.
- **Vérifier maintenant** respecte la même échéance que le contrôle automatique : il n’existe pas de bouton pour forcer les requêtes pendant l’attente.
- **Historique** conserve les nouvelles annonces indépendamment de la page. Une annonce déjà observée, retirée puis réapparue n’émet pas une seconde alerte pour le même jeu de filtres.
- **Comment ça marche → Activer les notifications navigateur** autorise les notifications sur cet appareil. La page doit rester ouverte, même en arrière-plan ; les navigateurs peuvent ralentir les onglets inactifs. **Page fermée : pas de notification système**, mais les annonces restent dans l’historique au retour.
- La page actualise les données de votre serveur toutes les quinze secondes. Ces requêtes locales à l’application ne contactent pas Tesla.
- Les heures sont affichées dans le fuseau du navigateur. Trois contrôles signifient trois recherches complètes ; une recherche peut nécessiter une visite de la page d’inventaire et plusieurs appels de pagination.

### Si Tesla refuse le serveur

Les erreurs **403**, **429**, pages non JSON et résultats incomplets s’affichent avec la prochaine échéance. Les derniers véhicules ne sont pas effacés lors d’un échec. Un délai `Retry-After` supérieur à huit heures prolonge l’attente. Changer d’hébergement ne garantit pas que Tesla acceptera le client.

L’import manuel dans **Comment ça marche** permet de continuer à consulter et comparer les résultats :

1. Sur votre ordinateur, ouvrir le site Tesla et appliquer exactement vos critères.
2. Ouvrir les outils de développement du navigateur, onglet **Réseau**, puis trouver la réponse `inventory-results`.
3. Copier **la réponse JSON**, pas les en-têtes, cookies ou une commande cURL.
4. Coller dans le formulaire d’import. Si la recherche contient plusieurs pages, réunir toutes les annonces dans la liste `results` en conservant le total complet. L’import refuse un résultat annoncé comme incomplet.

Les bornes numériques, années et codes de couleur/version présents dans la réponse sont vérifiés localement. Si Tesla ne fournit pas certains codes, l’application s’appuie sur la recherche déjà filtrée par le site. L’import est explicitement identifié comme manuel et ne réinitialise pas la limite des contrôles automatiques. Il ne rend pas une collecte bloquée automatique.

## Données, mise à jour et entretien

SQLite, le profil Chromium et ses cookies restent dans le volume Docker `tesla-inventory-watch_inventory_data`. Ne pas supprimer ce volume pour mettre à jour. Pour une sauvegarde, arrêter l’application puis sauvegarder **tout le volume**, y compris les fichiers SQLite annexes. Le profil contient des cookies : traiter la sauvegarde comme privée.

```sh
# Version locale
# Depuis le dossier webapp
git pull
docker compose up -d --build
```

Avec HTTPS, utiliser `docker compose -f compose.ovh.yaml up -d --build` à la place. `docker compose down` conserve les données ; `docker compose down -v` les supprime.

Mot de passe oublié :

```sh
# En local ; ajouter -f compose.ovh.yaml après compose pour le VPS HTTPS
docker compose exec app python -m app.manage reset-password
```

La commande demande le nouveau mot de passe dans le terminal et déconnecte toutes les sessions, sans effacer les annonces.

## Lancement sans Docker et développement

Python **3.13** et Chromium système sont nécessaires. Sur Debian/Ubuntu :

```sh
sudo apt-get update
sudo apt-get install -y chromium
cd webapp
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m app
```

L’adresse est `http://127.0.0.1:8080`. Par défaut, les données sont dans `webapp/data`. Variables disponibles : `DATA_DIR`, `HOST`, `PORT`, `ALLOWED_HOSTS`, `PUBLIC_URL`, `COOKIE_SECURE`, `CHROMIUM_EXECUTABLE`, `BROWSER_HEADLESS` et `FORWARDED_ALLOW_IPS`. Ne pas utiliser plusieurs workers. Dans un environnement nécessitant un proxy, les variables standard `HTTPS_PROXY`/`HTTP_PROXY` et `NO_PROXY` sont transmises au navigateur. Les autorités de confiance doivent être configurées dans le système/Chromium ; aucun réglage d’ignorance des certificats n’est utilisé.

Tests sans appel Tesla ni compte réel :

```sh
python -m pip install --require-hashes -r requirements-test.lock
python -m unittest discover -s tests -v
# Parcours complet dans Chromium, avec données simulées et instance temporaire
python tests/browser_smoke.py
```

Les tests vérifient l’authentification, les sessions, les origines, les filtres, la concurrence SQLite, les refus Tesla, la pagination, les nouveaux VIN, l’import et la persistance de la cadence. Le parcours de l’interface est également vérifié dans Chromium sur ordinateur et téléphone. Les données utilisées pour ces tests sont simulées ; les tests ne prouvent pas que Tesla accepte toutes les adresses de serveur.

MIT. Projet communautaire indépendant, ni développé ni approuvé par Tesla.
