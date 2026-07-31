# ADR-0025 — Gestion de la mémoire

## Statut

Accepté

## Date

2026-07-08

## Contexte

Ohana-Agent dispose déjà d’un noyau stable : cycle de vie, services cœur, runtime MQTT, auto-réparation, capacités et scheduler.

Le Sprint 7 introduit une nouvelle brique fondamentale : la mémoire.

L’objectif n’est pas de créer une mémoire “intelligente” complexe dès maintenant, mais de fournir une base simple, testable et extensible permettant à l’agent de conserver des informations utiles pendant son exécution.

## Décision

Ohana-Agent introduit un composant dédié :

```text
MemoryManager
```

Le `MemoryManager` devient le point d’entrée unique pour lire, écrire, mettre à jour et supprimer des informations mémorisées.

La mémoire est structurée autour de plusieurs scopes :

```text
MemoryScope.RUNTIME
MemoryScope.SESSION
MemoryScope.PERSISTENT
```

Chaque élément mémorisé est représenté par une entrée typée :

```text
MemoryEntry
```

Une entrée mémoire contient au minimum :

```text
key
value
scope
created_at
updated_at
metadata
```

## Architecture retenue

```text
Application
    └── MemoryManager
            ├── RuntimeMemory
            ├── SessionMemory
            ├── PersistentMemory
            ├── MemoryEntry
            ├── MemoryScope
            ├── MemoryPolicy
            └── MemoryStatistics
```

## Principes

La mémoire doit rester :

* simple ;
* explicite ;
* typée ;
* testable ;
* indépendante du transport MQTT ;
* indépendante du scheduler ;
* indépendante des capacités métier ;
* extensible vers une future mémoire persistante plus avancée.

## Responsabilités du MemoryManager

Le `MemoryManager` est responsable de :

```text
set(key, value, scope)
get(key)
delete(key)
clear(scope)
exists(key)
keys(scope)
```

Il gère également :

```text
hits
misses
created entries
updated entries
deleted entries
expired entries
```

## Ce qui est volontairement exclu

Cette ADR ne couvre pas encore :

* mémoire vectorielle ;
* embeddings ;
* base de données externe ;
* chiffrement ;
* synchronisation distribuée ;
* résolution automatique de conflits ;
* mémoire conversationnelle longue durée ;
* apprentissage automatique.

Ces sujets pourront faire l’objet d’ADR futures.

## Conséquences positives

Cette décision apporte :

* une mémoire unifiée ;
* une API simple ;
* une séparation claire entre mémoire volatile et mémoire persistante ;
* une meilleure observabilité ;
* une base solide pour les workflows futurs ;
* une meilleure capacité d’auto-diagnostic ;
* une préparation naturelle au raisonnement contextuel.

## Conséquences négatives

Cette décision ajoute :

* de nouveaux modules ;
* une nouvelle responsabilité cœur ;
* des tests supplémentaires ;
* une gestion plus stricte de la sérialisation ;
* une attention particulière à la taille mémoire.

## Alternatives étudiées

### Utiliser un simple dictionnaire global

Rejeté.

Trop implicite, difficile à tester et difficile à faire évoluer.

### Ajouter la mémoire directement dans Application

Rejeté.

Cela aurait alourdi `Application` et cassé la séparation des responsabilités.

### Utiliser directement un fichier JSON partout

Rejeté.

La persistance doit rester une option de stockage, pas le modèle mémoire principal.

## Décision finale

Ohana-Agent adopte un `MemoryManager` central, basé sur des entrées typées et des scopes explicites.

Cette approche devient la base officielle de la mémoire interne de l’agent à partir du Sprint 7.
