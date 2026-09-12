# Python Style

**Statut :** Accepté  
**Version :** 1.0  
**Date :** 2026-07-07  
**Projet :** Ohana-Agent
**Décideurs :** Cédric Harnois, ChatGPT

---

## Objectif

Définir les règles de style applicables au code Python de Shikamaru.

L'objectif est d'obtenir un code :

- lisible ;
- homogène ;
- maintenable ;
- explicite ;
- simple à faire évoluer.

---

## Philosophie

Le code doit être écrit pour être relu.

La priorité est donnée à la clarté plutôt qu'à la sophistication.

Shikamaru applique les principes suivants :

- **KISS** : Keep It Simple.
- **YAGNI** : ne pas coder ce qui n'est pas encore nécessaire.
- **SRP** : une classe possède une seule responsabilité.
- **DRY** : éviter les duplications inutiles.
- **Explicit is better than implicit**.

---

## Version Python

Le projet cible Python 3.13 ou supérieur.

Chaque fichier Python commence par :

```python
from __future__ import annotations
```

---

## Structure d'un fichier Python

Chaque fichier suit l'ordre suivant :

```python
"""
Ohana-Agent

Component:
    Lifecycle

Description:
    Manages the application lifecycle.

Author:
    Cédric Harnois
"""

from __future__ import annotations

# Standard library
from enum import Enum

# Third-party libraries
import yaml

# Internal imports
from ohana_agent.core.lifecycle import Lifecycle
```

---

## Imports

Les imports sont regroupés dans cet ordre :

1. Bibliothèque standard Python.
2. Bibliothèques externes.
3. Imports internes au projet.

Les imports inutilisés sont interdits.

---

## Typage

Les méthodes publiques doivent être typées.

```python
def transition_to(self, new_state: AgentState) -> None: ...
```

Les attributs importants doivent également être typés.

```python
self.state: AgentState = AgentState.CREATED
```

---

## Nommage

Les noms doivent exprimer clairement leur responsabilité.

### Classes

```python
Application
Lifecycle
Config
Logger
MQTTClient
PluginManager
HealthMonitor
```

### Méthodes publiques

Les méthodes publiques utilisent des verbes.

```python
initialize()
run()
stop()
transition_to()
connect()
disconnect()
load()
publish()
collect()
```

### Méthodes privées

Les méthodes privées commencent par `_`.

```python
def _validate_transition(self) -> None: ...
```

---

## Constantes

Les constantes sont écrites en majuscules.

```python
DEFAULT_CONFIG_PATH = "config/config.yaml"
HEALTH_INTERVAL_SECONDS = 30
```

---

## Enums

Les enums représentent des états ou des choix fermés.

```python
class AgentState(Enum):
    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
```

---

## Classes

Une classe doit avoir une responsabilité unique.

Chaque classe publique possède une docstring courte.

```python
class Lifecycle:
    """Manages the application lifecycle state."""
```

---

## Méthodes

Une méthode doit faire une seule chose.

Une méthode trop longue doit être découpée.

Une méthode publique doit être compréhensible sans lire son implémentation.

---

## Commentaires

Les commentaires expliquent l'intention, pas le fonctionnement évident du code.

Correct :

```python
# STOPPED is terminal: the application must not restart itself.
```

À éviter :

```python
# Set state to READY
self.state = AgentState.READY
```

---

## Exceptions

Les erreurs doivent être explicites.

```python
raise ValueError(f"Invalid transition: {current_state} -> {new_state}")
```

Les exceptions ne doivent pas être masquées silencieusement.

---

## Logging

Le logging doit être utilisé pour les événements importants :

- démarrage ;
- arrêt ;
- changement d'état ;
- connexion ou déconnexion ;
- erreur significative.

Le logging ne doit pas remplacer les exceptions.

---

## Ruff

Ruff est l'outil officiel pour :

- vérifier le style ;
- détecter les erreurs simples ;
- trier les imports ;
- formater le code.

La configuration est centralisée dans :

```text
pyproject.toml
```

---

## Tests

Les tests seront écrits avec `pytest`.

Les fichiers de test suivent le format :

```text
tests/test_lifecycle.py
tests/test_application.py
```

Chaque composant important doit avoir ses tests associés.

---

## TODO et FIXME

Les marqueurs sont autorisés uniquement s'ils sont explicites.

```python
# TODO: Add transition history when metrics are introduced.
# FIXME: Handle MQTT reconnection failure.
```

Un TODO vague est interdit.

---

## Exemple complet

```python
"""
Ohana-Agent

Component:
    Lifecycle

Description:
    Manages the application lifecycle.

Author:
    Cédric Harnois
"""

from __future__ import annotations

from enum import Enum


class AgentState(Enum):
    """Available lifecycle states for the application."""

    CREATED = "CREATED"
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class Lifecycle:
    """Manages the application lifecycle state."""

    def __init__(self) -> None:
        self.state: AgentState = AgentState.CREATED

    def transition_to(self, new_state: AgentState) -> None:
        """Transition to a new application state."""
        self._validate_transition(new_state)
        self.state = new_state

    def _validate_transition(self, new_state: AgentState) -> None:
        allowed_transitions = {
            AgentState.CREATED: {AgentState.INITIALIZING, AgentState.ERROR},
            AgentState.INITIALIZING: {AgentState.READY, AgentState.ERROR},
            AgentState.READY: {
                AgentState.RUNNING,
                AgentState.STOPPING,
                AgentState.ERROR,
            },
            AgentState.RUNNING: {AgentState.STOPPING, AgentState.ERROR},
            AgentState.STOPPING: {AgentState.STOPPED, AgentState.ERROR},
            AgentState.STOPPED: set(),
            AgentState.ERROR: {AgentState.STOPPING},
        }

        if new_state not in allowed_transitions[self.state]:
            raise ValueError(
                f"Invalid transition: {self.state.value} -> {new_state.value}"
            )
```

---

## Non-objectifs

Ce standard ne définit pas encore :

- la politique complète de tests ;
- l'intégration continue ;
- les hooks Git ;
- la convention de versioning ;
- la structure définitive des packages Python.

Ces sujets seront traités dans des documents dédiés si nécessaire.

---

## Références

- ADR-0001 — Lifecycle
- ADR-0002 — Application
- ADR-0003 — Composition
- ADR-0004 — State Transitions
- docs/architecture/Core.md
