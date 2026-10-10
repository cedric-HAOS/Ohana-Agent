# Conventions MQTT

## Publications réellement utilisées par Home Assistant

Le préfixe est `home_assistant.topic_prefix` dans la configuration du plugin
MQTT, avec `ohana` dans le modèle livré. Le `topic_prefix` du contrôle roundtrip
est distinct : il sert aux sondes, pas au résumé Home Assistant.

| Topic avec le préfixe par défaut | Charge utile | Rétention |
|---|---|---|
| `ohana/status` | Texte `online` / `offline` ; Last Will `offline` | Oui |
| `ohana/health/summary` | JSON de synthèse de l'infrastructure | Oui |
| `ohana/host/health` | JSON des mesures hôte et de leurs vitaux | Oui |
| `ohana/icloud/connectivity` | JSON de connexion iCloud | Oui |

Le publisher conserve aussi les messages MQTT Discovery nécessaires aux
entités Home Assistant. Vérifier les préfixes effectifs avant de lire un topic.
Source : [publisher Home Assistant](../../src/ohana_agent/plugins/mqtt/home_assistant_publisher.py).

## Exemple de disponibilité

Sur `ohana/status`, la charge utile est du texte brut :

```text
online
```

Elle n'est ni un document JSON ni un message dans l'enveloppe historique.
La synthèse `health/summary` contient notamment `score`, `state`, `active_alerts`,
`critical_incidents`, les compteurs de services, `stale_capabilities`,
`updated_at`, les équipements/capacités affectés et les alertes.
Contrôler sa date : un message retenu ancien ne prouve pas un Agent actif.

## Transports du noyau et familles conceptuelles

Le noyau dispose de modèles spécialisés de disponibilité, statut, commande
et événement. Les anciennes familles `observations/<capability>`,
`states/<capability>`, `events/<type>` et `commands/<target>` décrivent une
architecture possible. Leur présence dans un dessin ou une classe ne garantit
pas une publication ou une voie d'exécution dans une installation donnée.

Pour intégrer un consommateur, identifier le publisher réellement configuré,
son topic, sa charge utile, son QoS et sa rétention. Utiliser
[Message-Model](Message-Model.md) pour distinguer les contrats REST et MQTT.
Les commandes restent soumises au contrôle d'autorisation Agent.

## Fiabilité et protection

Le Last Will indique une perte de connexion MQTT ; une absence de mesure récente
peut aussi indiquer un processus figé ou une collecte en retard. Comparer les
vitaux, les journaux et les dates, puis vérifier la capacité fonctionnelle.
L'authentification et les accès du broker protègent le transport. Ne pas placer
de secret ou de jeton dans les topics ni dans les journaux de diagnostic.

Shikamaru observe ; Tsunade coordonne ; Agent autorise ; MQTT transporte les
charges utiles propres à chaque contrat.
