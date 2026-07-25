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

# v1.3.0 — Capacités supplémentaires

Objectifs envisagés :

- reprise plus fine après erreurs transitoires ;
- métriques internes de synchronisation ;
- diagnostics de connectivité avec Vision ;
- visibilité sur l'état des plugins ;
- amélioration de l'endurance et des tests ARM64/Linux ;
- journalisation d'exploitation enrichie.

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
