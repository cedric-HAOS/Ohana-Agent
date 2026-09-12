# Concepts fondamentaux

## Introduction

Ce document définit les concepts fondamentaux utilisés par Ohana-Agent.

Chaque décision d'architecture, chaque plugin et chaque ligne de code doivent s'appuyer sur ces définitions.

Un concept ne décrit pas une implémentation.

Il décrit une idée stable, indépendante des technologies utilisées.

---

# Le modèle d'Ohana-Agent

Ohana-Agent repose sur un principe simple.

Une infrastructure est définie par les capacités qu'elle fournit.

Le rôle de l'agent est de garantir ces capacités.

Pour cela, il suit en permanence le cycle suivant :

```text
Capacité
      │
      ▼
Observation
      │
      ▼
Évaluation
      │
      ▼
Décision
      │
      ▼
Action
      │
      ▼
Nouvelle observation
```

Tout le logiciel est construit autour de ce cycle.

---

# Mission

La mission représente la raison d'être du logiciel.

Elle est unique.

Elle ne change pas selon les machines ou les plugins.

Mission :

Garantir les capacités définies par l'architecture d'Ohana-House.

---

# Capacité

Une capacité représente un service attendu de l'infrastructure.

Une capacité est indépendante de son implémentation.

Exemples :

- Résolution DNS
- Attribution DHCP
- Publication MQTT
- Accès Home Assistant
- Synchronisation NTP
- Sauvegarde
- Accès distant

Une capacité peut être assurée par une ou plusieurs implémentations.

L'agent ne garantit jamais une implémentation.

Il garantit une capacité.

---

# Observation

Une observation est un fait mesurable.

Une observation ne contient aucune interprétation.

Exemples :

- une requête DNS répond ;
- un bail DHCP est distribué ;
- un ping réussit ;
- une API répond ;
- une température est reçue.

Une observation est toujours objective.

---

# État

Un état représente la situation actuelle d'une capacité.

Exemples :

- Inconnu
- Disponible
- Dégradé
- Indisponible
- En réparation

Un état est obtenu par l'évaluation des observations.

---

# Évaluation

L'évaluation transforme des observations en état.

Elle applique les règles définies pour une capacité.

Exemple :

Si trois résolutions DNS consécutives échouent,

alors

la capacité DNS devient indisponible.

---

# Décision

Une décision détermine l'action à entreprendre.

Elle dépend :

- de l'état actuel ;
- de l'historique ;
- des règles de fonctionnement.

Une décision peut être :

- ne rien faire ;
- continuer à observer ;
- déclencher une réparation ;
- demander une intervention humaine.

---

# Action

Une action est une opération réalisée par l'agent.

Exemples :

- redémarrer un service ;
- envoyer une commande MQTT ;
- appeler une API ;
- publier un événement ;
- enregistrer un journal.

Une action est toujours le résultat d'une décision.

---

# Plugin

Un plugin ajoute une ou plusieurs capacités à l'agent.

Chaque plugin est autonome.

Le noyau ne connaît jamais les détails d'une technologie.

Le noyau dialogue uniquement avec les capacités exposées par les plugins.

---

# Contrat

Un contrat définit les engagements entre le noyau et un plugin.

Il décrit :

- les observations produites ;
- les commandes acceptées ;
- les états possibles ;
- les capacités fournies.

Tous les plugins respectent le même modèle de contrat.

---

# Événement

Un événement représente un changement observable.

Exemples :

- une capacité devient disponible ;
- un plugin démarre ;
- une réparation commence ;
- une réparation échoue.

Les événements permettent aux composants de communiquer sans dépendance directe.

---

# Commande

Une commande est une demande adressée à un plugin.

Elle ne garantit jamais le résultat.

Elle demande uniquement l'exécution d'une action.

Le résultat est confirmé ultérieurement par de nouvelles observations.

---

# Garantie

Une capacité est garantie lorsque les observations démontrent qu'elle est disponible.

Une configuration ne constitue jamais une garantie.

Seule l'observation permet de garantir une capacité.

---

# Réparation

Une réparation est une suite d'actions visant à restaurer une capacité.

La réussite d'une réparation n'est jamais supposée.

Elle est toujours vérifiée par une nouvelle observation.

---

# Résumé

Le fonctionnement complet d'Ohana-Agent peut être résumé par une seule phrase.

Observer.

Comprendre.

Décider.

Agir.

Vérifier.