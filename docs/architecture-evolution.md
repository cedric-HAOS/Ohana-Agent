# Organisation d’Agent et investigations Tsunade

## Organisation actuelle

Tout le code applicatif est installé dans le namespace `ohana_agent`, depuis
`src/ohana_agent`. La racine conserve le projet Python, les configurations,
les scripts, les tests, le déploiement et la documentation.

```text
src/ohana_agent/
├── api/             # serveur HTTP et service applicatif
├── companions/      # sessions Shizune et notifications
├── configuration/   # modèles, loaders et builders
├── contracts/       # contrats publics partagés
├── core/            # événements, commandes et abstractions
├── host/            # DHCP, NetworkManager et helpers restreints
├── infrastructure/  # topologie et dépôt de configuration
├── jobs/            # file Katsuyu, journaux et Wake-on-LAN
├── observation/     # observation, santé et suivi Shikamaru
├── persistence/     # mémoires et stockage
├── plugins/         # implémentations et runtime des plugins
├── recovery/        # stratégies de récupération
├── runtime/         # assemblage, cycle de vie et CLI
├── scheduler/       # planification et déclencheurs
└── tsunade/         # incidents, expertise et investigations
```

Les noms de modules internes aux plugins et aux builders ne répètent plus le
nom du dossier : `plugins/dns/check.py`, `plugins/dns/plugin.py`,
`configuration/builders/dns.py`. Les guides sont classés sous `docs/`, avec
[un index](README.md).

## Domaine Tsunade

Le domaine Tsunade est regroupé sous `src/ohana_agent/tsunade/` :

| Module | Responsabilité |
| --- | --- |
| `incidents.py` | Incidents, historique et demandes utilisateur persistés |
| `expertise.py` | Diagnostic déterministe et interprétation des résultats IA |
| `investigations.py` | Catalogue fermé des sondes Agent |
| `followups.py` | Collecte complémentaire autorisée et réévaluation |
| `followup_store.py` | Persistance transactionnelle du plan et de l’autorisation |
| `incident_summary.py` | Synthèse commune pour Vision et Shizune |

`api/http.py` porte les routes, l’authentification et les réponses HTTP.
`api/service.py` coordonne les opérations entre les domaines. L’assemblage des
services et du runtime reste dans `runtime/bootstrap.py`. Les contrats partagés
ne chargent pas le serveur HTTP ; les initialisateurs de paquets restent légers.

Setuptools découvre uniquement `src/ohana_agent`. Les anciens paquets génériques
à la racine et la façade `administration` ont été retirés. Pour développer,
installer le dépôt avec `python -m pip install -e ".[development]"`.
`ohana-agent` et `python -m ohana_agent` lancent la même CLI. Les autres commandes
publiques, les fichiers YAML et les bases SQLite conservent leur contrat.

Le helper DHCP importe son implémentation sans charger Pydantic ni le runtime.
Les chemins Python internes ont changé : les extensions Python éventuelles
doivent utiliser le nouveau namespace, par exemple
`from ohana_agent.plugins.runtime import Plugin`. Les identifiants de capacités,
les routes et les noms des services système ne sont pas des chemins Python et
ne sont pas renommés.

## Parcours livré dans le code

1. Une analyse Katsuyu suggère une collecte de journaux. Tsunade vérifie que
   l’incident `logs.health` est actif et que les observations sont encore actuelles.
2. Tsunade construit un plan `logs.investigate` sur une source configurée, avec
   un motif littéral dérivé des constats, une fenêtre de deux heures et les
   limites de volume et de durée déjà configurées. Le texte IA ne devient jamais
   une commande exécutable.
3. Une demande persistée apparaît dans Shizune : source, motif, fenêtre, volume
   maximal et choix **Autoriser / Refuser / Plus tard**. Une notification utilise
   le canal existant lorsqu’il est configuré. La demande expire après 24 heures.
4. L’accord et l’identité du compagnon sont enregistrés dans la même transaction
   que l’intention d’exécution. Le job peut ensuite être repris après interruption.
   Les limites et la source sont revérifiées avant le dispatch.
5. Katsuyu utilise son handler existant. Un résultat `KO` signifie que des lignes
   correspondent au motif ; un échec de collecte est un statut de job distinct.
6. Tsunade prépare une seule réévaluation IA avec la collecte, son périmètre et
   ses limites. Zéro correspondance et une collecte tronquée sont explicitement
   transmis ; ils ne prouvent pas la résolution. L’incident reste sous observation.
7. La conclusion et l’état du parcours apparaissent dans Shizune. Une analyse
   encore insuffisante termine le cycle avec cette limite explicitée.

Le journal des incidents et la file de jobs restent les stockages existants.
La table additive `tsunade_followups` conserve le plan et les identifiants de
jobs. Une réponse répétée ou simultanée reprend la même intention. Le polling
traite aussi les collectes annulées ou expirées avant de libérer le worker.

Une même empreinte des constats ne redemande pas l’accord après un refus ou un
cycle terminé. Une réévaluation issue d’une collecte complémentaire ne crée
jamais une nouvelle boucle. Les suggestions anciennes encore actuelles sont
réconciliées lors de la consultation du compagnon, sans relancer l’IA. Une
suggestion sans capacité correspondante est signalée comme non exécutable.

Ce premier parcours réutilise le protocole Katsuyu et les routes compagnon ;
aucune migration YAML ni nouvelle capacité worker n’est nécessaire. Installer
Agent et la PWA Shizune actualisés rend le nouveau parcours visible. La validation
locale ne vaut pas validation d’une collecte sur les machines de production.

## Vérifications et évolution

`pytest -q` construit une fois les distributions dans un répertoire temporaire
pour contrôler le code courant. Il ne dépend plus du dernier wheel laissé dans
`dist/`. Pour contrôler des artefacts préparés séparément, `OHANA_TEST_DIST`
permet de sélectionner explicitement leur répertoire. Les contrôles vérifient
notamment que tous les fichiers Python du wheel appartiennent à `ohana_agent`
et que les points d’entrée désignent les nouveaux modules.

Le service applicatif conserve la coordination existante. Son éventuel découpage
plus fin peut désormais être effectué séparément, sans déplacer de nouveau les
domaines ni modifier le transport HTTP.

Pour étendre les investigations, ajouter des plans typés par capacité plutôt
qu’un interpréteur de commandes IA. Les sondes ordinaires conservent leur politique
actuelle ; une collecte plus étendue devra décrire son périmètre et ses limites
avant autorisation. Les réparations gardent leur validation distincte.
