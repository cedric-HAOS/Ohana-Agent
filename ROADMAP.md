# ROADMAP

## Mission

Ohana-Agent garantit les capacités attendues d'une infrastructure déclarative.
Il observe les services réels, normalise leurs états et fournit à Ohana-Vision
la définition de référence de l'infrastructure, de sa topologie et de ses
observations.

Agent reste propriétaire de la configuration et de l'exécution. Ses capacités
d'administration sont exposées par des contrats publics, versionnés et conçus
pour revenir à un état sûr en cas d'échec.

## État actuel

**Version publiée : 1.12.1 — Santé hôte et services redondants.**

Le socle actuel couvre notamment :

- l'infrastructure déclarative et sa synchronisation avec Vision ;
- le scheduler, le pipeline d'observation et le Plugin Manager ;
- l'administration locale sécurisée de l'infrastructure, du réseau, du DHCP et
  des plugins ;
- les observations DNS, NTP, MQTT, DHCP, réseau, Z-Wave, WireGuard,
  Téléinformation et télémétrie Home Assistant ;
- les plages de surveillance et l'état suspendu neutre ;
- la publication MQTT Discovery vers Home Assistant ;
- la santé de la machine hôte et l'agrégation des services redondants dans
  Home Assistant ;
- la livraison durable et ordonnée des observations vers Vision.

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

### 1.1 — Infrastructure et topologie synchronisées

- Agent comme source de vérité de l'infrastructure ;
- équipements, liaisons, layouts et positions logiques ;
- contrat public vers Vision et synchronisation résiliente ;
- suspension puis reprise automatique lors d'une désynchronisation initiale.

**Statut : livré.**

### 1.2 — Administration graphique

- API locale d'administration protégée ;
- gestion de l'infrastructure depuis Vision ;
- gestion DHCP et réservations dnsmasq ;
- découverte dynamique des services DNS et replanification sans redémarrage.

**Statut : livré.**

### 1.3 — Plugins et administration

- intégration de NTP et MQTT au pipeline d'observation ;
- inventaire des plugins réellement enregistrés ;
- lecture, activation, modification, reconfiguration et test immédiat ;
- restauration de la configuration en cas d'échec et protection des secrets.

**Statut : livré.**

### 1.4 — Présence réseau des équipements

- découverte des équipements adressables ;
- observation générique `network.reachable` ;
- détection ICMP avec confirmation ARP locale ;
- seuil d'échecs, état inconnu et absence d'incidence sur la santé globale.

**Statut : livré.**

### 1.5 — Observation DHCP

- plugin DHCP intégré au Plugin Manager ;
- observation non intrusive de dnsmasq, de sa plage et de ses baux ;
- calcul de l'occupation et seuil de santé configurable ;
- reconfiguration et test immédiat sans redémarrage de l'Agent.

**Statut : livré.**

### 1.6 et 1.7 — Z-Wave, WireGuard et télémétrie

- observations Z-Wave et WireGuard ;
- intégration Freebox WireGuard ;
- télémétrie Shelly par service ;
- replanification dynamique et exécution selon les services déclarés.

**Statut : livré.**

### 1.8 — Téléinformation Linky

- plugin `teleinformation` intégré au Plugin Manager ;
- contrôle contextuel de la fraîcheur de SINSTS, NTARF et des index Tempo ;
- lecture des index EASF01 à EASF06 ;
- administration, test immédiat et publication vers Vision.

**Statut : livré.**

### 1.9 — Télémétrie générique et cibles réseau

- remplacement compatible de Shelly Telemetry par
  `home_assistant_telemetry` ;
- acceptation des noms d'hôte et noms DNS dans l'infrastructure ;
- résolution au moment du contrôle avec conservation de la cible déclarée.

**Statut : livré.**

### 1.10 — Téléinformation directe et plages de surveillance

- réception HTTP directe des données de `teleinfo2mqtt` ;
- indépendance fonctionnelle vis-à-vis de Home Assistant pour Linky ;
- plages horaires héritées par la présence réseau et les services ;
- état suspendu neutre et publication unique de la transition.

**Statut : livré.**

### 1.11 — Administration réseau et stabilité opérationnelle

- lecture et configuration NetworkManager avec helper privilégié restreint ;
- sauvegarde, confirmation et rollback automatique ;
- application fiable des réservations DHCP ;
- découverte des équipements Z-Wave et publication de leur état ;
- stabilisation des suspensions planifiées et de la présence réseau Windows ;
- synthèse Home Assistant stable et alertes contextualisées par équipement et
  capacité.

**Statut : livré.**

### 1.12 — Livraison durable vers Vision

- outbox SQLite écrite avant la première tentative d'envoi ;
- rejeu ordonné après une indisponibilité ou un redémarrage ;
- identifiant immuable et message transmis au premier niveau du contrat ;
- poursuite des observations lorsque Vision devient indisponible après la
  synchronisation initiale.

**Statut : livré.**

---

## Prochaines priorités

### Maintenant — Consolidation de la version 1.12

- exposer des diagnostics exploitables sur la taille et l'âge du backlog ;
- cadrer la rétention et la maintenance de l'outbox ;
- renforcer les scénarios de reprise après interruption prolongée ;
- conserver une publication Home Assistant concise et stable lors des
  dégradations.

**Statut : en consolidation.**

### Ensuite — Actions contrôlées

Objectif : passer progressivement de l'observation à l'action sans introduire
d'auto-réparation implicite.

- politiques explicites de remédiation ;
- redémarrage contrôlé de services ;
- bascule de capacités redondantes ;
- exécution d'actions validées et suivi de leur résultat ;
- audit, autorisation et stratégie de retour à un état sûr.

**Statut : à cadrer pour une future version majeure.**

### Plus tard — Écosystème multi-agents

- identité stable des Agents et des sites ;
- contrats compatibles avec une vue consolidée dans Vision ;
- prévention des conflits d'identifiants ;
- enrichissement du SDK et de la documentation des capacités des plugins.

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
8. un comportement testable et reproductible.
