import pytest

from bnc_kb.embeddings import StubEmbedder
from bnc_kb.parser.tree import build_nodes
from bnc_kb.models import IngestManifest
from bnc_kb.queries.ingest import persist_nodes

pytestmark = pytest.mark.integration


def _ingest(db, files, commit="c1"):
    m = IngestManifest(
        capability_slug="manage-time", category="ops", domain="workforce", source_commit=commit
    )
    nodes, unreached = build_nodes(files, m)
    return persist_nodes(db, m, nodes, unreached, StubEmbedder(dim=1024))


BASE = {
    "manage-time/kb-manifest.yaml": "x",
    "manage-time/architecture/documents/01-context-and-requirements/ctx.adoc": "ctx body one",
    "manage-time/requirements/business-fct-1/solution-requirements.md": "sol body",
}


def test_first_ingest_creates_nodes_and_embeddings(db):
    s = _ingest(db, BASE)
    assert s.nodes_created == 2
    assert s.idempotent_hit is False
    n_nodes = db.execute("SELECT count(*) FROM node").fetchone()[0]
    assert n_nodes == 4  # capability(1) + business_function(1) + 2 leaf documents
    n_emb = db.execute("SELECT count(*) FROM node_chunk_embedding").fetchone()[0]
    assert n_emb >= 2


def test_reingest_same_commit_is_idempotent(db):
    _ingest(db, BASE, commit="c1")
    s2 = _ingest(db, BASE, commit="c1")
    assert s2.idempotent_hit is True
    assert db.execute("SELECT count(*) FROM node").fetchone()[0] == 4


def test_reingest_new_commit_versions_changed_leaf(db):
    _ingest(db, BASE, commit="c1")
    changed = dict(BASE)
    changed["manage-time/architecture/documents/01-context-and-requirements/ctx.adoc"] = "ctx body TWO"
    s2 = _ingest(db, changed, commit="c2")
    assert s2.nodes_versioned == 1
    assert s2.nodes_skipped == 1
    superseded = db.execute(
        "SELECT count(*) FROM node WHERE status = 'superseded'"
    ).fetchone()[0]
    assert superseded == 1
    v2 = db.execute(
        "SELECT version FROM node WHERE body = 'ctx body TWO'"
    ).fetchone()[0]
    assert v2 == 2
