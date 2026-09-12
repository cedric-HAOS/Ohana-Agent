# Commandes

## Introduction

Les commandes permettent à Shikamaru d'agir sur l'infrastructure.

Une commande exprime une intention.

Elle ne constitue jamais une preuve qu'une action a réussi.

La réussite d'une commande est toujours confirmée par une ou plusieurs observations.

---

# Définition

Une commande est une demande adressée à un plugin ou à une interface.

Elle demande l'exécution d'une action.

Le plugin décide de la manière de réaliser cette action en fonction de la technologie qu'il implémente.

---

# Une commande n'est pas un résultat

L'envoi d'une commande ne modifie jamais directement l'état d'une capacité.

Exemple :

```text
Commande
    │
    ▼
Redémarrer AdGuard
```

Cette commande ne signifie pas que la capacité **Résolution DNS** est disponible.

Seules les observations suivantes permettront à Shikamaru de le confirmer.

---

# Cycle de vie d'une commande

Toutes les commandes suivent le même cycle.

```text
Créée
   │
   ▼
Envoyée
   │
   ▼
Exécutée
   │
   ▼
Observée
   │
   ▼
Terminée
```

L'échec d'une commande ne signifie pas nécessairement que la capacité est indisponible.

Inversement, une commande exécutée avec succès ne garantit pas que la capacité est restaurée.

---

# Responsabilités

## Shikamaru

Shikamaru :

* décide de créer une commande ;
* choisit le plugin destinataire ;
* suit son exécution ;
* attend les observations de validation.

---

## Le plugin

Le plugin :

* reçoit la commande ;
* exécute l'action demandée ;
* publie les événements techniques associés.

Le plugin ne modifie jamais directement les états des capacités.

---

# Types de commandes

Les commandes peuvent appartenir à plusieurs catégories.

## Observation

Déclencher une observation immédiate.

Exemples :

* tester une résolution DNS ;
* vérifier la disponibilité d'une API ;
* interroger un équipement.

---

## Réparation

Déclencher une action corrective.

Exemples :

* redémarrer un service ;
* recharger une configuration ;
* relancer une synchronisation.

---

## Maintenance

Effectuer une opération planifiée.

Exemples :

* sauvegarder une configuration ;
* nettoyer des journaux ;
* lancer une mise à jour.

---

## Administration

Modifier le fonctionnement de l'agent.

Exemples :

* activer un plugin ;
* désactiver une capacité ;
* recharger la configuration.

---

# Idempotence

Dans la mesure du possible, une commande doit pouvoir être exécutée plusieurs fois sans produire d'effet indésirable.

Cette propriété améliore la résilience du système.

---

# Traçabilité

Chaque commande possède un identifiant unique.

Il doit être possible de connaître :

* qui a créé la commande ;
* pourquoi elle a été créée ;
* quand elle a été envoyée ;
* quel plugin l'a reçue ;
* quelles observations ont suivi.

---

# Commandes et événements

Une commande peut produire plusieurs événements techniques.

Exemples :

* commande envoyée ;
* commande reçue ;
* commande exécutée ;
* commande échouée.

Ces événements décrivent le déroulement de l'exécution.

Ils ne constituent pas une preuve que la capacité est restaurée.

---

# Validation

Une commande est considérée comme efficace uniquement si les observations suivantes démontrent que la capacité est de nouveau garantie.

La validation repose toujours sur les observations.

Jamais sur la commande elle-même.

---

# Principes

Les commandes respectent les principes suivants :

* elles expriment une intention ;
* elles déclenchent une action ;
* elles ne modifient jamais directement un état ;
* elles sont entièrement traçables ;
* elles sont validées uniquement par observation.

---

# Résumé

Tsunade propose une opération lorsqu'un diagnostic le justifie.

Ohana-Agent valide son autorisation et sa conformité au contrat.

Les commandes expriment une intention.

Les plugins agissent.

Shikamaru observe et valide le résultat.
