# ADR-0019 — Mode dégradé (Degraded Mode)

## Statut

Accepté

## Date

2026-07-08

## Contexte

Les ADR précédentes ont introduit les principaux composants de l'architecture d'auto-réparation :

* ADR-0015 — Health Monitor
* ADR-0016 — Watchdog & Heartbeat
* ADR-0017 — Recovery Engine
* ADR-0018 — Recovery Policies

Grâce à ces composants, Shikamaru est capable de détecter une anomalie et de tenter une récupération automatique.

Cependant, certaines situations ne peuvent pas être corrigées immédiatement :

* un plugin ne redémarre plus ;
* un service externe est indisponible ;
* une ressource système est insuffisante ;
* une dépendance réseau est perdue durablement.

Dans ces cas, arrêter complètement l'agent n'est pas souhaitable si une partie de ses fonctionnalités peut continuer à être assurée.

Il est donc nécessaire d'introduire un **mode dégradé**, permettant à l'agent de poursuivre son fonctionnement tout en signalant clairement la perte de certaines capacités.

## Décision

Ohana-Agent adopte un **Mode dégradé** (`DEGRADED`).

Ce mode représente un état de fonctionnement partiel.

L'agent continue à exécuter les services encore opérationnels tout en désactivant ou en isolant les composants défaillants.

Le mode dégradé n'est pas un état d'erreur fatal.

Il constitue un mode d'exploitation contrôlé permettant de maintenir la meilleure qualité de service possible.

## Principes

Le mode dégradé repose sur les principes suivants :

* privilégier la continuité de service ;
* isoler les composants défaillants ;
* empêcher les boucles infinies de récupération ;
* informer les autres composants de l'état courant ;
* permettre un retour automatique à un fonctionnement normal.

## Architecture

Le mode dégradé ne constitue pas un nouveau composant.

Il résulte de la collaboration entre :

```text
HealthMonitor

↓

RecoveryEngine

↓

RecoveryPolicy

↓

Application
```

Chaque composant conserve sa responsabilité propre.

## État global

Le Health Monitor calcule un état global.

Lorsque certaines capacités critiques sont indisponibles sans empêcher totalement l'exécution de l'agent, l'état global devient :

```python
HealthStatus.DEGRADED
```

L'agent reste en fonctionnement.

## Capacité dégradée

Une capacité est considérée comme dégradée lorsqu'elle :

* n'est plus pleinement opérationnelle ;
* ne peut pas être récupérée immédiatement ;
* n'empêche pas l'exécution des autres capacités.

Exemples :

* plugin DNS arrêté ;
* plugin DHCP désactivé ;
* supervision temporairement indisponible ;
* interface Web inaccessible.

## Capacité critique

Une capacité est dite critique lorsqu'elle conditionne le fonctionnement du noyau.

Exemples :

* boucle principale de l'application ;
* gestionnaire d'événements ;
* runtime interne indispensable.

Si une capacité critique devient indisponible sans possibilité de récupération, l'agent passe en état `UNHEALTHY`.

## Déclenchement

Le passage en mode dégradé peut être déclenché notamment lorsque :

* toutes les tentatives prévues par une Recovery Policy échouent ;
* un plugin est volontairement désactivé ;
* une dépendance externe reste indisponible ;
* un watchdog reste en échec durable.

## Retour à l'état normal

Le retour à l'état `HEALTHY` est automatique.

Il intervient lorsque :

* les contrôles de santé redeviennent positifs ;
* les watchdogs sont satisfaits ;
* les capacités précédemment indisponibles redeviennent opérationnelles.

Aucun redémarrage global n'est nécessaire.

## Comportement de l'application

Lorsque l'application est en mode dégradé :

* les capacités disponibles continuent de fonctionner ;
* les commandes concernant un composant indisponible peuvent être refusées ;
* les événements continuent d'être publiés ;
* les métriques restent disponibles ;
* les tentatives de récupération peuvent continuer en arrière-plan selon les politiques définies.

## Événements produits

Le système pourra publier les événements suivants :

```text
application.degraded
application.recovered
application.unhealthy
```

Ces événements seront relayés par :

* MQTT ;
* les journaux ;
* l'interface web ;
* les systèmes de supervision.

## Visibilité

Le mode dégradé doit être visible :

* dans les journaux ;
* via les événements internes ;
* dans les métriques de santé ;
* via MQTT ;
* dans la future interface Web.

L'utilisateur doit pouvoir identifier rapidement :

* les capacités indisponibles ;
* leur cause ;
* les tentatives de récupération en cours ;
* le retour éventuel à un état normal.

## Principes de conception

Le mode dégradé doit être :

* explicite ;
* observable ;
* déterministe ;
* réversible ;
* indépendant des plugins ;
* compatible avec les futurs mécanismes de supervision.

Il ne doit jamais masquer une défaillance.

## Limites de cette ADR

Cette ADR ne définit pas :

* les notifications vers Home Assistant ;
* les notifications par e-mail ou messagerie ;
* les tableaux de bord de supervision ;
* les politiques propres à chaque plugin.

Ces éléments seront traités dans des évolutions ultérieures.

## Conséquences positives

* Continuité de service en cas de panne partielle.
* Réduction des interruptions complètes.
* Meilleure résilience du système.
* Retour automatique à l'état nominal.
* Architecture cohérente avec le Health Monitor et le Recovery Engine.
* Préparation de la supervision avancée.

## Conséquences négatives

* Gestion plus complexe de l'état global.
* Nécessité de classifier les capacités critiques.
* Risque d'exploitation prolongée en mode dégradé si aucune intervention n'est réalisée.

## Décision finale

Ohana-Agent adopte un **Mode dégradé** permettant de maintenir l'exécution des capacités encore disponibles lorsqu'une récupération complète n'est pas possible.

Le passage en mode dégradé est déterminé par le `HealthMonitor` à partir des résultats de santé et des décisions du `RecoveryEngine`.

Cette approche garantit une continuité de service, une meilleure résilience et une architecture cohérente avec les principes de Shikamaru, dont l'objectif est de rester opérationnel aussi longtemps que possible, même face à des défaillances partielles.
