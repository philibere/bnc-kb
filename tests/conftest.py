from __future__ import annotations

import io
import os
import zipfile

import psycopg
import pytest

from bnc_kb.db.migrate import apply_migrations

# Deterministic, torch-free embedder for tests (also the bnc-kb default).
os.environ.setdefault("EMBEDDING_MODEL", "fake-v1")

TEST_DB_URL = os.environ.get("DATABASE_URL", "postgresql://kb:kb@localhost:5433/kb")


def _migrated_once() -> None:
    try:
        apply_migrations(TEST_DB_URL)
    except psycopg.OperationalError:
        pass  # no DB available; integration tests will be skipped/failed explicitly


@pytest.fixture(scope="session", autouse=True)
def _schema():
    _migrated_once()


_SEED_DIMENSIONS = (
    "context-and-requirements",
    "quality-attributes",
    "constraints",
    "architecture-diagrams",
    "infrastructure-costs",
    "architectural-decisions",
    "risks-and-technical-debts",
    "processes",
    "solution-requirements",
    "data-requirements",
    "business-rules",
)

# Governed link-type whitelist preserved between tests: the original bnc-kb 6 plus
# the 16 shaper edge kinds seeded by 0006_shaper_convergence.sql (the converged
# ingestion writes these). The fixture deletes only test-added link types.
_SEED_LINK_TYPES = (
    # bnc-kb originals (0003)
    "belongs_to",
    "derives_from",
    "supersedes",
    "traces_to",
    "depends_on",
    # shaper edge kinds (0006)
    "contains",
    "affects-entity",
    "performed-by",
    "integrates-with",
    "broader",
    "conflicts-with",
    "refines",
    "satisfies",
    "addresses",
    "constrains",
    "realizes",
    "serves",
    "governed-by",
    "threatens",
    "mitigated-by",
    "accepted-by",
)


@pytest.fixture
def db():
    """A connection with data tables truncated and the governed whitelists restored.

    The whitelist re-seed is idempotent and self-healing: 0006 seeds the shaper link
    types once, but a prior run may have dropped them, so we re-insert before each
    test rather than rely on migration-application history.
    """
    with psycopg.connect(TEST_DB_URL, autocommit=True) as conn:
        conn.execute(
            "TRUNCATE node_chunk_embedding, spec_link, node, ingestion RESTART IDENTITY CASCADE"
        )
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO link_type (code, label) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING",
                [(c, c) for c in _SEED_LINK_TYPES],
            )
        conn.execute(
            "DELETE FROM spec_dimension WHERE code <> ALL(%s::text[])",
            (list(_SEED_DIMENSIONS),),
        )
        conn.execute(
            "DELETE FROM link_type WHERE code <> ALL(%s::text[])",
            (list(_SEED_LINK_TYPES),),
        )
        yield conn


@pytest.fixture
def db_url() -> str:
    """The DSN the durable sinks (BncKbSink) connect to."""
    return TEST_DB_URL


def make_zip(tree: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in tree.items():
            zf.writestr(path, content)
    return buf.getvalue()
