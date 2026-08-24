# MQTT

## Introduction

MQTT est une interface de communication d'Ohana-Agent.

Son rôle est de transporter les informations entre Ohana-Agent et les systèmes externes.

MQTT ne fait pas partie du moteur de décision.

Il ne contient aucune logique métier.

Il constitue uniquement un moyen d'échanger des concepts internes avec le monde extérieur.

---

# Position dans l'architecture

Ohana-Agent est construit autour de concepts indépendants des technologies.

Shikamaru manipule exclusivement :

* des capacités ;
* des observations ;
* des états ;
* des décisions ;
* des commandes ;
* des événements.

MQTT permet simplement de transporter ces informations.

```text
                 Ohana-Agent

                  Shikamaru
        (Moteur de décision)

                     │

        Concepts du domaine
                     │

          Interface MQTT
                     │

              Broker MQTT
                     │

         Systèmes externes
```

Le moteur de décision ne dépend jamais de MQTT.

---

# Objectifs

L'interface MQTT poursuit plusieurs objectifs.

* Diffuser les observations.
* Publier les états calculés.
* Notifier les événements.
* Recevoir des commandes.
* Faciliter l'intégration avec les systèmes tiers.

---

# Responsabilités

L'interface MQTT est responsable de :

* transformer les concepts internes en messages MQTT ;
* transformer les messages MQTT en commandes internes ;
* garantir une représentation cohérente des données ;
* masquer les détails du protocole au reste du logiciel.

Elle n'est jamais responsable :

* de calculer les états ;
* de prendre des décisions ;
* d'évaluer une capacité ;
* de coordonner les plugins.

Ces responsabilités appartiennent exclusivement à Shikamaru.

---

# Informations transportées

L'interface MQTT peut transporter plusieurs familles d'informations.

## Observations

Les observations décrivent des faits mesurés.

Exemples :

* une résolution DNS réussit ;
* une API répond ;
* une température est reçue.

Les observations sont produites par les plugins.

---

## États

Les états représentent l'évaluation réalisée par Shikamaru.

Ils décrivent le niveau de garantie d'une capacité.

Exemples :

* AVAILABLE
* DEGRADED
* UNAVAILABLE

Les états ne sont jamais calculés à partir de MQTT.

Ils sont uniquement publiés.

---

## Événements

Les événements signalent un changement significatif.

Exemples :

* capacité disponible ;
* capacité dégradée ;
* réparation démarrée ;
* réparation terminée ;
* plugin chargé.

Ils permettent aux systèmes externes de suivre la vie d'Ohana-Agent.

---

## Commandes

Les commandes reçues via MQTT sont converties en commandes internes.

Leur traitement est identique à celui de toute autre commande.

Le protocole de transport n'influence jamais la logique métier.

---

# Découplage

MQTT constitue une frontière entre Ohana-Agent et son environnement.

Le remplacement de MQTT par un autre protocole ne nécessite aucune modification de :

* Shikamaru ;
* la logique métier ;
* les plugins.

Seule l'interface de communication est concernée.

---

# Fiabilité

Les mécanismes de transport (QoS, conservation des messages, reconnexions, etc.) relèvent de l'implémentation de l'interface MQTT.

Ils ne modifient jamais les principes d'architecture du système.

La garantie d'une capacité repose toujours sur les observations et l'évaluation
de Shikamaru. Une décision coordonnée par Tsunade ne remplace jamais cette
preuve observable.

---

# Sécurité

MQTT peut s'appuyer sur les mécanismes de sécurité du broker :

* authentification ;
* chiffrement ;
* contrôle d'accès.

Ces mécanismes appartiennent à l'infrastructure de communication.

Ils restent indépendants du moteur de décision.

---

# Évolution

L'architecture permet :

* d'ajouter de nouveaux messages sans modifier Shikamaru ;
* de remplacer MQTT par une autre interface ;
* d'utiliser plusieurs interfaces simultanément (MQTT, API, Web, CLI...).

Le modèle métier reste inchangé.

---

# Documentation associée

Ce document décrit le rôle architectural de MQTT.

Les aspects techniques sont définis dans des documents dédiés :

* MQTT-Convention.md
* API-Convention.md
* Plugin-Convention.md

Cette séparation garantit la stabilité de l'architecture tout en permettant aux conventions d'évoluer indépendamment.

---

# Principes

MQTT respecte les principes suivants :

* il transporte les informations ;
* il ne contient aucune logique métier ;
* il est interchangeable ;
* il reflète les concepts internes d'Ohana-Agent ;
* il reste indépendant des capacités qu'il transporte.

---

# Résumé

MQTT est une interface de communication.

Shikamaru observe et évalue l'état des capacités.

Tsunade coordonne les incidents et propose les décisions.

Ohana-Agent contrôle l'autorisation des opérations.

Les plugins produisent les observations et exécutent les commandes.

Les capacités demeurent le cœur du modèle d'Ohana-Agent.
