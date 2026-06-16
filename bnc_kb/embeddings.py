"""Query-time embedding helpers.

Ingestion embeds via the vendored ``spec_ingestion`` engine (``EMBEDDING_MODEL``
selects FakeEmbedder or BgeM3Embedder). Query-time embedding MUST use the SAME
model so the query vector and the stored vectors live in one space; we therefore
go through ``spec_ingestion.embedding.select_embedder`` here too, cached so the
real bge-m3 model loads once per process.

``to_vector_literal`` stays a pure helper used by the read queries to pass a
vector as a ``::vector`` literal.
"""

from __future__ import annotations

from functools import lru_cache

from spec_ingestion.embedding import Embedder, select_embedder

Vector = list[float]


@lru_cache(maxsize=1)
def _query_embedder() -> Embedder:
    """Cached embedder shared across query requests (same model as ingestion)."""
    return select_embedder()


def embed_query(text: str) -> Vector:
    """Embed a query string into the ingestion vector space."""
    return [float(x) for x in _query_embedder().encode([text])[0]]


def to_vector_literal(vec: Vector) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
