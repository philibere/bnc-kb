"""Tiny self-contained shaper corpus fixtures for the converged ingestion tests.

Ported from the vendored engine's test corpus. Mirrors the canonical pool-hockey
shape against the DEFAULT metamodel (``metamodel/bnc.metamodel.yaml``): one feature
(with a REQ and a feature_summary), one glossary entity it affects, one glossary
actor it is performed by, and one invariant constraining it.

Each corpus exposes its ``{relative_path: content}`` mapping so a test can either
write it to disk (``write_corpus``) for the engine, or zip it for the HTTP endpoint.
"""

from __future__ import annotations

FEATURE_MD = """---
id: FEAT-T-001
kind: feature
title: Gerer les joueurs
status: draft
module: test-module
actors:       [orga]
entities:     [joueur]
summary: >
  L'organisateur gere le bassin de joueurs : creation, modification, suppression.
---

## Exigences

### REQ-001  [F-BUSINESS]
statement:  L'organisateur DOIT pouvoir creer un joueur.
hash:       abc123
acceptance: |
  Etant donne un organisateur
  Quand il cree un joueur
  Alors le joueur est ajoute
"""

ENTITY_MD = """---
id: joueur
kind: entity
name: Joueur
aliases: [player]
status: active
parent: null
definition: >
  Hockeyeur inscrit au bassin du pool, caracterise par un nom.
---
"""

ACTOR_MD = """---
id: orga
kind: actor
name: Organisateur
aliases: [admin]
status: active
parent: null
definition: >
  Personne responsable de la configuration du pool.
---
"""

INVARIANT_MD = """---
id: INV-T-001
kind: invariant
name: Un joueur, une boite
status: active
constrains:
  entities: [joueur]
  features: [FEAT-T-001]
verified-by: derive(test)
hash:
---

## Enonce
A tout instant, un joueur appartient a au plus une boite.
"""

DUP_FEATURE_A_MD = """---
id: FEAT-DUP-001
kind: feature
title: Premier
status: draft
module: dup-module
actors:       []
entities:     []
summary: >
  Premiere declaration de l'id en double.
---
"""

DUP_FEATURE_B_MD = """---
id: FEAT-DUP-001
kind: feature
title: Second
status: draft
module: dup-module
actors:       []
entities:     []
summary: >
  Seconde declaration du meme id.
---
"""

BAD_FRONTMATTER_MD = """---
id: FEAT-T-003
kind: feature
title: Frontmatter casse
actors: [unclosed
---

## Exigences
"""

# A second, standalone feature (its own module) referencing the SAME glossary actor
# and entity as FEAT-T-001. Used for partial-merge tests: ingested alone, its
# performed-by/affects-entity edges are pending until orga/joueur are in the store.
FEATURE2_MD = """---
id: FEAT-T-009
kind: feature
title: Gerer les equipes
status: draft
module: team-module
actors:       [orga]
entities:     [joueur]
summary: >
  L'organisateur gere les equipes du pool : creation, composition, dissolution.
---

## Exigences

### REQ-009  [F-BUSINESS]
statement:  L'organisateur DOIT pouvoir creer une equipe.
hash:       zzz999
acceptance: |
  Etant donne un organisateur
  Quand il cree une equipe
  Alors l'equipe est ajoutee
"""

# {relative_path: content} mappings ----------------------------------------------
VALID_FILES: dict[str, str] = {
    "modules/test-module/features/FEAT-T-001.md": FEATURE_MD,
    "glossary/entities/joueur.md": ENTITY_MD,
    "glossary/actors/orga.md": ACTOR_MD,
    "invariants/INV-T-001.md": INVARIANT_MD,
}

DUPLICATE_FILES: dict[str, str] = {
    "modules/dup-module/features/a.md": DUP_FEATURE_A_MD,
    "modules/dup-module/features/b.md": DUP_FEATURE_B_MD,
}

INVALID_FILES: dict[str, str] = {
    "modules/test-module/features/FEAT-T-003.md": BAD_FRONTMATTER_MD,
}

# A single standalone feature, for partial-merge tests.
FEATURE2_FILES: dict[str, str] = {
    "modules/team-module/features/FEAT-T-009.md": FEATURE2_MD,
}


def write_corpus(root, files: dict[str, str]) -> str:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return str(root)


def valid_corpus(tmp_path) -> str:
    return write_corpus(tmp_path / "valid", VALID_FILES)


def duplicate_id_corpus(tmp_path) -> str:
    return write_corpus(tmp_path / "dup", DUPLICATE_FILES)


def invalid_corpus(tmp_path) -> str:
    return write_corpus(tmp_path / "invalid", INVALID_FILES)
