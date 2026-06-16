"""Phase 5: pluggable embedder + tier chunking (AC-05/AC-11/AC-04 socle).

An ``Embedder`` turns texts into a deterministic ``(N, 1024)`` float32 matrix and
exposes a ``model_version`` string. Two implementations:

* ``FakeEmbedder`` — deterministic by (text, model_version), no heavy deps; the
  default in tests for speed.
* ``BgeM3Embedder`` — the real ``BAAI/bge-m3`` model via sentence-transformers.

``sentence_transformers`` / ``torch`` are the optional ``embed`` extra and are
NOT installed by default; they are lazy-imported INSIDE ``BgeM3Embedder`` so that
``import spec_ingestion.embedding`` always succeeds without torch.

``embed_chunks`` takes the tier chunks already produced by ``extraction`` (REQ
context-header+statement+acceptance, feature_summary, glossary_definition) and
fills in the embedding plus the composite-key fields ``content_hash`` /
``embedding_model_version`` / ``pipeline_version``. Incrementality is driven by
that composite key ``(node_id, tier, content_hash, embedding_model_version,
pipeline_version)`` and is proven end-to-end in the store slice (P7): an unchanged
key skips re-embedding (AC-05); a model/pipeline-version bump changes the key and
forces a re-embed (AC-11).
"""

from __future__ import annotations

import hashlib
from dataclasses import replace
from typing import Protocol, runtime_checkable

import numpy as np

from spec_ingestion.config import embedding_model

EMBEDDING_DIM = 1024


@runtime_checkable
class Embedder(Protocol):
    """Encodes texts into an ``(N, EMBEDDING_DIM)`` float32 matrix."""

    model_version: str

    def encode(self, texts: list[str]) -> np.ndarray: ...


class FakeEmbedder:
    """Deterministic embedder keyed by (text, model_version).

    Hashes each text (salted by the model version) into a stable seed, draws a
    1024-d vector from a seeded RNG, then L2-normalizes it. Same input -> identical
    vector; different input or model version -> different vector. No heavy deps.
    """

    def __init__(self, model_version: str = "fake-v1") -> None:
        self.model_version = model_version

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.empty((len(texts), EMBEDDING_DIM), dtype=np.float32)
        for i, text in enumerate(texts):
            out[i] = self._vector(text)
        return out

    def _vector(self, text: str) -> np.ndarray:
        seed_material = f"{self.model_version}\x00{text}".encode("utf-8")
        digest = hashlib.sha256(seed_material).digest()
        seed = int.from_bytes(digest[:8], "big")
        rng = np.random.default_rng(seed)
        vec = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)
        norm = np.linalg.norm(vec)
        if norm == 0:
            vec[0] = 1.0
            norm = 1.0
        return vec / norm


class BgeM3Embedder:
    """Real ``BAAI/bge-m3`` embedder (1024-d, multilingual).

    ``sentence_transformers``/``torch`` are lazy-imported here so the module
    imports without the optional ``embed`` extra installed.
    """

    def __init__(self, model_id: str = "BAAI/bge-m3", revision: str | None = None) -> None:
        from sentence_transformers import SentenceTransformer  # lazy: optional extra

        self.model_id = model_id
        self.revision = revision
        self._model = SentenceTransformer(model_id, revision=revision)
        self.model_version = model_id if revision is None else f"{model_id}@{revision}"

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return np.asarray(vectors, dtype=np.float32)


def select_embedder(model: str | None = None) -> Embedder:
    """Pick the embedder from config: ``fake*`` -> FakeEmbedder, else BgeM3Embedder.

    The model id is resolved from ``EMBEDDING_MODEL`` when not passed explicitly so
    the same selection drives the whole pipeline (one vector space).
    """
    model = model if model is not None else embedding_model()
    if model.lower().startswith("fake"):
        return FakeEmbedder(model_version=model)
    return BgeM3Embedder(model_id=model)


def embed_chunks(chunks, embedder: Embedder, pipeline_version: str) -> list:
    """Embed tier chunks, returning copies with the composite key fully populated.

    ``chunks`` are the tier chunks emitted by ``extraction`` (their ``tier``,
    ``text`` and ``content_hash`` are already set). This stamps each chunk with the
    embedder's vector, ``embedding_model_version`` and ``pipeline_version`` so the
    store can compare composite keys for incrementality.
    """
    chunk_list = list(chunks)
    if not chunk_list:
        return []
    vectors = embedder.encode([c.text for c in chunk_list])
    embedded = []
    for chunk, vector in zip(chunk_list, vectors):
        embedded.append(
            replace(
                chunk,
                embedding_model_version=embedder.model_version,
                pipeline_version=pipeline_version,
                embedding=[float(x) for x in vector],
            )
        )
    return embedded


def stamp_versions(chunks, model_version: str, pipeline_version: str) -> list:
    """Stamp the composite-key version fields WITHOUT embedding (no vector cost).

    The incremental path stamps every desired chunk so it can compute each one's
    prospective composite key ``(node_id, tier, content_hash, model_version,
    pipeline_version)`` and compare it against the store; only the chunks whose key
    is absent are then actually embedded. Unembedded chunks keep ``embedding=[]``.
    """
    return [
        replace(
            c,
            embedding_model_version=model_version,
            pipeline_version=pipeline_version,
            embedding=[],
        )
        for c in chunks
    ]
