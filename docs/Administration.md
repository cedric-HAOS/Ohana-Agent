# Administration graphique d'Ohana-Agent

Ohana-Vision permet de gérer les baux DHCP, l'architecture et les plugins sans
exposer les fichiers YAML à l'utilisateur. Ohana-Agent reste la source de vérité
et le seul composant autorisé à valider, écrire puis appliquer les
configurations.

## Flux

```text
Navigateur
    |
    | /api/administration/*
    v
Ohana-Vision
    |
    | Bearer token, boucle locale
    v
Ohana-Agent :8765
    |
    +-- infrastructure.yaml
    +-- fichiers dnsmasq gérés
    +-- plugins/dhcp.yaml
    +-- plugins/dns.yaml
    +-- plugins/ntp.yaml
    +-- plugins/mqtt.yaml
    +-- plugins/network.yaml
    +-- plugins/zwave.yaml
    +-- plugins/wireguard.yaml
    +-- plugins/home-assistant-telemetry.yaml
    +-- plugins/teleinformation.yaml
```

Le jeton n'est jamais envoyé au navigateur. Vision le lit dans
`/etc/ohana-vision/management.token` et l'utilise uniquement pour communiquer
avec l'Agent sur la boucle locale.

## Contrat versionné

| Méthode | Endpoint | Rôle |
|---|---|---|
| `GET` | `/v1/capabilities` | Découvrir les opérations disponibles |
| `GET` | `/v1/infrastructure` | Lire l'architecture courante |
| `PUT` | `/v1/infrastructure` | Valider et remplacer l'architecture |
| `GET` | `/v1/dhcp` | Lire les paramètres, réservations et baux |
| `PUT` | `/v1/dhcp` | Valider et remplacer la configuration DHCP |
| `GET` | `/v1/system/network` | Lire l’état NetworkManager de l’hôte Agent |
| `PUT` | `/v1/system/network` | Appliquer une configuration IPv4 avec retour automatique |
| `POST` | `/v1/system/network/{transaction_id}/confirm` | Confirmer la nouvelle configuration |
| `POST` | `/v1/system/network/{transaction_id}/rollback` | Restaurer immédiatement l’ancienne configuration |
| `GET` | `/v1/plugins` | Lister les plugins administrables et leur état |
| `GET` | `/v1/plugins/{plugin_id}` | Lire un plugin et sa configuration publique |
| `PUT` | `/v1/plugins/{plugin_id}` | Valider, enregistrer et appliquer sa configuration |
| `POST` | `/v1/plugins/{plugin_id}/test` | Exécuter un contrôle immédiat |
| `POST` | `/v1/jobs` | Créer ou rejouer idempotemment une demande Tsunade |
| `GET` | `/v1/jobs/{job_id}` | Lire l'état et le résultat d'un job |
| `POST` | `/v1/jobs/{job_id}/cancel` | Annuler un job non terminal |
| `GET` | `/v1/jobs/workers` | Lister les workers enregistrés et leur dernière activité |
| `POST` | `/v1/jobs/workers/pairings` | Ouvrir une demande d'appairage temporaire |
| `GET` | `/v1/jobs/workers/pairings` | Lister les demandes sans secret ni jeton |
| `POST` | `/v1/jobs/workers/pairings/{pairing_id}/approve` | Autoriser la demande après comparaison du code |
| `POST` | `/v1/jobs/workers/pairings/{pairing_id}/reject` | Refuser une demande non reconnue |
| `POST` | `/v1/jobs/workers/pairings/{pairing_id}/poll` | Récupérer une fois le jeton après autorisation |
| `POST` | `/v1/jobs/workers/register` | Enregistrer Katsuyu et annoncer ses capacités |
| `POST` | `/v1/jobs/claim` | Attribuer un job compatible à Katsuyu |
| `POST` | `/v1/jobs/{job_id}/heartbeat` | Renouveler le bail de l'exécution courante |
| `POST` | `/v1/jobs/{job_id}/complete` | Publier le résultat terminal vérifié |

Les opérations sont annoncées explicitement par `/v1/capabilities` :

- `infrastructure.read` et `infrastructure.write` ;
- `dhcp.read`, `dhcp.write` et `dhcp.leases.read` lorsque DHCP est activé ;
- `plugins.read`, `plugins.write` et `plugins.test` lorsque l’administration des
  plugins est disponible ;
- `system.network.read`, `system.network.write`, `system.network.confirm` et
  `system.network.rollback` lorsque le helper NetworkManager est installé.

## Jobs distribués Tsunade vers Katsuyu

Le protocole est une extension optionnelle de l'API d'administration existante.
Il ne crée ni bus d'événements, ni ordonnanceur distant générique, ni voie
d'exécution contournant Agent. Il est désactivé par défaut.

Deux plans d'autorisation restent séparés :

- Tsunade utilise le jeton d'administration existant pour créer, lire ou
  annuler un job ;
- Katsuyu utilise exclusivement un Bearer worker pour s'enregistrer, prendre un
  job, renouveler son bail et remettre son résultat ;
- les deux jetons doivent être différents ; un jeton worker ne permet de lire
  ni l'infrastructure, ni le DHCP, ni les plugins, ni les autres jobs.
- Une nouvelle installation ouvre une demande bornée sans authentification,
  affiche son code local et attend l'approbation via l'administration existante.
  Le secret de sondage reste sur Bubule ; Vision ne reçoit que l'identité, les
  capacités, le code et l'expiration. Après approbation, Agent délivre un jeton
  individuel une seule fois, conserve uniquement son SHA-256 et le lie au
  `worker_id`. Le jeton global historique reste accepté pour compatibilité.

Le Bearer doit circuler dans un transport protégé. Si Bubule est distant,
Katsuyu joint l'adresse d'INFRA-01 à travers le WireGuard existant et une ACL
réseau limite le port d'administration à Bubule. L'API ne doit jamais être
publiée directement sur Internet.

### Contrat v1

Une création contient `protocol_version: 1`, un UUID `job_id` fourni par
Tsunade, un type déclaré, une date RFC 3339 avec fuseau, des paramètres et un
timeout entre 1 seconde et 24 heures. Le même `job_id` et le même document
retournent le job existant ; un contenu différent pour cet identifiant produit
un conflit HTTP 409.

Les quatre types du MVP sont strictement déclarés :

- `system.health` ne prend aucun paramètre et mesure exclusivement l'hôte
  Katsuyu ;
- `backup.compress` reçoit les chemins relatifs `source` et `destination` dans
  l'espace Katsuyu ainsi qu'un niveau gzip de 1 à 9 ;
- `backup.encrypt` reçoit deux chemins relatifs et une clé publique `age1...` ;
  l'exécutable `age` est fixé par la configuration locale du worker ;
- `backup.verify` reçoit un chemin relatif, un SHA-256 attendu et,
  facultativement, une taille attendue.

Les trois résultats de sauvegarde publient SHA-256 et tailles. Une divergence
de vérification est un succès technique avec `valid: false`, afin que Tsunade
puisse décider de la suite sans confondre une corruption avec une panne du
worker. Les sorties déjà présentes sont relues et vérifiées lors d'une reprise,
ce qui évite de refaire une opération terminée après une perte de connexion.

Tous les chemins sont confinés dans un espace de travail configuré sur Bubule.
Les chemins absolus, `..`, les liens symboliques et les fichiers non réguliers
sont refusés. Aucun job ne transporte de commande, d'URL, de clé privée ou de
chemin d'exécutable. L'analyse ciblée de journaux reste réservée à sa phase
dédiée : aucun contrat ne centralise ni ne persiste des journaux.

### États, reprise et vérification

Les états publics sont `CREATED`, `QUEUED`, `WAITING_WORKER`, `RUNNING`,
`SUCCEEDED`, `FAILED`, `CANCELLED` et `TIMEOUT`. `CREATED` et chaque transition
sont conservés dans le journal SQLite ; le document courant est retourné en
`QUEUED` après acceptation.

La prise d'un job est atomique. Elle attribue un numéro de tentative et un bail
court. Le heartbeat prolonge ce bail sans dépasser le timeout global, persiste
un instantané borné `{percent, stage, message}` et renvoie l'état courant.
Katsuyu arrête ainsi son handler par coopération dès qu'il observe `CANCELLED`
ou `TIMEOUT`. Après une perte de connexion, l'expiration du bail replace le job
en file et la tentative
suivante reçoit un nouveau numéro ; un résultat tardif de l'ancien worker est
refusé. Aucun balayage périodique n'est nécessaire : la reprise, les timeouts et
la purge sont appliqués lors du prochain accès au magasin.

Un succès est revalidé contre le modèle de résultat du type puis accompagné du
SHA-256 de sa forme JSON canonique. Un échec doit fournir un code, un message
borné et le caractère retentable. Les fins de jobs peuvent être rejouées à
l'identique, mais une seconde valeur différente est refusée.

Le magasin est limité à 1 000 jobs actifs par défaut. Les jobs terminés et leur
journal sont purgés après 30 jours. Ces limites sont configurables. Aucune IA
n'intervient dans ce protocole ou dans le type v1.

### Worker Katsuyu minimal

Le worker est livré par le projet Windows autonome **Ohana-Katsuyu**. Agent ne
contient que le plan de contrôle : contrats stricts, authentification, file,
baux, progression, annulation et validation des résultats. Cette séparation
évite d'installer les plugins et dépendances d'Agent sur Bubule.

Katsuyu s'enregistre avec son identité, sa plateforme, sa version et la liste
exacte de ses handlers. Il réutilise le jeton worker et les endpoints décrits
ci-dessus ; aucun transport ou système d'authentification parallèle n'est
créé. Son installation Windows, son workspace, ses logs et `age.exe` sont
documentés dans son propre dépôt. Aucun worker ne doit être activé sur
INFRA-01.

## Administration réseau de l’hôte

Ohana-Agent ne lance jamais `nmcli` avec les droits de son utilisateur de
service. Ohana-Installer déploie un helper root dédié et une règle `sudoers`
limitée à ce seul exécutable. Le document reçu depuis Vision ne peut contenir
ni chemin arbitraire ni commande système.

Lors d’une modification :

1. Agent valide l’interface, le mode IPv4, l’adresse, la passerelle et les DNS ;
2. le helper sauvegarde la connexion NetworkManager active ;
3. un rollback systemd est programmé entre 30 et 300 secondes ;
4. la nouvelle configuration est appliquée ;
5. Vision doit confirmer la transaction après reconnexion ;
6. sans confirmation, l’ancienne connexion est restaurée automatiquement.

Une seule transaction peut être en attente. Les instantanés sont stockés sous
`/var/lib/ohana-agent/network` avec des permissions réservées à root.

## Plugins administrables

L'inventaire provient du `PluginManager`. Un plugin ne peut donc pas apparaître
dans l'API s'il n'est pas réellement enregistré dans l'Agent.

La version 1.11.1 expose :

- **DHCP** — capacité `dhcp.status` ;
- **DNS** — capacité `dns.resolve` ;
- **NTP** — capacité `ntp.query` ;
- **MQTT** — capacité `mqtt.roundtrip` ;
- **Présence réseau** — capacité `network.reachable` ;
- **Z-Wave** — capacité `zwave.status` ;
- **WireGuard** — capacité `wireguard.status` ;
- **Télémétrie Home Assistant** — capacité `home_assistant.telemetry.freshness` ;
- **Téléinformation** — capacité `teleinformation.freshness`.

Pour chaque plugin, l'API fournit notamment :

- la version et l'état de cycle de vie ;
- l'activation ;
- le nombre de tâches planifiées et d'exécutions ;
- les dates de dernière et prochaine exécution ;
- la dernière erreur connue ;
- la configuration modifiable.

DHCP conserve aussi son contrat d’administration dédié pour modifier les
paramètres dnsmasq, les réservations et lire les baux. Le plugin `dhcp` est
strictement observationnel : il mesure l’état du service et l’occupation de la
plage sans modifier ces fichiers.

## Reconfiguration immédiate

Une écriture `PUT /v1/plugins/{plugin_id}` suit ce déroulement :

1. validation du document par le modèle Pydantic du plugin ;
2. écriture atomique du fichier YAML ;
3. reconfiguration du plugin déjà enregistré ;
4. suppression puis reconstruction de ses tâches planifiées ;
5. restauration du fichier et de la configuration précédente si l'application
   échoue.

L'activation ou la désactivation est appliquée sans redémarrer l'Agent. Un
plugin désactivé reste enregistré, mais ses tâches sont retirées du scheduler.

Les mots de passe MQTT ne sont jamais retournés. L'API indique uniquement si un
mot de passe existe. Une valeur vide lors d'une modification conserve le secret
déjà enregistré.

Pour DHCP, l’API peut modifier l’intervalle, le seuil d’occupation et
l’activation du contrôle de service. Le nœud et les chemins dnsmasq restent
issus de `shikamaru.yaml`. La commande système exécutée est définie dans le code
d’Agent et ne provient jamais du document reçu depuis Vision.

## Test immédiat

`POST /v1/plugins/{plugin_id}/test` exécute un contrôle ponctuel avec la
configuration courante :

- premier service DHCP activé ;
- première requête et premier service DNS activé ;
- premier service NTP activé ;
- premier courtier MQTT activé ;
- premier équipement adressable de la topologie.

Le résultat contient la réussite, le contrôle exécuté, le message, la latence,
la date et les métadonnées non sensibles. Le test ne modifie ni la
planification normale ni l'historique des échecs de présence réseau.

## Architecture administrable

Le document d'infrastructure transmis par `PUT /v1/infrastructure` contient les
nœuds, services, équipements, liaisons et layouts. Vision peut ainsi :

- déplacer un équipement en modifiant sa cellule `column` / `row` ;
- rattacher un service au nœud d'un équipement ;
- créer ou modifier une liaison et ses extrémités ;
- préciser la technologie, le sens et le débit de cette liaison.

Avant toute écriture, Agent vérifie les identifiants, les références entre
objets, l'unicité des cellules de grille et la validité de l'ensemble du modèle.

## Sécurité des modifications DHCP

L'Agent ne reçoit jamais de chemin de fichier ni de commande système dans la
requête HTTP. Ces valeurs proviennent exclusivement de sa configuration locale.

Lors d'une modification :

1. le document complet est validé par Pydantic ;
2. les fichiers gérés sont écrits atomiquement ;
3. `dnsmasq --test` vérifie la configuration installée ;
4. en cas de rejet, tous les fichiers précédents sont restaurés ;
5. l'Agent compare les réservations aux baux actifs et place dans
   `/run/ohana-agent/dhcp-reload.request` uniquement les MAC dont l'adresse
   louée contredit une réservation par son équipement ou par son adresse ;
6. le helper privilégié valide cette liste, arrête brièvement dnsmasq, supprime
   uniquement les baux obsolètes puis redémarre le service pour relire toute la
   configuration.

Les baux sans conflit sont conservés. L'Agent ne dispose lui-même ni du droit de
modifier la base de baux ni de lancer une commande privilégiée.

## Fichiers dnsmasq gérés

- `/etc/dnsmasq.d/00-ohana.conf`
- `/etc/dnsmasq.d/10-infrastructure.conf`
- `/etc/dnsmasq.d/20-serveurs.conf`
- `/etc/dnsmasq.d/30-infrastructure-reseau.conf`
- `/etc/dnsmasq.d/40-passerelles-domotiques.conf`
- `/etc/dnsmasq.d/50-equipements-critiques.conf`

Le fichier local `/etc/dnsmasq.d/99-local.conf` reste hors du périmètre
d'Ohana.

## Configuration

L'exemple complet se trouve dans `config/shikamaru.example.yaml`, sous la clé
`administration`. L'écoute doit rester sur `127.0.0.1` lorsque Vision et Agent
sont installés sur le même hôte.

Pour les jobs, la sous-clé `administration.jobs` déclare le fichier SQLite, le
fichier du jeton Katsuyu, la durée du bail, le délai `WAITING_WORKER`, la
rétention et la limite de file. L'activation sur une adresse accessible à
Bubule exige d'abord le tunnel WireGuard, l'ACL réseau et le provisionnement du
jeton worker avec les mêmes permissions `0640` que les secrets Agent existants.
