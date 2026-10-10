# ADR-0003 — Composition

**Statut :** Accepté  
**Version :** 1.0  
**Date :** 2026-07-07  
**Décideurs :** Cédric Harnois, ChatGPT

---

## Contexte

Shikamaru doit assembler plusieurs composants internes :

- Logger
- Configuration
- MQTT
- Plugins
- Health

Plusieurs approches sont possibles :

- création directe par `Application` ;
- injection de dépendances ;
- conteneur applicatif ;
- bootstrap externe.

Pour le Sprint 1, le nombre de composants reste limité.

---

## Décision

Pour le Sprint 1, la classe `Application` crée directement ses composants.

Exemple :

```python
self.logger = Logger(config.logging)
self.plugins = Config(config.plugins)
self.mqtt = MQTT(config.mqtt)
self.health = Health(config.health)
```
