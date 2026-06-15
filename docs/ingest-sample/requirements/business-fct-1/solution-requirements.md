# Fonction d'affaires 1 — Création de la sélection

L'expérience du participant qui compose son alignement. Couvre les histoires 1 à 5
du carnet d'origine, ordonnées du premier au dernier geste posé par le participant.

## SR-1.1 — Visualisation des boîtes (histoire 1)

Le participant voit les joueurs regroupés par boîtes distinctes (« Boîte 1 » à
« Boîte 5 »), afin de comprendre quels joueurs sont en compétition les uns avec les
autres. Chaque boîte présente ses cinq joueurs et leurs points.

## SR-1.2 — Génération des boîtes depuis la source NHL (histoire 2)

L'organisateur amorce automatiquement les boîtes à partir d'un fichier JSON local
des 25 meilleurs marqueurs de la ligue, répartis en 5 boîtes de 5 joueurs selon leur
rang au pointage. L'amorce est reproductible et fonctionne hors ligne : aucun appel
réseau n'est fait au moment de l'amorce.

## SR-1.3 — Sélection d'un joueur (histoire 3)

Le participant clique sur un joueur pour le sélectionner dans sa boîte. Toute
sélection précédente dans la même boîte est automatiquement remplacée : un seul choix
est permis par boîte.

## SR-1.4 — Validation de l'alignement (histoire 4)

Le participant voit un indicateur visuel (compteur ou barre de progression) qui
confirme s'il a fait un choix dans chaque boîte, afin de s'assurer que son alignement
est complet avant de soumettre.

## SR-1.5 — Soumission des choix (histoire 5)

Le participant clique sur « Soumettre mon pool » pour enregistrer ses choix et son
nom, confirmant officiellement sa participation. La soumission n'est acceptée que si
l'alignement est complet (voir les règles d'affaires).
