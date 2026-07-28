# Arborescence Linux d’Ohana-Agent

## Objectif

Ce document définit l’arborescence Linux de référence utilisée pour installer et exécuter Ohana-Agent en tant que service système.

Cette organisation sépare clairement :

* le logiciel installé ;
* la configuration administrée ;
* les données persistantes ;
* les journaux ;
* le service `systemd`.

Elle constitue le contrat de déploiement d’Ohana-Agent pour la version 1.5.0.

---

## Principes

L’installation Linux respecte les principes suivants :

* le dépôt Git n’est pas utilisé comme répertoire d’exécution en production ;
* le code installé n’est pas mélangé avec la configuration locale ;
* les fichiers de configuration sont conservés lors d’une mise à jour ;
* l’application s’exécute avec un utilisateur système dédié ;
* les journaux sont transmis à `systemd-journald` ;
* les chemins nécessaires sont fournis explicitement au CLI ;
* aucune donnée modifiable n’est écrite dans l’environnement Python installé.

---

## Arborescence de référence

```text
/
├── etc/
│   ├── ohana-agent/
│   │   ├── shikamaru.yaml
│   │   ├── infrastructure.yaml
│   │   └── plugins/
│   │       ├── dhcp.yaml
│   │       ├── dns.yaml
│   │       ├── ntp.yaml
│   │       ├── mqtt.yaml
│   │       ├── network.yaml
│   │       ├── zwave.yaml
│   │       └── wireguard.yaml
│   │
│   └── systemd/
│       └── system/
│           └── ohana-agent.service
│
├── opt/
│   └── ohana-agent/
│       └── venv/
│           ├── bin/
│           │   ├── python
│           │   └── ohana-agent
│           └── ...
│
└── var/
    └── lib/
        └── ohana-agent/
```

---

## Logiciel installé

Le logiciel est installé dans un environnement Python isolé :

```text
/opt/ohana-agent/venv/
```

Le point d’entrée exécutable est :

```text
/opt/ohana-agent/venv/bin/ohana-agent
```

Le répertoire `/opt/ohana-agent` contient uniquement les éléments nécessaires à l’exécution du logiciel installé.

Il ne contient pas :

* les fichiers de configuration de l’utilisateur ;
* une copie de travail du dépôt Git ;
* les tests ;
* les scripts de développement ;
* les journaux ;
* les données persistantes.

Les mises à jour remplacent ou mettent à niveau l’environnement Python sans écraser la configuration située dans `/etc/ohana-agent`.

---

## Configuration

Les fichiers de configuration actifs sont placés dans :

```text
/etc/ohana-agent/
```

La structure retenue est :

```text
/etc/ohana-agent/
├── shikamaru.yaml
├── infrastructure.yaml
└── plugins/
    ├── dhcp.yaml
    ├── dns.yaml
    ├── ntp.yaml
    ├── mqtt.yaml
    ├── network.yaml
    ├── zwave.yaml
    └── wireguard.yaml
```

### Configuration principale

```text
/etc/ohana-agent/shikamaru.yaml
```

Ce fichier contient la configuration générale de l’agent :

* identité de l’agent ;
* environnement ;
* MQTT ;
* journalisation ;
* santé ;
* plugins ;
* connexion à Ohana-Vision.

### Infrastructure

```text
/etc/ohana-agent/infrastructure.yaml
```

Ce fichier décrit l’infrastructure observée :

* nœuds ;
* endpoints ;
* services ;
* capacités associées.

### Plugin DHCP

```text
/etc/ohana-agent/plugins/dhcp.yaml
```

Ce fichier contient la configuration du plugin d’observation DHCP :

* activation du contrôle de l’unité `dnsmasq.service` ;
* délai et intervalle d’exécution ;
* taux maximal d’occupation de la plage.

L’adresse et le port du service DHCP restent déclarés dans
`infrastructure.yaml`. Le nœud local et les chemins dnsmasq sont réutilisés
depuis la section `administration.dhcp` de `shikamaru.yaml`. La commande
`systemctl` est interne à l’Agent et n’est pas configurable depuis l’API.

### Plugin DNS

```text
/etc/ohana-agent/plugins/dns.yaml
```

Ce fichier contient la configuration propre au plugin DNS :

* requêtes de contrôle ;
* délais ;
* tentatives ;
* intervalle d’exécution ;
* politique de santé.

Les adresses des serveurs DNS restent déclarées uniquement dans
`infrastructure.yaml`.

### Plugin NTP

```text
/etc/ohana-agent/plugins/ntp.yaml
```

Ce fichier contient la configuration propre au plugin NTP :

* délai et nombre de tentatives ;
* intervalle d'exécution ;
* décalage d'horloge maximal ;
* strate maximale acceptée.

Les adresses et ports des serveurs NTP restent déclarés uniquement dans
`infrastructure.yaml`.

### Plugin MQTT

```text
/etc/ohana-agent/plugins/mqtt.yaml
```

Ce fichier contient la configuration propre au plugin d'observation MQTT :

* délais, tentatives et intervalle d'exécution ;
* préfixes du client et du topic temporaire ;
* niveau de QoS ;
* authentification éventuelle ;
* paramètres TLS éventuels.

Les adresses et ports des brokers MQTT restent déclarés uniquement dans
`infrastructure.yaml`.

### Présence réseau

```text
/etc/ohana-agent/plugins/network.yaml
```

Ce fichier règle la vérification générique des équipements adressables :

* activation du plugin ;
* délai et nombre de tentatives immédiates ;
* intervalle d’exécution ;
* nombre d’échecs consécutifs avant déclaration d’absence.

Les adresses des équipements restent déclarées dans `infrastructure.yaml`,
directement sur l’équipement ou par l’intermédiaire de son nœud.

### Fichiers d’exemple

Les fichiers `.example.yaml` appartiennent au dépôt et à la documentation du projet.

Ils ne sont pas utilisés directement par le service de production.

Lors de l’installation initiale, l’installateur peut s’en servir pour créer les fichiers actifs dans `/etc/ohana-agent`, mais il ne doit pas écraser une configuration déjà présente.

---

## Données persistantes

Le répertoire réservé aux données persistantes est :

```text
/var/lib/ohana-agent/
```

Il appartient à l’utilisateur système exécutant Ohana-Agent.

Dans la version actuelle, le bootstrap de production ne persiste encore aucune donnée dans ce répertoire. Celui-ci est réservé aux fonctionnalités futures qui nécessiteront réellement un stockage local, par exemple :

* mémoire persistante ;
* état de reprise ;
* files d’attente temporaires durables ;
* métadonnées d’exécution.

Aucun fichier fictif ne doit être créé pour simuler un besoin de persistance.

Le répertoire peut ne pas être créé tant qu’aucun composant de production ne l’utilise.

---

## Journaux

Ohana-Agent écrit ses journaux sur la sortie standard et la sortie d’erreur.

En tant que service `systemd`, ces flux sont collectés par :

```text
systemd-journald
```

Aucun répertoire dédié n’est donc requis sous :

```text
/var/log/ohana-agent/
```

Les journaux sont consultés avec :

```bash
journalctl -u ohana-agent
```

Pour suivre l’exécution en direct :

```bash
journalctl -u ohana-agent -f
```

Cette stratégie évite :

* la gestion manuelle de fichiers de log ;
* la rotation propre à l’application ;
* les problèmes de permissions dans `/var/log` ;
* la duplication entre fichiers et journal système.

Si une sortie vers fichiers devient nécessaire ultérieurement, elle devra être décidée explicitement.

---

## Service systemd

Le fichier de service administré localement est placé dans :

```text
/etc/systemd/system/ohana-agent.service
```

Il démarre l’exécutable :

```text
/opt/ohana-agent/venv/bin/ohana-agent
```

avec les chemins de configuration explicites :

```text
--config /etc/ohana-agent/shikamaru.yaml
--infrastructure /etc/ohana-agent/infrastructure.yaml
--dhcp-config /etc/ohana-agent/plugins/dhcp.yaml
--dns-config /etc/ohana-agent/plugins/dns.yaml
--ntp-config /etc/ohana-agent/plugins/ntp.yaml
--mqtt-config /etc/ohana-agent/plugins/mqtt.yaml
--network-config /etc/ohana-agent/plugins/network.yaml
--zwave-config /etc/ohana-agent/plugins/zwave.yaml
--wireguard-config /etc/ohana-agent/plugins/wireguard.yaml
```

Le service ne doit pas dépendre du répertoire courant pour retrouver ses fichiers.

Le contenu précis de l’unité est défini dans l’étape consacrée au service `systemd`.

---

## Utilisateur système

Ohana-Agent s’exécute avec un compte système dédié :

```text
ohana-agent
```

Ce compte :

* ne possède pas de shell interactif ;
* ne possède pas de mot de passe ;
* n’exécute pas l’application avec les droits `root` ;
* peut lire `/etc/ohana-agent` ;
* peut exécuter l’environnement situé dans `/opt/ohana-agent/venv` ;
* peut écrire dans `/var/lib/ohana-agent` seulement lorsque ce répertoire est utilisé.

Le groupe système associé porte également le nom :

```text
ohana-agent
```

---

## Propriétaires et permissions

### Logiciel

```text
/opt/ohana-agent
```

Propriétaire recommandé :

```text
root:root
```

Permissions recommandées pour les répertoires :

```text
0755
```

Le compte `ohana-agent` peut exécuter le logiciel, mais ne peut pas le modifier.

### Configuration

```text
/etc/ohana-agent
```

Propriétaire recommandé :

```text
root:ohana-agent
```

Permissions recommandées pour les répertoires :

```text
0750
```

Permissions recommandées pour les fichiers ne contenant aucun secret :

```text
0640
```

Le compte de service peut lire les fichiers, mais ne peut pas les modifier.

Si une configuration contient ultérieurement des secrets, elle doit rester lisible uniquement par `root` et le groupe `ohana-agent`.

### Données persistantes

```text
/var/lib/ohana-agent
```

Propriétaire recommandé :

```text
ohana-agent:ohana-agent
```

Permissions recommandées :

```text
0750
```

---

## Correspondance avec le CLI

Le service Linux utilise les arguments déjà fournis par Ohana-Agent :

| Argument           | Chemin Linux                            |
| ------------------ | --------------------------------------- |
| `--config`         | `/etc/ohana-agent/shikamaru.yaml`      |
| `--infrastructure` | `/etc/ohana-agent/infrastructure.yaml` |
| `--dhcp-config`    | `/etc/ohana-agent/plugins/dhcp.yaml`   |
| `--dns-config`     | `/etc/ohana-agent/plugins/dns.yaml`    |
| `--ntp-config`     | `/etc/ohana-agent/plugins/ntp.yaml`    |
| `--mqtt-config`    | `/etc/ohana-agent/plugins/mqtt.yaml`   |
| `--network-config` | `/etc/ohana-agent/plugins/network.yaml` |
| `--zwave-config` | `/etc/ohana-agent/plugins/zwave.yaml` |
| `--wireguard-config` | `/etc/ohana-agent/plugins/wireguard.yaml` |
| `--log-level`      | niveau choisi par le service            |

Commande de référence :

```bash
/opt/ohana-agent/venv/bin/ohana-agent \
  --config /etc/ohana-agent/shikamaru.yaml \
  --infrastructure /etc/ohana-agent/infrastructure.yaml \
  --dhcp-config /etc/ohana-agent/plugins/dhcp.yaml \
  --dns-config /etc/ohana-agent/plugins/dns.yaml \
  --ntp-config /etc/ohana-agent/plugins/ntp.yaml \
  --mqtt-config /etc/ohana-agent/plugins/mqtt.yaml \
  --network-config /etc/ohana-agent/plugins/network.yaml \
  --zwave-config /etc/ohana-agent/plugins/zwave.yaml \
  --wireguard-config /etc/ohana-agent/plugins/wireguard.yaml \
  --log-level INFO
```

Cette commande ne dépend d’aucun chemin relatif.

---

## Développement et production

Les chemins présents dans le dépôt restent valides pour le développement :

```text
config/shikamaru.yaml
config/infrastructure.yaml
config/plugins/dhcp.yaml
config/plugins/dns.yaml
config/plugins/ntp.yaml
config/plugins/mqtt.yaml
config/plugins/network.yaml
```

Ils permettent de lancer localement :

```bash
ohana-agent
```

L’installation de production utilise en revanche les chemins absolus sous `/etc/ohana-agent`.

Les deux modes ne doivent pas être confondus :

| Contexte             | Configuration             |
| -------------------- | ------------------------- |
| développement        | `config/` dans le dépôt   |
| production Linux     | `/etc/ohana-agent/`      |
| logiciel installé    | `/opt/ohana-agent/venv/` |
| données persistantes | `/var/lib/ohana-agent/`  |
| journaux             | `systemd-journald`        |

---

## Éléments volontairement absents

L’arborescence ne prévoit pas actuellement :

```text
/var/log/ohana-agent/
/run/ohana-agent/
/var/cache/ohana-agent/
/usr/share/ohana-agent/
/opt/ohana-agent/config/
```

Ces emplacements ne répondent à aucun besoin réel du bootstrap actuel.

Ils ne devront être ajoutés que lorsqu’un composant de production les utilisera effectivement.

---

## Contrat pour la version 1.5.0

L’arborescence Linux de référence d’Ohana-Agent 1.5.0 est :

```text
Logiciel       /opt/ohana-agent/venv
Exécutable     /opt/ohana-agent/venv/bin/ohana-agent
Configuration  /etc/ohana-agent
Service        /etc/systemd/system/ohana-agent.service
Données        /var/lib/ohana-agent
Journaux       systemd-journald
Utilisateur    ohana-agent
Groupe         ohana-agent
```

Cette structure doit être utilisée par le service `systemd`, les procédures d’installation et le futur Ohana-Installer.
