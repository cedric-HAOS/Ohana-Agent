# Ohana-Agent

> Garantir les capacités de l'infrastructure, plutôt que surveiller des équipements.

Ohana-Agent est le moteur d'observation de l'écosystème Ohana. Il charge une infrastructure déclarative, exécute les plugins de capacité, produit des observations normalisées et les transmet à Ohana-Vision.

Depuis la version 1.1.0, l'Agent est la source de vérité de la topologie :
nœuds, services, équipements, liens et positions logiques sur la grille. La
version 1.2.0 ajoute leur administration graphique sécurisée depuis Vision.
La version 1.2.1 synchronise automatiquement les observations DNS avec les
services ajoutés, modifiés ou supprimés depuis cette administration. Le
développement courant ajoute la même découverte dynamique pour la capacité NTP.

---

# Administration graphique

Ohana-Agent expose une API locale permettant à Ohana-Vision de modifier
l'infrastructure et le serveur DHCP sans édition manuelle de YAML.

- l'API écoute par défaut sur `127.0.0.1:8765` ;
- chaque requête exige le jeton partagé installé dans
  `/etc/ohana-agent/management.token` ;
- l'Agent demeure seul propriétaire des fichiers de configuration ;
- une configuration DHCP n'est conservée que si `dnsmasq --test` l'accepte ;
- toute écriture est atomique et restaurée automatiquement en cas d'échec.

Le contrat et le modèle de sécurité sont détaillés dans
[`docs/Administration.md`](docs/Administration.md).

---

# Principes

## Infrastructure déclarative

L'infrastructure est décrite une seule fois dans :

```text
config/infrastructure.yaml
```

Ce fichier définit notamment :

- l'identité de l'infrastructure ;
- les nœuds et leurs endpoints ;
- les services ;
- les équipements de topologie ;
- les liens ;
- les positions logiques sur la grille.

Les plugins référencent les services par identifiant et ne dupliquent pas les adresses IP.

## Plugins indépendants

Chaque capacité est fournie par un plugin spécialisé. Les plugins DNS et NTP
utilisent le même pipeline d'observation standardisé.

```text
plugins/
├── dns/
└── ntp/
```

Chaque plugin possède sa configuration et produit des observations standardisées.

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
6. si Vision devient indisponible, les observations sont suspendues jusqu'à la resynchronisation.

Configuration :

```yaml
vision:
  enabled: true
  observation_url: http://127.0.0.1:8000/api/observations
  infrastructure_url: http://127.0.0.1:8000/api/infrastructure
  timeout_seconds: 5.0
  infrastructure_retry_seconds: 10.0
  infrastructure_refresh_seconds: 300.0
```

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

```bash
ohana-agent \
  --config config/shikamaru.yaml \
  --infrastructure config/infrastructure.yaml \
  --dns-config config/plugins/dns.yaml \
  --ntp-config config/plugins/ntp.yaml \
  --mqtt-config config/plugins/mqtt.yaml
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
- plugins DNS et NTP ;
- Observation Engine ;
- Observation Export Pipeline ;
- synchronisation persistante avec Ohana-Vision ;
- service systemd et scripts de déploiement ;
- packaging wheel et sdist.

---

# Licence

Projet distribué sous licence MIT.
