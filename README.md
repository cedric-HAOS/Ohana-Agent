# Ohana-Agent

> Garantir les capacités de l'infrastructure, plutôt que surveiller des équipements.

Ohana-Agent est le moteur d'observation de l'écosystème Ohana. Il charge une infrastructure déclarative, exécute les plugins de capacité, produit des observations normalisées et les transmet à Ohana-Vision.

Depuis la version 1.1.0, l'Agent est la source de vérité de la topologie :
nœuds, services, équipements, liens et positions logiques sur la grille. La
version 1.2.0 ajoute leur administration graphique sécurisée depuis Vision.
La version 1.2.1 synchronise automatiquement les observations DNS avec les
services ajoutés, modifiés ou supprimés depuis cette administration. La version
1.3.0 ajoute les capacités NTP et MQTT ainsi que l’administration graphique des
plugins. La version 1.4.0 ajoute une présence réseau légère des équipements
déclarés dans la topologie. La version 1.5.0 ajoute l’observation DHCP locale,
en complément de l’administration dnsmasq existante. La version 1.6.0 ajoute
la santé du contrôleur Z-Wave. La version 1.7.0 contrôle le serveur WireGuard
fourni par la Freebox et ajoute la vérification de fraîcheur des télémétries
Shelly reçues par Home Assistant. La version 1.7.1 installe la commande
d’autorisation Freebox nécessaire sur INFRA-01. La version 1.7.2 adapte le
plugin Z-Wave au serveur WebSocket exposé par Home Assistant sur le port 3000
et publie la version de l’Agent dans son API d’administration. La version 1.7.3
modélise chaque contrôle Shelly Telemetry comme un service de l’équipement. La
version 1.7.4 replanifie ces services après une modification de l’architecture
ou du plugin. La version 1.7.5 corrige leur exécution périodique à travers le
dispatcher et restaure la publication automatique vers Vision. La version
1.8.0 ajoute le contrôle de la chaîne Téléinformation Linky transmise par
`teleinfo2mqtt`, MQTT et Home Assistant, avec interprétation du tarif Tempo. La
version 1.8.1 adapte la fraîcheur au fonctionnement réel de Tempo : `NTARF` et
les index inactifs peuvent rester inchangés, tandis que `SINSTS` et l’index actif
restent surveillés. La version 1.9.0 généralise Shelly Telemetry en
**Télémétrie Home Assistant**, accepte les noms DNS comme cibles réseau et
conserve les anciens contrats le temps de leur migration. La version 1.10.0 reçoit directement les trames décodées de `teleinfo2mqtt` sur une API dédiée et ajoute des plages horaires de surveillance aux équipements. La version 1.11.0 ajoute la lecture et la modification sécurisée de la configuration NetworkManager de l’hôte Agent, avec sauvegarde et retour automatique. La version 1.11.1 purge uniquement les anciens baux qui contredisent une nouvelle réservation DHCP et corrige la lecture des listes DNS NetworkManager.

---

# Administration graphique

Ohana-Agent expose une API locale permettant à Ohana-Vision de modifier
l’infrastructure, le DHCP et la configuration des plugins intégrés.

L’inventaire des plugins est fourni par le `PluginManager`. Les plugins DHCP,
DNS, NTP, MQTT, Présence réseau, Z-Wave, WireGuard, Télémétrie Home Assistant et
Téléinformation peuvent être activés, reconfigurés et testés sans redémarrer
l’Agent.
Les secrets MQTT, Freebox et Home Assistant restent masqués.

- l'API écoute par défaut sur `127.0.0.1:8765` ;
- chaque requête exige le jeton partagé installé dans
  `/etc/ohana-agent/management.token` ;
- l'Agent demeure seul propriétaire des fichiers de configuration ;
- une configuration DHCP n'est conservée que si `dnsmasq --test` l'accepte ;
- toute écriture est atomique et restaurée automatiquement en cas d’échec ;
- les modifications réseau passent par un helper root limité et doivent être
  confirmées avant l’expiration du délai de retour.

Le contrat et le modèle de sécurité sont détaillés dans
[`docs/Administration.md`](docs/Administration.md).

---

# Principes

## Infrastructure déclarative

En exploitation, l'infrastructure est décrite une seule fois dans :

```text
/etc/ohana-agent/infrastructure.yaml
```

Le profil complet publié par Agent est `config/infrastructure.example.yaml` ;
Ohana-Installer le copie vers ce chemin de production. Dans le dépôt,
`config/infrastructure.yaml` est volontairement un profil minimal réservé aux
tests de démarrage. Les commandes locales complètes utilisent le fichier
`.example`, sans jamais dupliquer la configuration dans Vision.

Les instances redondantes d'un même service peuvent partager la métadonnée
`availability_group`. Le résumé Home Assistant les compte alors comme un seul
service logique : toutes disponibles signifie sain, toutes indisponibles
signifie indisponible, et tout état intermédiaire signifie dégradé. Les alertes
actives restent détaillées par instance.

```yaml
metadata:
  availability_group: dns
```

Agent publie également un appareil MQTT Discovery séparé, **Ohana Host**. Il
expose l'état synthétique de la machine hôte, CPU, charge par cœur, mémoire,
swap, disque racine, température disponible, uptime hôte et uptime Agent. Les
attributs indiquent les raisons actives, l'espace libre, les redémarrages
systemd d'Agent et les éventuelles unités `ohana-*` en échec. Les métriques de
ressources doivent dépasser leur seuil pendant trois mesures consécutives ; le
disque presque plein et les incidents systemd sont immédiats.

Les uptimes sont présentés sous forme compacte (`8 j 19 h 29 min`). Le même
snapshot, avec les secondes brutes conservées, est envoyé à Vision via la
capacité `host.health` afin que les deux interfaces affichent la même mesure.

Le document d'infrastructure définit notamment :

- l'identité de l'infrastructure ;
- les nœuds et leurs endpoints ;
- les services ;
- les équipements de topologie ;
- les liens ;
- les positions logiques sur la grille.

Les plugins référencent les services par identifiant et ne dupliquent pas les adresses IP.

## Plugins indépendants

Chaque capacité est fournie par un plugin spécialisé. Les plugins DHCP, DNS,
NTP, MQTT et réseau utilisent le même pipeline d'observation standardisé.

```text
plugins/
├── dhcp/
├── dns/
├── mqtt/
├── network/
├── ntp/
├── home_assistant_telemetry/
├── teleinformation/
├── wireguard/
└── zwave/
```

Chaque plugin possède sa configuration et produit des observations standardisées.

## Téléinformation directe depuis RPI-Linky

Le mode recommandé ne consulte plus Home Assistant. `teleinfo2mqtt` envoie chaque
trame décodée directement au récepteur dédié d’Ohana-Agent :

```text
Compteur Linky → RPI-Linky / teleinfo2mqtt → HTTP → Ohana-Agent
                                      └──→ MQTT → HA-Green
```

Le récepteur écoute par défaut sur le port `8770` et accepte uniquement :

```text
POST /v1/teleinformation/frames
Authorization: Bearer <jeton dédié>
```

La sortie MQTT de `teleinfo2mqtt` et la sortie Ohana restent indépendantes. Une
indisponibilité de HA-Green ne bloque donc pas les trames reçues par Agent, et une
indisponibilité d’Agent ne bloque pas Home Assistant. Le mode historique
`home_assistant` reste disponible pendant la migration.

## Plages horaires de surveillance

Une plage facultative peut être placée dans les métadonnées d’un équipement.
Toutes les tâches rattachées à son nœud héritent de cette plage :

```yaml
metadata:
  monitoring_schedule:
    enabled: true
    timezone: Europe/Paris
    periods:
      - days: [monday, tuesday, wednesday, thursday, friday, saturday, sunday]
        start: "07:00"
        end: "22:00"
    startup_grace_seconds: 300
```

En dehors de la plage et pendant le délai de démarrage, le service prend l’état
`Suspended`. Cet état reste visible dans Vision sans créer d’incident ni
dégrader la santé globale. Une seule observation est publiée au début de chaque
période de suspension.

## Présence réseau des équipements

Le plugin `network` découvre automatiquement les équipements de
`topology.devices` qui possèdent une adresse ou qui référencent un nœud avec un
endpoint IP ou DNS. Il produit la capacité `network.reachable`.

La vérification reste volontairement légère :

- un contrôle par équipement et par intervalle, réparti dans le temps pour
  éviter un pic de requêtes ;
- ICMP en première intention ;
- confirmation par la table ARP locale lorsque l'équipement ne répond pas au
  ping ;
- état `unknown` avant d'atteindre le seuil d'échecs consécutifs ;
- aucun impact sur la santé globale des services.

Configuration :

```yaml
enabled: true
timeout: 1.0
retries: 0
interval_seconds: 60
failure_threshold: 3
```

Un équipement joignable n'est pas nécessairement fonctionnel : les plugins DNS,
NTP ou MQTT continuent de vérifier les capacités réelles.

## Contrôle Z-Wave

Le plugin `zwave` découvre les services de type `zwave` déclarés dans
`infrastructure.yaml`. Pour le module complémentaire Home Assistant, il se
connecte au serveur Z-Wave JS par WebSocket :

```yaml
- id: zwave-primary
  name: Z-Wave JS
  type: zwave
  node: zwave-01
  port: 3000
  implementation: Z-Wave JS Server
  enabled: true
  critical: true
```

Le schéma par défaut est `ws`. `wss`, `http` et `https` restent acceptés pour
les installations qui exposent un autre point d’accès. Une observation
`zwave.status` n’est saine que lorsque la connexion est ouverte et que le
pilote Z-Wave est initialisé.

Avec une connexion `ws` ou `wss`, l’Agent découvre aussi automatiquement les
nœuds exposés par Z-Wave JS. Il les ajoute à la topologie publiée vers Vision
sans modifier `infrastructure.yaml`, puis publie une observation
`zwave.node.alive` pour chacun d’eux. Les états `alive`, `awake` et `asleep`
sont considérés vivants — un équipement sur batterie endormi n’est donc pas
signalé en panne. L’état `dead` est indisponible et l’état devient inconnu si
le contrôleur ne permet plus de l’observer.

Chaque nœud découvert porte le type de topologie dédié `zwave_module`, ce qui
permet à Vision de lui appliquer un libellé et une icône radio explicites.

La topologie ne reproduit pas le maillage Z-Wave : chaque équipement découvert
est uniquement rattaché à la passerelle portant le rôle `zwave_gateway`. Les
points d’accès HTTP historiques continuent de contrôler le serveur, mais ne
permettent pas cette découverte détaillée.

## Observations standardisées

Tous les plugins produisent le même modèle d'observation :

- capacité ;
- nœud ;
- service ;
- statut ;
- latence ;
- message ;
- métadonnées techniques.

Le pipeline d'export envoie ensuite ces observations à Ohana-Vision.

---

# Architecture

```text
infrastructure.yaml
        │
        ├── définition des nœuds et services
        └── définition de la topologie et de la grille
        │
        ▼
InfrastructureLoader
        │
        ▼
InfrastructureValidator
        │
        ├── VisionInfrastructureMapper
        │         │
        │         ▼
        │   PUT /api/infrastructure
        │
        ▼
Scheduler
        │
        ▼
DispatcherTaskExecutor
        │
        ▼
PluginObservationDispatcher
        │
        ▼
PluginObservationExecutor
        │
        ▼
Plugin.execute()
        │
        ▼
ObservationEngine
        │
        ▼
ObservationExportPipeline
        │
        ▼
POST /api/observations
```

Chaque étape possède une responsabilité unique.

---

# Synchronisation avec Ohana-Vision

Avant de démarrer les observations, l'Agent transmet un snapshot complet de l'infrastructure à Vision.

Le snapshot contient :

- les nœuds ;
- les services ;
- les équipements ;
- les liens ;
- les layouts ;
- les positions `column` / `row` sur la grille.

Vision reste responsable de la conversion de cette grille en coordonnées de rendu.

Le comportement est le suivant :

1. l'Agent tente d'envoyer le snapshot ;
2. tant que Vision ne répond pas, le scheduler d'observation reste arrêté ;
3. une nouvelle tentative est effectuée toutes les 10 secondes ;
4. après acceptation du snapshot, les observations démarrent ;
5. le snapshot est renvoyé toutes les 5 minutes ;
6. si Vision devient indisponible après le démarrage, chaque observation est
   conservée dans une outbox SQLite et rejouée dans l'ordre dès son retour ;
7. le scheduler continue ses contrôles pendant cette indisponibilité.

Configuration :

```yaml
vision:
  enabled: true
  observation_url: http://127.0.0.1:8000/api/observations
  infrastructure_url: http://127.0.0.1:8000/api/infrastructure
  timeout_seconds: 5.0
  infrastructure_retry_seconds: 10.0
  infrastructure_refresh_seconds: 300.0
  outbox_path: /var/lib/ohana-agent/vision-outbox.db
  outbox_retry_seconds: 10.0
```

L'identifiant immuable de chaque observation rend le rejeu idempotent côté
Vision. L'outbox n'est supprimée qu'après un accusé de réception HTTP valide.

---

# Configuration

## Application

```text
config/shikamaru.yaml
```

Ce fichier configure notamment :

- l'environnement ;
- la journalisation ;
- MQTT ;
- les plugins ;
- l'export vers Vision ;
- les temporisations de synchronisation.

## Infrastructure

```text
config/infrastructure.yaml
```

Exemple de service :

```yaml
services:
  - id: dns-primary
    name: DNS principal
    type: dns
    node: infra-01
    port: 53
```

Exemple de position logique :

```yaml
topology:
  layouts:
    - id: ohana-house-physical
      label: Carte physique Ohana-House
      kind: physical
      positions:
        internet:
          column: 0
          row: 1
        freebox:
          column: 1
          row: 1
```

## Plugin DHCP

```text
config/plugins/dhcp.yaml
```

```yaml
enabled: true
check_service_active: true
timeout: 3.0
interval_seconds: 60

policy:
  maximum_pool_usage_percent: 90.0
```

Le service DHCP du nœud déclaré par `administration.dhcp.server_node_id` est
découvert dans `infrastructure.yaml`. Les chemins dnsmasq déjà définis dans
`shikamaru.yaml` sont réutilisés sans duplication. Le plugin produit
`dhcp.status` en vérifiant l’état local de `dnsmasq`, la plage configurée, les
baux actifs et le taux d’occupation. Il ne demande pas de bail factice et ne
modifie jamais la configuration DHCP.

La commande de contrôle `systemctl is-active dnsmasq.service` est interne à
l’Agent : l’administration graphique peut seulement activer ou désactiver ce
contrôle, pas remplacer la commande exécutée.

## Plugin DNS

```text
config/plugins/dns.yaml
```

```yaml
queries:
  - example.com
  - openai.com

timeout: 2.0
retries: 1
```

Tous les services de type `dns` déclarés dans `infrastructure.yaml` sont
découverts automatiquement. Une modification réalisée depuis Vision remplace
immédiatement les tâches DNS : les services ajoutés commencent à produire des
observations et les services supprimés ne sont plus interrogés.

## Plugin NTP

```text
config/plugins/ntp.yaml
```

```yaml
timeout: 2.0
retries: 1
interval_seconds: 60

policy:
  maximum_offset_ms: 1000.0
  maximum_stratum: 15
```

Les services de type `ntp` sont découverts dans `infrastructure.yaml`. Chaque
service activé produit une observation `ntp.query` contenant notamment le
décalage d'horloge, le temps aller-retour et la strate du serveur.

## Plugin MQTT

```text
config/plugins/mqtt.yaml
```

```yaml
timeout: 5.0
retries: 1
interval_seconds: 60
keepalive_seconds: 60
client_id_prefix: ohana-agent
topic_prefix: ohana/agent/check
qos: 1

authentication:
  username: null
  password: null

tls:
  enabled: false
  ca_file: null
  insecure: false
```

Les services de type `mqtt` sont découverts dans `infrastructure.yaml`. Pour
chaque broker activé, l'Agent se connecte, s'abonne à un topic temporaire,
publie un message unique et attend de recevoir ce même message. L'observation
`mqtt.roundtrip` valide ainsi la connexion, l'abonnement, la publication et la
distribution du message.

## Plugin WireGuard Freebox

```text
config/plugins/wireguard.yaml
```

Le service de type `wireguard` doit être déclaré sur le nœud Freebox avec son
adresse locale. L’Agent ouvre une session Freebox OS et contrôle que le serveur
VPN nommé `wireguard` est démarré. Il n’exécute aucune commande `wg` locale.

Exemple minimal dans `infrastructure.yaml` :

```yaml
nodes:
  - id: freebox
    name: Freebox Pop
    endpoint:
      type: ip
      address: 192.168.1.1

services:
  - id: wireguard-freebox
    name: WireGuard Freebox
    type: wireguard
    node: freebox
    enabled: true
```

L’autorisation initiale est demandée une seule fois depuis INFRA-01, après
installation du wheel :

```bash
sudo /opt/ohana-agent/venv/bin/ohana-agent-authorize-freebox \
    --url http://192.168.1.1
```

La commande utilise par défaut
`/etc/ohana-agent/plugins/wireguard.yaml`. La demande doit ensuite être
validée sur l’écran de la Freebox. Aucun dépôt source n’est nécessaire sur
INFRA-01.

## Plugin Télémétrie Home Assistant

```text
config/plugins/home-assistant-telemetry.yaml
```

L’ancien identifiant `shelly_telemetry`, ses métadonnées `power_entity_id` /
`energy_entity_id` et l’argument CLI historique restent acceptés pendant la
migration vers la configuration générique.


```yaml
enabled: true
interval_seconds: 300
maximum_age_seconds: 900
home_assistant_url: http://ha-green.ohana.lan:8123
access_token: null
access_token_environment_variable: OHANA_HOME_ASSISTANT_TOKEN
```

La connexion Home Assistant et la politique de fraîcheur restent globales. Un
contrôle est déclaré dans `infrastructure.yaml` sous la forme d'un **service**
`home_assistant_telemetry` rattaché au nœud de l'équipement :

```yaml
nodes:
  - id: shelly-cuisine
    name: Shelly cuisine
    endpoint:
      type: ip
      address: 192.168.1.40

services:
  - id: home-assistant-telemetry-cuisine
    name: Télémétrie Shelly cuisine
    type: home_assistant_telemetry
    node: shelly-cuisine
    implementation: Home Assistant
    enabled: true
    critical: false
    metadata:
      primary_entity_id: sensor.shelly_cuisine_power
      secondary_entity_id: sensor.shelly_cuisine_energy
      maximum_age_seconds: 900
```

Le champ `node` devient automatiquement le `node_id` de l'observation. Pour
chaque service activé, le plugin lit les entités Home Assistant et vérifie la
date de leur dernier rapport. Une valeur de puissance égale à zéro
reste valide si le rapport est récent ; l’observation échoue uniquement lorsque
l’entité est indisponible, invalide ou trop ancienne.

## Plugin Téléinformation

```text
config/plugins/teleinformation.yaml
```

Le mode recommandé `direct_http` ne consulte ni Home Assistant ni le broker
MQTT de HA-Green. Le fork `teleinfo2mqtt Ohana` transmet chaque trame décodée
directement à l’API d’ingestion d’Agent, en parallèle de sa publication MQTT :

```yaml
enabled: true
mode: direct_http
interval_seconds: 30
maximum_age_seconds: 30
listen_host: 0.0.0.0
listen_port: 8770
ingestion_token: null
ingestion_token_environment_variable: OHANA_TELEINFORMATION_INGESTION_TOKEN
```

Le service d’architecture identifie le compteur et la source RPI-Linky :

```yaml
services:
  - id: teleinformation
    name: Téléinformation Linky
    type: teleinformation
    node: linky-01
    implementation: teleinfo2mqtt via HTTP direct
    enabled: true
    metadata:
      meter_id: "041964385922"
      source_id: rpi-linky
      maximum_age_seconds: 30
```

Agent horodate la réception de la trame. `SINSTS` doit être présent et la
trame doit rester récente. `NTARF` doit contenir une valeur de 1 à 6 et désigne
l’index Tempo actif parmi `EASF01` à `EASF06`. Les index inactifs ne sont pas
considérés comme périmés. La capacité publiée reste
`teleinformation.freshness`.

Le mode `home_assistant` et les anciens identifiants d’entités restent acceptés
pendant la migration des installations 1.8.x et 1.9.x.

---

# Installation de développement

Prérequis : Python 3.13 ou supérieur.

```bash
python -m venv .venv
```

Sous Windows :

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[development]"
```

Sous Linux :

```bash
source .venv/bin/activate
python -m pip install -e ".[development]"
```

---

# Exécution

Pour une exécution depuis les deux dépôts Agent et Vision placés côte à côte,
créer d'abord le jeton local ignoré par Git :

```bash
python -c "import secrets; from pathlib import Path; Path('config/management.development.token').write_text(secrets.token_urlsafe(32), encoding='utf-8')"
```

Utiliser ensuite le profil de développement et l'infrastructure complète :

```bash
ohana-agent \
  --config config/shikamaru.development.yaml \
  --infrastructure config/infrastructure.example.yaml \
  --dhcp-config config/plugins/dhcp.yaml \
  --dns-config config/plugins/dns.yaml \
  --ntp-config config/plugins/ntp.yaml \
  --mqtt-config config/plugins/mqtt.yaml \
  --network-config config/plugins/network.yaml \
  --zwave-config config/plugins/zwave.yaml \
  --wireguard-config config/plugins/wireguard.yaml \
  --home-assistant-telemetry-config config/plugins/home-assistant-telemetry.yaml \
  --teleinformation-config config/plugins/teleinformation.yaml
```

Version :

```bash
ohana-agent --version
```

---

# Tests et qualité

Le code courant est validé par :

- plus de 1000 tests ;
- Ruff ;
- tests d'intégration Agent ↔ Vision ;
- démarrage dans les deux ordres ;
- perte et reprise de Vision ;
- arrêt propre pendant la boucle de synchronisation.

```bash
ruff check .
pytest -q
```

---

# État actuel

Le code courant comprend notamment :

- infrastructure déclarative ;
- topologie déclarative sur grille ;
- validation complète des références ;
- Scheduler et Dispatcher ;
- EventBus ;
- Plugin SDK et Plugin Manager ;
- plugins DHCP, DNS, NTP, MQTT, présence réseau, Z-Wave, WireGuard, Télémétrie Home Assistant et Téléinformation ;
- Observation Engine ;
- Observation Export Pipeline ;
- synchronisation persistante avec Ohana-Vision ;
- service systemd et scripts de déploiement ;
- packaging wheel et sdist.

---

# Licence

Projet distribué sous licence MIT.
