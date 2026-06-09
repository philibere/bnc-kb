import pytest
from pydantic import ValidationError

from bnc_kb.parser.adoc import extract_adoc_attrs
from bnc_kb.parser.dimensions import dimension_for
from bnc_kb.parser.manifest import parse_manifest


def test_parse_manifest_ok():
    raw = b"capability_slug: manage-time\ncategory: ops\ndomain: workforce\nsource_commit: abc123\n"
    m = parse_manifest(raw)
    assert m.capability_slug == "manage-time"
    assert m.domain == "workforce"


def test_parse_manifest_missing_field():
    with pytest.raises(ValidationError):
        parse_manifest(b"capability_slug: x\n")


@pytest.mark.parametrize(
    "path,expected",
    [
        ("cap/architecture/documents/01-context-and-requirements/a.adoc", "context-and-requirements"),
        ("cap/architecture/documents/06-architectural-decisions/decision_records/ADR-001-x.adoc", "architectural-decisions"),
        ("cap/architecture/documents/07-risks-and-technical-debts/risks/RISK-002-y.adoc", "risks-and-technical-debts"),
        ("cap/processes/flow.md", "processes"),
        ("cap/requirements/business-fct-1/solution-requirements.md", "solution-requirements"),
        ("cap/requirements/business-fct-1/data-requirements.md", "data-requirements"),
        ("cap/requirements/business-fct-1/business-rules.md", "business-rules"),
        ("cap/architecture/00-business-capability-architecture.adoc", None),
        ("cap/README.md", None),
    ],
)
def test_dimension_for(path, expected):
    assert dimension_for(path) == expected


def test_extract_adoc_attrs():
    text = ":status: accepted\n:deciders: alice, bob\n\n== Heading\nbody"
    attrs = extract_adoc_attrs(text)
    assert attrs["status"] == "accepted"
    assert attrs["deciders"] == "alice, bob"
