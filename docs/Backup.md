# Sauvegardes HAOS et INFRA-01 vers iCloud

Le plugin `backup` orchestre les sauvegardes de HA-01, LINKY-01 et ZWAVE-01
sans enregistrer les archives sur la carte microSD d'INFRA-01.

Il peut aussi sauvegarder INFRA-01 lui-même. Cette cible produit un instantané
cohérent de la base SQLite de Vision, archive les configurations nécessaires à
la reconstruction, chiffre le flux avec `age`, puis le transmet à iCloud sans
écrire l'archive en clair ou chiffrée sur la microSD.

## Sauvegarde d'INFRA-01

Ohana-Installer installe `age`, crée l'identité dans
`/etc/ohana-agent/keys/infra-01.agekey` et en dérive automatiquement le
destinataire public. Agent copie l'identité de récupération dans
`icloud:Ohana/Recovery/infra-01.agekey` avant de publier chaque sauvegarde.
Avec la Protection avancée des données iCloud, cette copie bénéficie aussi du
chiffrement de bout en bout Apple. Vision ne demande donc plus de clé publique.

Lors d'une restauration iCloud sur une nouvelle machine, Installer récupère
cette identité avant de déchiffrer l'archive, puis la réinstalle localement.
L'identité ne doit jamais être recréée pour restaurer une archive existante.
La sauvegarde contient :

- `/etc/ohana-agent` ;
- `/etc/ohana-vision` ;
- `/etc/dnsmasq.d` ;
- `/etc/chrony/chrony.conf` ;
- un instantané cohérent de `/var/lib/ohana-vision/vision.db`.

Avec `use_katsuyu: true`, Agent crée un job `backup.infra` et diffuse à son
propriétaire un tar non compressé sur le listener HTTPS Katsuyu. Katsuyu
compresse, chiffre avec le destinataire public `age`, calcule l'intégrité puis
renvoie l'artefact. Agent transmet ce retour directement à `rclone rcat` sans
le stocker et publie le manifeste JSON en dernier. Ce manifeste permet à
Ohana-Installer de sélectionner uniquement une sauvegarde complètement publiée
et de réinstaller la composition Agent/Vision correspondante. Un second
descripteur placé à l'intérieur de l'archive chiffrée reprend l'identité et les
versions de la sauvegarde ; Installer exige sa correspondance exacte avec le
manifeste public avant d'appliquer le moindre fichier.

Seul l'instantané SQLite cohérent demeure produit temporairement sur le `tmpfs`
d'INFRA-01, au moyen de l'API de sauvegarde en ligne SQLite. INFRA-01 ne
compresse plus, ne chiffre plus et ne conserve ni tar ni archive chiffrée. Le
jeton worker, l'identité du propriétaire du job et son numéro de tentative
protègent les deux flux ; aucun chemin arbitraire n'est accepté.

Le résultat du job contient durée, temps CPU, pic mémoire du processus Katsuyu,
volumes logiques lus/écrits, tailles avant/après et SHA-256. Ces mesures se
comparent aux observations hôte Agent/Shikamaru prises avant et pendant le job.
Les sauvegardes HAOS ne changent pas : elles restent créées et chiffrées
nativement par HA-01, LINKY-01 et ZWAVE-01, puis seulement relayées en flux.

La rétention iCloud est indépendante de la sauvegarde locale des HAOS. La valeur
`remote_retention_count: 0` conserve toutes les sauvegardes INFRA-01. Une valeur
positive active la rotation : elle n'intervient qu'après la validation et la
publication du nouveau manifeste, et ne supprime que les plus anciens dossiers
horodatés qui possèdent eux-mêmes un manifeste. Un dossier incomplet n'est jamais
pris comme preuve d'une sauvegarde valide et n'est pas supprimé automatiquement.

## Garanties

- la sauvegarde complète est créée sur le Home Assistant OS cible ;
- un mot de passe explicite chiffre chaque sauvegarde ;
- l'archive est téléchargée et transmise à `rclone rcat` par blocs bornés ;
- la taille est annoncée à rclone et contrôlée après l'envoi ;
- un fichier `.sha256` est envoyé à côté de l'archive ;
- les fichiers temporaires rclone sont autorisés uniquement sur un `tmpfs` ;
- l'ancienne sauvegarde locale gérée par Ohana n'est supprimée qu'après la
  confirmation rclone, le contrôle de taille distant et l'envoi du SHA-256 ;
- les sauvegardes manuelles, dont le nom ne commence pas par `Ohana-<id>-`,
  ne sont jamais supprimées.

Deux sauvegardes Ohana peuvent donc coexister temporairement sur une cible.
Après un cycle réussi, seule la plus récente reste locale. Un échec de création,
d'envoi, de validation ou de checksum conserve l'ancienne sauvegarde.

## Configuration

Copier `config/plugins/backup.example.yaml` vers
`/etc/ohana-agent/plugins/backup.yaml`. Le plugin livré reste désactivé tant que
les prérequis ne sont pas installés.

Les jetons Home Assistant et les mots de passe de chiffrement se saisissent
directement dans **Vision → Configuration → Plugins → Sauvegardes**. Agent
les conserve dans `plugins/backup.yaml`, protège ce fichier en mode `0600` et
ne renvoie jamais leurs valeurs à Vision. L'API indique seulement si chaque
secret est configuré ; un champ laissé vide conserve la valeur existante.

L'ancien fichier `/etc/ohana-agent/backup.env` reste accepté pendant la
migration :

```text
OHANA_BACKUP_HA_01_TOKEN=...
OHANA_BACKUP_HA_01_PASSWORD=...
OHANA_BACKUP_LINKY_01_TOKEN=...
OHANA_BACKUP_LINKY_01_PASSWORD=...
OHANA_BACKUP_ZWAVE_01_TOKEN=...
OHANA_BACKUP_ZWAVE_01_PASSWORD=...
```

Le fichier historique doit appartenir à `root:ohana-agent` avec le mode `0640`.
Les jetons Home Assistant doivent appartenir à des administrateurs. Agent les
utilise sur l'API WebSocket publique (`backup/info`, `backup/generate` et
`backup/delete`) et sur la route publique `/api/backup/download/{backup_id}` ;
il n'utilise plus le proxy interne `/api/hassio/*`.

Les mots de passe de sauvegarde doivent aussi être conservés hors d'INFRA-01,
dans le gestionnaire de mots de passe et la procédure de reconstruction. Une
archive iCloud est inutilisable sans le mot de passe correspondant.

### Administration depuis Vision

Une fois le plugin installé, la page **Configuration → Plugins → Sauvegardes**
de Vision permet de modifier sans redémarrage :

- l'activation globale et l'activation de chaque cible ;
- l'adresse HAOS, y compris sous la forme
  `http://ha-01.ohana.lan:8123` ;
- l'heure quotidienne, le délai maximal et la vérification TLS ;
- le dossier de destination dans iCloud Drive ;
- les jetons Home Assistant et mots de passe de chiffrement, dans des champs
  masqués identiques aux autres plugins ;
- la connexion ou reconnexion iCloud avec identifiant Apple, mot de passe et
  code 2FA ponctuel ;
- le script de préparation NVM de ZWAVE-01.
- l'activation, l'horaire et le destinataire public `age` d'INFRA-01.
- le nombre de sauvegardes INFRA-01 complètes à conserver dans iCloud (`0` pour
  une conservation illimitée).

Vision affiche uniquement si les secrets sont présents sur Agent. Leurs valeurs
ne sont jamais renvoyées par l'API d'administration. Le bouton de test
vérifie l'accès aux trois HAOS activés et au remote rclone sans créer de
sauvegarde, sans envoyer d'archive et sans supprimer de sauvegarde locale.

Une cible activée peut aussi être lancée immédiatement depuis la fiche de
l'équipement dans la vue d'ensemble de Vision. Le bouton n'est affiché que si
l'identifiant technique de l'équipement correspond exactement à l'identifiant
d'une cible activée : `ha-01` lance uniquement la cible `ha-01`, `linky-01`
uniquement `linky-01`, etc. Agent accepte la demande rapidement puis poursuit
la création, l'envoi, la validation et la rotation en arrière-plan. Une seconde
demande simultanée pour la même cible est refusée.

Home Assistant peut diffuser l'archive locale en HTTP segmenté, sans en-tête
`Content-Length`. Agent récupère alors la taille exacte dans les métadonnées
`backup/info` avant de démarrer rclone. Si aucune taille positive n'est
disponible dans les métadonnées ou la réponse HTTP, le flux reste refusé :
l'archive n'est jamais mise en tampon sur la carte microSD d'INFRA-01.

## iCloud et rclone

Ohana-Installer installe une version vérifiée de rclone comprenant le backend
`iclouddrive`. Vision pilote ensuite le flux SRP et la validation 2FA. Le mot de
passe Apple normal est requis : les mots de passe spécifiques aux applications
ne sont pas acceptés par rclone. La configuration résultante est conservée dans
`/etc/ohana-agent/rclone.conf` en mode `0600`.

Le jeton de confiance iCloud expire périodiquement. Lorsque le test signale une
session expirée, utiliser **Reconnecter iCloud** dans Vision et saisir le
nouveau code 2FA.

Valider avant activation :

```bash
sudo -u ohana-agent rclone lsd \
  --config /etc/ohana-agent/rclone.conf \
  icloud:Ohana/Backups
```

Le service systemd crée `/run/ohana-agent`. Le plugin vérifie que le système de
fichiers contenant `temporary_directory` est réellement `tmpfs`. Il échoue au
lieu de se rabattre sur la microSD. `require_tmpfs: false` ne doit être utilisé
qu'avec un stockage externe explicitement validé, par exemple un SSD USB.

`use_katsuyu: false` conserve le chemin local historique pour un retour arrière
explicite. Ce mode local compresse et chiffre sur INFRA-01 et ne constitue pas
la cible d'exploitation normale.

## ZWAVE-01

La sauvegarde HAOS capture le dossier persistant de Z-Wave JS UI, mais le NVM
du contrôleur doit d'abord y avoir été exporté. La cible ZWAVE-01 déclare donc
une `pre_backup_action`.

Le script Home Assistant `script.ohana_backup_zwave_nvm` est spécifique au
déploiement. Il doit déclencher un export NVM Z-Wave JS UI, attendre sa fin et
échouer si l'export n'est pas confirmé. Le plugin ne crée pas la sauvegarde
HAOS si cette action échoue.

## Activation progressive

1. Saisir les trois mots de passe et jetons dans Vision.
2. Connecter iCloud dans Vision, valider le code 2FA et tester le remote.
3. Valider manuellement le script NVM de ZWAVE-01.
4. Activer d'abord HA-01 et contrôler archive, taille, SHA-256 et restauration.
5. Ajouter LINKY-01, puis ZWAVE-01.
6. Activer finalement le plugin et les trois cibles depuis Vision.

L'activation et les essais sur les machines réelles constituent une opération
de déploiement distincte du code du plugin.
