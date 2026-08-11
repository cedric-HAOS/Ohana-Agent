# Sauvegardes HAOS vers iCloud

Le plugin `backup` orchestre les sauvegardes de HA-01, LINKY-01 et ZWAVE-01
sans enregistrer les archives sur la carte microSD d'INFRA-01.

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
directement dans **Vision → Configuration → Plugins → Sauvegardes HAOS**. Agent
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

Une fois le plugin installé, la page **Configuration → Plugins → Sauvegardes
HAOS** de Vision permet de modifier sans redémarrage :

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

Vision affiche uniquement si les secrets sont présents sur Agent. Leurs valeurs
ne sont jamais renvoyées par l'API d'administration. Le bouton de test
vérifie l'accès aux trois HAOS activés et au remote rclone sans créer de
sauvegarde, sans envoyer d'archive et sans supprimer de sauvegarde locale.

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
