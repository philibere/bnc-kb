from __future__ import annotations

from uuid import UUID

import pytest
from _corpus import duplicate_id_corpus, valid_corpus

from spec_ingestion import engine
from spec_ingestion import metamodel as mm
from spec_ingestion.sinks import BncKbSink, _nid

from bnc_kb.ingestion import run_corpus_ingest

pytestmark = pytest.mark.integration


def _counts(db) -> tuple[int, int, int]:
    n = db.execute("SELECT count(*) FROM node").fetchone()[0]
    e = db.execute("SELECT count(*) FROM spec_link").fetchone()[0]
    c = db.execute("SELECT count(*) FROM node_chunk_embedding").fetchone()[0]
    return n, e, c


def test_ingest_writes_nodes_edges_chunks(db, db_url, tmp_path):
    report = engine.ingest(valid_corpus(tmp_path), sink=BncKbSink(db_url))
    assert report["status"] == "success"

    n, e, c = _counts(db)
    assert n > 0 and e > 0 and c > 0

    # FEAT-T-001 landed: business id kept in slug, body filled from a tier chunk,
    # status defaulted to 'approved' (the search filter keeps it).
    row = db.execute(
        "SELECT slug, body, status FROM node WHERE slug = 'FEAT-T-001'"
    ).fetchone()
    assert row is not None
    assert row[1] is not None
    assert row[2] == "approved"

    # every chunk carries a shaper tier + a real pgvector (fake embedder, 1024-d).
    assert db.execute(
        "SELECT count(*) FROM node_chunk_embedding WHERE tier IS NULL"
    ).fetchone()[0] == 0
    assert db.execute(
        "SELECT count(*) FROM node_chunk_embedding WHERE embedding IS NULL"
    ).fetchone()[0] == 0


def test_contains_graph_sets_parent_id(db, db_url, tmp_path):
    engine.ingest(valid_corpus(tmp_path), sink=BncKbSink(db_url))
    # the REQ child points at its feature via parent_id (the shaper `contains` graph,
    # set in BncKbSink's second pass). This is what bnc-kb's recursive spec walk uses.
    feat = UUID(_nid("FEAT-T-001"))
    children = db.execute(
        "SELECT count(*) FROM node WHERE parent_id = %s AND kind = 'REQ'", (feat,)
    ).fetchone()[0]
    assert children >= 1


def test_incremental_reingest_is_idempotent(db, db_url, tmp_path):
    corpus = valid_corpus(tmp_path)
    sink = BncKbSink(db_url)
    engine.ingest(corpus, sink=sink)
    before = _counts(db)

    report = engine.ingest(corpus, sink=sink, incremental=True)
    delta = report["delta"]
    assert delta["nodes"] == {"added": 0, "updated": 0, "deleted": 0}
    assert delta["edges"] == {"added": 0, "deleted": 0}
    assert delta["chunks"]["embedded"] == 0
    assert delta["chunks"]["deleted"] == 0
    assert _counts(db) == before  # store unchanged


def test_ingest_seeds_all_manifest_edge_kinds(db, db_url, tmp_path):
    # link_type (the spec_link.rel FK target) is aligned with the manifest, not just
    # the 16 hardcoded in 0006, so any corpus edge kind has its FK target.
    run_corpus_ingest(valid_corpus(tmp_path), db_url, incremental=False)
    present = {r[0] for r in db.execute("SELECT code FROM link_type").fetchall()}
    assert set(mm.EDGE_KINDS) <= present


def test_validation_rejects_duplicate_id_and_writes_nothing(db, db_url, tmp_path):
    report = engine.ingest(duplicate_id_corpus(tmp_path), sink=BncKbSink(db_url))
    assert report["status"] == "rejected"
    assert report["faulty"]
    assert _counts(db) == (0, 0, 0)  # rejection writes nothing
