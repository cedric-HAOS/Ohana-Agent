# Philosophie

## Introduction

Ohana-Agent n'est pas construit autour de technologies.

Il est construit autour de principes.

Ces principes guident toutes les décisions d'architecture, de développement et d'évolution du projet.

Ils constituent les règles fondamentales auxquelles le logiciel doit rester fidèle, quelles que soient les implémentations futures.

---

# Notre philosophie

Nous considérons qu'une infrastructure ne se résume pas aux logiciels qui la composent.

Elle est définie par les capacités qu'elle fournit.

Les technologies évoluent.

Les protocoles changent.

Les matériels sont remplacés.

Les capacités, elles, doivent rester garanties.

Toute l'architecture d'Ohana-Agent découle de cette idée.

---

# Les principes fondamentaux

## Les capacités avant les implémentations

Une capacité peut être assurée par différentes technologies.

Le logiciel garantit toujours une capacité.

Jamais une implémentation particulière.

---

## L'observation avant la configuration

Une configuration décrit une intention.

Elle ne prouve jamais un fonctionnement.

Seule l'observation permet d'affirmer qu'une capacité est réellement disponible.

---

## La preuve avant la supposition

Une décision ne doit jamais être fondée sur une hypothèse.

Elle doit reposer sur des faits observables.

Lorsqu'un doute subsiste, l'état reste inconnu.

---

## Les contrats avant les dépendances

Le noyau ne dépend jamais directement des technologies.

Il dépend uniquement de contrats clairement définis.

Les implémentations restent remplaçables.

---

## La composition avant le couplage

Chaque composant doit pouvoir évoluer indépendamment.

Le logiciel privilégie des composants simples, spécialisés et faiblement couplés.

---

## Les plugins avant le code spécifique

Toute nouvelle capacité doit pouvoir être ajoutée sans modifier le noyau.

Le cœur du logiciel reste stable.

Les plugins portent les spécificités techniques.

---

## Le noyau avant les technologies

Le noyau ne connaît ni Home Assistant, ni MQTT, ni AdGuard, ni WireGuard.

Il manipule uniquement des concepts :

- capacités ;
- observations ;
- états ;
- commandes ;
- événements.

Les technologies sont confinées dans les plugins.

---

## Les événements avant les appels directs

Les composants communiquent par des événements.

Ils ne doivent pas dépendre directement les uns des autres.

Cette approche favorise la modularité et la résilience.

---

## L'autonomie avant l'intervention humaine

Lorsqu'une anomalie est détectée, le logiciel privilégie toujours une réparation autonome.

L'utilisateur est sollicité uniquement lorsque cela devient nécessaire.

---

## La simplicité avant l'optimisation

Une architecture simple est préférable à une architecture complexe, même si cette dernière paraît plus performante.

La simplicité facilite la compréhension, les tests et la maintenance.

---

## L'évolution avant la réécriture

Une bonne architecture permet d'ajouter des capacités sans remettre en cause l'existant.

Les évolutions doivent être incrémentales.

---

## La lisibilité avant l'ingéniosité

Le code est lu bien plus souvent qu'il n'est écrit.

Chaque décision doit privilégier la compréhension plutôt que l'astuce.

---

## Les tests avant la confiance

Une fonctionnalité n'est considérée comme fiable que lorsqu'elle est vérifiée.

Les tests constituent une partie intégrante du logiciel.

---

## Les journaux avant les suppositions

Lorsqu'un comportement est inattendu, les journaux doivent permettre de comprendre ce qui s'est produit.

Le logiciel doit toujours être observable.

---

## Les décisions avant les habitudes

Chaque choix d'architecture doit pouvoir être expliqué.

Aucune décision ne doit être prise uniquement parce qu'elle est courante ou familière.

---

# Ce que nous cherchons à construire

Nous voulons construire un logiciel :

- fiable ;
- prévisible ;
- observable ;
- extensible ;
- autonome ;
- testable ;
- durable.

---

# Notre engagement

Chaque évolution d'Ohana-Agent devra respecter cette philosophie.

Si une fonctionnalité apporte de la complexité sans renforcer les capacités garanties par le logiciel, elle devra être remise en question.

---

# Une phrase

La technologie est un moyen.

Les capacités sont la finalité.