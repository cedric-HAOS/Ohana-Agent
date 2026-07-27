# ROADMAP

## Vision

Ohana-Agent garantit les capacités attendues d'une infrastructure déclarative. Il observe les services réels, normalise leurs états et fournit à Ohana-Vision la définition de référence de l'infrastructure et de sa topologie.

---

# Versions publiées

## v1.0.0 — Agent de production

**Statut : terminé.**

Principaux acquis :

- configuration stricte et versionnée ;
- infrastructure déclarative ;
- scheduler, dispatcher et EventBus ;
- Plugin SDK et Plugin Manager ;
- plugin DNS ;
- moteur d'observation ;
- export HTTP vers Ohana-Vision ;
- bootstrap de production ;
- service systemd ;
- scripts d'installation et de mise à jour ;
- packaging wheel et sdist ;
- audit final de production.

## v1.1.0 — Infrastructure et topologie synchronisées

**Statut : terminé.**

Objectifs réalisés :

- Agent propriétaire de la définition d'infrastructure ;
- topologie déclarative dans `infrastructure.yaml` ;
- équipements, liens et layouts ;
- positions logiques `column` / `row` ;
- contrat public versionné vers Ohana-Vision ;
- transmission par `PUT /api/infrastructure` ;
- validation des références et des cellules de grille ;
- première synchronisation obligatoire avant les observations ;
- nouvelle tentative toutes les 10 secondes ;
- rafraîchissement toutes les 5 minutes ;
- suspension des observations lorsque Vision est désynchronisé ;
- reprise automatique après resynchronisation ;
- tests d'intégration réels Agent ↔ Vision.

---

## v1.2.0 — Administration graphique

**Statut : terminé.**

Principaux acquis :

- API locale d'administration protégée ;
- gestion de l'infrastructure depuis Ohana-Vision ;
- gestion DHCP et réservations dnsmasq ;
- synchronisation immédiate du snapshot d'infrastructure.

## v1.2.1 — Services DNS dynamiques

**Statut : terminé.**

Principaux acquis :

- découverte de tous les services DNS depuis l'infrastructure ;
- observations distinctes pour chaque identifiant de service ;
- ajout et suppression de tâches DNS sans redémarrage ;
- absence de limite au nombre de services DNS déclarés.

---

# v1.3.0 — Plugins et administration

**Statut : terminé.**

Principaux acquis :

- plugins NTP et MQTT intégrés au pipeline d’observation ;
- contrat d’administration versionné des plugins ;
- inventaire fondé sur les plugins réellement enregistrés ;
- exposition des plugins DNS, NTP et MQTT ;
- activation, désactivation et modification de leur configuration ;
- reconfiguration et replanification sans redémarrage ;
- test immédiat de chaque capacité ;
- restauration automatique en cas d’échec d’application ;
- protection des secrets MQTT ;
- DHCP conservé dans son administration dédiée tant qu’il ne constitue pas un
  plugin d’observation du `PluginManager`.

---

# v1.4.0 — Présence réseau des équipements

**Statut : terminé.**

Principaux acquis :

- découverte des équipements adressables depuis la topologie ;
- observation générique `network.reachable` ;
- détection ICMP avec confirmation ARP locale ;
- répartition temporelle des contrôles pour préserver la légèreté du scheduler ;
- seuil d'échecs consécutifs avant déclaration d'absence ;
- état intermédiaire `unknown` ;
- absence d'impact sur la santé globale des capacités ;
- replanification après modification de l'infrastructure ;
- configuration et administration du plugin réseau.

---

# v1.5.0 — Observation DHCP

**Statut : terminé.**

Principaux acquis :

- plugin DHCP enregistré dans le `PluginManager` ;
- découverte des services DHCP depuis l’infrastructure ;
- observation `dhcp.status` du service dnsmasq local ;
- lecture de la plage et des baux sans allocation artificielle ;
- calcul de l’occupation de la plage et seuil de santé configurable ;
- reconfiguration, planification et test immédiat sans redémarrage ;
- commande système interne non modifiable depuis Vision ;
- maintien de l’administration DHCP dédiée pour les paramètres et réservations.

---

# v2.0.0 — Actions contrôlées

Objectif : passer progressivement de l'observation à l'action.

Pistes envisagées :

- politiques explicites de remédiation ;
- redémarrage contrôlé de services ;
- bascule de capacités redondantes ;
- exécution d'actions validées ;
- audit et traçabilité des actions ;
- mécanismes de sécurité et d'autorisation.

Aucune auto-réparation ne sera introduite sans contrat public, contrôle explicite et stratégie de retour à un état sûr.

---

# Principes durables

Les évolutions futures doivent préserver les règles suivantes :

1. une seule source de vérité pour l'infrastructure ;
2. les capacités avant les implémentations ;
3. les observations avant les hypothèses ;
4. aucun détail de rendu dans la configuration métier ;
5. des plugins indépendants du cœur ;
6. des contrats publics versionnés ;
7. un comportement testable et reproductible.
