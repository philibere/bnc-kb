# Fonction d'affaires 2 — Exigences de données

## Classement

- `participant_nom` — participant classé.
- `total_points` — somme des points (buts + aides) des joueurs sélectionnés par le
  participant.
- `rang` — position au classement général, dérivée du total décroissant.

## Détail d'un participant

- `participant_nom` — participant consulté.
- `joueurs_selectionnes` — liste des joueurs retenus (un par boîte).
- `points_par_joueur` — points courants de chaque joueur retenu.

## Administration des boîtes et du pointage

- Opérations CRUD sur les joueurs et leur appartenance à une boîte.
- Mise à jour du champ `points` d'un joueur (buts + aides).
- Trace minimale : la dernière mise à jour de pointage alimente le recalcul du
  classement.
