from bnc_kb.models import IngestManifest
from bnc_kb.parser.tree import build_nodes


def _manifest():
    return IngestManifest(
        capability_slug="manage-time", category="ops", domain="workforce", source_commit="c1"
    )


def test_build_nodes_shapes_tree():
    files = {
        "manage-time/kb-manifest.yaml": "ignored",
        "manage-time/architecture/00-business-capability-architecture.adoc": "master",
        "manage-time/architecture/documents/01-context-and-requirements/ctx.adoc": ":status: draft\nctx body",
        "manage-time/architecture/documents/06-architectural-decisions/decision_records/ADR-001-x.adoc": ":status: accepted\nadr body",
        "manage-time/architecture/documents/07-risks-and-technical-debts/risks/RISK-001-y.adoc": "risk body",
        "manage-time/requirements/business-fct-1/solution-requirements.md": "sol body",
        "manage-time/requirements/business-fct-1/business-rules.md": "rules body",
    }
    nodes, unreached = build_nodes(files, _manifest())

    by_kind = {}
    for n in nodes:
        by_kind.setdefault(n.kind, []).append(n)

    assert len(by_kind["capability"]) == 1
    cap = by_kind["capability"][0]
    assert cap.parent_local_id is None
    assert cap.attrs["domain"] == "workforce"

    assert len(by_kind["business_function"]) == 1
    bf = by_kind["business_function"][0]
    assert bf.parent_local_id == cap.local_id

    assert len(by_kind["decision_record"]) == 1
    assert by_kind["decision_record"][0].dimension_code == "architectural-decisions"
    assert by_kind["decision_record"][0].attrs["status"] == "accepted"

    assert len(by_kind["risk"]) == 1

    # ctx.adoc is a capability-level document; the two requirement files sit under
    # the business-fct-1 container.
    docs = by_kind["document"]
    assert {d.dimension_code for d in docs} == {
        "context-and-requirements",
        "solution-requirements",
        "business-rules",
    }
    ctx = next(d for d in docs if d.dimension_code == "context-and-requirements")
    assert ctx.parent_local_id == cap.local_id
    assert ctx.attrs["status"] == "draft"
    bf_docs = [
        d
        for d in docs
        if d.dimension_code in {"solution-requirements", "business-rules"}
    ]
    assert all(d.parent_local_id == bf.local_id for d in bf_docs)

    assert any("00-business-capability-architecture" in p for p in unreached)
    assert not any("kb-manifest" in p for p in unreached)


def test_unmatched_files_are_unreached_not_nodes():
    files = {"cap/random/notes.txt": "x"}
    m = IngestManifest(capability_slug="cap", category="c", domain="d", source_commit="s")
    nodes, unreached = build_nodes(files, m)
    assert [n.kind for n in nodes] == ["capability"]
    assert unreached == ["cap/random/notes.txt"]
