from bnc_kb.models import Coverage, IngestResult, SearchRequest


def test_ingest_result_defaults():
    r = IngestResult(status="success")
    assert r.nodes == 0
    assert r.faulty == []
    assert r.delta is None


def test_coverage_defaults():
    c = Coverage()
    assert c.partial is False
    assert c.sources_unreached == []


def test_search_request_defaults():
    r = SearchRequest(query="hello")
    assert r.status == "approved"
    assert r.k == 12
