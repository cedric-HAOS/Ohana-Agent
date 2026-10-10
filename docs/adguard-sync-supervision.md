# Supervision de la synchronisation AdGuard

Le plugin `adguard_sync` fournit la capacité `adguard_sync.status` sur le serveur
qui exécute `adguardhome-sync.service`, actuellement INFRA-01. Il produit des
observations par le circuit normal Agent → Vision et figure dans l'administration
des plugins. Il ne déclenche ni synchronisation, ni redémarrage, ni réparation.

## Surveillance centrée sur la réplication (Agent 1.48.0)

Vision 1.38.1 ne présente plus de nom DNS de contrôle. Les anciens fichiers
contenant `dns_probe_name` sont acceptés ; ce champ est ignoré et disparaît
lors du prochain enregistrement. Aucun réglage du plugin DNS n’est modifié.

## Contrôles

- Chargement du service et du timer systemd ; timer actif.
- Résultat du dernier cycle terminé et âge depuis sa fin. Le seuil par défaut
  est 15 minutes pour un cycle normalement planifié toutes les 5 minutes.
- Comparaison des sections activées dans `features` du fichier existant
  `/etc/ohana-agent/adguardhome-sync.yaml` : réécritures et leur activation,
  paramètres DNS, listes d'accès, filtres et règles personnelles, clients
  persistants, services bloqués, réglages généraux, journal et statistiques.

La disponibilité DNS est contrôlée séparément par le plugin DNS. Aucune requête
DNS de contrôle n’est effectuée par ce plugin.

Les compteurs, dates de téléchargement et identifiants locaux des filtres, les
clients découverts automatiquement et les résolveurs PTR détectés localement
ne sont pas comparés. L'ordre des listes sans signification pour le moteur
de réplication est normalisé. La désactivation volontaire des résolveurs PTR
privés sur la réplique lorsque l'origine n'en définit aucun est prise en compte.

Un cycle en cours diffère la comparaison. Le service est relu après les appels
API pour écarter une comparaison traversant un nouveau cycle de synchronisation.
Un code de sortie systemd réussi ne suffit jamais à établir l'état sain : les
comparaisons des sections répliquées via les API doivent également réussir.

## Administration après la mise à jour

Disponible dans Platform 1.0.143 : Agent 1.46.1, Vision 1.37.0 et Shizune 0.5.0.

Au premier démarrage en production de l'Agent mis à jour, avec son administration activée,
le service de supervision est ajouté automatiquement à l'infrastructure sur le
nœud local configuré (INFRA-01). Les services déjà déclarés, leurs identifiants et
leurs désactivations sont conservés. Aucun ajout manuel de service n'est requis.

Dans Vision, ouvrir **Configuration → Plugins → Synchronisation AdGuard**,
activer la surveillance, ajuster l'intervalle, le délai API et l'âge maximal du
cycle, puis enregistrer et tester. Le fichier du plugin
est créé par l'administration au premier enregistrement ; aucun fichier n'est à
créer à la main. Les accès du moteur de synchronisation existant sont réutilisés.

Shizune reçoit automatiquement une tuile **Synchro AdGuard** dans **Services
essentiels** via sa synthèse habituelle. Elle indique une synchronisation vérifiée,
un défaut ou un état non vérifié tant qu'aucune mesure n'est disponible.
Lorsque la synchronisation est vérifiée et que la fin du dernier cycle réussi
est connue, la tuile affiche son âge, par exemple **Dernière synchro il y a 3 min**.
Cet âge progresse depuis la fin du cycle ; il ne représente pas l'âge du contrôle.
Une surveillance désactivée ou une mesure datant de plus de quinze minutes
est également présentée comme non vérifiée, jamais comme un succès actuel.

Sans ce nouveau fichier, les installations existantes chargent un plugin
désactivé. Le formulaire d'administration peut créer son fichier lors du premier
enregistrement. Les identifiants restent uniquement dans le fichier de
synchronisation existant ; ils ne sont pas recopiés dans ce formulaire.

Depuis Agent 1.46.1, les listes de filtres et de clients explicitement `null`
sont interprétées comme vides, conformément au comportement observé des API
AdGuard installées. Une liste absente ou de type incorrect reste non vérifiable.

## Interprétation

| `sync_state` | Sens | Santé exportée |
|---|---|---|
| `healthy` | Cycle récent, sections répliquées identiques | healthy |
| `cycle_failed` | Dernier cycle systemd en échec | unavailable |
| `stale` | Cycle trop ancien ou exécution trop longue | unavailable |
| `divergent` | Écart dans au moins une section comparée | unavailable |
| `units_missing` / `timer_inactive` | Service absent ou planification inactive | unavailable |
| `never_completed` | Aucun cycle terminé depuis le démarrage système | unavailable |
| `running` | Comparaison différée pendant un cycle | unknown |
| `unverifiable` | Accès, configuration ou réponse API non exploitable | unknown |

Les métadonnées incluent les sections contrôlées, les noms des sections divergentes
et l'âge du dernier cycle terminé lorsque disponible. Aucun contenu de règle, mot de passe, réponse API brute ou texte
d'exception n'est publié. Les états inconnus ne constituent pas une preuve de santé.

## Périmètre et limites

Le plugin vise le modèle Ohana existant : une origine et une réplique sur deux
adresses IP différentes, fichier YAML et cycle systemd oneshot. Les substitutions
de configuration du moteur par variables d'environnement ou options de lancement
ne sont pas interprétées. La réplication DHCP et TLS, les listes de répliques et
les fonctionnalités surchargées par réplique sont hors périmètre : les formats
détectés non pris en charge donnent `unverifiable`. Les certificats HTTPS sont
vérifiés. Les appels utilisent uniquement GET, avec délais et tailles bornés ;
le budget de collecte API est 25 secondes, hors lectures systemd (3 secondes
maximum par appel). Un fichier illisible ou une API incompatible ne donne jamais
un succès de comparaison.

Contrats consultés : [API officielle AdGuard Home](https://github.com/AdguardTeam/AdGuardHome/blob/master/openapi/openapi.yaml)
et [actions de réplication adguardhome-sync](https://github.com/bakito/adguardhome-sync/blob/main/internal/sync/action-general.go).

Les tests locaux utilisent des API et unités systemd simulées. La publication
ne confirme pas le déploiement : après mise à jour, activer et tester dans Vision,
puis vérifier la tuile Shizune et les observations des deux instances réelles.

## Moteur administrable (Agent 1.47.0)

Avec Installer 1.16.0 et Vision 1.38.0, la même fiche présente le moteur et sa
surveillance séparément. Les accès se configurent depuis Vision ; les mots de
passe restent masqués et un champ vide conserve leur valeur. Agent valide les
deux API avant de démarrer le timer installé par Installer.
L’activation initiale ne dépend pas encore des réécritures DNS. La surveillance
vérifie le résultat du cycle et la cohérence des configurations après son exécution.

Le choix d’activation du moteur est enregistré dans
`/etc/ohana-agent/adguard-sync-state.json`, inclus dans les sauvegardes.
Installer reconstruit le moteur et ses unités lors de la restauration, puis
réactive uniquement un choix sauvegardé après validation des accès. Une ancienne
sauvegarde sans ce choix laisse le timer inactif.
Voir [le guide Installer](https://github.com/cedric-HAOS/Ohana-Installer/blob/main/docs/AdGuard-Sync.md).
