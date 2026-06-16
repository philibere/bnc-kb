from __future__ import annotations

import pytest
from _corpus import (
    FEATURE2_FILES,
    SAME_MODULE_FILES,
    VALID_FILES,
    valid_corpus,
    write_corpus,
)

from bnc_kb.ingestion import run_merge
from spec_ingestion import engine
from spec_ingestion.sinks import BncKbSink

pytestmark = pytest.mark.integration


def _node_count(db) -> int:
    return db.execute("SELECT count(*) FROM node").fetchone()[0]


def test_merge_adds_specs_without_deleting_the_rest(db, db_url, tmp_path):
    # whole corpus first (FEAT-T-001 + glossary + invariant)
    engine.ingest(valid_corpus(tmp_path), sink=BncKbSink(db_url))
    before = _node_count(db)

    # partial merge of a NEW standalone feature
    sub = write_corpus(tmp_path / "extra", FEATURE2_FILES)
    report = run_merge(sub, db_url)
    assert report["status"] == "success"
    assert report["delta"]["mode"] == "merge"

    # the rest of the store is intact AND the new feature landed
    assert db.execute("SELECT count(*) FROM node WHERE slug = 'FEAT-T-001'").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM node WHERE slug = 'FEAT-T-009'").fetchone()[0] == 1
    assert _node_count(db) > before


def test_merge_resolves_pending_against_existing_store(db, db_url, tmp_path):
    # joueur + orga already in the store (from the full corpus)
    engine.ingest(valid_corpus(tmp_path), sink=BncKbSink(db_url))

    sub = write_corpus(tmp_path / "feat2", FEATURE2_FILES)
    run_merge(sub, db_url)

    # FEAT-T-009 -> joueur (affects-entity) resolved to a real dst_id (joueur exists)
    resolved = db.execute(
        "SELECT count(*) FROM spec_link l "
        "JOIN node s ON s.id = l.src_id JOIN node d ON d.id = l.dst_id "
        "WHERE s.slug = 'FEAT-T-009' AND d.slug = 'joueur' AND l.pending = false"
    ).fetchone()[0]
    assert resolved >= 1


def test_merge_is_idempotent(db, db_url, tmp_path):
    engine.ingest(valid_corpus(tmp_path), sink=BncKbSink(db_url))
    sub = write_corpus(tmp_path / "feat2", FEATURE2_FILES)
    run_merge(sub, db_url)
    before = _node_count(db)

    report = run_merge(sub, db_url)  # re-merge the same spec
    delta = report["delta"]
    assert delta["nodes"] == {"added": 0, "updated": 0, "deleted": 0}
    assert delta["edges"]["added"] == 0
    assert delta["edges"]["deleted"] == 0
    assert delta["edges"]["resolved_pending"] == 0  # already resolved, no churn
    assert delta["chunks"]["embedded"] == 0
    assert _node_count(db) == before


def test_merge_keeps_other_features_in_shared_module(db, db_url, tmp_path):
    # FEAT-T-001 and FEAT-T-010 share module test-module (one shared Module node).
    full = dict(VALID_FILES)
    full.update(SAME_MODULE_FILES)
    engine.ingest(write_corpus(tmp_path / "shared", full), sink=BncKbSink(db_url))
    contains_before = db.execute(
        "SELECT count(*) FROM spec_link l JOIN node s ON s.id = l.src_id "
        "WHERE s.kind = 'Module' AND l.rel = 'contains'"
    ).fetchone()[0]
    assert contains_before >= 2

    # merge ONLY FEAT-T-010: the Module's contains edge to FEAT-T-001 must survive.
    report = run_merge(write_corpus(tmp_path / "one", SAME_MODULE_FILES), db_url)
    assert report["delta"]["edges"]["deleted"] == 0
    survived = db.execute(
        "SELECT count(*) FROM spec_link l JOIN node s ON s.id = l.src_id "
        "JOIN node d ON d.id = l.dst_id "
        "WHERE s.kind = 'Module' AND l.rel = 'contains' AND d.slug = 'FEAT-T-001'"
    ).fetchone()[0]
    assert survived == 1


def test_merge_does_not_reject_on_external_refs(db, db_url, tmp_path):
    # FEAT-T-009 references orga/joueur which are NOT in the batch and NOT yet stored:
    # partial mode keeps those edges pending instead of rejecting.
    sub = write_corpus(tmp_path / "lonely", FEATURE2_FILES)
    report = run_merge(sub, db_url)
    assert report["status"] == "success"
    assert db.execute("SELECT count(*) FROM node WHERE slug = 'FEAT-T-009'").fetchone()[0] == 1
    pending = db.execute("SELECT count(*) FROM spec_link WHERE pending = true").fetchone()[0]
    assert pending >= 1
