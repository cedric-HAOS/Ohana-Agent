# Message Model

## Introduction

Tous les échanges d'informations d'Ohana-Agent reposent sur un modèle de message unique.

Ce modèle constitue le langage commun utilisé par l'ensemble du système.

Il est indépendant :

* du protocole de transport ;
* de l'interface utilisée ;
* de l'implémentation des plugins ;
* des technologies externes.

Chaque message échangé dans Ohana-Agent respecte ce modèle.

---

# Objectifs

Le modèle de message poursuit plusieurs objectifs :

* uniformiser tous les échanges ;
* simplifier les interfaces ;
* faciliter les tests ;
* améliorer la journalisation ;
* garantir la compatibilité entre les composants.

---

# Principe

Les concepts internes d'Ohana-Agent sont transportés dans une enveloppe commune.

Cette enveloppe est identique quel que soit le canal de communication.

Exemples :

* MQTT
* REST
* WebSocket
* CLI
* Journalisation
* Fichiers d'export
* Tests unitaires

Tous utilisent exactement le même modèle.

---

# Structure générale

Chaque message possède la structure suivante :

```json
{
  "version": 1,
  "id": "uuid",
  "timestamp": "2026-07-07T12:34:56Z",
  "source": "...",
  "category": "...",
  "type": "...",
  "payload": { }
}
```

---

# Métadonnées

## version

Version du modèle de message.

Elle garantit la compatibilité entre les producteurs et les consommateurs.

---

## id

Identifiant unique du message.

Il permet :

* la traçabilité ;
* le débogage ;
* le suivi des traitements.

---

## timestamp

Date et heure de création du message.

Toutes les dates sont exprimées au format UTC ISO-8601.

---

## source

Origine logique du message.

Exemples :

* shikamaru
* plugin.dns
* plugin.homeassistant
* api
* mqtt

La source décrit un composant logique.

Jamais une machine.

---

## category

Famille du message.

Valeurs prévues :

* observation
* state
* event
* command
* health

Cette liste constitue le cœur du modèle.

---

## type

Nature précise du message.

Exemples :

* dns.available
* dns.lookup
* repair.started
* plugin.loaded

Le type permet aux consommateurs de comprendre le contenu du message.

---

## payload

Contenu métier.

Sa structure dépend de la catégorie et du type.

Le payload ne contient aucune information de transport.

---

# Principes

Tous les messages respectent les règles suivantes.

## Une seule responsabilité

Un message décrit un seul fait.

Il ne mélange jamais plusieurs événements.

---

## Immutabilité

Un message ne doit jamais être modifié après sa création.

Toute évolution produit un nouveau message.

---

## Auto-description

Chaque message contient toutes les informations nécessaires à sa compréhension.

Aucune information externe n'est requise.

---

## Indépendance

Le modèle est indépendant :

* de MQTT ;
* de REST ;
* du stockage ;
* des logs.

---

## Compatibilité

Les nouveaux champs doivent être ajoutés de manière compatible.

Les suppressions sont exceptionnelles.

---

# Cycle de vie

Le même message peut suivre plusieurs chemins.

```text
Observation
      │
      ▼
Message
      │
      ├── MQTT
      ├── REST
      ├── WebSocket
      ├── Log
      ├── Test
      └── Archive
```

Le contenu reste identique.

Seul le transport change.

---

# Bénéfices

Un modèle unique permet :

* un seul format JSON ;
* une seule documentation ;
* une seule stratégie de tests ;
* une seule stratégie de journalisation ;
* une forte cohérence du système.

---

# Résumé

Les concepts représentent le métier.

Le Message Model représente leur langage.

Les interfaces transportent ce langage.
