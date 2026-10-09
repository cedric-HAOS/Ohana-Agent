# Noms des réservations DHCP vers AdGuard Home

Agent 1.45.0 fournit `ohana-agent-adguard-reservations`. Cette commande réutilise
le lecteur DHCP pour produire les réécritures exactes des réservations dans
`ohana.lan`. Elle ne lit pas les baux dynamiques et ne démarre aucun serveur DHCP.

Le service systemd `adguardhome-sync` enchaîne cette commande, la réplication
ZWAVE-01 → LINKY-01 et la vérification des réécritures par API. Ses modèles sont
publiés avec [Ohana-House 2.2.0](https://github.com/cedric-HAOS/Ohana-House/blob/v2.2.0/docs/INFRA-01/Capacites/DNS/Synchroniser-Reservations-DHCP.md).
Ils sont à installer explicitement ; une mise à jour de l'Agent seule ne les active pas.

Configuration : `/etc/ohana-agent/adguardhome-sync.yaml` ; registre :
`/etc/ohana-agent/adguard-reservations-state.json`. Les fichiers sont lisibles
par le groupe `ohana-agent` pour leur sauvegarde chiffrée iCloud. Le registre
ne doit pas être effacé : il identifie les seules règles pouvant être supprimées.
Une règle manuelle différente pour un nom réservé bloque le cycle avant mutation.

Commandes de contrôle : `--dry-run` (aucune mutation) et `--verify-replica`
(comparaison des deux listes de réécritures). La présence des règles par API
ne remplace pas une requête DNS de validation sur chaque serveur.

Une ancienne sauvegarde reste restaurable sans ces nouveaux fichiers. Le
restaurateur remet les versions exactes sauvegardées : **restaurer d'abord,
mettre à jour ensuite vers Platform 1.0.140 / Agent 1.45.0**, puis renseigner
les accès AdGuard et installer le cycle DNS. Les prochaines sauvegardes
incluront ces fichiers sous `/etc/ohana-agent` ; les anciennes ne sont pas modifiées.
