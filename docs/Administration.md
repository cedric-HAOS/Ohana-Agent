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
| `GET` | `/v1/jobs/workers/trust` | Lire uniquement le certificat public et son empreinte SHA-256 |
| `GET` | `/v1/jobs/workers/pairings` | Lister les demandes sans secret ni jeton |
| `POST` | `/v1/jobs/workers/pairings/{pairing_id}/approve` | Autoriser la demande après comparaison du code |
| `POST` | `/v1/jobs/workers/pairings/{pairing_id}/reject` | Refuser une demande non reconnue |
| `POST` | `/v1/jobs/workers/pairings/{pairing_id}/poll` | Récupérer une fois le jeton après autorisation |
| `POST` | `/v1/jobs/workers/register` | Enregistrer Katsuyu et annoncer ses capacités |
| `POST` | `/v1/jobs/claim` | Attribuer un job compatible à Katsuyu |
| `POST` | `/v1/jobs/{job_id}/heartbeat` | Renouveler le bail de l'exécution courante |
| `POST` | `/v1/jobs/{job_id}/complete` | Publier le résultat terminal vérifié |
| `POST` | `/v1/incidents/logs/check` | Demander le contrôle déterministe des journaux configurés |
| `POST` | `/v1/incidents/{incident_id}/logs/investigate` | Autoriser un suivi ciblé d’un incident de journaux |
| `POST` | `/v1/incidents/{incident_id}/repairs` | Proposer une réparation finie et autorisée par Agent |
| `POST` | `/v1/incidents/{incident_id}/repairs/authorize` | Enregistrer la validation Vision/Shizune puis exécuter |
| `POST` | `/v1/incidents/{incident_id}/experience` | Confirmer manuellement une réparation connue |

Les opérations sont annoncées explicitement par `/v1/capabilities` :

- `infrastructure.read` et `infrastructure.write` ;
- `dhcp.read`, `dhcp.write` et `dhcp.leases.read` lorsque DHCP est activé ;
- `plugins.read`, `plugins.write` et `plugins.test` lorsque l’administration des
  plugins est disponible ;
- `system.network.read`, `system.network.write`, `system.network.confirm` et
  `system.network.rollback` lorsque le helper NetworkManager est installé.

## Compagnon personnel Shizune

Shizune étend les contrats d’incidents Tsunade ; elle ne reçoit ni le jeton
d’administration de Vision, ni le jeton worker de Katsuyu. Un listener HTTPS
limité, activé par Installer sur le port `8767`, expose seulement :

- l’ouverture et le suivi d’une association temporaire ;
- la santé globale synthétique, les demandes structurées et l’activité récente ;
- la réponse à une demande Tsunade ;
- l’enregistrement ou la désactivation du jeton APNs de l’iPhone.

L’association produit un code et l’empreinte courte de l’autorité TLS. Ces deux
valeurs doivent être identiques dans Shizune et dans Vision avant autorisation.
Agent délivre ensuite une seule fois un Bearer propre à l’iPhone, n’en conserve
que le SHA-256, l’expire après 90 jours par défaut et permet sa révocation dans
Vision. L’application stocke le jeton dans le trousseau iOS et épingle
l’autorité Konoha après l’association.

Une réponse Shizune porte uniquement un choix fini. Agent impose lui-même la
provenance `shizune`, retrouve la proposition côté serveur puis passe par le
même validateur et le même exécuteur que Vision. Une validation concurrente
trouve la demande déjà traitée et ne peut pas déclencher une seconde exécution.
Le listener ne publie aucune route d’infrastructure, DHCP, plugin, job ou
opération système.

Les notifications iOS sont envoyées directement par Agent à APNs en HTTP/2 ;
elles ne passent ni par Home Assistant ni par MQTT. Le canal reste facultatif :
une erreur Apple, une file pleine ou l’absence d’iPhone ne bloque jamais Agent,
Tsunade, Shikamaru, Katsuyu, une réparation ou une sauvegarde. Les demandes
restent persistées dans la base de contrôle et sont récupérées à la prochaine
ouverture de l’application.

Configuration minimale :

```yaml
administration:
  companion:
    enabled: true
    port: 8767
    certificate_file: /etc/ohana-agent/tls/worker.crt
    private_key_file: /etc/ohana-agent/tls/worker.key
    ca_certificate_file: /etc/ohana-agent/tls/ca.crt
    credential_ttl_days: 90
    push:
      enabled: true
      environment: production
      team_id: ABCDEFGHIJ
      key_id: ABCDEFGHIJ
      bundle_id: fr.ohana.Shizune
      private_key_file: /etc/ohana-agent/shizune-apns.p8
```

La clé privée Apple reste exclusivement sur INFRA-01, lisible par le compte de
service Agent. Le port `8767` est destiné au LAN et au tunnel WireGuard de
l’iPhone, jamais à une redirection publique.

Lors d’une mise à niveau vers Agent 1.24.0, Installer ajoute cette section à
la configuration locale uniquement si elle est absente. Il conserve toute
section existante et laisse `push.enabled: false` jusqu’à la fourniture des
identifiants Apple réels.

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
  affiche son code local et l'empreinte de l'autorité HTTPS, puis attend
  l'approbation via l'administration existante.
  Le secret de sondage reste sur Bubule ; Vision ne reçoit que l'identité, les
  capacités, le code et l'expiration. Après approbation, Agent délivre un jeton
  individuel une seule fois, conserve uniquement son SHA-256 et le lie au
  `worker_id`. Le jeton global historique reste accepté pour compatibilité.

Le Bearer circule exclusivement dans le listener HTTPS worker. Ce listener
n'expose que l'amorçage de confiance, l'appairage et les opérations Katsuyu ;
l'administration Vision reste sur `127.0.0.1:8765`. À la première installation,
Katsuyu télécharge uniquement le certificat public, calcule lui-même son
SHA-256 et vérifie ensuite le nom d'Agent. Vision affiche la même empreinte :
l'utilisateur doit comparer le code et l'empreinte complète avant d'autoriser.
Une connexion distante à travers Internet exige toujours une protection réseau
supplémentaire ; le port worker ne doit jamais être redirigé publiquement.

### Contrat v1

Une création contient `protocol_version: 1`, un UUID `job_id` fourni par
Tsunade, un type déclaré, une date RFC 3339 avec fuseau, des paramètres et un
timeout entre 1 seconde et 24 heures. Le même `job_id` et le même document
retournent le job existant ; un contenu différent pour cet identifiant produit
un conflit HTTP 409.

Les types de jobs sont strictement déclarés :

- `system.health` ne prend aucun paramètre et mesure exclusivement l'hôte
  Katsuyu ;
- `backup.compress` reçoit les chemins relatifs `source` et `destination` dans
  l'espace Katsuyu ainsi qu'un niveau gzip de 1 à 9 ;
- `backup.encrypt` reçoit deux chemins relatifs et une clé publique `age1...` ;
  l'exécutable `age` est fixé par la configuration locale du worker ;
- `backup.verify` reçoit un chemin relatif, un SHA-256 attendu et,
  facultativement, une taille attendue.

Deux extensions conservent les mêmes règles de contrôle :

- `backup.infra` orchestre le transfert en flux d'une source préparée par
  Agent vers Katsuyu, puis sa compression, son chiffrement et sa vérification ;
- `ai.inference` reçoit une question et de courts extraits de preuves identifiés.
  L'ensemble est limité à 48 000 caractères et le résultat strict contient un
  verdict `OK`, `KO` ou `INSUFFICIENT_CONTEXT`, des constats sourcés, le contexte
  manquant et l'investigation recommandée. Le contrat avancé version 2 ajoute
  une interprétation et des hypothèses explicitement incertaines avec causes
  possibles, éléments concordants et contradictoires et confiance calibrée ;
  Agent continue d'accepter le résultat historique version 1.
- `logs.health_check` limite les cibles à HA-01, LINKY-01 et ZWAVE-01, la
  fenêtre à quarante-huit heures et le volume à quatre Mio par cible ;
- `logs.investigate` exige un incident, une cible, un motif littéral et une
  fenêtre maximale de deux heures.

`GET /v1/incidents` conserve la collection version 1 et ajoute une synthèse
compatible : compteurs historiques, dernier job `logs.health_check` sans
journal brut, état compact des trois sources et taux de réussite des
réparations confirmées. Chaque constat de journal peut inclure
`reference_occurrences`, valeur utilisée par Katsuyu pour qualifier son
évolution.

Les trois résultats de sauvegarde publient SHA-256 et tailles. Une divergence
de vérification est un succès technique avec `valid: false`, afin que Tsunade
puisse décider de la suite sans confondre une corruption avec une panne du
worker. Les sorties déjà présentes sont relues et vérifiées lors d'une reprise,
ce qui évite de refaire une opération terminée après une perte de connexion.

Tous les chemins sont confinés dans un espace de travail configuré sur Bubule.
Les chemins absolus, `..`, les liens symboliques et les fichiers non réguliers
sont refusés. Aucun job ne transporte de commande, d'URL, de clé privée ou de
chemin d'exécutable. Les paramètres de journaux ne contiennent ni URL ni jeton :
Agent remet au seul worker propriétaire un descripteur éphémère sur le listener
HTTPS, puis Katsuyu contacte directement la cible HAOS. `ai.inference` ne
collecte rien et ne crée aucune
centralisation permanente : il traite seulement les extraits bornés joints au
job, soumis à la rétention normale du magasin de jobs.

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
journal sont purgés après 30 jours. Ces limites sont configurables. Le protocole,
ses transitions et ses décisions restent déterministes. Un LLM optionnel peut
seulement produire le résultat borné d'un job `ai.inference` ; l'absence d'un
worker doté de cette capacité laisse le job en attente sans affecter Agent.

### Cycle d'expertise Tsunade

Pour un incident actif, Tsunade cherche d'abord une procédure connue et exécute
uniquement les investigations du catalogue Agent. Un échec concret suffit à
produire un diagnostic déterministe et une proposition non autorisée. Si ces
preuves ne suffisent pas, Tsunade demande `ai.inference` seulement lorsqu'un
worker authentifié annonce cette capacité.

Le job IA reçoit au maximum huit fragments : architecture strictement concernée,
observation Shikamaru, historique pertinent, résultats des investigations,
anomalies de journaux déjà groupées et réparations connues. Il ne reçoit ni
topologie complète, ni historique global, ni journaux bruts. Son résultat est
conservé comme hypothèse avec une décision Tsunade en attente ; il ne devient ni
fait, ni résultat final, ni autorisation d'action.

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
rétention et la limite de file. `administration.jobs.worker_tls` déclare le
listener HTTPS dédié, le certificat serveur, sa clé privée et le certificat
public de l'autorité locale. Le jeton et la clé serveur conservent des
permissions `0640`; la clé privée de l'autorité reste exclusivement lisible par
`root`.

`administration.jobs.wake_on_lan` définit uniquement la politique de réveil :
activation, broadcast UDP, port et délais. L'identité du worker et sa MAC ne sont
plus dupliquées dans cette configuration : Katsuyu les annonce lors de son
enregistrement et Agent les conserve dans la base des workers.

Lorsqu'un job compatible arrive après expiration de la fraîcheur du worker,
Agent émet un paquet magique, expose le worker en `WAKING`, puis conserve
`woken_by_ohana: true` lorsque Katsuyu s'enregistre. Une arrivée spontanée reste
`woken_by_ohana: false`. L'administration expose aussi `GET
/v1/jobs/wake-on-lan` pour lire la politique effective et `POST
/v1/jobs/workers/{worker_id}/wake` pour un test de réveil explicite. L'envoi du
Magic Packet reste exécuté par Agent/Tsunade. Cette version n'implémente aucune
extinction de Bubule.

## Incidents Tsunade

Tsunade réutilise directement l'événement `ObservationPublished` déjà produit
par Shikamaru. Il ne crée ni nouveau bus ni copie permanente de l'historique
Vision. La base de contrôle existante conserve seulement l'état courant par
capacité, les incidents et les références nécessaires à leur évolution.

Un incident est ouvert sur `degraded` ou `unhealthy`, mis à jour sans être
recréé pour les observations suivantes, escaladé de dégradé à critique et
résolu uniquement par une observation `healthy`. Les états `unknown` et
`suspended` ne provoquent ni incident ni résolution artificielle. Les routes
authentifiées existantes exposent :

- `GET /v1/incidents`, `/resolved` ou `/all` ;
- `GET /v1/incidents/{incident_id}` pour l'évolution bornée ;
- `POST /v1/incidents/{incident_id}/records` pour une investigation, un
  diagnostic, une action proposée ou un résultat final.
- `POST /v1/incidents/logs/check` pour lancer manuellement le contrôle borné
  des sources configurées ; Agent construit lui-même le job Katsuyu ;
- `POST /v1/incidents/{incident_id}/logs/investigate` avec un unique `pattern`
  texte pour autoriser une analyse complémentaire d’un incident `logs.health`.
- `POST /v1/incidents/{incident_id}/repairs` pour créer une proposition finie ;
- `POST /v1/incidents/{incident_id}/repairs/authorize` pour enregistrer la
  provenance `vision` ou `shizune`, puis demander l’exécution à Agent ;
- `POST /v1/incidents/{incident_id}/experience` pour confirmer manuellement
  une réparation connue après succès vérifié.

Un simple enregistrement d'action documente une décision mais ne l'exécute
jamais. La phase initiale des réparations accepte uniquement
`restart_service` sur `dnsmasq.service`. Elle réutilise le oneshot privilégié
installé par Installer, sans shell ni nom d’unité fourni librement. Toute
exécution exige une validation humaine. Après l’action, seule une nouvelle
observation `healthy` de Shikamaru marque la réparation comme réussie ; une
nouvelle observation dégradée la marque en échec.

Une expérience n’est proposée que si le diagnostic a été confirmé par une
investigation déterministe, si une réparation autorisée a réussi et si
Shikamaru a résolu l’incident. Elle n’est enregistrée qu’après confirmation
explicite depuis Vision ou Shizune. Une hypothèse LLM, une corrélation ou une
disparition spontanée ne peuvent donc pas devenir une réparation connue.

## Investigations déterministes

`GET /v1/investigations` retourne le catalogue réellement disponible et
`POST /v1/investigations` exécute une opération avec le jeton d'administration.
La première liste réutilise les contrôles et métriques déjà présents :

- `network.ping`, `dns.query`, `mqtt.status` ;
- `backup.status` ;
- `memory.status`, `cpu.status`, `disk.usage`, `service.status`.

Ces opérations travaillent exclusivement sur la configuration Agent existante
et n'acceptent encore aucun paramètre de cible. Chaque appel a un timeout borné,
un résultat structuré et une trace dans le journal Agent. `service.logs` reste
absent tant qu'un lecteur strictement borné, filtré et audité n'a pas été ajouté.
Un LLM peut recommander une opération, mais seul Agent peut accepter cet appel.

## Contrôle distribué des journaux

`administration.jobs.logs` active une tâche Cron quotidienne, désactivée par
défaut. La valeur recommandée `0 5 * * *` produit un contrôle par vingt-quatre
heures. La tâche réutilise la file distribuée et Wake-on-LAN ; elle n'ajoute ni
daemon d'analyse ni indexation sur INFRA-01. Un nouvel incident Shikamaru sur
l'une des trois cibles déclenche aussi un contrôle immédiat d'une heure.

Katsuyu utilise le jeton Home Assistant déjà configuré pour les sauvegardes. Ce
jeton doit appartenir à un administrateur pour que le proxy WebSocket
`supervisor/api` autorise `/core/logs/latest`, `/addons` et les logs des add-ons
ciblés. `/api/error_log` sert de repli explicite lorsque Supervisor est
indisponible. Seuls résultats, compteurs, tendances et corrélations temporelles
sont conservés dans le job et l'incident ; une corrélation n'est jamais déclarée
comme causalité.

Le job `backup.infra` étend le même listener HTTPS avec deux flux liés au job :
`GET /v1/jobs/{job_id}/input` et `POST /v1/jobs/{job_id}/artifact`. Le jeton
individuel, le worker propriétaire et la tentative courante sont tous vérifiés.
La source est une liste fixe détenue par Agent ; les paramètres ne contiennent
ni commande, ni chemin, ni secret rclone.
