# ADR-0030 — Migrations de configuration

**Statut :** Accepté
**Version :** 1.0
**Date :** 2026-07-17
**Décideurs :** Cédric Harnois, ChatGPT

---

## Objectif

Définir la politique de versionnement, de compatibilité et de migration des fichiers de configuration d’Ohana-Agent.

Cette décision encadre l’évolution des schémas YAML sans introduire de mécanisme de migration avant qu’un besoin réel existe.

---

## Contexte

Ohana-Agent charge plusieurs fichiers de configuration déclarative :

```text
config/shikamaru.yaml
config/infrastructure.yaml
config/plugins/dhcp.yaml
config/plugins/dns.yaml
```

La configuration principale possède un numéro de version explicite :

```yaml
version: 1
```

Le modèle Python accepte uniquement cette version :

```python
version: Literal[1] = 1
```

Une configuration déclarant une version inconnue est donc rejetée lors de sa validation.

À l’approche de la version 1.0.0 d’Ohana-Agent, il est nécessaire de définir comment les futures évolutions incompatibles seront traitées.

Cependant, aucun ancien schéma public ne nécessite actuellement de conversion.

---

## Décision

Ohana-Agent utilise un versionnement explicite du schéma de sa configuration principale.

La seule version prise en charge avant et lors de la publication d’Ohana-Agent 1.0.0 est :

```yaml
version: 1
```

Toute version inconnue est refusée au démarrage.

Ohana-Agent ne tente jamais :

* d’interpréter silencieusement une version future ;
* d’ignorer le numéro de version ;
* de convertir automatiquement une configuration sans politique documentée ;
* de modifier directement les fichiers de configuration de l’utilisateur.

---

## Absence de migration en version 1

Aucun moteur de migration n’est développé tant qu’il n’existe qu’un seul schéma officiel.

Il n’est notamment pas nécessaire de créer :

* un registre de migrations ;
* une classe abstraite de migration ;
* un pipeline de conversion ;
* des migrations fictives de la version 1 vers elle-même ;
* une dépendance dédiée aux migrations.

Cette décision évite d’introduire une architecture inutilisée et difficile à valider.

---

## Compatibilité au sein de la version 1

Les évolutions compatibles conservent le numéro de schéma `1`.

Une évolution est considérée comme compatible lorsqu’elle n’empêche pas une configuration version 1 existante de fonctionner.

Les évolutions compatibles peuvent notamment inclure :

* l’ajout d’un champ facultatif disposant d’une valeur par défaut ;
* l’ajout d’une nouvelle section facultative ;
* l’assouplissement d’une contrainte de validation ;
* l’ajout d’un nouveau plugin possédant son propre fichier de configuration ;
* l’amélioration des messages d’erreur.

Une évolution compatible ne doit pas modifier silencieusement le sens d’un champ existant.

---

## Changements incompatibles

Un nouveau numéro de schéma est requis lorsqu’une évolution rend une configuration existante incompatible.

Cela concerne notamment :

* la suppression d’un champ ;
* le renommage d’un champ ;
* le déplacement obligatoire d’un champ ;
* la modification de son type ;
* la modification incompatible de sa signification ;
* le remplacement d’une valeur précédemment valide ;
* l’ajout d’un champ obligatoire sans valeur par défaut.

Le prochain schéma incompatible devra utiliser :

```yaml
version: 2
```

---

## Introduction d’une migration

Une migration ne sera ajoutée que lors de l’introduction effective d’un nouveau schéma.

Avant la publication d’une version nécessitant `version: 2`, le projet devra définir :

1. les différences entre les schémas 1 et 2 ;
2. les transformations automatisables ;
3. les transformations nécessitant une intervention humaine ;
4. le comportement en cas d’échec ;
5. la stratégie de sauvegarde du fichier d’origine ;
6. la commande ou procédure déclenchant la migration ;
7. les tests de compatibilité associés.

Cette politique devra faire l’objet d’une nouvelle ADR ou d’une révision explicite de la présente décision.

---

## Migration explicite

Une future migration devra être une opération explicite.

Le démarrage normal d’Ohana-Agent ne devra pas réécrire automatiquement la configuration de l’utilisateur.

Le comportement attendu restera :

```text
chargement
    ↓
lecture de la version
    ↓
validation du schéma pris en charge
    ↓
démarrage ou erreur explicite
```

Si une migration devient nécessaire, elle devra être déclenchée par une commande ou une procédure dédiée.

---

## Conservation de l’original

Toute future migration écrivant un fichier devra conserver la configuration d’origine avant modification.

La stratégie exacte sera définie avec le premier mécanisme de migration, mais aucune conversion destructive ne sera autorisée.

---

## Fichiers de plugins

Les configurations propres aux plugins ne reçoivent pas obligatoirement un numéro de version dès leur création.

Un plugin doit introduire un versionnement explicite lorsque son schéma devient un contrat public susceptible d’évoluer de manière incompatible.

En l’absence de version propre, la compatibilité de son fichier de configuration suit celle de la version d’Ohana-Agent qui le fournit.

---

## Configuration d’infrastructure

La valeur :

```yaml
metadata:
  version: "1.0"
```

décrit actuellement le document d’infrastructure.

Elle ne constitue pas un mécanisme de sélection ou de migration du schéma.

Elle ne doit pas être interprétée comme l’équivalent de :

```yaml
version: 1
```

dans `shikamaru.yaml`.

Si le schéma d’infrastructure nécessite ultérieurement un versionnement technique, celui-ci devra être défini séparément et sans changer silencieusement la signification de `metadata.version`.

---

## Fichiers d’exemple

Les fichiers `.example.yaml` doivent toujours représenter le schéma actuellement pris en charge.

Ils sont validés par les mêmes loaders que les fichiers réels.

Lors de l’introduction d’une nouvelle version de schéma, les exemples devront être mis à jour dans la même modification.

---

## Erreurs

Une version non prise en charge doit provoquer une erreur explicite avant le démarrage de l’application.

Ohana-Agent ne doit pas :

* continuer avec une configuration partiellement comprise ;
* remplacer silencieusement la version déclarée ;
* appliquer automatiquement les valeurs d’un autre schéma ;
* ignorer les champs inconnus.

La validation stricte Pydantic reste le mécanisme de référence.

---

## Tests requis lors d’une évolution

Toute évolution du schéma doit vérifier au minimum :

* que les configurations compatibles restent chargeables ;
* que les versions prises en charge sont acceptées ;
* que les versions inconnues sont rejetées ;
* que les fichiers `.example.yaml` restent valides ;
* qu’une éventuelle migration produit une configuration conforme au schéma cible ;
* que les données non transformées sont préservées.

---

## Conséquences

### Avantages

* comportement prévisible au démarrage ;
* absence de conversion silencieuse ;
* compatibilité clairement définie ;
* architecture minimale tant qu’aucune migration n’est nécessaire ;
* possibilité d’introduire ultérieurement un mécanisme fondé sur un besoin réel.

### Limites

* une future évolution incompatible nécessitera une décision et une implémentation dédiées ;
* les utilisateurs devront migrer explicitement leur configuration lors d’un changement majeur de schéma ;
* les configurations provenant d’une version future seront refusées par les anciennes versions d’Ohana-Agent.

---

## État pour la version 1.0.0

Pour Ohana-Agent 1.0.0 :

```text
Schéma pris en charge : 1
Migration disponible   : aucune
Migration nécessaire   : aucune
Version inconnue       : rejetée
Réécriture automatique : interdite
```

La configuration version 1 constitue le contrat initial stable d’Ohana-Agent.
