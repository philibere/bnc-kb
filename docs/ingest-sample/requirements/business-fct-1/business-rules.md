# Fonction d'affaires 1 — Règles d'affaires

## BR-1.1 — Un seul choix par boîte

Le participant ne peut retenir qu'un joueur par boîte. Sélectionner un nouveau joueur
dans une boîte remplace automatiquement le choix précédent dans cette boîte.

## BR-1.2 — Répartition par paliers de rang

Les 25 joueurs sont découpés en 5 boîtes de 5 selon leur rang (rangs 1 à 5 dans la
boîte 1, 6 à 10 dans la boîte 2, etc.). Chaque boîte rassemble des joueurs de calibre
comparable.

## BR-1.3 — Paliers décroissants assumés

Conséquence assumée du regroupement par rangs adjacents : les boîtes forment des
paliers décroissants (la boîte 1 regroupe les meilleurs marqueurs), donc les boîtes
n'ont pas une valeur équivalente. C'est voulu, puisque le participant choisit un
joueur par boîte à travers les différents paliers. Un rééquilibrage en serpentin est
hors portée (voir la fonction d'affaires 2, configuration des boîtes).

## BR-1.4 — Amorce hors ligne et reproductible

L'amorce des boîtes ne fait aucun appel réseau : elle lit le fichier JSON local
versionné. Le même fichier produit toujours la même répartition.

## BR-1.5 — Alignement complet avant soumission

La soumission n'est acceptée que si le participant a fait un choix dans chacune des
cinq boîtes.
