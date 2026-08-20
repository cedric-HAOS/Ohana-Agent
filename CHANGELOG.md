# CHANGELOG

Toutes les évolutions importantes d'Ohana-Agent sont documentées dans ce fichier.

Le projet suit les principes de **Semantic Versioning**.

---

# [1.17.0] — Canal HTTPS dédié aux workers — 2026-08-20

## Ajouté

- Agent peut servir le protocole Katsuyu sur un listener HTTPS distinct de
  l'administration locale, avec certificat et clé configurables.
- L'appairage publie l'empreinte SHA-256 de l'autorité locale afin que
  l'installateur Katsuyu puisse épingler explicitement cette confiance.

## Sécurité

- Le listener worker n'expose que l'appairage, l'enregistrement, la prise de
  job, le heartbeat et la remise de résultat ; les routes de gestion y restent
  indisponibles.
- Les jetons individuels issus de l'appairage sont obligatoires sur ce canal :
  le jeton worker partagé historique n'y est jamais accepté.
- TLS 1.2 constitue la version minimale et le listener d'administration reste
  lié à l'interface locale en HTTP.

# [1.16.0] — Appairage Katsuyu et jobs déterministes — 2026-08-20

## Ajouté

- Agent enregistre les workers Katsuyu, expose leurs capacités à Tsunade et
  persiste une progression bornée pendant le renouvellement du bail.
- Les contrats stricts `backup.compress`, `backup.encrypt` et `backup.verify`
  complètent `system.health`, avec tailles et SHA-256 vérifiables.
- Le worker et l'installation Windows sont extraits dans le projet autonome
  Ohana-Katsuyu afin de ne pas installer Agent sur Bubule.
- Agent expose un appairage temporaire approuvé par Tsunade/Vision et lie le
  jeton délivré à l'identité du worker.

## Sécurité

- Le Bearer worker existant reste l'unique mécanisme d'authentification. Le
  jeton global demeure compatible, tandis que les nouvelles installations
  reçoivent un jeton individuel stocké uniquement sous forme de SHA-256.
- Le secret d'appairage expire, n'est jamais visible dans Vision et le jeton
  individuel n'est délivré qu'une seule fois après approbation explicite.
- Un heartbeat terminal n'est retourné qu'au worker et à la tentative qui
  possédaient effectivement le job.

# [1.15.2] — Arrêt Agent sans faux incident DHCP — 2026-08-20

## Corrigé

- Le helper DHCP considère la disparition attendue de sa requête avec le
  répertoire d'exécution de l'Agent comme une absence de travail, sans laisser
  `ohana-dhcp-reload.service` en échec lors d'un arrêt ou d'une mise à jour.

# [1.15.1] — Export non bloquant et premier worker Katsuyu — 2026-08-20

## Ajouté

- La commande `ohana-katsuyu` réclame exclusivement les types de jobs pour
  lesquels un handler local existe et exécute `system.health` sans shell, LLM
  ni paramètre libre.
- Katsuyu réutilise le jeton worker, les ACL et les endpoints de jobs Agent
  introduits en 1.15.0 ; aucun nouveau transport ni système d'authentification
  n'est ajouté.

## Corrigé

- La livraison durable vers Vision reste asynchrone après la mise en file. Un
  rattrapage volumineux ne bloque plus le scheduler, MQTT ou la publication de
  la santé de l'hôte Agent.

## Validation

- 1 308 tests réussis, 1 ignoré, Ruff et tests du cycle complet
  `system.health` Katsuyu vers Agent validés.

# [1.15.0] — Protection INFRA-01 et jobs distribués — 2026-08-20

## Ajouté

- Un protocole de jobs Tsunade vers Katsuyu, optionnel et désactivé par
  défaut, avec authentification worker distincte, types autorisés, validation
  stricte, timeout, bail, reprise, idempotence, rétention et résultat vérifié
  par SHA-256.
- Le premier contrat déterministe `system.health`, sans paramètre libre, pour
  mesurer les ressources de l'hôte Katsuyu sans LLM.
- La télémétrie de l'hôte publie désormais la RAM totale et disponible, le
  swap et la température lorsqu'elle est accessible.

## Modifié

- La file d'observations Vision est bornée et compactable afin de protéger la
  mémoire et le stockage d'INFRA-01.
- La sauvegarde INFRA-01 vérifie la capacité du tmpfs avant l'instantané et
  expose des diagnostics de ressources plus précis.

## Validation

- 1302 tests réussis, 1 ignoré, Ruff et contrôles de distribution validés.

# [1.14.4] — Fin correcte du chiffrement INFRA-01 — 2026-08-13

## Corrigé

- La sauvegarde INFRA-01 ferme désormais explicitement le flux envoyé à
  `age` avant d'attendre la fin du chiffrement. Le processus ne reste plus
  bloqué indéfiniment après la création de l'archive.
- L'état d'exécution de la sauvegarde redevient disponible après la fin du
  chiffrement au lieu de rester sur `Backup in progress`.

## Validation

- 1285 tests réussis, 1 ignoré, Ruff et contrôles de distribution validés.

# [1.14.3] — Archive INFRA-01 adaptée au tmpfs — 2026-08-13

## Corrigé

- L'archive tar d'INFRA-01 est désormais compressée en flux avant son
  chiffrement avec `age`, afin que l'instantané SQLite et l'archive puissent
  coexister dans le tmpfs sans saturer `/run`.
- Agent vérifie avant la sauvegarde que le tmpfs peut contenir l'instantané
  Vision et une réserve minimale pour l'archive.
- Si `age` interrompt le flux, son diagnostic est désormais remonté à la place
  du message générique `[Errno 32] Broken pipe`.

## Validation

- 1285 tests réussis, 1 ignoré, Ruff et contrôles de distribution validés.

# [1.14.2] — Inventaire Vision via l'API locale — 2026-08-13

## Corrigé

- La sauvegarde INFRA-01 lit la version de Vision depuis son API locale
  `/api/version`, accessible au compte `ohana-agent`, sans tenter d'exécuter un
  binaire protégé dans l'environnement privé du compte `ohana-vision`.

## Validation

- 1283 tests réussis, 1 ignoré, Ruff et contrôles de distribution validés.

# [1.14.1] — Inventaire Vision fiable pour les sauvegardes — 2026-08-13

## Corrigé

- La sauvegarde INFRA-01 lit la version de Vision depuis son propre
  environnement `/opt/ohana-vision/venv`, au lieu de la rechercher à tort dans
  l'environnement Python séparé d'Agent.

## Validation

- 1282 tests réussis, 1 ignoré, Ruff et contrôles de distribution validés.

# [1.14.0] — Identité age gérée pour INFRA-01 — 2026-08-13

## Modifié

- La sauvegarde INFRA-01 lit automatiquement son destinataire public dans
  `/etc/ohana-agent/keys/infra-01.agepub`.
- Avant chaque sauvegarde, Agent envoie et valide la copie de récupération de
  l'identité dans `icloud:Ohana/Recovery/infra-01.agekey`.
- L'ancien champ direct `age_recipient` reste accepté pour la migration.

## Validation

- 1279 tests réussis, 1 ignoré, Ruff et contrôles de distribution validés.

# [1.13.1] — Identité du plugin Sauvegardes — 2026-08-13

## Corrigé

- Le plugin est désormais présenté comme **Sauvegardes**, puisqu'il protège à
  la fois les systèmes HAOS et INFRA-01.
- Son manifeste décrit l'ensemble des sauvegardes Ohana et passe en version
  interne `0.2.0`.

# [1.13.0] — Sauvegarde logique d'INFRA-01 — 2026-08-13

## Ajouté

- Le plugin `backup` archive les configurations Agent, Vision, dnsmasq et
  Chrony ainsi qu'un instantané SQLite cohérent de Vision.
- L'archive est produite et chiffrée avec `age` dans un `tmpfs`, puis envoyée
  directement vers iCloud sans staging sur la carte microSD.
- Un descripteur placé dans l'archive chiffrée lie son identité, sa date et ses
  versions au manifeste public utilisé par Ohana-Installer.
- La sauvegarde peut être planifiée ou lancée immédiatement avec l'identifiant
  strict `infra-01`.

## Sécurité

- Le manifeste est publié uniquement après validation distante de l'archive.
- La rétention iCloud est désactivée par défaut. Lorsqu'elle est activée, elle
  protège la nouvelle sauvegarde et ne supprime que d'anciens dossiers complets.
- La clé privée `age` n'est jamais enregistrée sur INFRA-01.

## Validation

- 1278 tests réussis, 1 ignoré, Ruff et contrôles de distribution validés.

# [1.12.7] — Streaming HAOS sans Content-Length — 2026-08-11

## Corrigé

- Le téléchargement d'une sauvegarde HAOS utilise désormais la taille exacte
  publiée par `backup/info` lorsque Home Assistant diffuse l'archive sans
  en-tête HTTP `Content-Length`.
- Le flux reste strictement borné : Agent refuse encore l'envoi si ni les
  métadonnées HAOS ni la réponse HTTP ne fournissent une taille positive.
- La protection de la carte microSD d'INFRA-01, le streaming vers rclone et la
  validation de la taille distante restent inchangés.

# [1.12.6] — Sauvegardes HAOS immédiates — 2026-08-11

## Ajouté

- L'administration peut déclencher immédiatement la sauvegarde d'une cible
  HAOS précise. L'appel répond sans attendre la création et l'envoi de
  l'archive, tandis que l'exécution continue en arrière-plan dans Agent.
- Le déclenchement vérifie l'identifiant exact de la cible, son activation et
  celle du plugin, et refuse une seconde exécution simultanée pour la même
  cible.
- L'état d'exécution de chaque cible est exposé à Vision jusqu'à la fin réelle
  de la tâche afin d'empêcher un nouveau déclenchement depuis l'interface.

# [1.12.5] — Configuration sécurisée dans Vision — 2026-08-11

## Modifié

- Les jetons Home Assistant et les mots de passe de chiffrement peuvent être
  enregistrés directement depuis les champs masqués de Vision. Une valeur
  laissée vide conserve le secret déjà enregistré.
- Le client de sauvegarde utilise les commandes WebSocket publiques
  `backup/info`, `backup/generate` et `backup/delete`, ainsi que la route
  publique de téléchargement de Home Assistant.
- Agent pilote la création ou la reconnexion du remote iCloud avec le protocole
  non interactif de rclone et une seconde étape 2FA.

## Sécurité

- Les secrets directs et la configuration rclone sont protégés en mode `0600`
  et ne sont jamais renvoyés par l'API d'administration.
- L'ancien fichier `backup.env` reste accepté uniquement comme mécanisme de
  migration.

# [1.12.4] — Sauvegardes HAOS chiffrées vers iCloud — 2026-08-11

## Ajouté

- Le plugin `backup` crée des sauvegardes complètes et chiffrées de HA-01,
  LINKY-01 et ZWAVE-01, puis les transmet directement à iCloud avec `rclone`
  sans écrire l'archive sur la carte microSD d'INFRA-01.
- Chaque cible dispose de sa propre activation, adresse HAOS, heure
  quotidienne, délai, politique TLS et action préparatoire optionnelle. La
  cible ZWAVE-01 peut ainsi attendre un export NVM avant la sauvegarde HAOS.
- L'administration Agent expose la configuration du plugin à Vision et
  l'applique immédiatement avec replanification atomique des tâches.

## Sécurité

- Les jetons HAOS et mots de passe de chiffrement sont lus depuis le fichier
  protégé `/etc/ohana-agent/backup.env` ou depuis l'environnement du processus,
  sans être renvoyés à Vision.
- Une ancienne sauvegarde Ohana n'est supprimée du HAOS qu'après envoi de
  l'archive, validation de sa taille distante et publication de son SHA-256.
- Les fichiers temporaires rclone sont refusés hors `tmpfs` par défaut.
- Le diagnostic immédiat vérifie les accès HAOS et rclone sans créer, envoyer
  ni supprimer de sauvegarde.

## Qualité

- Tests de configuration, planification cron, API HAOS, chiffrement, streaming,
  validation distante, rotation locale, lecture sécurisée des secrets et
  administration depuis Vision.

---

# [1.12.3] — Santé hôte partagée et uptimes lisibles — 2026-08-10

## Modifié

- La santé de la machine hôte est collectée une seule fois par Agent puis
  publiée à l'identique vers Home Assistant et Vision.
- Les uptimes de l'hôte et d'Agent sont affichés sous forme compacte en jours,
  heures et minutes, tout en conservant les secondes brutes dans le snapshot.
- Les services redondants déterminent désormais aussi l'état global, les
  incidents critiques et l'impact sur leur équipement. La perte d'un seul DNS
  produit un service et un état global dégradés ; le DNS n'est indisponible que
  si toutes ses instances le sont.
- Les installations existantes possédant plusieurs DNS activés bénéficient
  automatiquement du groupe logique `dns`, même si leur ancien fichier de
  configuration ne contient pas encore `availability_group`.

## Ajouté

- Agent transmet à Vision une observation `host.health` avec les ressources,
  la température disponible, les uptimes et les diagnostics systemd.

## Qualité

- Tests du formatage des durées, du mapping d'observation, du reporter partagé
  et des scénarios DNS partiellement ou totalement indisponible avec Z-Wave.

---

# [1.12.2] — Correctif santé hôte et helper DHCP — 2026-08-10

## Corrigé

- Les modèles MQTT Discovery des métriques hôte optionnelles produisent
  désormais un template Jinja valide. CPU, charge normalisée, mémoire, swap,
  disque et uptime hôte ne restent plus à `Inconnu` lorsque la valeur est
  disponible.
- Le point d'entrée privilégié du helper DHCP ne charge plus les modèles
  Pydantic de l'API d'administration. Il reste exécutable lorsqu'une demande
  DHCP arrive pendant le remplacement de l'environnement Python d'Agent.

## Qualité

- Tests de non-régression sur le modèle MQTT exact et sur l'absence
  d'importation de Pydantic par le point d'entrée DHCP.

---

# [1.12.1] — Santé hôte et services redondants — 2026-08-10

## Ajouté

- Agent publie dans Home Assistant un appareil « Ohana Host » distinct avec
  l'état synthétique de la machine, le CPU, la charge normalisée, la mémoire,
  le swap, le disque racine, la température lorsqu'elle est disponible et les
  uptimes de l'hôte et d'Agent.
- Les redémarrages automatiques d'Agent et les unités systemd Ohana en échec
  sont exposés avec les raisons de dégradation ou d'incident critique.
- Les pressions CPU, charge, mémoire, swap et température doivent persister
  pendant trois mesures avant d'affecter la santé ; un disque presque plein,
  une boucle de redémarrage ou une unité Ohana en échec sont signalés
  immédiatement.

## Modifié

- Les instances partageant `metadata.availability_group` sont comptées comme
  un service logique dans la synthèse Home Assistant. Une panne partielle du
  DNS redondant produit ainsi un service dégradé, sans masquer les alertes
  techniques propres à chaque instance.

## Qualité

- Tests déterministes de collecte procfs/sysfs, seuils persistants,
  récupération, incidents immédiats, MQTT Discovery et agrégation DNS.
- Suite complète, lint, formatage, paquets et installation isolée validés avant
  publication.

---

# [1.12.0] — Livraison durable vers Vision — 2026-08-10

## Ajouté

- Les observations destinées à Ohana-Vision sont enregistrées dans une outbox
  SQLite avant leur première tentative d'envoi.
- Un worker rejoue automatiquement le backlog dans son ordre d'origine après
  une indisponibilité ou un redémarrage, sans dupliquer les observations déjà
  acceptées par Vision.
- Les réglages `vision.outbox_path` et `vision.outbox_retry_seconds` permettent
  d'adapter le stockage et la cadence de reprise ; la production utilise par
  défaut `/var/lib/ohana-agent/vision-outbox.db`.

## Modifié

- Le contrat Agent vers Vision expose désormais l'identifiant immuable et le
  message de l'observation au premier niveau du document JSON.
- Une panne de Vision après la synchronisation initiale ne suspend plus les
  contrôles : les observations continuent et restent garanties sur disque.

## Qualité

- Tests de redémarrage, déduplication, ordre de rejeu et reprise automatique.
- Suite complète, lint, formatage et installation isolée validés avant
  publication.

---

# [1.11.11] — Alertes Home Assistant contextualisées — 2026-08-10

## Modifié

- Le capteur Home Assistant « Alertes actives » expose les équipements et les
  capacités affectés, ainsi qu'un détail stable de chaque anomalie, sans ajouter
  une entité par équipement ou par capacité.
- Le capteur MQTT Discovery « Dernière évaluation » est supprimé de
  Home Assistant afin de ne plus encombrer le journal avec un horodatage à
  chaque nouvelle synthèse. L'horodatage reste présent dans la synthèse MQTT.
- Le message critique détaillé reste disponible dans la synthèse MQTT brute,
  mais n'est plus exposé comme attribut Home Assistant susceptible de devenir
  périmé entre deux changements d'état significatifs.
- Les changements d'infrastructure réinitialisent correctement l'état de
  déduplication des synthèses Home Assistant.

## Qualité

- Le test MQTT Discovery vérifie la suppression automatique de l'ancienne
  entité déjà enregistrée.
- Des tests garantissent qu'un changement d'horodatage ou de message seul ne
  republie rien, tandis qu'un changement de santé est publié immédiatement.

---

# [1.11.10] — Synthèse Home Assistant stable — 2026-08-07

## Corrigé

- La synthèse MQTT Home Assistant n'est plus republiée lorsque seul son
  horodatage change ; seuls les changements de santé significatifs créent un
  nouvel état.
- Le battement périodique ne provoque plus de nouvelle évaluation visible dans
  Home Assistant lorsque la santé reste inchangée.
- Les entités Discovery ne deviennent plus faussement indisponibles entre deux
  synthèses stables.

## Qualité

- Version du paquet alignée sur `1.11.10`.

---

# [1.11.9] — Correction test ping — 2026-08-05

## Modifié

- Une réponse ICMP Windows n’est désormais valide que si elle contient un TTL..

## Qualité

- Tests adaptés.
- Version du paquet alignée sur `1.11.9`.

---

# [1.11.8] — Type dédié aux modules Z-Wave — 2026-08-04

## Modifié

- Les équipements découverts par Z-Wave JS sont désormais publiés avec le
  type explicite `zwave_module`, distinct des passerelles et des objets
  connectés génériques.
- Le contrat de topologie accepte officiellement le type « Module Z-Wave ».

## Qualité

- Tests de découverte adaptés pour vérifier le nouveau type tout en préservant
  les équipements manuels existants.
- Version du paquet alignée sur `1.11.8`.

---

# [1.11.7] — Découverte automatique des nœuds Z-Wave — 2026-08-04

## Ajouté

- Le plugin Z-Wave découvre automatiquement les nœuds exposés par Z-Wave JS
  via WebSocket et les projette dans la topologie publiée vers Vision.
- Une observation `zwave.node.alive` est publiée pour chaque équipement afin
  d’exposer explicitement son état vivant, mort ou inconnu.
- Les états `alive`, `awake` et `asleep` sont considérés sains afin qu’un
  équipement sur batterie endormi ne soit pas signalé en panne.

## Modifié

- La topologie Z-Wave ne reproduit pas le maillage radio : chaque équipement
  découvert est uniquement rattaché à la passerelle `zwave_gateway`.
- La configuration de production déclare `ZWAVE-01` et le service Z-Wave JS
  WebSocket sur le port 3000.

## Qualité

- Tests de découverte, réconciliation, retrait de nœud, panne du contrôleur et
  intégration complète du démarrage Agent vers Vision.
- Version du paquet alignée sur `1.11.7`.

---

# [1.11.6] — Cohérence des capacités suspendues — 2026-08-04

## Corrigé

- Les suspensions planifiées du plugin de télémétrie Home Assistant publient
  désormais la capacité publique `home_assistant.telemetry.freshness`, comme
  les observations exécutées, au lieu de la commande interne
  `home_assistant_telemetry.freshness`.
- La timeline ne conserve plus deux capacités concurrentes pouvant maintenir
  un ancien état indisponible pendant une plage de surveillance inactive.

## Qualité

- Test du chemin suspendu pour garantir l'identifiant envoyé à Ohana-Vision.
- Version du paquet alignée sur `1.11.6`.

---

# [1.11.5] — Routage des suspensions d’équipements — 2026-08-01

## Corrigé

- Les observations suspendues des équipements conservent désormais le
  discriminant `target_type: device` normalement ajouté par le plugin réseau.
- Une surveillance planifiée hors plage est ainsi routée vers l’équipement
  concerné au lieu d’être interprétée comme un service d’infrastructure.

## Qualité

- Reproduction du second crash observé sur Infra-01 après le déploiement de
  1.11.4 pour la surveillance planifiée de `SUN-01`.
- Tests du routage suspendu, du moteur d’observation et de l’export Vision.
- Version du paquet alignée sur `1.11.5`.

---

# [1.11.4] — Stabilité des surveillances planifiées — 2026-08-01

## Corrigé

- Les observations suspendues hors de leur plage horaire sont désormais
  exportées vers Ohana-Vision avec l'état `unknown`, seul état neutre accepté
  par le contrat Vision, au lieu de provoquer l'arrêt d'Ohana-Agent.
- Les métadonnées `monitoring_suspended` et `next_activation` sont conservées
  afin de distinguer une suspension planifiée d'une panne.

## Qualité

- Test du mapping de tous les états Agent, y compris `SUSPENDED`.
- Test d'intégration de l'export HTTP d'une observation suspendue vers Vision.
- Version du paquet alignée sur `1.11.4`.

---

# [1.11.3] — Stabilité MQTT Home Assistant — 2026-08-01

## Corrigé

- Les mises à jour d’infrastructure ne redémarrent plus la connexion MQTT
  lorsque sa configuration est inchangée et ne publient donc plus un faux état
  `offline` dans Home Assistant.
- Le résumé de santé MQTT est désormais retenu afin de restaurer immédiatement
  l’état des entités après une reconnexion de Home Assistant.

## Qualité

- Test de non-régression vérifiant qu’une reconfiguration d’infrastructure ne
  déconnecte pas le publisher et ne publie pas `offline`.
- Version du paquet alignée sur `1.11.3`.

---

# [1.11.2] — Résolution des serveurs DNS nommés — 2026-07-31

## Corrigé

- Résolution préalable des noms d’hôte utilisés comme serveurs DNS explicites
  afin de fournir à `dnspython` l’adresse IP qu’il exige, sans modifier le nom
  de serveur publié dans les observations.

## Qualité

- Tests de résolution des serveurs DNS nommés et des erreurs de résolution.
- Version du paquet alignée sur `1.11.2`.

---

# [1.11.1] — Application fiable des réservations DHCP — 2026-07-31

## Ajouté

- Helper privilégié `ohana-agent-dhcp-reload-helper` chargé d’appliquer les
  changements DHCP sans donner au processus Agent un accès direct à la base des
  baux dnsmasq.

## Corrigé

- Suppression ciblée des anciens baux qui contredisent une nouvelle réservation
  par adresse MAC ou par adresse IPv4 avant le redémarrage de dnsmasq.
- Lecture correcte des serveurs DNS NetworkManager lorsque `nmcli` les sépare
  avec le caractère `|`.
- Autorisation du helper NetworkManager restreint par sudo depuis l’unité
  `ohana-agent.service`.

## Qualité

- Validation du format de la demande privilégiée, des adresses MAC et du
  redémarrage systématique de dnsmasq même si la purge échoue.
- Version du paquet alignée sur `1.11.1`.

---

# [1.11.0] — Lot C : administration réseau sécurisée — 2026-07-30

## Ajouté

- Lecture de l’état NetworkManager de l’hôte Agent : interface, connexion,
  adresse IPv4, passerelle, DNS et mode statique ou DHCP.
- API d’administration `system.network.*` pour préparer, appliquer, confirmer
  ou restaurer une configuration réseau.
- Helper privilégié limité `ohana-agent-network-helper`, sans droit root
  général pour le processus Agent.
- Application des changements avec sauvegarde et retour automatique entre 30
  et 300 secondes si la nouvelle configuration n’est pas confirmée.

## Sécurité

- Une seule transaction réseau peut être en attente à la fois.
- Les interfaces, adresses, passerelles, DNS et identifiants de transaction sont
  validés avant toute commande NetworkManager.
- Les instantanés de restauration sont conservés dans un répertoire root en
  permissions `0700`, avec fichiers `0600`.

## Qualité

- Tests des modèles réseau, du repository, des routes HTTP et du refus d’une
  seconde transaction en attente.
- Version du paquet alignée sur `1.11.0`.

---

# [1.10.0] — Lot B : Téléinformation directe et plages de surveillance — 2026-07-30

## Ajouté

- Récepteur HTTP authentifié dédié aux trames décodées envoyées directement par
  `teleinfo2mqtt`, sans dépendance à Home Assistant ni au broker de HA-Green.
- Mode `direct_http` du plugin Téléinformation, avec identification de la source
  et du compteur Linky, contrôle de `SINSTS`, `NTARF` et de l’index Tempo actif.
- Plages horaires facultatives sur les équipements, avec fuseau horaire, jours
  actifs et délai de démarrage.
- État `suspended` publié lors de la suspension planifiée et exclu des incidents
  et de la dégradation de la santé globale.

## Compatibilité

- Le mode historique Home Assistant reste accepté pour les configurations
  Téléinformation existantes.
- Une seule observation de suspension est publiée par période continue afin de
  ne pas remplir inutilement l’historique.

## Qualité

- Tests du récepteur HTTP, de son authentification, du stockage des trames, du
  contrôle direct Tempo et des plages horaires, y compris les périodes passant
  minuit et le délai de démarrage.
- Version interne du plugin Téléinformation portée à `0.2.0`.
- Version du paquet alignée sur `1.10.0`.

---

# [1.9.0] — Lot A : télémétrie générique et cibles réseau — 2026-07-30

## Ajouté

- Plugin `home_assistant_telemetry` et capacité `home_assistant.telemetry.freshness`.
- Prise en charge des noms d’hôte et noms DNS pour les équipements.
- Adresse résolue exposée dans les observations de présence réseau.

## Modifié

- Shelly Telemetry devient **Télémétrie Home Assistant**.
- Les services et configurations `shelly_telemetry` restent acceptés pendant la migration.
- Nouvel argument `--home-assistant-telemetry-config`, avec ancien argument conservé comme alias.

---

# [1.8.1] — Fraîcheur Tempo contextuelle — 2026-07-29

## Corrigé

- `NTARF` n’est plus considéré comme une télémétrie devant être actualisée en
  continu : sa valeur reste validée, mais son ancienneté est normale entre les
  bascules de 6 h et 22 h.
- Seuls `SINSTS` et l’index Tempo désigné par la valeur courante de `NTARF`
  doivent présenter une mesure récente.
- Les cinq index Tempo inactifs restent disponibles dans les métadonnées sans
  dégrader le service lorsque leur horodatage est ancien.
- Une grâce de 30 secondes évite une fausse alerte lorsque `NTARF` bascule juste
  avant la première mise à jour du nouvel index actif.
- Version interne du plugin Téléinformation portée à `0.1.1`.

## Qualité

- Tests de non-régression ajoutés pour un `NTARF` ancien, des index inactifs
  anciens, un index actif ancien et la courte transition de période Tempo.
- Version du paquet alignée sur `1.8.1`.

# [1.8.0] — Téléinformation Linky — 2026-07-29

## Ajouté

- Nouveau plugin `teleinformation` et capacité
  `teleinformation.freshness`.
- Contrôle de la chaîne Linky → série → `teleinfo2mqtt` → MQTT → Home
  Assistant à partir des entités `SINSTS` et `NTARF`.
- Lecture facultative des six index Tempo `EASF01` à `EASF06`.
- Interprétation automatique de la couleur Bleue, Blanc ou Rouge et de la
  période HC ou HP à partir de `NTARF`.
- Configuration et test immédiat depuis l’administration des plugins.
- Déclaration par service dans `infrastructure.yaml`, avec une tâche périodique
  par compteur Linky.

## Qualité

- Tests unitaires du client Home Assistant, de la fraîcheur, du mapping Tempo,
  du builder, du plugin et du parcours scheduler → Vision.
- Version du paquet alignée sur `1.8.0`.

# [1.7.5] — Exécution planifiée Shelly Telemetry — 2026-07-29

## Corrigé

- Les tâches périodiques Shelly utilisent désormais la commande
  `shelly_telemetry.freshness`, conforme à l’identifiant enregistré du plugin.
- Le dispatcher ne cherche plus un plugin inexistant nommé `shelly` lors des
  exécutions automatiques.
- Les observations programmées sont de nouveau publiées vers Vision et peuvent
  alimenter l’état du service et de l’équipement.
- Version interne du plugin Shelly Telemetry portée à `0.2.1`.

## Qualité

- Test de non-régression complété sur la commande générée et son exécution
  réelle à travers le dispatcher et le pipeline d’observation.
- 1 158 tests réussis après construction du wheel et du sdist.
- Version du paquet alignée sur `1.7.5`.

# [1.7.4] — Replanification Shelly Telemetry — 2026-07-29

## Corrigé

- La reconfiguration du plugin Shelly Telemetry reconstruit désormais ses
  services à partir de l’infrastructure d’exécution courante.
- L’application d’une architecture contenant des services
  `shelly_telemetry` recrée immédiatement les tâches correspondantes.
- Les tâches périodiques Shelly restent cohérentes après modification de la
  connexion Home Assistant ou de l’intervalle du plugin.

## Qualité

- Test de non-régression ajouté pour deux services Shelly ajoutés par
  l’architecture puis replanifiés par la configuration globale.
- 1 158 tests réussis après construction du wheel et du sdist.
- Version du paquet alignée sur `1.7.4`.

# [1.7.3] — Shelly Telemetry par service — 2026-07-28

## Ajouté

- Publication MQTT du résumé de santé global sur `ohana/health/summary`.
- MQTT Discovery Home Assistant pour le score, l'état global, les incidents
  critiques, les alertes, les services dégradés ou indisponibles, les capacités
  sans observation récente et la date de dernière évaluation.
- Topic de disponibilité `ohana/status` avec Last Will MQTT.
- Paramètres Home Assistant intégrés au plugin MQTT : activation, Discovery,
  préfixes et battement périodique.

## Corrigé

- Shelly Telemetry est désormais déclaré comme un service rattaché au nœud de
  l’équipement, au lieu d’utiliser des métadonnées particulières sur la carte.
- Les observations ciblent le service déclaré, ce qui permet à la criticité du
  service d’alimenter naturellement la santé, les alertes et les incidents.
- L’entité de puissance, l’entité d’énergie facultative et l’âge maximal sont
  configurés dans les métadonnées de chaque service `shelly_telemetry`.

## Qualité

- Version du paquet alignée sur `1.7.3`.
- 1157 tests réussis.

# [1.7.2] — Z-Wave JS Server WebSocket — 2026-07-28

## Corrigé

- Le plugin `zwave` utilise désormais le protocole WebSocket de Z-Wave JS
  Server exposé par Home Assistant sur le port `3000`.
- Le contrôle attend l’initialisation complète du pilote Z-Wave avant de
  produire une observation saine.
- Les installations autonomes exposant encore `/health/zwave` en HTTP ou HTTPS
  restent prises en charge explicitement par les métadonnées du service.
- La sélection Shelly Telemetry et les identifiants d’entités Home Assistant
  sont désormais définis sur chaque équipement de la topologie, et non dans la
  configuration globale du plugin.
- Les observations Shelly ciblent maintenant directement l’équipement concerné.

## Ajouté

- Versions du serveur et du pilote, identifiant Home ID et nombre de nœuds dans
  les métadonnées de l’observation `zwave.status`.
- Version d’Ohana-Agent dans la réponse `/v1/capabilities` de l’API
  d’administration, pour affichage dans Vision.
- Dépendance d’exécution `zwave-js-server-python`.

## Qualité

- Version du paquet alignée sur `1.7.2`.
- Tests dédiés au protocole WebSocket, au port `3000` par défaut et au contrat
  de version d’administration.
- 1150 tests réussis.

---

# [1.7.1] — Commande d’autorisation Freebox — 2026-07-28

## Corrigé

- Le script d’autorisation Freebox n’est plus dépendant du dépôt source sur INFRA-01.
- La configuration WireGuard de production est utilisée par défaut depuis
  `/etc/ohana-agent/plugins/wireguard.yaml`.

## Ajouté

- Commande installée `ohana-agent-authorize-freebox`.
- Module d’exécution inclus dans le wheel sous
  `plugins.wireguard.authorize_freebox`.
- Tests du stockage du jeton après validation et du refus d’autorisation.
- Vérification de la présence du nouvel exécutable dans les métadonnées du wheel.

## Qualité

- Version du paquet et version applicative Freebox alignées sur 1.7.1.
- 1144 tests réussis.
- Wheel et archive source Ohana-Agent 1.7.1 construites et vérifiées.

---

# [1.7.0] — Freebox WireGuard et Shelly Telemetry — 2026-07-27

## Corrigé

- Le plugin `wireguard` n’inspecte plus une interface locale sur INFRA-01.
- L’état du serveur WireGuard est désormais lu directement dans Freebox OS à partir du service WireGuard déclaré sur le nœud Freebox.

## Ajouté

- Authentification à l’API Freebox OS avec `app_id`, `app_token` et session temporaire.
- Contrôle de l’état `started` du serveur VPN `wireguard` et remontée du nombre de connexions lorsqu’il est disponible.
- Script `scripts/authorize_freebox.py` pour demander l’autorisation sur l’écran de la Freebox et enregistrer le jeton.
- Plugin `shelly_telemetry` et capacité `shelly.telemetry.freshness`.
- Vérification de la fraîcheur des capteurs de puissance et d’énergie Shelly via l’API REST de Home Assistant.
- Distinction entre une puissance valide de `0 W` et une télémétrie qui n’est plus remontée.
- Masquage et conservation des jetons Freebox et Home Assistant dans l’administration des plugins.
- Nouvel argument `--shelly-telemetry-config` et intégration au service systemd.

## Qualité

- 1140 tests unitaires, d’intégration, HTTP et de packaging réussis.
- Wheel et archive source 1.7.0 construites et vérifiées.

---

# [1.6.0] — Z-Wave et WireGuard — 2026-07-27

## Ajouté

- Plugin intégré `zwave` et capacité `zwave.status`.
- Interrogation de l’état de connexion de Z-Wave JS UI via son point de santé.
- Découverte des services Z-Wave depuis `infrastructure.yaml`, avec port 8091 par défaut.
- Plugin intégré `wireguard` et capacité `wireguard.status`.
- Inspection locale des interfaces WireGuard avec `wg show` et contrôle optionnel de l’âge du dernier échange d’un pair.
- Reconfiguration à chaud, planification et test immédiat des deux plugins depuis Vision.
- Nouveaux arguments `--zwave-config` et `--wireguard-config`.

## Sécurité

- Le plugin WireGuard exécute uniquement la commande fixe `wg show <interface> latest-handshakes`.
- Aucune clé privée WireGuard n’est lue ni exposée dans les observations.
- La vérification TLS du plugin Z-Wave reste activée par défaut.

## Qualité

- 1131 tests unitaires, d’intégration, HTTP et de packaging réussis.
- Tests dédiés aux chargeurs, constructeurs, politiques, reprises et contrats d’observation.
- Service systemd, scripts de déploiement et artefacts de distribution mis à jour.

---

# [1.5.0] — Observation DHCP — 2026-07-27

## Ajouté

- Plugin intégré `dhcp` et capacité `dhcp.status`.
- Découverte automatique des services de type `dhcp` depuis
  `infrastructure.yaml`.
- Vérification locale de l’état `dnsmasq` sans demande de bail artificielle.
- Réutilisation du lecteur dnsmasq existant pour la configuration et les baux.
- Lecture de la plage IPv4 configurée et des baux dnsmasq actifs.
- Exclusion des baux expirés, des adresses hors plage et des doublons.
- Calcul du nombre d’adresses disponibles et du taux d’occupation de la plage.
- Seuil configurable transformant une occupation excessive en observation
  indisponible.
- Reconfiguration à chaud, reconstruction des tâches et test immédiat depuis
  l’administration des plugins.
- Nouvel argument `--dhcp-config`, fichier de configuration et intégration au
  service systemd.
- Déclaration du service `dhcp-primary` dans l’infrastructure de production.
- La surveillance de présence réseau peut être activée ou désactivée pour
  chaque équipement depuis
  `topology.devices[].metadata.network_presence_enabled`.

## Sécurité

- La commande `systemctl is-active dnsmasq.service` est définie dans le code et
  ne peut pas être remplacée par une requête d’administration.
- Le plugin lit les fichiers dnsmasq mais ne les modifie jamais.
- L’administration existante des paramètres et réservations DHCP reste séparée
  du plugin d’observation.

## Qualité

- 1115 tests unitaires, d’intégration, HTTP et de packaging réussis.
- Construction et installation validées des artefacts wheel et sdist 1.5.0.

## Contrat d’observation

- `capability_id` : `dhcp.status` ;
- `service_id` : identifiant du service DHCP ;
- métadonnées : état du service, plage, taille du pool, baux actifs, baux
  expirés et taux d’occupation.

# [1.4.0] — Présence réseau des équipements — 2026-07-27

## Ajouté

- Plugin intégré `network` et capacité `network.reachable`.
- Découverte automatique des équipements de topologie disposant d'une adresse
  directe ou rattachés à un nœud avec endpoint IP.
- Vérification légère par ICMP, complétée par la table ARP locale lorsqu'un
  équipement ne répond pas au ping.
- Répartition des contrôles sur tout l'intervalle pour éviter une rafale de
  requêtes lorsque plusieurs équipements sont déclarés.
- Validation des adresses IP portées directement par les équipements de
  topologie.
- Délai configurable, retries immédiats et seuil de plusieurs cycles échoués
  avant de déclarer un équipement indisponible.
- État `unknown` pendant la confirmation d'une absence ou lorsque la commande
  système de vérification n'est pas disponible.
- Observations de présence séparées de la santé globale des services et de
  l'infrastructure.
- Reconfiguration automatique des tâches après une modification de la
  topologie depuis Ohana-Vision.
- Administration, test immédiat sans modification de l'historique des échecs,
  configuration CLI et unité systemd du plugin réseau.

## Qualité

- 1088 tests unitaires, d'intégration, HTTP et de packaging réussis.
- Construction validée des artefacts wheel et sdist 1.4.0.

## Contrat d'observation

- `capability_id` : `network.reachable` ;
- `service_id` : identifiant de l'équipement ;
- `node_id` : nœud rattaché, ou identifiant de l'équipement en son absence ;
- métadonnées : adresse, méthode, tentatives, échecs consécutifs et seuil.

# [1.3.0] — Administration des plugins — 2026-07-27

## Ajouté

- Contrat public d’administration des plugins avec inventaire, lecture,
  modification et test immédiat.
- Exposition des états de cycle de vie, de planification, d’exécution et de la
  dernière erreur connue.
- Activation et désactivation persistantes des plugins DNS, NTP et MQTT.
- Reconfiguration à chaud et reconstruction des tâches du scheduler sans
  redémarrage de l’Agent.
- Écriture atomique avec restauration de la configuration précédente en cas
  d’échec d’application.
- Masquage du mot de passe MQTT et conservation du secret lorsque le champ est
  laissé vide par Vision.
- Tests immédiats `dns.resolve`, `ntp.query` et `mqtt.roundtrip`.
- Capacités `plugins.read`, `plugins.write` et `plugins.test`.
- Client SNTP natif sans dépendance Python supplémentaire.
- Découverte automatique des services de type `ntp` dans
  `infrastructure.yaml`.
- Observation `ntp.query` avec décalage d'horloge, temps aller-retour, strate,
  version NTP et indicateur de synchronisation.
- Politique de santé configurable par décalage maximal et strate maximale.
- Reconfiguration immédiate des tâches NTP après modification de
  l'infrastructure depuis Ohana-Vision.
- Configuration, CLI, service systemd, packaging et tests d'intégration dédiés.
- Plugin `mqtt.roundtrip` réalisant une connexion, un abonnement, une
  publication et la réception du message de test.
- Découverte automatique des services de type `mqtt` depuis
  `infrastructure.yaml`.
- Authentification MQTT, QoS et TLS configurables sans exposer les secrets dans
  les observations.
- Reconfiguration immédiate des tâches MQTT après modification de
  l'infrastructure depuis Ohana-Vision.
- Dépendance réseau `paho-mqtt` limitée à la couche d'observation MQTT, sans
  modification du transport MQTT interne du noyau.

## Qualité

- 1070 tests unitaires, d’intégration, HTTP et de packaging réussis.
- Construction validée des artefacts wheel et sdist 1.3.0.

---

# [1.2.1] — Découverte dynamique des services DNS

## Modifié

- Découverte automatique de tous les services de type `dns` depuis
  `infrastructure.yaml`.
- Suppression de la liste de services dupliquée dans `plugins/dns.yaml`.
- Création d'une tâche d'observation pour chaque couple service DNS / requête.
- Routage des observations par identifiant stable de service plutôt que par type.
- Reconfiguration immédiate des tâches DNS après une modification enregistrée
  depuis Ohana-Vision, sans redémarrage de l'Agent.
- Prise en charge de zéro, un ou plusieurs services DNS activés.

## Compatibilité

- La clé historique `services` de `dns.yaml` reste acceptée mais n'est plus
  utilisée, afin de ne pas invalider les installations existantes.

---

# [1.2.0] — Administration graphique — 2026-07-24

## Ajouté

- API d'administration locale, versionnée et protégée par jeton Bearer.
- Lecture et modification des paramètres DHCP, réservations et baux actifs.
- Validation de la configuration par `dnsmasq --test` avant rechargement.
- Écriture atomique et restauration automatique des fichiers DHCP en cas de rejet.
- Lecture, validation et écriture atomique de l'infrastructure.
- Synchronisation immédiate de l'architecture modifiée avec Ohana-Vision.
- Déclaration enrichie des services : implémentation, activation, criticité et métadonnées.
- Modèle Ohana-House complet avec DHCP, DNS, NTP, MQTT, Z-Wave,
  téléinformation et Home Assistant.

## Sécurité

- Écoute limitée à `127.0.0.1` par défaut.
- Authentification constante par secret partagé installé hors du dépôt.
- Chemins de fichiers et commandes système définis exclusivement par la
  configuration locale de l'Agent.
- Taille maximale des requêtes d'administration limitée à 1 Mio.

---

# [1.1.1] — Nommage Ohana cohérent

## Modifié

- Harmonisation du nom du projet, du package et des commandes avec `Ohana`.
- Préparation d'artefacts `ohana_agent` distincts de la release `v1.1.0`
  publiée avec l'ancien nom.
- Alignement du prérequis de développement documenté sur Python 3.13.

---

# [1.1.0] — Infrastructure et topologie synchronisées

## Ajouté

### Topologie déclarative

- Ajout de la topologie complète dans `config/infrastructure.yaml`.
- Déclaration des équipements, liens et layouts.
- Positionnement logique par cellules `column` / `row`.
- Conservation de la responsabilité du rendu et des coordonnées graphiques dans Ohana-Vision.
- Ajout des types d'équipements, de liens, de directions et de layouts alignés sur Vision.

### Contrat d'infrastructure vers Vision

- Ajout de `VisionInfrastructureMapper`.
- Transmission des nœuds, services, équipements, liens et layouts.
- Ajout de `HttpVisionClient.send_infrastructure()`.
- Envoi du snapshot par `PUT /api/infrastructure`.
- Versionnement explicite du contrat avec `schema_version`.

### Synchronisation persistante

- Première synchronisation obligatoire avant le démarrage des observations.
- Nouvelle tentative toutes les 10 secondes tant que Vision ne répond pas.
- Rafraîchissement du snapshot toutes les 5 minutes.
- Suspension du scheduler lorsque Vision devient indisponible.
- Reprise automatique après resynchronisation.
- Attentes interruptibles permettant un arrêt systemd propre.

### Validation

- Validation de l'unicité des équipements, liens et layouts.
- Validation des références entre nœuds, services et équipements.
- Validation des extrémités de liens.
- Validation des équipements positionnés.
- Rejet de plusieurs équipements dans une même cellule de grille.
- Activation du validateur d'infrastructure dans le bootstrap de production.

## Modifié

- Ohana-Agent devient la source de vérité de la définition d'infrastructure et de topologie.
- Les observations ne sont plus émises tant que Vision n'a pas accepté le snapshot courant.
- La configuration Vision comprend désormais les URL d'infrastructure et d'observation ainsi que les temporisations de retry et de refresh.
- Le bootstrap prépare le contrat de synchronisation sans effectuer d'appel réseau prématuré.

## Qualité

- 1000 tests unitaires et d'intégration.
- Validation Ruff.
- Validation réelle des quatre scénarios Agent ↔ Vision :
  - Vision démarrée avant Agent ;
  - Agent démarré avant Vision ;
  - perte et reprise de Vision ;
  - arrêt propre pendant la boucle de retry.

---

# [0.14.0] — Pipeline d'observation déclaratif

## Ajouté

### Infrastructure déclarative

* Ajout du chargement de `config/infrastructure.yaml`.
* Ajout d'un modèle de configuration typé (`InfrastructureConfig`).
* Ajout de `InfrastructureLoader`.
* Ajout de `InfrastructureBuilder`.
* Construction automatique du modèle métier `Infrastructure`.
* Validation de la cohérence des nœuds, services et endpoints.

### Configuration déclarative des plugins

* Ajout du fichier `config/plugins/dns.yaml`.
* Ajout de `DNSPluginConfig`.
* Ajout de `DNSConfigLoader`.
* Séparation entre configuration déclarative et configuration d'exécution.

### DNSConfigurationBuilder

* Ajout du composant `DNSConfigurationBuilder`.
* Construction automatique du `DNSConfig` à partir de :

  * `Infrastructure`
  * `DNSPluginConfig`
* Résolution automatique des services déclarés.
* Vérification du type des services.
* Vérification de la présence des endpoints.
* Génération automatique des serveurs DNS utilisés par le plugin.

### Pipeline d'exécution

Le pipeline complet est désormais :

```text
Scheduler
        │
DispatcherTaskExecutor
        │
PluginObservationDispatcher
        │
PluginObservationExecutor
        │
Plugin.execute()
        │
ObserverResult
        │
ObservationEngine
        │
ObservationPublished
        │
ObservationExportPipeline
        │
VisionObservationExporter
        │
Ohana-Vision
```

### Observation Engine

* Normalisation complète des observations.
* Publication d'événements `ObservationPublished`.
* Mise à jour automatique du runtime infrastructure.
* Export automatique des observations.

### Export Ohana-Vision

* Ajout de `VisionClient`.
* Ajout de `VisionObservationExporter`.
* Ajout de `ObservationExportPipeline`.
* Ajout de `ObservationExportHandler`.
* Sérialisation JSON standardisée des observations.

### Plugin DNS

Le plugin DNS est désormais capable de :

* charger automatiquement sa configuration ;
* résoudre les serveurs DNS depuis l'infrastructure déclarative ;
* mesurer la latence réelle des requêtes DNS ;
* produire des `ObserverResult` standardisés ;
* alimenter automatiquement le `ObservationEngine`.

Les métadonnées exportées contiennent désormais :

* hostname
* serveur DNS interrogé
* adresse IP obtenue
* erreur éventuelle

### Démonstration

Ajout d'un script de démonstration complet :

```text
scripts/demo_dns_pipeline.py
```

Le script réalise une exécution réelle :

* chargement des deux fichiers YAML ;
* résolution automatique du serveur DNS ;
* interrogation réelle du serveur DNS ;
* mise à jour du runtime ;
* génération d'une observation ;
* export vers un faux client Ohana-Vision.

Cette démonstration constitue le premier pipeline complet de bout en bout d'Ohana-Agent.

---

## Modifié

### Architecture

L'architecture est désormais entièrement orientée observations.

Les plugins ne produisent plus directement des états techniques.

Ils produisent des observations normalisées.

### Configuration DNS

Les adresses IP ne sont plus déclarées dans le plugin.

Le plugin référence désormais uniquement des identifiants de services définis dans l'infrastructure.

### Runtime

Le runtime infrastructure est automatiquement synchronisé avec les observations produites.

### Scheduler

Le Scheduler exécute désormais les plugins via le pipeline unifié d'observation.

---

## Qualité

* 851 tests unitaires et d'intégration.
* Validation Ruff.
* Typage Python.
* Architecture modulaire.
* Injection de dépendances.
* Configuration déclarative.
* Démonstration réelle de bout en bout validée.

---

# Historique

## v0.13.0

* Observation Engine.
* Infrastructure Runtime.
* Observation Export Pipeline.
* Plugin SDK unifié.
* Premier connecteur Ohana-Vision.

## v0.12.0

* Infrastructure Runtime.
* Observation Manager.
* Observation Factory.
* Observation Mapper.
* Observation Exporter.

## v0.11.0

* Plugin SDK.
* DNS Plugin.
* Capability Engine.
* Runtime Plugins.

## v0.10.0

* Scheduler.
* Dispatcher.
* EventBus.
* Runtime.

## v0.9.0

* Fondation de Shikamaru.
* Configuration.
* MQTT.
* Architecture logicielle.
* Cycle de vie de l'application.
