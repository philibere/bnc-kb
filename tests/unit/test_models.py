import pytest
from pydantic import ValidationError

from bnc_kb.models import Coverage, IngestManifest, SearchRequest


def test_manifest_requires_all_fields():
    with pytest.raises(ValidationError):
        IngestManifest(capability_slug="x", category="c")  # missing domain, source_commit


def test_coverage_defaults():
    c = Coverage()
    assert c.partial is False
    assert c.sources_unreached == []


def test_search_request_defaults():
    r = SearchRequest(query="hello")
    assert r.status == "approved"
    assert r.k == 12
