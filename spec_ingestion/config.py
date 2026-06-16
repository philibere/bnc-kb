"""Configuration read from the environment.

JSON-only pipeline: the embedder model id and pipeline version are the only knobs
read from the environment. No database / DSN concern remains.

VENDORED in bnc-kb: the default embedder is ``fake-v1`` (deterministic, no torch),
the bnc-kb default. The real ``BAAI/bge-m3`` is opt-in via ``EMBEDDING_MODEL`` plus
the optional ``embed`` extra (sentence-transformers + torch).
"""

from __future__ import annotations

import os

DEFAULT_EMBEDDING_MODEL = "fake-v1"
DEFAULT_PIPELINE_VERSION = "v1"


def embedding_model() -> str:
    return os.environ.get("EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL)


def pipeline_version() -> str:
    return os.environ.get("PIPELINE_VERSION", DEFAULT_PIPELINE_VERSION)
