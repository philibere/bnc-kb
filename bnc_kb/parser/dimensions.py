from __future__ import annotations

# Folder-substring -> dimension, derived from the spec's provenance table.
DIMENSION_BY_FOLDER: list[tuple[str, str]] = [
    ("documents/01-context-and-requirements", "context-and-requirements"),
    ("documents/02-quality-attributes", "quality-attributes"),
    ("documents/03-constraints", "constraints"),
    ("documents/04-architecture-diagrams", "architecture-diagrams"),
    ("documents/05-infrastructure-costs", "infrastructure-costs"),
    ("documents/06-architectural-decisions", "architectural-decisions"),
    ("documents/07-risks-and-technical-debts", "risks-and-technical-debts"),
    ("/processes/", "processes"),
]

REQUIREMENT_FILES: dict[str, str] = {
    "solution-requirements.md": "solution-requirements",
    "data-requirements.md": "data-requirements",
    "business-rules.md": "business-rules",
}


def dimension_for(path: str) -> str | None:
    base = path.rsplit("/", 1)[-1]
    if "requirements/" in path and base in REQUIREMENT_FILES:
        return REQUIREMENT_FILES[base]
    for folder, dim in DIMENSION_BY_FOLDER:
        if folder in path:
            return dim
    return None
