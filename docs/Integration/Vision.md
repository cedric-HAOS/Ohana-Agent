# Vision

## Pourquoi Ohana-Agent existe

Une infrastructure fiable n'est pas uniquement une infrastructure qui fonctionne. C'est une infrastructure dont les capacités sont garanties dans le temps.

Les logiciels évoluent, les machines tombent en panne, les configurations dérivent et les dépendances changent. Pourtant, les capacités attendues doivent rester disponibles.

Ohana-Agent observe ces capacités et fournit à l'écosystème Ohana une définition fiable de l'infrastructure qui les porte.

---

## Mission

Ohana-Agent :

- charge et valide l'infrastructure déclarative ;
- décrit les nœuds, services, équipements et liens ;
- observe les capacités réelles ;
- normalise les résultats ;
- synchronise l'infrastructure avec Ohana-Vision ;
- poursuit l'observation locale même sans Vision et met en file durable les
  observations dont la livraison échoue.

Il ne se limite pas à vérifier qu'un processus est démarré. Il vérifie que la capacité attendue est réellement disponible.

---

## Source de vérité

La définition de référence réside dans :

```text
config/infrastructure.yaml
```

Elle contient :

- les nœuds ;
- les services ;
- les endpoints ;
- les équipements de topologie ;
- les liens ;
- les layouts ;
- les positions logiques sur une grille.

Ohana-Vision ne conserve pas une seconde configuration métier. Il reçoit un snapshot normalisé, le valide, le projette et l'affiche.

---

## Relation avec Ohana-Vision

```text
Ohana-Agent
    │
    ├── PUT /api/infrastructure
    │       nœuds, services, équipements,
    │       liens et grille
    │
    └── POST /api/observations
            états, latences et métadonnées
```

Depuis la Phase 5, les sondes ne dépendent pas de la disponibilité de Vision :

1. l'Agent tente de synchroniser le snapshot puis démarre le scheduler, même si
   cette tentative échoue ;
2. les sondes et la santé hôte continuent localement ;
3. les échecs de livraison alimentent la file SQLite durable ;
4. le snapshot est rafraîchi périodiquement, avec de nouvelles tentatives en cas
   d'échec, sans arrêter les observations ;
5. le retour de Vision permet la reprise de livraison et le rattrapage de la file.

Vision peut recevoir une observation avant le snapshot. Distinguer observation,
synchronisation de topologie et fraîcheur de livraison dans le diagnostic.
Voir [le contrat d'intégration Vision](https://github.com/cedric-HAOS/Ohana-Vision/blob/main/INTEGRATION.md).

---

## Principes fondateurs

### Les capacités avant les implémentations

Une capacité peut être assurée par plusieurs implémentations. L'Agent garantit la capacité et ne dépend pas d'une technologie particulière.

### Les observations avant les hypothèses

Une configuration ne constitue pas une preuve de fonctionnement. Seule une observation réelle permet d'évaluer une capacité.

### Une seule source de vérité

L'infrastructure et la topologie sont déclarées une seule fois dans l'Agent puis transmises à Vision par un contrat public versionné.

### La structure avant le rendu

L'Agent transmet une position logique `column` / `row`. Vision reste propriétaire des marges, espacements, dimensions de canvas et coordonnées graphiques.

### Les plugins avant le code spécifique

Chaque capacité doit pouvoir être ajoutée sans modifier le cœur du logiciel.

### L'autonomie contrôlée

L'Agent privilégie la reprise automatique, mais toute future action de remédiation devra être explicite, traçable et sûre.

---

## Ambition

Construire un agent simple, fiable, observable, extensible et résilient, capable de garantir durablement les capacités d'une infrastructure moderne.

> Ohana-Agent ne surveille pas des logiciels. Il garantit des capacités.
