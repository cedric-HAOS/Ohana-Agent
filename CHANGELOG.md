# CHANGELOG

Toutes les évolutions importantes d'Ohana-Agent sont documentées dans ce fichier.

Le projet suit les principes de **Semantic Versioning**.

---

# [1.2.1] — Découverte dynamique des services DNS

## Modifié

- Découverte automatique de tous les services de type `dns` depuis
  `infrastructure.yaml`.
- Suppression de la liste de services dupliquée dans `plugins/dns.yaml`.
- Création d'une tâche d'observation pour chaque couple service DNS / requête.
- Routage des observations par identifiant stable de service plutôt que par type.
- Reconfiguration immédiate des tâches DNS après une modification enregistrée
  depuis Ohana-Vision, sans redémarrage de l'Agent.
- Prise en charge de zéro, un ou plusieurs services DNS activés.

## Compatibilité

- La clé historique `services` de `dns.yaml` reste acceptée mais n'est plus
  utilisée, afin de ne pas invalider les installations existantes.

---

# [1.2.0] — Administration graphique — 2026-07-24

## Ajouté

- API d'administration locale, versionnée et protégée par jeton Bearer.
- Lecture et modification des paramètres DHCP, réservations et baux actifs.
- Validation de la configuration par `dnsmasq --test` avant rechargement.
- Écriture atomique et restauration automatique des fichiers DHCP en cas de rejet.
- Lecture, validation et écriture atomique de l'infrastructure.
- Synchronisation immédiate de l'architecture modifiée avec Ohana-Vision.
- Déclaration enrichie des services : implémentation, activation, criticité et métadonnées.
- Modèle Ohana-House complet avec DHCP, DNS, NTP, MQTT, Z-Wave,
  téléinformation et Home Assistant.

## Sécurité

- Écoute limitée à `127.0.0.1` par défaut.
- Authentification constante par secret partagé installé hors du dépôt.
- Chemins de fichiers et commandes système définis exclusivement par la
  configuration locale de l'Agent.
- Taille maximale des requêtes d'administration limitée à 1 Mio.

---

# [1.1.1] — Nommage Ohana cohérent

## Modifié

- Harmonisation du nom du projet, du package et des commandes avec `Ohana`.
- Préparation d'artefacts `ohana_agent` distincts de la release `v1.1.0`
  publiée avec l'ancien nom.
- Alignement du prérequis de développement documenté sur Python 3.13.

---

# [1.1.0] — Infrastructure et topologie synchronisées

## Ajouté

### Topologie déclarative

- Ajout de la topologie complète dans `config/infrastructure.yaml`.
- Déclaration des équipements, liens et layouts.
- Positionnement logique par cellules `column` / `row`.
- Conservation de la responsabilité du rendu et des coordonnées graphiques dans Ohana-Vision.
- Ajout des types d'équipements, de liens, de directions et de layouts alignés sur Vision.

### Contrat d'infrastructure vers Vision

- Ajout de `VisionInfrastructureMapper`.
- Transmission des nœuds, services, équipements, liens et layouts.
- Ajout de `HttpVisionClient.send_infrastructure()`.
- Envoi du snapshot par `PUT /api/infrastructure`.
- Versionnement explicite du contrat avec `schema_version`.

### Synchronisation persistante

- Première synchronisation obligatoire avant le démarrage des observations.
- Nouvelle tentative toutes les 10 secondes tant que Vision ne répond pas.
- Rafraîchissement du snapshot toutes les 5 minutes.
- Suspension du scheduler lorsque Vision devient indisponible.
- Reprise automatique après resynchronisation.
- Attentes interruptibles permettant un arrêt systemd propre.

### Validation

- Validation de l'unicité des équipements, liens et layouts.
- Validation des références entre nœuds, services et équipements.
- Validation des extrémités de liens.
- Validation des équipements positionnés.
- Rejet de plusieurs équipements dans une même cellule de grille.
- Activation du validateur d'infrastructure dans le bootstrap de production.

## Modifié

- Ohana-Agent devient la source de vérité de la définition d'infrastructure et de topologie.
- Les observations ne sont plus émises tant que Vision n'a pas accepté le snapshot courant.
- La configuration Vision comprend désormais les URL d'infrastructure et d'observation ainsi que les temporisations de retry et de refresh.
- Le bootstrap prépare le contrat de synchronisation sans effectuer d'appel réseau prématuré.

## Qualité

- 1000 tests unitaires et d'intégration.
- Validation Ruff.
- Validation réelle des quatre scénarios Agent ↔ Vision :
  - Vision démarrée avant Agent ;
  - Agent démarré avant Vision ;
  - perte et reprise de Vision ;
  - arrêt propre pendant la boucle de retry.

---

# [0.14.0] — Pipeline d'observation déclaratif

## Ajouté

### Infrastructure déclarative

* Ajout du chargement de `config/infrastructure.yaml`.
* Ajout d'un modèle de configuration typé (`InfrastructureConfig`).
* Ajout de `InfrastructureLoader`.
* Ajout de `InfrastructureBuilder`.
* Construction automatique du modèle métier `Infrastructure`.
* Validation de la cohérence des nœuds, services et endpoints.

### Configuration déclarative des plugins

* Ajout du fichier `config/plugins/dns.yaml`.
* Ajout de `DNSPluginConfig`.
* Ajout de `DNSConfigLoader`.
* Séparation entre configuration déclarative et configuration d'exécution.

### DNSConfigurationBuilder

* Ajout du composant `DNSConfigurationBuilder`.
* Construction automatique du `DNSConfig` à partir de :

  * `Infrastructure`
  * `DNSPluginConfig`
* Résolution automatique des services déclarés.
* Vérification du type des services.
* Vérification de la présence des endpoints.
* Génération automatique des serveurs DNS utilisés par le plugin.

### Pipeline d'exécution

Le pipeline complet est désormais :

```text
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

### Observation Engine

* Normalisation complète des observations.
* Publication d'événements `ObservationPublished`.
* Mise à jour automatique du runtime infrastructure.
* Export automatique des observations.

### Export Ohana-Vision

* Ajout de `VisionClient`.
* Ajout de `VisionObservationExporter`.
* Ajout de `ObservationExportPipeline`.
* Ajout de `ObservationExportHandler`.
* Sérialisation JSON standardisée des observations.

### Plugin DNS

Le plugin DNS est désormais capable de :

* charger automatiquement sa configuration ;
* résoudre les serveurs DNS depuis l'infrastructure déclarative ;
* mesurer la latence réelle des requêtes DNS ;
* produire des `ObserverResult` standardisés ;
* alimenter automatiquement le `ObservationEngine`.

Les métadonnées exportées contiennent désormais :

* hostname
* serveur DNS interrogé
* adresse IP obtenue
* erreur éventuelle

### Démonstration

Ajout d'un script de démonstration complet :

```text
scripts/demo_dns_pipeline.py
```

Le script réalise une exécution réelle :

* chargement des deux fichiers YAML ;
* résolution automatique du serveur DNS ;
* interrogation réelle du serveur DNS ;
* mise à jour du runtime ;
* génération d'une observation ;
* export vers un faux client Ohana-Vision.

Cette démonstration constitue le premier pipeline complet de bout en bout d'Ohana-Agent.

---

## Modifié

### Architecture

L'architecture est désormais entièrement orientée observations.

Les plugins ne produisent plus directement des états techniques.

Ils produisent des observations normalisées.

### Configuration DNS

Les adresses IP ne sont plus déclarées dans le plugin.

Le plugin référence désormais uniquement des identifiants de services définis dans l'infrastructure.

### Runtime

Le runtime infrastructure est automatiquement synchronisé avec les observations produites.

### Scheduler

Le Scheduler exécute désormais les plugins via le pipeline unifié d'observation.

---

## Qualité

* 851 tests unitaires et d'intégration.
* Validation Ruff.
* Typage Python.
* Architecture modulaire.
* Injection de dépendances.
* Configuration déclarative.
* Démonstration réelle de bout en bout validée.

---

# Historique

## v0.13.0

* Observation Engine.
* Infrastructure Runtime.
* Observation Export Pipeline.
* Plugin SDK unifié.
* Premier connecteur Ohana-Vision.

## v0.12.0

* Infrastructure Runtime.
* Observation Manager.
* Observation Factory.
* Observation Mapper.
* Observation Exporter.

## v0.11.0

* Plugin SDK.
* DNS Plugin.
* Capability Engine.
* Runtime Plugins.

## v0.10.0

* Scheduler.
* Dispatcher.
* EventBus.
* Runtime.

## v0.9.0

* Fondation de Shikamaru.
* Configuration.
* MQTT.
* Architecture logicielle.
* Cycle de vie de l'application.
