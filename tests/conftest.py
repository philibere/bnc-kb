from __future__ import annotations

import io
import os
import zipfile
from pathlib import Path

import psycopg
import pytest

from bnc_kb.db.migrate import apply_migrations

TEST_DB_URL = os.environ.get("DATABASE_URL", "postgresql://kb:kb@localhost:5433/kb")


def _migrated_once() -> None:
    try:
        apply_migrations(TEST_DB_URL)
    except psycopg.OperationalError:
        pass  # no DB available; integration tests will be skipped/failed explicitly


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _migrated_once()


@pytest.fixture
def db():
    """A connection with the data tables truncated before each test."""
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE node_chunk_embedding, spec_link, node, ingestion RESTART IDENTITY CASCADE"
        )
        yield conn


def make_zip(tree: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in tree.items():
            zf.writestr(path, content)
    return buf.getvalue()


@pytest.fixture
def sample_zip() -> bytes:
    root = Path(__file__).parent / "fixtures" / "sample-capability"
    tree: dict[str, str] = {}
    for p in root.rglob("*"):
        if p.is_file():
            tree[str(p.relative_to(root.parent))] = p.read_text()
    return make_zip(tree)
