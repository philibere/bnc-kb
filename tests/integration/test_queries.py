import pytest

from bnc_kb.embeddings import StubEmbedder
from bnc_kb.models import IngestManifest
from bnc_kb.parser.tree import build_nodes
from bnc_kb.queries.ingest import persist_nodes
from bnc_kb.queries.links import get_links
from bnc_kb.queries.search import search_specs
from bnc_kb.queries.spec import get_spec

pytestmark = pytest.mark.integration

FILES = {
    "manage-time/kb-manifest.yaml": "x",
    "manage-time/architecture/documents/01-context-and-requirements/ctx.adoc": "timesheet approval context",
    "manage-time/requirements/business-fct-1/solution-requirements.md": "overtime calculation rules",
}


@pytest.fixture
def seeded(db):
    m = IngestManifest(
        capability_slug="manage-time", category="ops", domain="workforce", source_commit="c1"
    )
    nodes, unreached = build_nodes(FILES, m)
    persist_nodes(db, m, nodes, unreached, StubEmbedder(dim=1024))
    cap_id = db.execute("SELECT id FROM node WHERE kind = 'capability'").fetchone()[0]
    return db, cap_id


def test_get_spec_returns_subtree_documents(seeded):
    db, cap_id = seeded
    rows = get_spec(db, cap_id, dimension=None, status="approved")
    dims = {r["dimension_code"] for r in rows}
    assert dims == {"context-and-requirements", "solution-requirements"}


def test_get_spec_filters_by_dimension(seeded):
    db, cap_id = seeded
    rows = get_spec(db, cap_id, dimension="solution-requirements", status="approved")
    assert len(rows) == 1
    assert rows[0]["body"] == "overtime calculation rules"


def test_hybrid_search_ranks_exact_text_first(seeded):
    db, _ = seeded
    qvec = StubEmbedder(dim=1024).embed(["overtime calculation rules"])[0]
    rows = search_specs(db, qvec, dimension=None, status="approved", k=12)
    assert rows
    assert rows[0]["body"] == "overtime calculation rules"
    assert rows[0]["score"] > 0.99  # stub embeds identical text identically


def test_get_links(seeded):
    db, cap_id = seeded
    src = db.execute(
        "SELECT id FROM node WHERE dimension_code = 'solution-requirements'"
    ).fetchone()[0]
    db.execute(
        "INSERT INTO spec_link (src_id, dst_id, rel) VALUES (%s, %s, 'belongs_to')",
        (src, cap_id),
    )
    links = get_links(db, src, rel=None)
    assert links == [{"rel": "belongs_to", "target": "manage-time"}]
