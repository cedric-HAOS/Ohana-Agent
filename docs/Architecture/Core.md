# CORE — Architecture d'Ohana-Agent

## Vision

Ohana-Agent est le moteur d'observation de l'écosystème Ohana.

Sa mission n'est pas de superviser des équipements.

Sa mission est de garantir que les **capacités** définies par l'architecture de référence restent disponibles dans le temps.

Une capacité représente un service rendu par l'infrastructure :

* DNS
* DHCP
* MQTT
* NTP
* Internet
* WireGuard
* Home Assistant
* Sauvegardes
* etc.

Chaque capacité est observée de manière indépendante, puis transformée en une observation normalisée.

Ces observations constituent le langage commun entre **Ohana-Agent** et **Ohana-Vision**.

---

# Les quatre couches de l'architecture

L'architecture est volontairement découpée en quatre niveaux.

```text id="4ngwud"
Infrastructure
        │
        ▼
Plugins
        │
        ▼
Observation Engine
        │
        ▼
Exporteurs
```

Chaque couche possède une responsabilité unique.

---

# 1. Infrastructure

L'infrastructure constitue la source de vérité.

Elle est décrite de manière déclarative dans :

```text id="3j53g8"
config/infrastructure.yaml
```

Elle décrit :

* les nœuds ;
* les services ;
* les endpoints ;
* les ports ;
* les relations entre les composants.

Exemple :

```yaml id="5c0ubg"
services:
  - id: dns-primary
    type: dns
    node: zwave-01
```

Une seule description existe.

Aucun plugin ne possède sa propre copie des informations d'infrastructure.

---

# 2. Plugins

Chaque capacité est implémentée par un plugin indépendant.

Exemple :

```text id="9d6q2z"
plugins/
    dns/
    mqtt/
    dhcp/
    ntp/
```

Chaque plugin possède :

* une configuration déclarative ;
* un runtime ;
* des statistiques ;
* une logique métier ;
* une méthode `execute()` commune.

Tous les plugins implémentent le même contrat.

Ils produisent tous un `ObserverResult`.

Ils ne connaissent ni Ohana-Vision, ni l'interface Web, ni Home Assistant.

---

# Configuration déclarative des plugins

Chaque plugin possède son propre fichier YAML.

Exemple :

```text id="9c0xq7"
config/plugins/dhcp.yaml
config/plugins/dns.yaml
```

Le plugin ne référence ni une adresse IP ni une liste de services.

Les services DNS sont découverts automatiquement parmi les services de type
`dns` déclarés dans l'infrastructure. Le fichier du plugin conserve uniquement
les paramètres communs aux observations :

```yaml id="dgw7ae"
queries:
  - example.com
  - openai.com
```

Le composant `DNSConfigurationBuilder` transforme ensuite l'infrastructure et
les paramètres du plugin en configuration d'exécution. Lorsqu'une modification
d'infrastructure est enregistrée par l'API d'administration, les tâches DNS
sont remplacées sans redémarrer Agent.

---

# 3. Observation Engine

Le cœur du système est l'Observation Engine.

Tous les plugins convergent vers lui.

Le pipeline est entièrement standardisé.

```text id="wjlm4u"
Plugin.execute()
        │
        ▼
ObserverResult
        │
        ▼
ObserverResultMapper
        │
        ▼
InfrastructureObservationMapper
        │
        ▼
ObservationEngine
        │
        ▼
ObservationPublished
```

Le moteur :

* met à jour le runtime ;
* normalise les observations ;
* publie un événement ;
* déclenche les exporteurs.

Les plugins n'ont aucune connaissance de cette mécanique.

---

# 4. Exporteurs

Une observation peut être exportée vers plusieurs destinations.

Aujourd'hui :

```text id="vb1prk"
VisionObservationExporter
```

Demain :

```text id="r2ry5w"
VisionObservationExporter
MQTTObservationExporter
HomeAssistantExporter
FileExporter
DatabaseExporter
WebhookExporter
```

Tous utilisent le même modèle d'observation.

---

# Pipeline d'exécution

Le Scheduler est désormais directement connecté au moteur d'observation.

```text id="lzy8wj"
Scheduler
        │
DispatcherTaskExecutor
        │
PluginObservationDispatcher
        │
PluginObservationExecutor
        │
Plugin.execute()
        │
ObserverResult
        │
ObservationEngine
        │
ObservationPublished
        │
ObservationExportPipeline
        │
VisionObservationExporter
        │
Ohana-Vision
```

Ce pipeline constitue désormais le chemin d'exécution officiel d'Ohana-Agent.

---

# Runtime

Deux runtimes coexistent.

## InfrastructureRuntime

Il représente l'état courant de l'infrastructure.

Il est automatiquement mis à jour par les observations.

Il ne contient aucune logique métier.

## Plugin Runtime

Chaque plugin conserve son propre état interne :

* statistiques ;
* historique ;
* informations spécifiques au protocole.

Ces données restent locales au plugin.

---

# Séparation des responsabilités

L'architecture suit une séparation stricte.

| Composant          | Responsabilité                         |
| ------------------ | -------------------------------------- |
| Infrastructure     | Décrire les services                   |
| Plugin             | Vérifier une capacité                  |
| Observation Engine | Transformer un résultat en observation |
| Runtime            | Conserver l'état courant               |
| Export Pipeline    | Diffuser les observations              |
| Ohana-Vision      | Présenter les observations             |

Aucun composant ne remplit plusieurs rôles.

---

# Principes d'architecture

Les décisions majeures sont les suivantes :

* une seule description de l'infrastructure ;
* aucune adresse IP dans les plugins ;
* plugins indépendants ;
* exécution unifiée via `Plugin.execute()` ;
* observations normalisées ;
* exporteurs découplés ;
* architecture événementielle ;
* injection de dépendances ;
* configuration déclarative.

Ces principes permettent d'ajouter de nouveaux plugins sans modifier le cœur du système.

---

# État actuel

Le cœur d'Ohana-Agent comprend désormais :

* Infrastructure déclarative ;
* InfrastructureBuilder ;
* InfrastructureRuntime ;
* Scheduler ;
* Dispatcher ;
* EventBus ;
* Plugin SDK ;
* Plugin Manager ;
* DNS Plugin ;
* DNSConfigurationBuilder ;
* Observation Engine ;
* Observation Export Pipeline ;
* VisionObservationExporter ;
* démonstration complète de bout en bout ;
* intégration prête pour Ohana-Vision.

---

# Vision à long terme

Ohana-Agent a vocation à devenir un moteur générique d'observation des infrastructures.

Chaque nouveau plugin devra uniquement répondre à une question :

> **La capacité attendue est-elle disponible ?**

La manière dont cette réponse est produite importe peu.

Une fois transformée en observation normalisée, elle pourra être exploitée de manière identique par Ohana-Vision, Home Assistant ou tout autre système consommateur.
