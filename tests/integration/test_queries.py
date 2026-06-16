from __future__ import annotations

from uuid import UUID

import pytest
from _corpus import valid_corpus
from pgvector.psycopg import register_vector

from bnc_kb.embeddings import embed_query
from bnc_kb.queries.links import get_links
from bnc_kb.queries.search import search_specs
from bnc_kb.queries.spec import get_spec
from spec_ingestion import engine
from spec_ingestion.sinks import BncKbSink, _nid

pytestmark = pytest.mark.integration


@pytest.fixture
def seeded(db, db_url, tmp_path):
    """bnc-kb store seeded by the vendored engine via BncKbSink (the new ingestion)."""
    engine.ingest(valid_corpus(tmp_path), sink=BncKbSink(db_url))
    return db


def test_search_self_retrieval(seeded):
    # bnc-kb's own SEARCH_SQL over shaper data: a node's stored vector retrieves the
    # node itself (pgvector round-trip through the converged store).
    register_vector(seeded)
    feat = UUID(_nid("FEAT-T-001"))
    vec = seeded.execute(
        "SELECT embedding FROM node_chunk_embedding "
        "WHERE node_id = %s AND embedding IS NOT NULL LIMIT 1",
        (feat,),
    ).fetchone()[0]
    qvec = [float(x) for x in vec]
    hits = search_specs(seeded, qvec, dimension=None, status="approved", k=5)
    assert hits
    assert hits[0]["slug"] == "FEAT-T-001"


def test_search_via_query_embedder(seeded):
    # the /search path: embed the query with the SAME embedder as ingestion, then run
    # bnc-kb's SEARCH_SQL. Proves the query-embedder wiring against the store.
    hits = search_specs(seeded, embed_query("gerer le bassin de joueurs"), None, "approved", 5)
    assert hits


def test_get_spec_traverses_contains(seeded):
    rows = get_spec(seeded, UUID(_nid("FEAT-T-001")), None, "approved")
    slugs = {r["slug"] for r in rows}
    assert "FEAT-T-001" in slugs  # the feature head
    assert any(r["kind"] == "REQ" for r in rows)  # walked contains -> its REQ child


def test_get_links_surfaces_typed_edges(seeded):
    links = get_links(seeded, UUID(_nid("FEAT-T-001")), rel=None)
    assert links
    rels = {r["rel"] for r in links}
    assert rels & {"affects-entity", "performed-by"}  # shaper edge kinds traverse
    assert all(r["target"] for r in links)  # resolved internal targets -> slugs
