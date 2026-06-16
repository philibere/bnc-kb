"""Domain model: typed graph nodes/edges, embedding chunks.

Node kinds, edge kinds and embedding tiers are CLOSED vocabularies (str enums).
A kind outside the set raises ``ValueError`` on construction, which is how the
validation gate fails a batch carrying an out-of-taxonomy reference (AC-02).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from spec_ingestion import metamodel as _mm

# Node/edge/tier kinds are CLOSED vocabularies, now sourced from the M2 manifest
# (metamodel) instead of being hardcoded here. Built dynamically as ``str`` enums
# with the SAME members, values and order as before; constructing a kind outside
# the set still raises ``ValueError`` (the validation gate's AC-02 behaviour).
# EdgeKind member identifiers use underscores; values carry the on-disk hyphens.
# ``candidate-*`` edges and ``derive(...)`` sentinels remain out of scope (the
# manifest simply does not emit them).
NodeKind = Enum("NodeKind", {name: name for name in _mm.NODE_KINDS}, type=str)
EdgeKind = Enum("EdgeKind", {value.replace("-", "_"): value for value in _mm.EDGE_KINDS}, type=str)
Tier = Enum("Tier", {name: name for name in _mm.TIERS}, type=str)


@dataclass
class Node:
    id: str
    kind: NodeKind
    props: dict
    content_hash: str
    source_path: str


@dataclass
class Edge:
    src_id: str
    dst_ref: str
    kind: EdgeKind
    dst_id: str | None = None
    pending: bool = False


@dataclass
class Chunk:
    node_id: str
    tier: Tier
    text: str
    content_hash: str
    embedding_model_version: str
    pipeline_version: str
    embedding: list[float]
    # Populated only on the read path (semantic_search): cosine similarity to the
    # query. ``None`` for chunks produced by extraction/embedding.
    score: float | None = None
