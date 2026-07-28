# MQTT Convention

## Introduction

Ce document définit les conventions d'utilisation de MQTT dans Ohana-Agent.

Le rôle de MQTT est exclusivement de transporter les messages définis dans **Message-Model.md**.

Aucune structure métier n'est définie dans ce document.

---

# Principes

L'interface MQTT respecte les principes suivants :

* transporter les messages du modèle commun ;
* rester indépendante des plugins ;
* rester indépendante des implémentations ;
* rester compatible avec les autres interfaces.

---

# Préfixe

Tous les topics commencent par :

```text
ohana/
```

---

# Hiérarchie

Les topics reflètent directement les catégories du Message Model.

```text
ohana/

    observations/
    states/
    events/
    commands/
    health/
```

---

# Topics

## Observations

```text
ohana/observations/<capability>
```

Exemples :

```text
ohana/observations/dns
ohana/observations/dhcp
ohana/observations/network
```

---

## États

```text
ohana/states/<capability>
```

---

## Événements

```text
ohana/events/<type>
```

---

## Commandes

```text
ohana/commands/<target>
```

---

## Santé

```text
ohana/status
ohana/health/summary
```

`ohana/status` publie la disponibilité d'Ohana-Agent avec un Last Will MQTT.

`ohana/health/summary` publie une synthèse JSON contenant le score global,
l'état, les alertes, les incidents critiques, la répartition des services et la
fraîcheur des capacités.

---

# Charge utile

Chaque publication contient un message conforme à **Message-Model.md**.

La convention MQTT ne modifie jamais la structure des messages.

---

# QoS

Le niveau de QoS est choisi selon le type de message.

Cette décision reste indépendante du contenu métier.

---

# Messages retenus

La politique de rétention est définie par catégorie.

Par exemple :

* états : retenus ;
* observations : non retenues ;
* événements : non retenus ;
* santé : retenue.

Cette politique peut évoluer sans modifier le Message Model.

---

# Versionnement

Les topics restent stables.

Les évolutions sont portées par le modèle de message.

---

# Compatibilité

Les consommateurs MQTT doivent pouvoir ignorer les champs inconnus.

Les producteurs doivent préserver la compatibilité ascendante.

---

# Ce qui est interdit

Les topics ne doivent jamais contenir :

* un nom de plugin ;
* un nom de logiciel ;
* une adresse IP ;
* un nom d'hôte ;
* une technologie.

Les topics représentent exclusivement les concepts métier.

---

# Résumé

MQTT transporte.

Le Message Model décrit.

Shikamaru décide.
