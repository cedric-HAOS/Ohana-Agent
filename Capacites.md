# Capacités

## Introduction

La mission d'Ohana-Agent est de garantir des capacités.

Une capacité représente un service attendu par l'infrastructure.

Les capacités sont indépendantes des logiciels, des machines et des protocoles qui les implémentent.

Ce document définit les familles de capacités que le logiciel est amené à garantir.

---

# Une capacité n'est pas un logiciel

Une capacité décrit ce que l'infrastructure doit fournir.

Elle ne décrit jamais comment elle est réalisée.

Par exemple :

| Ce n'est pas une capacité | C'est une capacité |
|---------------------------|--------------------|
| AdGuard | Résolution DNS |
| Mosquitto | Messagerie MQTT |
| Home Assistant | Automatisation domotique |
| WireGuard | Accès distant sécurisé |
| Raspberry Pi | Exécution d'un service |

Le logiciel garantit toujours la colonne de droite.

---

# Les familles de capacités

Les capacités sont regroupées par domaine fonctionnel.

Cette organisation permet de faire évoluer les implémentations sans modifier le modèle.

---

# Infrastructure

Ces capacités assurent le fonctionnement de base de la maison.

Exemples :

- résolution DNS ;
- attribution DHCP ;
- synchronisation temporelle ;
- connectivité réseau ;
- routage ;
- accès Internet.

La présence `network.reachable` est une observation technique complémentaire.
Elle indique qu'un équipement est visible sur le réseau, sans affirmer que ses
services ou ses capacités fonctionnelles sont disponibles. Elle n'entre donc
pas directement dans la santé globale de l'infrastructure.

---

# Communication

Ces capacités permettent aux systèmes d'échanger des informations.

Exemples :

- publication MQTT ;
- abonnement MQTT ;
- communication HTTP ;
- communication HTTPS ;
- communication WebSocket.

---

# Automatisation

Ces capacités concernent le fonctionnement de la domotique.

Exemples :

- disponibilité de Home Assistant ;
- exécution des automatisations ;
- réception des événements ;
- contrôle des équipements.

---

# Supervision

Ces capacités permettent d'observer l'infrastructure.

Exemples :

- collecte des états ;
- disponibilité des métriques ;
- journalisation ;
- alertes.

---

# Résilience

Ces capacités permettent au système de continuer à fonctionner malgré une anomalie.

Exemples :

- redondance ;
- bascule automatique ;
- redémarrage automatique ;
- restauration d'un service.

---

# Sécurité

Ces capacités protègent l'infrastructure.

Exemples :

- authentification ;
- autorisation ;
- accès distant sécurisé ;
- chiffrement des communications.

---

# Exploitation

Ces capacités facilitent l'administration du système.

Exemples :

- sauvegardes ;
- restauration ;
- mises à jour ;
- gestion de la configuration.

---

# Relations entre les capacités

Les capacités peuvent dépendre d'autres capacités.

Exemple :

```text
Automatisation
        │
        ▼
Communication MQTT
        │
        ▼
Résolution DNS
        │
        ▼
Connectivité réseau
```

Une défaillance peut donc avoir des conséquences en cascade.

Le rôle d'Ohana-Agent est d'identifier la capacité réellement défaillante.

---

# Niveau de garantie

Chaque capacité possède un niveau de garantie attendu.

Ce niveau est défini par :

- les observations disponibles ;
- les règles d'évaluation ;
- les critères de disponibilité ;
- les actions de réparation possibles.

Le niveau de garantie est indépendant de l'implémentation.

---

# Évolution

Une nouvelle capacité peut être ajoutée sans modifier les capacités existantes.

L'ajout d'une nouvelle implémentation ne modifie jamais la définition d'une capacité.

---

# Résumé

Une capacité décrit un service attendu.

Elle est indépendante :

- du matériel ;
- des logiciels ;
- des protocoles ;
- des implémentations.

Les capacités constituent le contrat fonctionnel d'Ohana-Agent.

# Téléinformation Linky

La capacité `teleinformation.freshness` garantit que la chaîne compteur Linky,
liaison série, `teleinfo2mqtt`, MQTT et Home Assistant continue à produire des
données récentes. L’observation contient la puissance apparente, la valeur
`NTARF`, la couleur Tempo, la période HC/HP et les index configurés.
