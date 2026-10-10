# Supervision de la synchronisation AdGuard

Le plugin `adguard_sync` fournit la capacité `adguard_sync.status` sur le serveur
qui exécute `adguardhome-sync.service`, actuellement INFRA-01. Il produit des
observations par le circuit normal Agent → Vision et figure dans l'administration
des plugins. Il ne déclenche ni synchronisation, ni redémarrage, ni réparation.

## Contrôles

- Chargement du service et du timer systemd ; timer actif.
- Résultat du dernier cycle terminé et âge depuis sa fin. Le seuil par défaut
  est 15 minutes pour un cycle normalement planifié toutes les 5 minutes.
- Comparaison des sections activées dans `features` du fichier existant
  `/etc/ohana-agent/adguardhome-sync.yaml` : réécritures et leur activation,
  paramètres DNS, listes d'accès, filtres et règles personnelles, clients
  persistants, services bloqués, réglages généraux, journal et statistiques.
- Requête DNS A pour un nom stable sur chacune des deux adresses IP, port 53.

Les compteurs, dates de téléchargement et identifiants locaux des filtres, les
clients découverts automatiquement et les résolveurs PTR détectés localement
ne sont pas comparés. L'ordre des listes sans signification pour le moteur
de réplication est normalisé. La désactivation volontaire des résolveurs PTR
privés sur la réplique lorsque l'origine n'en définit aucun est prise en compte.
La réponse DNS doit contenir une adresse ; le plugin ne compare pas les réponses
de domaines publics, qui peuvent varier selon les caches et les serveurs amont.

Un cycle en cours diffère la comparaison. Le service est relu après les appels
API pour écarter une comparaison traversant un nouveau cycle de synchronisation.
Un code de sortie systemd réussi ne suffit jamais à établir l'état sain : les
comparaisons API et les deux requêtes DNS doivent également réussir.

## Administration après la mise à jour

Disponible dans Platform 1.0.143 : Agent 1.46.1, Vision 1.37.0 et Shizune 0.5.0.

Au premier démarrage en production de l'Agent mis à jour, avec son administration activée,
le service de supervision est ajouté automatiquement à l'infrastructure sur le
nœud local configuré (INFRA-01). Les services déjà déclarés, leurs identifiants et
leurs désactivations sont conservés. Aucun ajout manuel de service n'est requis.

Dans Vision, ouvrir **Configuration → Plugins → Synchronisation AdGuard**,
activer la surveillance, ajuster l'intervalle, le délai API/DNS, l'âge maximal du
cycle et le nom DNS de contrôle, puis enregistrer et tester. Le fichier du plugin
est créé par l'administration au premier enregistrement ; aucun fichier n'est à
créer à la main. Les accès du moteur de synchronisation existant sont réutilisés.

Shizune reçoit automatiquement une tuile **Synchro AdGuard** dans **Services
essentiels** via sa synthèse habituelle. Elle indique une synchronisation vérifiée,
un défaut ou un état non vérifié tant qu'aucune mesure n'est disponible.
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
| `healthy` | Cycle récent, sections identiques, DNS fonctionnel | healthy |
| `cycle_failed` | Dernier cycle systemd en échec | unavailable |
| `stale` | Cycle trop ancien ou exécution trop longue | unavailable |
| `divergent` | Écart dans au moins une section comparée | unavailable |
| `dns_failed` | Une requête DNS échoue | unavailable |
| `units_missing` / `timer_inactive` | Service absent ou planification inactive | unavailable |
| `never_completed` | Aucun cycle terminé depuis le démarrage système | unavailable |
| `running` | Comparaison différée pendant un cycle | unknown |
| `unverifiable` | Accès, configuration ou réponse API non exploitable | unknown |

Les métadonnées incluent les sections contrôlées, les noms des sections divergentes,
le résultat de chaque requête DNS et l'âge du dernier cycle terminé lorsque
disponible. Aucun contenu de règle, mot de passe, réponse API brute ou texte
d'exception n'est publié. Les états inconnus ne constituent pas une preuve de santé.

## Périmètre et limites

Le plugin vise le modèle Ohana existant : une origine et une réplique sur deux
adresses IP différentes, fichier YAML et cycle systemd oneshot. Les substitutions
de configuration du moteur par variables d'environnement ou options de lancement
ne sont pas interprétées. La réplication DHCP et TLS, les listes de répliques et
les fonctionnalités surchargées par réplique sont hors périmètre : les formats
détectés non pris en charge donnent `unverifiable`. Les certificats HTTPS sont
vérifiés. Les appels utilisent uniquement GET, avec délais et tailles bornés ;
le budget de collecte API/DNS est 25 secondes, hors lectures systemd (3 secondes
maximum par appel). Un fichier illisible ou une API incompatible ne donne jamais
un succès de comparaison.

Contrats consultés : [API officielle AdGuard Home](https://github.com/AdguardTeam/AdGuardHome/blob/master/openapi/openapi.yaml)
et [actions de réplication adguardhome-sync](https://github.com/bakito/adguardhome-sync/blob/main/internal/sync/action-general.go).

Les tests locaux utilisent des API et unités systemd simulées. La publication
ne confirme pas le déploiement : après mise à jour, activer et tester dans Vision,
puis vérifier la tuile Shizune et les observations des deux instances réelles.
