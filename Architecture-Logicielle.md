# Architecture logicielle

## Introduction

Ohana-Agent est construit autour d'une séparation stricte des responsabilités.

Le logiciel ne doit jamais dépendre directement d'une technologie particulière.

Il doit manipuler des concepts stables :

* capacités ;
* observations ;
* états ;
* décisions ;
* commandes ;
* événements ;
* plugins.

L'architecture logicielle garantit que les implémentations peuvent évoluer sans remettre en cause le modèle général.

---

# Vue d'ensemble

Ohana-Agent est le runtime technique et la frontière de sécurité qui héberge
plusieurs rôles fonctionnels. Il est organisé autour de quatre grands
ensembles :

```text
Ohana-Agent
│
├── Shikamaru
│   Observation et évaluation de l'état
│
├── Tsunade
│   Incidents, expertise et coordination
│
├── Plugins
│   Fournisseurs de capacités
│
└── Interfaces
    Points d'entrée et de sortie
```

---

# Shikamaru

Shikamaru est le rôle de supervision et d'observation hébergé par Ohana-Agent.

Il est responsable de :

* recevoir les observations ;
* évaluer les capacités ;
* déterminer les états ;
* publier les événements.

Shikamaru ne connaît aucune technologie externe.

Il ne connaît ni DNS, ni DHCP, ni MQTT, ni Home Assistant.

Il manipule uniquement les concepts fondamentaux du système.

---

# Tsunade

Tsunade est le rôle de coordination et d'expertise hébergé par Ohana-Agent.

Il est responsable de :

* transformer les évolutions anormales en incidents ;
* coordonner les investigations déterministes ;
* solliciter Katsuyu lorsque le traitement doit être déporté ;
* construire un diagnostic à partir de preuves bornées ;
* proposer une décision ou une réparation ;
* recueillir et tracer les validations humaines ;
* superviser l'exécution d'une opération autorisée.

Tsunade ne transforme jamais une hypothèse en fait. Ohana-Agent contrôle les
permissions et les contrats d'exécution. Shikamaru vérifie ensuite, par une
nouvelle observation, si la capacité est réellement revenue à l'état attendu.

---

# Plugins

Les plugins sont les fournisseurs de capacités.

Ils sont responsables de :

* observer des systèmes externes ;
* produire des observations ;
* recevoir des commandes ;
* exécuter des actions ;
* publier des événements techniques.

Un plugin ne décide jamais.

Il ne calcule pas l'état global d'une capacité.

Il ne coordonne pas d'autres plugins.

Il reste spécialiste d'une technologie ou d'un domaine.

---

# Interfaces

Les interfaces permettent à Ohana-Agent d'échanger avec l'extérieur.

Exemples :

* interface MQTT ;
* interface API ;
* interface CLI ;
* interface Web ;
* interface de configuration ;
* interface de journalisation.

Une interface ne contient pas de logique métier.

Elle expose ou transporte des informations produites par Shikamaru et les plugins.

---

# Flux principal

Le fonctionnement nominal suit le cycle suivant :

```text
Plugin
  │
  ▼
Observation
  │
  ▼
Shikamaru
  │
  ▼
Évaluation
  │
  ▼
État
  │
  ├── sain ────────────────────────────────┐
  │                                        │
  └── anomalie                             │
       │                                   │
       ▼                                   │
     Tsunade                               │
       │                                   │
       ▼                                   │
  Diagnostic / proposition                 │
       │                                   │
       ▼                                   │
  Validation éventuelle                    │
       │                                   │
       ▼                                   │
  Exécution autorisée                      │
       │                                   │
       └──────────► Nouvelle observation ◄─┘
```

La réussite d'une action n'est jamais supposée.

Elle est toujours confirmée par une nouvelle observation.

---

# Séparation des responsabilités

## Shikamaru observe et qualifie

Shikamaru porte la logique d'évaluation des capacités.

Il détermine :

* si une capacité est disponible ;
* si une capacité est dégradée ;
* si une évolution d'état doit être publiée.

---

## Tsunade coordonne et propose

Tsunade explique les anomalies, orchestre les investigations et propose les
suites possibles. Il ne peut pas contourner les autorisations d'Ohana-Agent.
Au départ, toute réparation exige une validation humaine explicite.

---

## Ohana-Agent autorise et exécute

Le runtime valide les schémas, les permissions et les délais. Il n'expose aucun
shell arbitraire et n'exécute que les opérations explicitement déclarées.

---

## Les plugins observent et agissent

Les plugins ne font que deux choses :

* produire des observations ;
* exécuter des commandes.

Ils ne portent aucune stratégie globale.

---

## Les interfaces exposent

Les interfaces permettent de consulter, piloter ou intégrer Ohana-Agent.

Elles ne décident pas.

Elles ne réparent pas.

Elles ne modifient pas directement l'état des capacités.

---

# État interne

L'état interne d'Ohana-Agent est construit à partir des observations.

Il ne doit jamais être déduit uniquement d'une configuration.

L'état peut concerner :

* une capacité ;
* un plugin ;
* une commande ;
* une réparation ;
* une interface ;
* l'agent lui-même.

---

# Événements

Les événements permettent de signaler les changements importants.

Exemples :

* une capacité devient disponible ;
* une capacité devient dégradée ;
* une commande est envoyée ;
* une réparation commence ;
* une réparation échoue ;
* un plugin devient indisponible.

Les événements permettent de découpler les composants.

---

# Commandes

Une commande est une demande adressée à un plugin ou à une interface.

Une commande ne garantit jamais son résultat.

Elle déclenche une action.

Le résultat est vérifié ensuite par observation.

---

# Configuration

La configuration décrit les intentions de déploiement.

Elle peut définir :

* les capacités attendues ;
* les plugins activés ;
* les seuils d'évaluation ;
* les règles de réparation ;
* les paramètres d'accès aux systèmes externes.

La configuration ne constitue jamais une preuve de fonctionnement.

---

# Journalisation

Ohana-Agent doit être observable.

Chaque décision importante doit pouvoir être expliquée.

Les journaux doivent permettre de comprendre :

* ce qui a été observé ;
* comment l'état a été évalué ;
* quelle décision a été prise ;
* quelle commande a été envoyée ;
* quel résultat a été observé ensuite.

---

# Testabilité

Chaque composant doit pouvoir être testé indépendamment.

En particulier :

* Shikamaru doit pouvoir être testé sans plugins réels ;
* Tsunade doit pouvoir être testé sans exécution réelle ni LLM ;
* un plugin doit pouvoir être testé sans infrastructure réelle ;
* les règles d'évaluation doivent pouvoir être testées avec des observations simulées ;
* les commandes doivent pouvoir être vérifiées sans action destructive.

La testabilité est une propriété fondamentale de l'architecture.

---

# Résumé

Ohana-Agent repose sur une séparation explicite :

```text
Shikamaru observe, évalue et vérifie.

Tsunade coordonne, diagnostique et propose.

Ohana-Agent autorise et exécute les opérations permises.

Les plugins observent et agissent.

Les interfaces exposent.

Les capacités constituent le contrat.
```

Cette organisation permet de construire un logiciel fiable, extensible et durable.
