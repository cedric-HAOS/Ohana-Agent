# Administration graphique d'Ohana-Agent

Ohana-Vision permet de gérer les baux DHCP, l'architecture et les plugins sans
exposer les fichiers YAML à l'utilisateur. Ohana-Agent reste la source de vérité
et le seul composant autorisé à valider, écrire puis appliquer les
configurations.

## Flux

```text
Navigateur
    |
    | /api/administration/*
    v
Ohana-Vision
    |
    | Bearer token, boucle locale
    v
Ohana-Agent :8765
    |
    +-- infrastructure.yaml
    +-- fichiers dnsmasq gérés
    +-- plugins/dhcp.yaml
    +-- plugins/dns.yaml
    +-- plugins/ntp.yaml
    +-- plugins/mqtt.yaml
    +-- plugins/network.yaml
    +-- plugins/zwave.yaml
    +-- plugins/wireguard.yaml
    +-- plugins/home-assistant-telemetry.yaml
    +-- plugins/teleinformation.yaml
```

Le jeton n'est jamais envoyé au navigateur. Vision le lit dans
`/etc/ohana-vision/management.token` et l'utilise uniquement pour communiquer
avec l'Agent sur la boucle locale.

## Contrat versionné

| Méthode | Endpoint | Rôle |
|---|---|---|
| `GET` | `/v1/capabilities` | Découvrir les opérations disponibles |
| `GET` | `/v1/infrastructure` | Lire l'architecture courante |
| `PUT` | `/v1/infrastructure` | Valider et remplacer l'architecture |
| `GET` | `/v1/dhcp` | Lire les paramètres, réservations et baux |
| `PUT` | `/v1/dhcp` | Valider et remplacer la configuration DHCP |
| `GET` | `/v1/system/network` | Lire l’état NetworkManager de l’hôte Agent |
| `PUT` | `/v1/system/network` | Appliquer une configuration IPv4 avec retour automatique |
| `POST` | `/v1/system/network/{transaction_id}/confirm` | Confirmer la nouvelle configuration |
| `POST` | `/v1/system/network/{transaction_id}/rollback` | Restaurer immédiatement l’ancienne configuration |
| `GET` | `/v1/plugins` | Lister les plugins administrables et leur état |
| `GET` | `/v1/plugins/{plugin_id}` | Lire un plugin et sa configuration publique |
| `PUT` | `/v1/plugins/{plugin_id}` | Valider, enregistrer et appliquer sa configuration |
| `POST` | `/v1/plugins/{plugin_id}/test` | Exécuter un contrôle immédiat |

Les opérations sont annoncées explicitement par `/v1/capabilities` :

- `infrastructure.read` et `infrastructure.write` ;
- `dhcp.read`, `dhcp.write` et `dhcp.leases.read` lorsque DHCP est activé ;
- `plugins.read`, `plugins.write` et `plugins.test` lorsque l’administration des
  plugins est disponible ;
- `system.network.read`, `system.network.write`, `system.network.confirm` et
  `system.network.rollback` lorsque le helper NetworkManager est installé.

## Administration réseau de l’hôte

Ohana-Agent ne lance jamais `nmcli` avec les droits de son utilisateur de
service. Ohana-Installer déploie un helper root dédié et une règle `sudoers`
limitée à ce seul exécutable. Le document reçu depuis Vision ne peut contenir
ni chemin arbitraire ni commande système.

Lors d’une modification :

1. Agent valide l’interface, le mode IPv4, l’adresse, la passerelle et les DNS ;
2. le helper sauvegarde la connexion NetworkManager active ;
3. un rollback systemd est programmé entre 30 et 300 secondes ;
4. la nouvelle configuration est appliquée ;
5. Vision doit confirmer la transaction après reconnexion ;
6. sans confirmation, l’ancienne connexion est restaurée automatiquement.

Une seule transaction peut être en attente. Les instantanés sont stockés sous
`/var/lib/ohana-agent/network` avec des permissions réservées à root.

## Plugins administrables

L'inventaire provient du `PluginManager`. Un plugin ne peut donc pas apparaître
dans l'API s'il n'est pas réellement enregistré dans l'Agent.

La version 1.11.1 expose :

- **DHCP** — capacité `dhcp.status` ;
- **DNS** — capacité `dns.resolve` ;
- **NTP** — capacité `ntp.query` ;
- **MQTT** — capacité `mqtt.roundtrip` ;
- **Présence réseau** — capacité `network.reachable` ;
- **Z-Wave** — capacité `zwave.status` ;
- **WireGuard** — capacité `wireguard.status` ;
- **Télémétrie Home Assistant** — capacité `home_assistant.telemetry.freshness` ;
- **Téléinformation** — capacité `teleinformation.freshness`.

Pour chaque plugin, l'API fournit notamment :

- la version et l'état de cycle de vie ;
- l'activation ;
- le nombre de tâches planifiées et d'exécutions ;
- les dates de dernière et prochaine exécution ;
- la dernière erreur connue ;
- la configuration modifiable.

DHCP conserve aussi son contrat d’administration dédié pour modifier les
paramètres dnsmasq, les réservations et lire les baux. Le plugin `dhcp` est
strictement observationnel : il mesure l’état du service et l’occupation de la
plage sans modifier ces fichiers.

## Reconfiguration immédiate

Une écriture `PUT /v1/plugins/{plugin_id}` suit ce déroulement :

1. validation du document par le modèle Pydantic du plugin ;
2. écriture atomique du fichier YAML ;
3. reconfiguration du plugin déjà enregistré ;
4. suppression puis reconstruction de ses tâches planifiées ;
5. restauration du fichier et de la configuration précédente si l'application
   échoue.

L'activation ou la désactivation est appliquée sans redémarrer l'Agent. Un
plugin désactivé reste enregistré, mais ses tâches sont retirées du scheduler.

Les mots de passe MQTT ne sont jamais retournés. L'API indique uniquement si un
mot de passe existe. Une valeur vide lors d'une modification conserve le secret
déjà enregistré.

Pour DHCP, l’API peut modifier l’intervalle, le seuil d’occupation et
l’activation du contrôle de service. Le nœud et les chemins dnsmasq restent
issus de `shikamaru.yaml`. La commande système exécutée est définie dans le code
d’Agent et ne provient jamais du document reçu depuis Vision.

## Test immédiat

`POST /v1/plugins/{plugin_id}/test` exécute un contrôle ponctuel avec la
configuration courante :

- premier service DHCP activé ;
- première requête et premier service DNS activé ;
- premier service NTP activé ;
- premier courtier MQTT activé ;
- premier équipement adressable de la topologie.

Le résultat contient la réussite, le contrôle exécuté, le message, la latence,
la date et les métadonnées non sensibles. Le test ne modifie ni la
planification normale ni l'historique des échecs de présence réseau.

## Architecture administrable

Le document d'infrastructure transmis par `PUT /v1/infrastructure` contient les
nœuds, services, équipements, liaisons et layouts. Vision peut ainsi :

- déplacer un équipement en modifiant sa cellule `column` / `row` ;
- rattacher un service au nœud d'un équipement ;
- créer ou modifier une liaison et ses extrémités ;
- préciser la technologie, le sens et le débit de cette liaison.

Avant toute écriture, Agent vérifie les identifiants, les références entre
objets, l'unicité des cellules de grille et la validité de l'ensemble du modèle.

## Sécurité des modifications DHCP

L'Agent ne reçoit jamais de chemin de fichier ni de commande système dans la
requête HTTP. Ces valeurs proviennent exclusivement de sa configuration locale.

Lors d'une modification :

1. le document complet est validé par Pydantic ;
2. les fichiers gérés sont écrits atomiquement ;
3. `dnsmasq --test` vérifie la configuration installée ;
4. en cas de rejet, tous les fichiers précédents sont restaurés ;
5. l'Agent compare les réservations aux baux actifs et place dans
   `/run/ohana-agent/dhcp-reload.request` uniquement les MAC dont l'adresse
   louée contredit une réservation par son équipement ou par son adresse ;
6. le helper privilégié valide cette liste, arrête brièvement dnsmasq, supprime
   uniquement les baux obsolètes puis redémarre le service pour relire toute la
   configuration.

Les baux sans conflit sont conservés. L'Agent ne dispose lui-même ni du droit de
modifier la base de baux ni de lancer une commande privilégiée.

## Fichiers dnsmasq gérés

- `/etc/dnsmasq.d/00-ohana.conf`
- `/etc/dnsmasq.d/10-infrastructure.conf`
- `/etc/dnsmasq.d/20-serveurs.conf`
- `/etc/dnsmasq.d/30-infrastructure-reseau.conf`
- `/etc/dnsmasq.d/40-passerelles-domotiques.conf`
- `/etc/dnsmasq.d/50-equipements-critiques.conf`

Le fichier local `/etc/dnsmasq.d/99-local.conf` reste hors du périmètre
d'Ohana.

## Configuration

L'exemple complet se trouve dans `config/shikamaru.example.yaml`, sous la clé
`administration`. L'écoute doit rester sur `127.0.0.1` lorsque Vision et Agent
sont installés sur le même hôte.
