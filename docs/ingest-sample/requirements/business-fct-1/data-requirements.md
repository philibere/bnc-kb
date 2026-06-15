# Fonction d'affaires 1 — Exigences de données

## Boîte

- `id` — identifiant unique de la boîte.
- `libelle` — libellé neutre (« Boîte 1 » à « Boîte 5 »), sans classement éditorial.
- `rang` — position ordinale de la boîte (1 à 5), reflétant le palier de calibre.

## Joueur

- `id` — identifiant unique du joueur.
- `nom` — nom affiché du joueur.
- `points` — total de points (buts + aides) au moment de l'amorce.
- `boite_id` — boîte d'appartenance.
- `rang_ligue` — rang du joueur au pointage de la ligue (1 à 25).

## Source d'amorce

- Fichier JSON local versionné dans le dépôt (ex. `src/data/`), pré-rempli à partir
  de la référence d'API NHL (`skater-stats-leaders`, joueurs triés par points).
- Contenu minimal par joueur : identifiant, nom, nombre de points.
- Sert de source de vérité reproductible, fonctionne hors ligne.

## Sélection (pool d'un participant)

- `participant_nom` — nom saisi par le participant.
- `choix` — exactement un joueur par boîte (cinq choix au total).
- `soumis_le` — horodatage de la soumission.
