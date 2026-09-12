# Configuration

## Introduction

La configuration décrit les attentes de l'utilisateur envers Ohana-Agent.

Elle ne décrit pas les implémentations.

Elle ne décrit pas les technologies.

Elle exprime les capacités que le système doit garantir ainsi que les règles de fonctionnement de l'agent.

---

# Objectifs

La configuration permet de :

* définir les capacités attendues ;
* adapter le comportement de Shikamaru ;
* ajuster les règles d'évaluation ;
* personnaliser les politiques de réparation.

La configuration ne contient aucune logique métier.

---

# Principe fondamental

La configuration décrit **ce qui est attendu**.

Le logiciel décide **comment y répondre**.

Exemple :

La configuration peut exprimer :

* une capacité DNS est requise ;
* une capacité MQTT est optionnelle.

Elle ne précise jamais quel plugin doit être utilisé.

---

# Capacités

Les capacités constituent le cœur de la configuration.

Chaque capacité peut définir :

* son niveau attendu ;
* ses paramètres fonctionnels ;
* ses règles d'évaluation ;
* ses règles de réparation.

---

# Découverte des plugins

Les plugins sont découverts automatiquement.

Chaque plugin déclare :

* les capacités qu'il fournit ;
* les commandes qu'il accepte ;
* les observations qu'il produit.

Shikamaru associe les capacités attendues aux plugins disponibles.

---

# Paramètres

La configuration peut contenir des paramètres nécessaires aux plugins.

Exemples :

* adresse d'une API ;
* identifiants d'accès ;
* seuils d'évaluation ;
* intervalles d'observation.

Ces paramètres restent indépendants des capacités elles-mêmes.

---

# Séparation

La configuration distingue clairement :

* les attentes fonctionnelles ;
* les paramètres techniques.

Cette séparation facilite les évolutions.

---

# Validation

Au démarrage, Shikamaru valide la configuration.

Il vérifie notamment :

* sa cohérence ;
* les capacités demandées ;
* les plugins disponibles ;
* les dépendances éventuelles.

Une configuration invalide empêche le démarrage normal du système.

---

# Rechargement

La configuration peut être rechargée.

Le rechargement doit :

* préserver les capacités déjà garanties lorsque cela est possible ;
* limiter les interruptions ;
* produire les événements appropriés.

---

# Versionnement

La configuration possède son propre numéro de version.

Les évolutions incompatibles doivent être clairement identifiées.

---

# Sécurité

Les informations sensibles ne doivent pas être stockées directement dans la configuration.

Le logiciel doit permettre l'utilisation de mécanismes adaptés :

* variables d'environnement ;
* coffre-fort de secrets ;
* fichiers sécurisés.

---

# Évolution

Une nouvelle capacité peut être ajoutée sans remettre en cause la structure générale de la configuration.

Une nouvelle technologie ne doit jamais nécessiter une modification du modèle de configuration.

---

# Principes

La configuration respecte les principes suivants :

* elle décrit les attentes ;
* elle ne décrit pas les implémentations ;
* elle reste indépendante des plugins ;
* elle est validée avant utilisation ;
* elle est versionnée.

---

# Résumé

La configuration exprime ce qui doit être garanti.

Shikamaru choisit comment le garantir.

Les plugins déclarent ce qu'ils savent faire.
