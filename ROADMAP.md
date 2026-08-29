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

**Version préparée : 1.26.11 — Réveil Katsuyu fiable.**

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
- le contrat compagnon Shizune, borné, révocable et sans voie d'exécution directe.

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

---

## Prochaines priorités

### Maintenant — Stabilisation Tsunade, Katsuyu et sauvegardes

- suivre en production les jobs créés dans la fenêtre Wake-on-LAN regroupée ;
- rendre les raisons de timeout, d'absence de worker et de réveil manqué plus
  exploitables dans les journaux et les incidents ;
- consolider les contrôles `logs.health` pour éviter les sévérités excessives ;
- documenter les chemins opérateur : diagnostic, investigation, autorisation,
  vérification et expérience.

**Statut : en consolidation.**

### Ensuite — Actions contrôlées étendues

Objectif : élargir prudemment les actions disponibles sans introduire
d'auto-réparation implicite.

- politiques explicites de remédiation par capacité ;
- nouveaux types d'actions supervisées au-delà de `dnsmasq.service` ;
- meilleure modélisation des conséquences et préconditions ;
- stratégie de retour à un état sûr après échec d'une action ;
- audit durable des autorisations humaines et des décisions Tsunade.

**Statut : à cadrer.**

### Plus tard — Écosystème multi-agents

- identité stable des Agents, workers, compagnons et sites ;
- contrats compatibles avec une vue consolidée dans Vision ;
- prévention des conflits d'identifiants ;
- enrichissement du SDK et de la documentation des capacités des plugins ;
- préparation d'une supervision multi-site sans changer la source de vérité.

**Statut : exploration.**

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
