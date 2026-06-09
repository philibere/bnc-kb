import pytest

pytestmark = pytest.mark.integration


def test_seeds_present(db):
    dims = {r[0] for r in db.execute("SELECT code FROM spec_dimension")}
    assert "architectural-decisions" in dims
    assert len(dims) == 11
    links = {r[0] for r in db.execute("SELECT code FROM link_type")}
    assert "supersedes" in links


def test_rls_written_but_disabled(db):
    enabled = db.execute(
        "SELECT relrowsecurity FROM pg_class WHERE relname = 'node'"
    ).fetchone()[0]
    assert enabled is False
    pol = db.execute("SELECT count(*) FROM pg_policies WHERE tablename = 'node'").fetchone()[0]
    assert pol >= 1
