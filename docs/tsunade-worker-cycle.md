# Contrôle des journaux, diagnostics et arrêt Katsuyu

Le contrôle quotidien termine un cycle borné avant de libérer le worker :

1. Katsuyu transmet le résultat validé de `logs.health_check`.
2. Agent enregistre les incidents des sources concernées. Tsunade réévalue les
   nouveaux éléments avec ses règles existantes. Cette réévaluation réutilise
   les journaux collectés, sans lancer une nouvelle série de sondes réseau.
3. Une conclusion déterministe `stable` ou `watch` est enregistrée directement.
   Si les règles demandent une investigation, un job `ai.inference` est créé.
   Les sources sans changement significatif ne consomment pas de diagnostic IA.
4. Les résultats IA et les échecs, annulations ou délais dépassés sont enregistrés.
5. Le prochain appel authentifié `POST /v1/jobs/next` prend un travail ou autorise
   l’arrêt si la file compatible et les résultats à traiter sont vides.

Le corps de `/v1/jobs/next` est celui de `/v1/jobs/claim`. La réponse ajoute
`shutdown_requested` au couple `protocol_version`, `job`. Un `job` non nul ne
donne jamais une permission d’arrêt à appliquer plus tard.

L’autorisation nécessite à la fois `shutdown_after_completion` activé dans la
configuration et un worker marqué comme réveillé par Ohana. Un démarrage manuel
ne donne pas cette permission. La permission de réveil est consommée lors de
l’autorisation d’arrêt. Une réponse perdue peut laisser le PC allumé ; elle ne
doit pas provoquer un arrêt sur la base d’une ancienne consigne.

La colonne SQLite `completion_processed` conserve les résultats en attente de
traitement. Elle est ajoutée automatiquement, sans réexécuter l’ancien historique.
Le prochain polling reprend un résultat reçu avant un redémarrage d’Agent.
Les contrôles rejoués ne doivent pas augmenter les occurrences des incidents.
Les diagnostics IA conservent leur délai maximal de 900 secondes.

## Mise à jour progressive

Installer Agent avant Katsuyu est recommandé. Un ancien Katsuyu utilise encore
`/v1/jobs/claim` mais ne reçoit plus de consigne anticipée d’arrêt. Un nouveau
Katsuyu face à un ancien Agent revient à `/v1/jobs/claim` uniquement sur HTTP 404
et ignore l’ancien indicateur d’arrêt. Le cycle complet avec arrêt automatique
nécessite les deux composants à jour. Aucune modification YAML n’est requise.

## Présentation et actions

Agent expose une `assessment` synthétique aux listes Vision et Shizune. Elle
distingue le signal observé, la conclusion, les éléments couverts, une analyse
incomplète, une attente Katsuyu et une demande d’action humaine. La date de
réception d’un résultat IA ne rend pas actuel un diagnostic sur de vieux éléments.

Shizune peut demander `POST /v1/incidents/{id}/diagnose` via son canal compagnon.
La session est obligatoire ; le corps doit être vide. Tsunade garde la décision
et Agent l’exécution. Cette route n’autorise aucune correction et ne reçoit ni
commande, ni chemin, ni cible arbitraire. Les réparations gardent leurs demandes
de validation existantes. Le jeton reste dans les en-têtes, jamais dans le lien
vers le dossier Vision.

## Incidents persistés et architecture

Au démarrage d’Agent et après chaque enregistrement réussi de l’architecture,
`reconcile_network_devices` compare les incidents réseau persistés à la liste
actuelle des équipements. Un incident `network.reachable` encore actif dont
l’équipement a été retiré est clôturé avec le motif `monitoring_removed`.
La reprise traite aussi les suppressions antérieures au dernier démarrage ;
elle ne dépend pas uniquement d’une différence entre deux fichiers en mémoire.
Les incidents des équipements toujours déclarés restent suivis normalement.
Les événements et incidents clôturés restent conservés pour consultation.

Vision filtre séparément l’« État courant » avec les identifiants de la topologie
actuelle et recalcule cet affichage après son actualisation. Ce filtre ne retire
aucune période historique. Il n’est donc pas nécessaire de supprimer les bases.

## Validation

Les tests du cycle couvrent journaux stables, diagnostic IA nécessaire, répétition
d’un résultat, reprise après interruption, réussite/échec/délai dépassé IA,
démarrage manuel et politique d’arrêt désactivée. Les routes de polling et de
diagnostic compagnon sont contrôlées avec leur authentification. La réconciliation
est couverte dans les tests incidents et administration. La vérification du
prochain cycle réel reste à effectuer après déploiement.
