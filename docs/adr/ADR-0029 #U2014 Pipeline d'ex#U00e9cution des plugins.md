# ADR-0029 — Pipeline d'exécution des plugins

- **Statut** : Accepté
- **Date** : 2026-07-10

---

# Contexte

Ohana-Agent supervise les capacités d'une infrastructure.

Les plugins réalisent des vérifications techniques (DNS, DHCP, MQTT, HTTP, NTP, etc.) et produisent des résultats d'observation.

Avant le Sprint 14, plusieurs composants étaient capables d'exécuter des vérifications, mais aucun pipeline unique ne reliait :

- le Scheduler ;
- les plugins ;
- le Runtime Infrastructure ;
- le modèle Observation ;
- le système d'événements.

Cette absence de chaîne d'exécution rendait difficile l'ajout de nouveaux plugins tout en conservant une architecture homogène.

---

# Décision

Toutes les exécutions de plugins suivent désormais le pipeline unique suivant :

```text
Task
    │
    ▼
DispatcherTaskExecutor
    │
    ▼
PluginObservationDispatcher
    │
    ▼
PluginCommand
    │
    ▼
PluginObservationExecutor
    │
    ▼
Plugin.execute(...)
    │
    ▼
ObserverResult
    │
    ▼
ObserverResultMapper
    │
    ▼
InfrastructureHealthUpdate
    │
    ▼
InfrastructureHealthManager
    │
    ▼
InfrastructureRuntime
    │
    ▼
InfrastructureObservationMapper
    │
    ▼
Observation
    │
    ▼
ObservationEventPublisher
    │
    ▼
ObservationPublished
```

Chaque composant possède une responsabilité unique.

---

# Responsabilités

## Scheduler

Le Scheduler décide uniquement **quand** une tâche doit être exécutée.

Il ne connaît aucun plugin.

Il ne manipule jamais le Runtime Infrastructure.

---

## DispatcherTaskExecutor

Le Dispatcher exécute une commande planifiée.

Il ne connaît pas les plugins.

Il délègue l'exécution au dispatcher métier.

---

## PluginObservationDispatcher

Le dispatcher transforme une commande planifiée en un objet `PluginCommand`.

Il applique uniquement les conventions de nommage des commandes.

Exemple :

```
dns.resolve
```

↓

```
PluginCommand(
    plugin_name="dns",
    operation="resolve",
    target_name="dns",
)
```

---

## PluginCommand

`PluginCommand` représente une intention d'exécution.

Il contient :

- le plugin ;
- l'opération ;
- la cible ;
- les arguments.

Il remplace progressivement les conventions basées sur les chaînes de caractères.

---

## PluginObservationExecutor

Le PluginObservationExecutor :

- récupère le plugin auprès du PluginManager ;
- exécute le plugin ;
- transmet le résultat à ObservationEngine.

Il ne réalise aucune transformation métier.

---

## Plugin

Tous les plugins implémentent désormais le contrat unique :

```python
register(context)

execute(**kwargs) -> ObserverResult
```

Les plugins ne manipulent jamais directement :

- InfrastructureRuntime ;
- Observation ;
- EventBus.

Ils produisent uniquement un `ObserverResult`.

---

## ObserverResult

ObserverResult représente le résultat technique brut d'une vérification.

Il contient notamment :

- success
- latency
- message
- check
- metadata

Il est indépendant de l'infrastructure.

---

## ObserverResultMapper

Le mapper convertit un ObserverResult en InfrastructureHealthUpdate.

Il effectue la traduction entre :

- résultat technique

et

- état de santé de l'infrastructure.

---

## InfrastructureHealthManager

Le HealthManager applique la mise à jour au Runtime Infrastructure.

Il est responsable :

- de la mise à jour des services ;
- de la mise à jour des nœuds.

Il ne publie aucun événement.

---

## InfrastructureObservationMapper

Le mapper convertit l'état de l'infrastructure en Observation standardisée.

Il enrichit les informations à partir du Runtime Infrastructure.

---

## ObservationEventPublisher

Le Publisher diffuse une ObservationPublished sur l'EventBus.

Les exporteurs, interfaces Web et intégrations externes écoutent ensuite ces événements.

---

# Conséquences

## Positives

Tous les plugins utilisent désormais la même API.

L'ajout d'un nouveau plugin nécessite uniquement :

- l'implémentation de `execute()`;
- la production d'un `ObserverResult`.

Le reste du pipeline est entièrement mutualisé.

Le Scheduler reste totalement indépendant des plugins.

Les responsabilités sont clairement séparées.

Chaque transformation possède son propre composant dédié.

L'architecture devient facilement testable.

---

## Négatives

Le pipeline comporte davantage d'objets intermédiaires.

Cette augmentation de la granularité est volontaire afin de limiter le couplage entre les composants.

---

# Alternatives étudiées

## Plugin → Runtime direct

Le plugin aurait pu mettre directement à jour InfrastructureRuntime.

Cette solution a été rejetée.

Elle créerait un fort couplage entre les plugins et le modèle d'infrastructure.

---

## Plugin → Observation directe

Le plugin aurait pu produire directement une Observation.

Cette solution a été rejetée.

Les plugins ne doivent pas connaître le modèle métier des observations.

Ils doivent uniquement produire des résultats techniques.

---

## Scheduler spécifique aux plugins

Le Scheduler aurait pu connaître les plugins.

Cette solution a été rejetée.

Le Scheduler doit rester générique.

Il ne connaît que des tâches.

---

# Compatibilité

Cette architecture est compatible avec les futurs plugins :

- DNS
- DHCP
- MQTT
- HTTP
- HTTPS
- NTP
- Internet
- WireGuard
- Backup
- Home Assistant

sans modification du Scheduler ni du Runtime Infrastructure.

---

# Vision

Cette ADR formalise le principe fondamental d'Ohana-Agent :

> Les plugins produisent des faits techniques.

> Le moteur d'observation transforme ces faits en connaissance métier.

Le cœur du système ne supervise donc pas des équipements.

Il supervise les **capacités** de l'infrastructure.