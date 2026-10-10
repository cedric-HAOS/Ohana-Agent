# Modèles de messages et contrats de transport

Les observations représentent les mêmes faits métier dans les différents
canaux, mais leur sérialisation dépend du contrat de chaque interface.
L'ancienne enveloppe conceptuelle `version/id/timestamp/source/category/type/payload`
est une proposition d'architecture historique, pas le schéma universel du
logiciel livré. Ne pas la transmettre telle quelle à Vision.

## Observations REST Agent vers Vision

Agent publie sur `POST /api/observations` le résultat de
[VisionObservationMapper](../../src/ohana_agent/observation/exporters/vision_observation_mapper.py).
Vision valide les champs avec `ObservationRequest`, en refusant les champs
supplémentaires. Exemple de payload accepté :

```json
{
  "observation_id": "00000000-0000-4000-8000-000000000001",
  "capability_id": "dns.resolve",
  "service_id": "dns-primary",
  "node_id": "infra-01",
  "status": "healthy",
  "observed_at": "2026-10-10T10:00:00Z",
  "message": "Résolution DNS réussie",
  "latency_ms": 3.8,
  "metadata": {}
}
```

| Champ | Contrat |
|---|---|
| `capability_id`, `service_id`, `node_id` | Chaînes non vides, requises |
| `status` | `healthy`, `degraded`, `unavailable` ou `unknown` |
| `observed_at` | Date de la mesure ; Agent exporte une date ISO-8601 avec fuseau |
| `observation_id` | UUID facultatif côté ingestion ; Agent fournit l'identifiant du fait |
| `message` | Texte facultatif |
| `latency_ms` | Durée facultative non négative |
| `metadata` | Objet extensible, vide par défaut |

Le mapper ajoute `metadata.agent_observation` pour conserver l'identifiant,
la source, le succès et le message Agent. Il traduit `unhealthy` en
`unavailable` et une suspension planifiée en `unknown`, en conservant ses
détails dans les métadonnées. Le transport ne doit pas transformer une
suspension en panne ni une hypothèse en fait.

La topologie utilise un autre contrat : `PUT /api/infrastructure`, avec
`schema_version: 1`. Voir [l'intégration Vision](../Integration/Vision.md) et
[le modèle d'ingestion Vision](https://github.com/cedric-HAOS/Ohana-Vision/blob/main/src/ohana_vision/web/observation_request.py).

## MQTT

Le publisher Home Assistant utilise le préfixe configuré, `ohana` par défaut :

| Topic sous ce préfixe | Charge utile |
|---|---|
| `status` | Texte brut `online` ou `offline`, retenu ; Last Will à `offline` |
| `health/summary` | JSON de synthèse : score, état, compteurs, fraîcheur, alertes |
| `host/health` | JSON de santé hôte et vitaux |
| `icloud/connectivity` | JSON d'état de connexion iCloud |

Ces publications n'utilisent pas l'enveloppe historique. Les classes du
[transport MQTT du noyau](../../src/ohana_agent/core/mqtt/messages.py) ont aussi
leurs formes propres : disponibilité, statut, commande et événement. Une
classe du noyau n'établit pas qu'un topic générique est activé en production.
Voir [les conventions MQTT](MQTT-Convention.md) et le
[publisher Home Assistant](../../src/ohana_agent/plugins/mqtt/home_assistant_publisher.py).

## Autres interfaces

Les événements WebSocket ont un discriminant `type` et des champs propres à
l'événement. Les contrats d'administration et de jobs exposent leurs modèles
versionnés, notamment `protocol_version: 1` pour les jobs. Les logs et la CLI
restent des interfaces de diagnostic ; ils ne partagent pas un schéma JSON
obligatoire avec REST.

Voir [Administration](../Administration.md), [le cycle Tsunade/Katsuyu](../tsunade-worker-cycle.md)
et [le protocole MQTT](MQTT.md).

## Compatibilité et responsabilité

Préserver la signification du fait, son identifiant lorsqu'il est transporté,
sa date et sa provenance. Ne jamais réécrire une observation déjà publiée.
Les projections et synthèses produisent leurs propres vues sans remplacer
l'observation originale.

La compatibilité se vérifie pour chaque producteur/consommateur : les champs
inconnus sont refusés par le modèle REST d'observation, alors que les
métadonnées restent extensibles. Une évolution incompatible exige une
migration/version identifiable et des tests entre les composants concernés.
Ajouter un champ à une enveloppe théorique ne garantit pas sa compatibilité.

Shikamaru observe et vérifie ; Tsunade coordonne et propose ; Agent valide les
autorisations et exécute ; Katsuyu apporte les traitements autorisés.
