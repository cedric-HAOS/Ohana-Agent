# CHANGELOG

Toutes les évolutions importantes d'Ohana-Agent sont documentées dans ce fichier.

Le projet suit les principes de **Semantic Versioning**.

---

# [1.11.2] — Résolution des serveurs DNS nommés — 2026-07-31

## Corrigé

- Résolution préalable des noms d’hôte utilisés comme serveurs DNS explicites
  afin de fournir à `dnspython` l’adresse IP qu’il exige, sans modifier le nom
  de serveur publié dans les observations.

## Qualité

- Tests de résolution des serveurs DNS nommés et des erreurs de résolution.
- Version du paquet alignée sur `1.11.2`.

---

# [1.11.1] — Application fiable des réservations DHCP — 2026-07-31

## Ajouté

- Helper privilégié `ohana-agent-dhcp-reload-helper` chargé d’appliquer les
  changements DHCP sans donner au processus Agent un accès direct à la base des
  baux dnsmasq.

## Corrigé

- Suppression ciblée des anciens baux qui contredisent une nouvelle réservation
  par adresse MAC ou par adresse IPv4 avant le redémarrage de dnsmasq.
- Lecture correcte des serveurs DNS NetworkManager lorsque `nmcli` les sépare
  avec le caractère `|`.
- Autorisation du helper NetworkManager restreint par sudo depuis l’unité
  `ohana-agent.service`.

## Qualité

- Validation du format de la demande privilégiée, des adresses MAC et du
  redémarrage systématique de dnsmasq même si la purge échoue.
- Version du paquet alignée sur `1.11.1`.

---

# [1.11.0] — Lot C : administration réseau sécurisée — 2026-07-30

## Ajouté

- Lecture de l’état NetworkManager de l’hôte Agent : interface, connexion,
  adresse IPv4, passerelle, DNS et mode statique ou DHCP.
- API d’administration `system.network.*` pour préparer, appliquer, confirmer
  ou restaurer une configuration réseau.
- Helper privilégié limité `ohana-agent-network-helper`, sans droit root
  général pour le processus Agent.
- Application des changements avec sauvegarde et retour automatique entre 30
  et 300 secondes si la nouvelle configuration n’est pas confirmée.

## Sécurité

- Une seule transaction réseau peut être en attente à la fois.
- Les interfaces, adresses, passerelles, DNS et identifiants de transaction sont
  validés avant toute commande NetworkManager.
- Les instantanés de restauration sont conservés dans un répertoire root en
  permissions `0700`, avec fichiers `0600`.

## Qualité

- Tests des modèles réseau, du repository, des routes HTTP et du refus d’une
  seconde transaction en attente.
- Version du paquet alignée sur `1.11.0`.

---

# [1.10.0] — Lot B : Téléinformation directe et plages de surveillance — 2026-07-30

## Ajouté

- Récepteur HTTP authentifié dédié aux trames décodées envoyées directement par
  `teleinfo2mqtt`, sans dépendance à Home Assistant ni au broker de HA-Green.
- Mode `direct_http` du plugin Téléinformation, avec identification de la source
  et du compteur Linky, contrôle de `SINSTS`, `NTARF` et de l’index Tempo actif.
- Plages horaires facultatives sur les équipements, avec fuseau horaire, jours
  actifs et délai de démarrage.
- État `suspended` publié lors de la suspension planifiée et exclu des incidents
  et de la dégradation de la santé globale.

## Compatibilité

- Le mode historique Home Assistant reste accepté pour les configurations
  Téléinformation existantes.
- Une seule observation de suspension est publiée par période continue afin de
  ne pas remplir inutilement l’historique.

## Qualité

- Tests du récepteur HTTP, de son authentification, du stockage des trames, du
  contrôle direct Tempo et des plages horaires, y compris les périodes passant
  minuit et le délai de démarrage.
- Version interne du plugin Téléinformation portée à `0.2.0`.
- Version du paquet alignée sur `1.10.0`.

---

# [1.9.0] — Lot A : télémétrie générique et cibles réseau — 2026-07-30

## Ajouté

- Plugin `home_assistant_telemetry` et capacité `home_assistant.telemetry.freshness`.
- Prise en charge des noms d’hôte et noms DNS pour les équipements.
- Adresse résolue exposée dans les observations de présence réseau.

## Modifié

- Shelly Telemetry devient **Télémétrie Home Assistant**.
- Les services et configurations `shelly_telemetry` restent acceptés pendant la migration.
- Nouvel argument `--home-assistant-telemetry-config`, avec ancien argument conservé comme alias.

---

# [1.8.1] — Fraîcheur Tempo contextuelle — 2026-07-29

## Corrigé

- `NTARF` n’est plus considéré comme une télémétrie devant être actualisée en
  continu : sa valeur reste validée, mais son ancienneté est normale entre les
  bascules de 6 h et 22 h.
- Seuls `SINSTS` et l’index Tempo désigné par la valeur courante de `NTARF`
  doivent présenter une mesure récente.
- Les cinq index Tempo inactifs restent disponibles dans les métadonnées sans
  dégrader le service lorsque leur horodatage est ancien.
- Une grâce de 30 secondes évite une fausse alerte lorsque `NTARF` bascule juste
  avant la première mise à jour du nouvel index actif.
- Version interne du plugin Téléinformation portée à `0.1.1`.

## Qualité

- Tests de non-régression ajoutés pour un `NTARF` ancien, des index inactifs
  anciens, un index actif ancien et la courte transition de période Tempo.
- Version du paquet alignée sur `1.8.1`.

# [1.8.0] — Téléinformation Linky — 2026-07-29

## Ajouté

- Nouveau plugin `teleinformation` et capacité
  `teleinformation.freshness`.
- Contrôle de la chaîne Linky → série → `teleinfo2mqtt` → MQTT → Home
  Assistant à partir des entités `SINSTS` et `NTARF`.
- Lecture facultative des six index Tempo `EASF01` à `EASF06`.
- Interprétation automatique de la couleur Bleue, Blanc ou Rouge et de la
  période HC ou HP à partir de `NTARF`.
- Configuration et test immédiat depuis l’administration des plugins.
- Déclaration par service dans `infrastructure.yaml`, avec une tâche périodique
  par compteur Linky.

## Qualité

- Tests unitaires du client Home Assistant, de la fraîcheur, du mapping Tempo,
  du builder, du plugin et du parcours scheduler → Vision.
- Version du paquet alignée sur `1.8.0`.

# [1.7.5] — Exécution planifiée Shelly Telemetry — 2026-07-29

## Corrigé

- Les tâches périodiques Shelly utilisent désormais la commande
  `shelly_telemetry.freshness`, conforme à l’identifiant enregistré du plugin.
- Le dispatcher ne cherche plus un plugin inexistant nommé `shelly` lors des
  exécutions automatiques.
- Les observations programmées sont de nouveau publiées vers Vision et peuvent
  alimenter l’état du service et de l’équipement.
- Version interne du plugin Shelly Telemetry portée à `0.2.1`.

## Qualité

- Test de non-régression complété sur la commande générée et son exécution
  réelle à travers le dispatcher et le pipeline d’observation.
- 1 158 tests réussis après construction du wheel et du sdist.
- Version du paquet alignée sur `1.7.5`.

# [1.7.4] — Replanification Shelly Telemetry — 2026-07-29

## Corrigé

- La reconfiguration du plugin Shelly Telemetry reconstruit désormais ses
  services à partir de l’infrastructure d’exécution courante.
- L’application d’une architecture contenant des services
  `shelly_telemetry` recrée immédiatement les tâches correspondantes.
- Les tâches périodiques Shelly restent cohérentes après modification de la
  connexion Home Assistant ou de l’intervalle du plugin.

## Qualité

- Test de non-régression ajouté pour deux services Shelly ajoutés par
  l’architecture puis replanifiés par la configuration globale.
- 1 158 tests réussis après construction du wheel et du sdist.
- Version du paquet alignée sur `1.7.4`.

# [1.7.3] — Shelly Telemetry par service — 2026-07-28

## Ajouté

- Publication MQTT du résumé de santé global sur `ohana/health/summary`.
- MQTT Discovery Home Assistant pour le score, l'état global, les incidents
  critiques, les alertes, les services dégradés ou indisponibles, les capacités
  sans observation récente et la date de dernière évaluation.
- Topic de disponibilité `ohana/status` avec Last Will MQTT.
- Paramètres Home Assistant intégrés au plugin MQTT : activation, Discovery,
  préfixes et battement périodique.

## Corrigé

- Shelly Telemetry est désormais déclaré comme un service rattaché au nœud de
  l’équipement, au lieu d’utiliser des métadonnées particulières sur la carte.
- Les observations ciblent le service déclaré, ce qui permet à la criticité du
  service d’alimenter naturellement la santé, les alertes et les incidents.
- L’entité de puissance, l’entité d’énergie facultative et l’âge maximal sont
  configurés dans les métadonnées de chaque service `shelly_telemetry`.

## Qualité

- Version du paquet alignée sur `1.7.3`.
- 1157 tests réussis.

# [1.7.2] — Z-Wave JS Server WebSocket — 2026-07-28

## Corrigé

- Le plugin `zwave` utilise désormais le protocole WebSocket de Z-Wave JS
  Server exposé par Home Assistant sur le port `3000`.
- Le contrôle attend l’initialisation complète du pilote Z-Wave avant de
  produire une observation saine.
- Les installations autonomes exposant encore `/health/zwave` en HTTP ou HTTPS
  restent prises en charge explicitement par les métadonnées du service.
- La sélection Shelly Telemetry et les identifiants d’entités Home Assistant
  sont désormais définis sur chaque équipement de la topologie, et non dans la
  configuration globale du plugin.
- Les observations Shelly ciblent maintenant directement l’équipement concerné.

## Ajouté

- Versions du serveur et du pilote, identifiant Home ID et nombre de nœuds dans
  les métadonnées de l’observation `zwave.status`.
- Version d’Ohana-Agent dans la réponse `/v1/capabilities` de l’API
  d’administration, pour affichage dans Vision.
- Dépendance d’exécution `zwave-js-server-python`.

## Qualité

- Version du paquet alignée sur `1.7.2`.
- Tests dédiés au protocole WebSocket, au port `3000` par défaut et au contrat
  de version d’administration.
- 1150 tests réussis.

---

# [1.7.1] — Commande d’autorisation Freebox — 2026-07-28

## Corrigé

- Le script d’autorisation Freebox n’est plus dépendant du dépôt source sur INFRA-01.
- La configuration WireGuard de production est utilisée par défaut depuis
  `/etc/ohana-agent/plugins/wireguard.yaml`.

## Ajouté

- Commande installée `ohana-agent-authorize-freebox`.
- Module d’exécution inclus dans le wheel sous
  `plugins.wireguard.authorize_freebox`.
- Tests du stockage du jeton après validation et du refus d’autorisation.
- Vérification de la présence du nouvel exécutable dans les métadonnées du wheel.

## Qualité

- Version du paquet et version applicative Freebox alignées sur 1.7.1.
- 1144 tests réussis.
- Wheel et archive source Ohana-Agent 1.7.1 construites et vérifiées.

---

# [1.7.0] — Freebox WireGuard et Shelly Telemetry — 2026-07-27

## Corrigé

- Le plugin `wireguard` n’inspecte plus une interface locale sur INFRA-01.
- L’état du serveur WireGuard est désormais lu directement dans Freebox OS à partir du service WireGuard déclaré sur le nœud Freebox.

## Ajouté

- Authentification à l’API Freebox OS avec `app_id`, `app_token` et session temporaire.
- Contrôle de l’état `started` du serveur VPN `wireguard` et remontée du nombre de connexions lorsqu’il est disponible.
- Script `scripts/authorize_freebox.py` pour demander l’autorisation sur l’écran de la Freebox et enregistrer le jeton.
- Plugin `shelly_telemetry` et capacité `shelly.telemetry.freshness`.
- Vérification de la fraîcheur des capteurs de puissance et d’énergie Shelly via l’API REST de Home Assistant.
- Distinction entre une puissance valide de `0 W` et une télémétrie qui n’est plus remontée.
- Masquage et conservation des jetons Freebox et Home Assistant dans l’administration des plugins.
- Nouvel argument `--shelly-telemetry-config` et intégration au service systemd.

## Qualité

- 1140 tests unitaires, d’intégration, HTTP et de packaging réussis.
- Wheel et archive source 1.7.0 construites et vérifiées.

---

# [1.6.0] — Z-Wave et WireGuard — 2026-07-27

## Ajouté

- Plugin intégré `zwave` et capacité `zwave.status`.
- Interrogation de l’état de connexion de Z-Wave JS UI via son point de santé.
- Découverte des services Z-Wave depuis `infrastructure.yaml`, avec port 8091 par défaut.
- Plugin intégré `wireguard` et capacité `wireguard.status`.
- Inspection locale des interfaces WireGuard avec `wg show` et contrôle optionnel de l’âge du dernier échange d’un pair.
- Reconfiguration à chaud, planification et test immédiat des deux plugins depuis Vision.
- Nouveaux arguments `--zwave-config` et `--wireguard-config`.

## Sécurité

- Le plugin WireGuard exécute uniquement la commande fixe `wg show <interface> latest-handshakes`.
- Aucune clé privée WireGuard n’est lue ni exposée dans les observations.
- La vérification TLS du plugin Z-Wave reste activée par défaut.

## Qualité

- 1131 tests unitaires, d’intégration, HTTP et de packaging réussis.
- Tests dédiés aux chargeurs, constructeurs, politiques, reprises et contrats d’observation.
- Service systemd, scripts de déploiement et artefacts de distribution mis à jour.

---

# [1.5.0] — Observation DHCP — 2026-07-27

## Ajouté

- Plugin intégré `dhcp` et capacité `dhcp.status`.
- Découverte automatique des services de type `dhcp` depuis
  `infrastructure.yaml`.
- Vérification locale de l’état `dnsmasq` sans demande de bail artificielle.
- Réutilisation du lecteur dnsmasq existant pour la configuration et les baux.
- Lecture de la plage IPv4 configurée et des baux dnsmasq actifs.
- Exclusion des baux expirés, des adresses hors plage et des doublons.
- Calcul du nombre d’adresses disponibles et du taux d’occupation de la plage.
- Seuil configurable transformant une occupation excessive en observation
  indisponible.
- Reconfiguration à chaud, reconstruction des tâches et test immédiat depuis
  l’administration des plugins.
- Nouvel argument `--dhcp-config`, fichier de configuration et intégration au
  service systemd.
- Déclaration du service `dhcp-primary` dans l’infrastructure de production.
- La surveillance de présence réseau peut être activée ou désactivée pour
  chaque équipement depuis
  `topology.devices[].metadata.network_presence_enabled`.

## Sécurité

- La commande `systemctl is-active dnsmasq.service` est définie dans le code et
  ne peut pas être remplacée par une requête d’administration.
- Le plugin lit les fichiers dnsmasq mais ne les modifie jamais.
- L’administration existante des paramètres et réservations DHCP reste séparée
  du plugin d’observation.

## Qualité

- 1115 tests unitaires, d’intégration, HTTP et de packaging réussis.
- Construction et installation validées des artefacts wheel et sdist 1.5.0.

## Contrat d’observation

- `capability_id` : `dhcp.status` ;
- `service_id` : identifiant du service DHCP ;
- métadonnées : état du service, plage, taille du pool, baux actifs, baux
  expirés et taux d’occupation.

# [1.4.0] — Présence réseau des équipements — 2026-07-27

## Ajouté

- Plugin intégré `network` et capacité `network.reachable`.
- Découverte automatique des équipements de topologie disposant d'une adresse
  directe ou rattachés à un nœud avec endpoint IP.
- Vérification légère par ICMP, complétée par la table ARP locale lorsqu'un
  équipement ne répond pas au ping.
- Répartition des contrôles sur tout l'intervalle pour éviter une rafale de
  requêtes lorsque plusieurs équipements sont déclarés.
- Validation des adresses IP portées directement par les équipements de
  topologie.
- Délai configurable, retries immédiats et seuil de plusieurs cycles échoués
  avant de déclarer un équipement indisponible.
- État `unknown` pendant la confirmation d'une absence ou lorsque la commande
  système de vérification n'est pas disponible.
- Observations de présence séparées de la santé globale des services et de
  l'infrastructure.
- Reconfiguration automatique des tâches après une modification de la
  topologie depuis Ohana-Vision.
- Administration, test immédiat sans modification de l'historique des échecs,
  configuration CLI et unité systemd du plugin réseau.

## Qualité

- 1088 tests unitaires, d'intégration, HTTP et de packaging réussis.
- Construction validée des artefacts wheel et sdist 1.4.0.

## Contrat d'observation

- `capability_id` : `network.reachable` ;
- `service_id` : identifiant de l'équipement ;
- `node_id` : nœud rattaché, ou identifiant de l'équipement en son absence ;
- métadonnées : adresse, méthode, tentatives, échecs consécutifs et seuil.

# [1.3.0] — Administration des plugins — 2026-07-27

## Ajouté

- Contrat public d’administration des plugins avec inventaire, lecture,
  modification et test immédiat.
- Exposition des états de cycle de vie, de planification, d’exécution et de la
  dernière erreur connue.
- Activation et désactivation persistantes des plugins DNS, NTP et MQTT.
- Reconfiguration à chaud et reconstruction des tâches du scheduler sans
  redémarrage de l’Agent.
- Écriture atomique avec restauration de la configuration précédente en cas
  d’échec d’application.
- Masquage du mot de passe MQTT et conservation du secret lorsque le champ est
  laissé vide par Vision.
- Tests immédiats `dns.resolve`, `ntp.query` et `mqtt.roundtrip`.
- Capacités `plugins.read`, `plugins.write` et `plugins.test`.
- Client SNTP natif sans dépendance Python supplémentaire.
- Découverte automatique des services de type `ntp` dans
  `infrastructure.yaml`.
- Observation `ntp.query` avec décalage d'horloge, temps aller-retour, strate,
  version NTP et indicateur de synchronisation.
- Politique de santé configurable par décalage maximal et strate maximale.
- Reconfiguration immédiate des tâches NTP après modification de
  l'infrastructure depuis Ohana-Vision.
- Configuration, CLI, service systemd, packaging et tests d'intégration dédiés.
- Plugin `mqtt.roundtrip` réalisant une connexion, un abonnement, une
  publication et la réception du message de test.
- Découverte automatique des services de type `mqtt` depuis
  `infrastructure.yaml`.
- Authentification MQTT, QoS et TLS configurables sans exposer les secrets dans
  les observations.
- Reconfiguration immédiate des tâches MQTT après modification de
  l'infrastructure depuis Ohana-Vision.
- Dépendance réseau `paho-mqtt` limitée à la couche d'observation MQTT, sans
  modification du transport MQTT interne du noyau.

## Qualité

- 1070 tests unitaires, d’intégration, HTTP et de packaging réussis.
- Construction validée des artefacts wheel et sdist 1.3.0.

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
