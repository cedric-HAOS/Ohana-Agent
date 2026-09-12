# États

## Introduction

Une capacité n'est jamais simplement « en fonctionnement » ou « en panne ».

Elle évolue au cours de son cycle de vie.

Les états permettent à Shikamaru de représenter cette évolution et de prendre des décisions cohérentes.

Les états sont indépendants des technologies et des implémentations.

Ils décrivent uniquement le niveau de garantie d'une capacité.

---

# Les états fondamentaux

Toutes les capacités utilisent les mêmes états.

## UNKNOWN

La capacité n'a pas encore été suffisamment observée.

Aucune conclusion ne peut être tirée.

Cet état est utilisé :

* au démarrage ;
* après le chargement d'un plugin ;
* lorsqu'aucune observation n'est disponible.

---

## AVAILABLE

Les observations démontrent que la capacité est garantie.

Le système fonctionne conformément aux attentes.

Aucune action n'est nécessaire.

---

## DEGRADED

La capacité reste disponible.

Cependant, les observations indiquent une perte de qualité ou de performance.

Exemples :

* temps de réponse élevé ;
* erreurs occasionnelles ;
* capacité partiellement assurée.

Une dégradation n'implique pas nécessairement une réparation immédiate.

---

## UNAVAILABLE

Les observations ne permettent plus de garantir la capacité.

La capacité est considérée comme indisponible.

Shikamaru peut décider :

* de continuer les observations ;
* de lancer une réparation ;
* de demander une intervention humaine.

---

## REPAIRING

Une réparation est en cours.

Aucune conclusion ne doit être tirée tant que de nouvelles observations ne sont pas disponibles.

Cet état est transitoire.

---

# Transitions

Les transitions entre états sont pilotées exclusivement par Shikamaru.

Les plugins ne changent jamais directement un état.

Ils produisent uniquement des observations.

---

# Diagramme d'états

```text
UNKNOWN
    │
    ▼
AVAILABLE
    │
    ▼
DEGRADED
    │
    ▼
UNAVAILABLE
    │
    ▼
REPAIRING
   ├──────────────┐
   ▼              ▼
AVAILABLE   UNAVAILABLE
```

Les transitions exactes dépendent des règles d'évaluation de chaque capacité.

---

# Les observations pilotent les états

Une observation ne modifie jamais directement un état.

Elle alimente le moteur d'évaluation.

C'est Shikamaru qui décide si une transition est nécessaire.

---

# Les états ne décrivent pas les plugins

Les états représentent le niveau de garantie d'une capacité.

Ils ne décrivent pas l'état interne d'un plugin.

Un plugin peut être opérationnel alors que la capacité qu'il fournit est indisponible.

Inversement, plusieurs plugins peuvent garantir ensemble une même capacité.

---

# États techniques

Les composants internes du système (plugins, interfaces, commandes) peuvent posséder leurs propres états techniques.

Ces états sont indépendants des états des capacités.

Ils ne doivent jamais être confondus.

---

# Persistance

Les états peuvent être conservés afin de :

* comprendre l'évolution d'une capacité ;
* analyser un incident ;
* mesurer la disponibilité ;
* produire des statistiques.

La persistance ne modifie jamais la logique de décision.

---

# Principes

Les états respectent les principes suivants :

* un état résulte toujours d'observations ;
* un état n'est jamais déduit d'une configuration ;
* un état est calculé par Shikamaru ;
* un état peut évoluer au fil des observations ;
* un état est indépendant de toute technologie.

---

# Résumé

Les plugins observent.

Shikamaru évalue.

Les capacités changent d'état.

Les décisions découlent de ces états.
