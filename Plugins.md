# Plugins

## Introduction

Le noyau d'Ohana-Agent ne connaît aucune technologie.

Il ne connaît ni DNS, ni MQTT, ni Home Assistant, ni WireGuard.

Le noyau connaît uniquement des capacités.

Les plugins permettent d'apporter ces capacités au système.

Ils constituent la seule partie du logiciel dépendante des technologies.

---

# Définition

Un plugin est un fournisseur de capacités.

Il implémente une ou plusieurs capacités définies par le système.

Le noyau ne dépend jamais de l'implémentation d'un plugin.

Il dépend uniquement du contrat que celui-ci expose.

---

# Le contrat

Chaque plugin signe un contrat avec le noyau.

Ce contrat décrit :

- les capacités fournies ;
- les observations produites ;
- les commandes acceptées ;
- les événements publiés ;
- les actions réalisables.

Le noyau ne connaît jamais davantage.

---

# Ce qu'un plugin peut faire

Un plugin peut :

- observer un système ;
- produire des observations ;
- recevoir des commandes ;
- exécuter des actions ;
- publier des événements.

---

# Ce qu'un plugin ne peut pas faire

Un plugin ne décide jamais.

Il n'évalue jamais l'état global.

Il ne coordonne jamais d'autres plugins.

Il ne contient aucune logique métier du noyau.

Toutes les décisions sont prises par le moteur central.

---

# Cycle de vie

Chaque plugin suit le même cycle de vie.

```text
Découverte
      │
      ▼
Chargement
      │
      ▼
Initialisation
      │
      ▼
Disponible
      │
      ▼
Exécution
      │
      ▼
Arrêt
```

Le noyau reste responsable de ce cycle.

---

# Les capacités

Un plugin peut fournir une ou plusieurs capacités.

Exemple :

Plugin AdGuard

Capacités :

- Résolution DNS
- Filtrage DNS

Plugin Home Assistant

Capacités :

- Automatisation
- Contrôle des équipements

Le noyau raisonne toujours sur les capacités.

Jamais sur le nom du plugin.

---

# Plugins intégrés

Ohana-Agent fournit actuellement :

- `dhcp` pour `dhcp.status` ;
- `dns` pour `dns.resolve` ;
- `ntp` pour `ntp.query` ;
- `mqtt` pour `mqtt.roundtrip` ;
- `network` pour `network.reachable` ;
- `zwave` pour `zwave.status` ;
- `wireguard` pour `wireguard.status` ;
- `shelly_telemetry` pour `shelly.telemetry.freshness` ;
- `teleinformation` pour `teleinformation.freshness`.

Le plugin réseau constitue une exception volontairement limitée : il observe la
présence d'un équipement, mais cette présence ne remplace jamais l'observation
d'une capacité fonctionnelle.

---

# Les observations

Les plugins produisent des observations.

Ils ne produisent jamais directement des états.

Exemple :

Observation :

"La résolution DNS a répondu en 18 ms."

L'état est calculé par le noyau.

---

# Les commandes

Le noyau peut envoyer une commande à un plugin.

Exemples :

- redémarrer ;
- recharger une configuration ;
- effectuer un test ;
- lancer une réparation.

Le plugin exécute la commande.

Le résultat est confirmé ultérieurement par une observation.

---

# Les événements

Les plugins publient les événements qu'ils observent.

Exemples :

- démarrage ;
- arrêt ;
- erreur ;
- changement de configuration ;
- observation réalisée.

Les événements ne constituent jamais une décision.

Ils décrivent uniquement un fait.

---

# Isolation

Les plugins sont indépendants les uns des autres.

Un plugin ne communique jamais directement avec un autre plugin.

Toutes les interactions passent par le noyau.

Cette règle limite fortement le couplage.

---

# Remplacement

Deux plugins peuvent fournir la même capacité.

Exemple :

```text
Capacité DNS

      ▲

 ┌────┴────┐
 │         │
AdGuard  Unbound
```

Le noyau ne dépend jamais du fournisseur.

Il dépend uniquement de la capacité.

---

# Évolution

Une nouvelle technologie est ajoutée sous forme d'un nouveau plugin.

Aucune modification du noyau ne doit être nécessaire.

Cette propriété garantit la stabilité de l'architecture.

---

# Résumé

Le noyau décide.

Les plugins observent et agissent.

Les capacités constituent le contrat entre les deux.