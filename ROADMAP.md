# ROADMAP

## Mission

Ohana-Agent garantit les capacités attendues d'une infrastructure déclarative.
Il observe les services réels, normalise leurs états et fournit à Ohana-Vision
la définition de référence de l'infrastructure, de sa topologie et de ses
observations.

Agent reste propriétaire de la configuration, de l'exécution et des décisions
opérationnelles. Ses capacités d'administration, de diagnostic, de sauvegarde et
de remédiation sont exposées par des contrats publics, versionnés et conçus pour
revenir à un état sûr en cas d'échec.

## État actuel

**Version publiée au 10 novembre 2026 : 1.58.1**, dans la composition
Ohana-Platform 1.0.157. Le numéro courant fait foi dans `pyproject.toml` et le
[CHANGELOG](CHANGELOG.md) : cette page ne suit pas chaque release.

Depuis la 1.28.0, Agent avance avec la [roadmap commune](https://github.com/cedric-HAOS/Ohana-Platform/blob/main/ROADMAP.md)
d'Ohana-Platform, phase par phase. Les critères de sortie, leurs preuves et ce
qui reste ouvert y sont tenus à jour ; cette page résume ce que cela a changé
dans Agent.

Le code applicatif est regroupé sous `src/ohana_agent`, par domaine, et les
guides sont classés dans `docs/`. Voir [l’organisation actuelle](docs/architecture-evolution.md)
et [le contrat du cycle worker](docs/tsunade-worker-cycle.md).

Le socle actuel couvre notamment :

- l'infrastructure déclarative et sa synchronisation durable avec Vision ;
- le scheduler, le pipeline d'observation, l'outbox SQLite et le Plugin Manager ;
- l'administration locale sécurisée de l'infrastructure, du réseau, du DHCP,
  des plugins, des workers Katsuyu et des compagnons Shizune ;
- les observations DNS, NTP, MQTT, DHCP, réseau, Z-Wave, WireGuard,
  Téléinformation et télémétrie Home Assistant ;
- les plages de surveillance, l'état suspendu neutre et la présence réseau
  distincte de la santé fonctionnelle ;
- la publication MQTT Discovery vers Home Assistant ;
- les sauvegardes HAOS chiffrées vers iCloud et la sauvegarde logique chiffrée
  d'INFRA-01, sans archive persistante sur la carte microSD ;
- les jobs distribués vers Katsuyu, avec appairage TLS, suivi de worker,
  Wake-on-LAN, fenêtre de regroupement et timeouts compatibles ;
- Tsunade comme cockpit Agent de diagnostic, d'investigation et de décision ;
- les incidents persistants, les contrôles `logs.health`, les investigations de
  journaux et les analyses Katsuyu AI bornées ;
- les réparations supervisées, explicitement autorisées, vérifiées et
  enregistrables comme expérience ;
- le contrat compagnon Shizune, borné, révocable et sans voie d'exécution directe ;
- la maintenance préventive : dérives de l'hôte, sauvegardes, session iCloud,
  mises à jour du système, certificats et mises à jour Home Assistant, sans
  incident ni réparation ;
- la supervision d'Ohana par Ohana : composants de l'Agent, Vision, Katsuyu et
  Shizune ;
- le registre des restaurations déclarées et la relecture indépendante des
  archives distantes ;
- la publication des réservations DHCP dans AdGuard Home et la supervision de
  la réplication entre les deux AdGuard ;
- la lecture de l'état apt d'INFRA-01 et les demandes de mise à jour, exécutées
  par les assistants root de l'Installer ;
- la prise connectée qui alimente Bubule le temps d'un réveil.

Le détail exhaustif des versions et correctifs publiés est conservé dans le
[CHANGELOG](CHANGELOG.md).

---

## Jalons livrés

### 1.0 — Agent de production

- configuration stricte et versionnée ;
- infrastructure déclarative, scheduler, dispatcher et EventBus ;
- Plugin SDK, Plugin Manager et premier plugin DNS ;
- export HTTP vers Vision, service systemd et packaging installable.

**Statut : livré.**

### 1.1 à 1.3 — Infrastructure, administration et plugins

- Agent comme source de vérité de l'infrastructure ;
- synchronisation résiliente des équipements, liaisons, layouts et positions ;
- API locale d'administration protégée ;
- gestion graphique de l'infrastructure, du réseau, du DHCP et des plugins ;
- reconfiguration et test immédiat avec restauration en cas d'échec.

**Statut : livré.**

### 1.4 à 1.10 — Observations spécialisées

- présence réseau `network.reachable`, ICMP et confirmation ARP locale ;
- observations DHCP, Z-Wave, WireGuard, NTP, MQTT et télémétrie Home Assistant ;
- Téléinformation Linky via Home Assistant puis réception HTTP directe ;
- cibles IPv4, noms d'hôte et noms DNS résolus au moment du contrôle ;
- plages horaires de surveillance et état suspendu neutre.

**Statut : livré.**

### 1.11 et 1.12 — Stabilité opérationnelle et livraison durable

- administration NetworkManager avec helper privilégié restreint ;
- confirmation et rollback réseau ;
- découverte Z-Wave et synthèse Home Assistant contextualisée ;
- outbox SQLite écrite avant envoi, rejeu ordonné et poursuite hors Vision ;
- identifiants immuables transmis au premier niveau des contrats.

**Statut : livré.**

### 1.13 et 1.14 — Sauvegardes HAOS et INFRA-01

- sauvegardes HAOS complètes et chiffrées vers iCloud ;
- secrets conservés côté Agent et rotation après validation distante ;
- sauvegarde logique chiffrée d'INFRA-01 et contrat de reconstruction Installer ;
- sauvegarde des configurations Agent, Vision, dnsmasq et chrony ;
- contrôles tmpfs, manifeste, versions Agent/Vision et erreurs structurées.

**Statut : livré.**

### 1.15 à 1.18 — Workers Katsuyu et sauvegarde distribuée

- protocole HTTPS dédié aux workers Katsuyu ;
- appairage temporaire validé par Tsunade/Vision et confiance TLS épinglée ;
- jobs déterministes `backup.compress`, `backup.encrypt` et `backup.verify` ;
- worker `AVAILABLE`, `UNAVAILABLE` ou `WAKING` avec capacités déclarées ;
- Wake-on-LAN sans shell et réveil ciblé avant les jobs distribués.

**Statut : livré.**

### 1.19 à 1.21 — Incidents Tsunade et santé des journaux

- inférence Katsuyu structurée et contexte borné ;
- incidents persistants dédupliqués par équipement, service et capacité ;
- catalogue fini d'investigations déterministes et résultats journalisés ;
- contrôle configurable `logs.health_check` pour HA-01, LINKY-01 et ZWAVE-01 ;
- anomalies de journaux groupées sans conservation des journaux bruts.

**Statut : livré.**

### 1.22 à 1.23 — Expertise, mémoire et réparations supervisées

- cycle Tsunade déterministe avec recours facultatif à Katsuyu AI ;
- hypothèses, preuves, contradictions, investigations proposées et confiance ;
- diagnostics et réparations réussies conservés après confirmation explicite ;
- premier contrat de réparation supervisée `restart_service` pour dnsmasq ;
- contrôle immédiat des journaux et investigation complémentaire bornée.

**Statut : livré.**

### 1.24 — Shizune et robustesse des sauvegardes

- contrat compagnon Shizune avec association explicite et session révocable ;
- synthèse Konoha, demandes/réponses Tsunade et activité récente ;
- notifications APNs facultatives et non bloquantes ;
- snapshot Vision compact avec retries SQLite ;
- erreurs de sauvegarde distribuée localisées avant compression.

**Statut : livré.**

### 1.25 et 1.26 — Wake-on-LAN piloté par Katsuyu

- adresse MAC WOL annoncée durablement par Katsuyu ;
- migration contrôlée de l'identité `katsuyu-bubule` ;
- API de politique Wake-on-LAN effective et réveil de test explicite ;
- diagnostics opérateur qui demandent Katsuyu même si le cycle automatique
  resterait en surveillance ;
- timeouts prolongés pour les jobs automatiques créés pendant la fenêtre de
  regroupement, afin d'attendre le réveil planifié de Katsuyu.

**Statut : livré.**

### 1.27 à 1.29 — Investigations en lecture seule et stabilisation de Tsunade

- code regroupé par domaine et investigations complémentaires autorisées ;
- investigations en lecture seule lancées automatiquement ;
- configuration et contrôles Supervisor, diagnostic Téléinformation déterministe ;
- preuves des réévaluations conservées, niveaux de diagnostic, sûreté des preuves.

**Statut : livré (Phase 1).**

### 1.30 à 1.37 — Réparations supervisées

- registre de plugins, serveur aiohttp et découpage des gros modules ;
- corrélation entre incidents, sans cause affirmée ;
- catalogue fini de réparations : dnsmasq, Mosquitto, teleinfo2mqtt, Z-Wave JS
  et chrony, chacune avec ses préconditions, son risque et sa vérification ;
- refus et report d'une réparation, vérification immédiate après exécution ;
- causes d'échec explicites, cascade DNS, incidents de journaux significatifs.

**Statut : livré (Phase 2).**

### 1.38 à 1.41 — Mémoire, prévention et supervision d'Ohana

- expérience des réparations réussies et résolution manuelle déclarée ;
- maintenance préventive et surveillance de la session iCloud ;
- composants de l'Agent, Vision, Katsuyu et Shizune observés comme le reste ;
- durcissement des phases 1 à 5.

**Statut : livré (Phases 3 à 5).**

### 1.42 à 1.44 — Katsuyu expliqué et synthèse Shizune

- journaux par composant, bruit accepté, statistiques et classement des réparations ;
- cycles de réveil journalisés avec leur raison, Wake-on-LAN mesuré, reprise
  bornée des travaux interrompus, veto d'arrêt rapporté par Katsuyu ;
- services essentiels et journaux par équipement dans la synthèse compagnon.

**Statut : livré ; essais réels des Phases 6 et 7 différés.**

### 1.45 à 1.48 — Réservations DNS et AdGuard

- noms des réservations DHCP publiés dans `ohana.lan` vers AdGuard Home ;
- autorisations Katsuyu et Shizune exportées dans la sauvegarde d'INFRA-01 ;
- capacité de synchronisation AdGuard et supervision centrée sur la réplication.

**Statut : livré.**

### 1.49 à 1.53 — Sauvegardes restaurables et observations stables

- registre des restaurations déclarées, sauvegarde jamais testée identifiable ;
- relecture indépendante des archives distantes, session iCloud, sauvegarde à
  l'heure, compte rendu d'`ohana restore` ;
- retard de télémétrie confirmé sur deux contrôles avant incident ;
- mémoire de l'Agent et de Vision mesurée séparément ;
- investigation de journaux étendue une fois à 24 heures ;
- purge quotidienne des observations déjà traitées.

**Statut : livré ; Phases 9 et 10 ouvertes (mesures et restauration réelle).**

### 1.54 à 1.58 — Maintenance du système et alimentation de Bubule

- état apt d'INFRA-01 et demandes d'actualisation ou de mise à jour ;
- échéances : correctifs de sécurité, certificats TLS, mises à jour Home Assistant ;
- diagnostic de mémoire à la demande et mémoire rendue après la sonde Z-Wave ;
- échec DNS confirmé sur deux contrôles, registre unique des règles préventives ;
- alerte Z-Wave sur la dernière connexion d'un équipement ;
- plugin « Prise connectée » : Ohana ne coupe que la prise qu'il a allumée.

**Statut : livré.**

---

## Prochaines priorités

Les priorités sont celles de la [roadmap commune](https://github.com/cedric-HAOS/Ohana-Platform/blob/main/ROADMAP.md#priorité-immédiate).
Ce qui suit est la part d'Agent, relevée le 10 novembre 2026.

### Maintenant — Mesurer avant de développer

- confirmer par la règle `memory_growth` l'effet du correctif mémoire de la
  1.55.0 ;
- compter les incidents de fraîcheur et de présence par semaine, et trouver
  pourquoi le DNS de LINKY-01 vacille (Phase 9) ;
- déclarer une restauration HAOS réelle dans le registre (Phase 10) ;
- mesurer l'effet de la nouvelle gravité des incidents (critique seulement pour
  ce que l'infrastructure déclare critique, décidée le 10 novembre 2026) sur ce
  qui alerte réellement, une fois déployée.

**Statut : en cours.**

### Ensuite — Actions contrôlées étendues

Objectif : élargir prudemment les actions disponibles sans introduire
d'auto-réparation implicite.

Livré depuis la 1.31 : cinq réparations au catalogue, avec préconditions,
conséquences, risque, vérification et journal des autorisations.

- politiques explicites de remédiation par capacité ;
- nouvelle réparation seulement après une panne réelle qui la justifie.

**Statut : à cadrer.**

### Plus tard — Écosystème multi-agents

- identité stable des Agents, workers, compagnons et sites ;
- contrats compatibles avec une vue consolidée dans Vision ;
- prévention des conflits d'identifiants ;
- enrichissement du SDK et de la documentation des capacités des plugins ;
- préparation d'une supervision multi-site sans changer la source de vérité.

**Statut : abandonné.**

---

## Principes durables

Les évolutions d'Agent doivent préserver les règles suivantes :

1. une seule source de vérité pour l'infrastructure ;
2. les capacités avant les implémentations ;
3. les observations avant les hypothèses ;
4. aucun détail de rendu dans la configuration métier ;
5. des plugins indépendants du cœur ;
6. des contrats publics versionnés ;
7. aucune action sensible sans autorisation, audit et retour à un état sûr ;
8. aucun journal brut ni secret inutile dans les flux Tsunade, Katsuyu ou Shizune ;
9. un comportement testable et reproductible.
