from __future__ import annotations

import hashlib
import random
from typing import Protocol

Vector = list[float]


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[Vector]: ...


class StubEmbedder:
    """Deterministic, dependency-free embedder for the POC.

    A real Vooban/BNC model wires in behind the same `embed` signature.
    """

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def embed(self, texts: list[str]) -> list[Vector]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> Vector:
        seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
        rng = random.Random(seed)
        v = [rng.gauss(0.0, 1.0) for _ in range(self.dim)]
        norm = sum(x * x for x in v) ** 0.5 or 1.0
        return [x / norm for x in v]


def chunk_text(text: str, size: int = 200, overlap: int = 40) -> list[str]:
    words = text.split()
    if not words:
        return []
    step = max(1, size - overlap)
    chunks: list[str] = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + size]))
        if start + size >= len(words):
            break
    return chunks


def to_vector_literal(vec: Vector) -> str:
    return "[" + ",".join(f"{x:.8f}" for x in vec) + "]"
