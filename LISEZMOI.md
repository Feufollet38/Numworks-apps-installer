# Installateur NumWorks — plusieurs applis à la fois

Deux interfaces au choix, même moteur :

- **Fenêtre** : `lancer.bat` (Windows) ou `python installer.py`.
- **Site local** : `lancer-web.bat` (Windows), `./lancer-web.sh` ou
  `python serveur_web.py`, puis <http://127.0.0.1:8765> (le navigateur s’ouvre
  tout seul ; `--port` pour changer de port, `--sans-navigateur` pour ne pas
  l’ouvrir). Le serveur n’écoute que sur cet ordinateur, et c’est lui qui parle
  à la calculatrice en USB : le navigateur n’a besoin d’aucun WebUSB.

## Utilisation

1. **Ajouter des applis** : choisissez un émulateur du catalogue puis « Ajouter à la
   liste » (le `.nwa` est téléchargé dans `telechargements/`), ou « Ajouter des
   fichiers .nwa… » pour vos propres applis (sélection multiple possible).
   Le même émulateur peut être ajouté plusieurs fois : une ligne par ROM.
2. Pour chaque appli qui a besoin d’une ROM ou de données (Game Boy, NES, PNG…),
   sélectionnez sa ligne puis « ROM / données… ». Sans ROM, un émulateur ne peut
   pas être assemblé.
3. « Essai sans calculatrice » assemble toute la liste en une image et vérifie
   qu’elle tient, sans rien envoyer.
4. « Valider et tout installer » envoie **toute la liste en un seul flash**.

## Presets

- **Exporter preset…** crée un fichier `.nwpreset` qui contient la liste dans le
  bon ordre, les fichiers `.nwa` et les ROM / données associées. Les fichiers du
  catalogue qui n’ont pas encore été téléchargés le sont au moment de l’export.
- **Importer preset…** restaure toute la liste depuis ce fichier et remplace la
  liste actuellement affichée après confirmation.

Le site local propose exactement les mêmes actions ; les fichiers choisis dans
le navigateur (`.nwa`, ROM) sont copiés dans `telechargements/importees/`.

## Pourquoi une liste et non des installations successives

La zone « applis externes » de la calculatrice est réécrite en entier à chaque
envoi : `nwlink install-nwa` lancé deux fois ne laisse que la dernière appli. Le
moteur de nwlink sait empaqueter plusieurs applis, mais sa ligne de commande ne
l’expose pas. `nwlink_multi.py` installe nwlink en local
(`telechargements/nwlink-runtime/`) et lui ajoute une commande `install-multi`
qui lit un manifeste JSON et écrit toutes les applis d’un coup.

Conséquence : la liste doit contenir **tout ce que vous voulez garder** sur la
calculatrice, pas seulement les nouveautés.

## Pré-requis

- Node.js LTS (npm) : <https://nodejs.org/> — indispensable pour l’envoi groupé.
- Calculatrice branchée en USB, un seul logiciel qui lui parle à la fois.
- Limite d’environ 8 Mo pour l’ensemble des applis (au-delà de ~2,5 Mo, le site
  NumWorks refuse sans Nwagra ; nwlink, lui, utilise déjà la plage élargie).
