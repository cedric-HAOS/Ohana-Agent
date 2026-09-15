# Investigations en lecture seule

Tsunade peut approfondir une recommandation sur les journaux sans demander un
accord à chaque test. L’autorisation est enregistrée comme `read_only_policy`,
distincte d’une réponse humaine Shizune. Les refus et reports existants restent
respectés. Les modifications et réparations conservent leur circuit séparé.

Le cycle collecte les journaux ciblés avec Katsuyu puis complète les preuves
depuis Agent : résolution DNS, connexion TCP, requête HTTP `HEAD /` pour les
services HTTP identifiés et métriques CPU, mémoire, disque et unités surveillées.
Les cibles viennent des services déclarés dans l’architecture, en privilégiant
le nœud concerné. Aucun shell, chemin HTTP proposé par l’IA, redirection,
identifiant ou contenu de réponse HTTP n’est utilisé.

Les tests portent au plus sur six points d’accès, l’hôte Agent et une lecture
de configuration, avec huit opérations concurrentes et dix secondes d’attente
globale au maximum. La lecture Supervisor est limitée à huit secondes. Les
résultats indisponibles ou hors délai sont conservés comme tels. Un code HTTP
401 ou 403 ne suffit pas à conclure à une panne.

Le lieu de mesure accompagne les preuves : tester HA-01 depuis INFRA-01 ne
prouve pas l’accès d’HA-01 à un service externe. Les accès Home Assistant déjà
configurés permettent des requêtes Supervisor GET fixes : options et état de
Mosquitto sur HA-01, options, consommation et exposition série de teleinfo2mqtt
sur LINKY-01. La configuration MQTT validée d’Agent est également examinée.
Seuls des champs sélectionnés sont transmis ; les secrets sont remplacés par
leur présence et les URL sont privées de leurs identifiants, chemins et requêtes.
L’absence d’un alias série dans l’inventaire ne prouve pas sa disparition.
Aucun port série n’est ouvert et aucune commande distante n’est exécutée.

Les résultats rejoignent une réévaluation Katsuyu. Un cycle ne relance pas les
mêmes tests sans nouveaux éléments. Les anciens dossiers sans ces nouvelles
preuves peuvent recevoir ce cycle supplémentaire ; le dossier affiche ensuite
ce qui reste à préciser si les moyens disponibles n’ont pas permis de conclure.
