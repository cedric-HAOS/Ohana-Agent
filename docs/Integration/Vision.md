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
- transmet les observations uniquement lorsque Vision possède la définition courante.

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

L'ordre est garanti :

1. Vision accepte le snapshot d'infrastructure ;
2. l'Agent démarre les observations ;
3. l'Agent rafraîchit périodiquement le snapshot ;
4. en cas de perte de Vision, les observations sont suspendues ;
5. elles reprennent après resynchronisation.

Cette règle évite qu'une observation soit reçue sans définition correspondante du nœud ou du service.

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
