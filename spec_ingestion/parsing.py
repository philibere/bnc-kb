"""Phase 3 parsing primitives: YAML frontmatter + atomic ``###`` blocks.

Generic, type-agnostic helpers consumed by the manifest-driven extractor
(``extraction.extract_generic``): split a markdown doc into (frontmatter, body),
iterate its ``### MARKER-`` atomic blocks, and parse a block's ``key: value``
fields (incl. ``key: |`` literals) and inline ``[a, b]`` lists. No per-type
knowledge lives here anymore -- spec types are described in the M2 manifest and
projected by the generic extractor.

Pure-Python, no DB.
"""

from __future__ import annotations

import re

import yaml


class ParseError(ValueError):
    """Raised when frontmatter is not parseable YAML or is structurally invalid."""


_FRONTMATTER_RE = re.compile(r"\A---\s*\n(?P<fm>.*?)\n---\s*\n?(?P<body>.*)\Z", re.DOTALL)

# Heading of an atomic block, e.g. "### REQ-001  [F-BUSINESS]" or
# "### CONTRACT-player-identity  [DATA]" or "### DEC-suppression-...".
_BLOCK_HEADING_RE = re.compile(
    r"^###\s+(?P<title>\S+)\s*(?:\[(?P<tag>[^\]]*)\])?\s*$",
    re.MULTILINE,
)

# A block field line: "key:   value" (value may be empty or a "|" literal marker).
_FIELD_RE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*):(?P<rest>.*)$")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Split a markdown document into (frontmatter dict, body string).

    Raises :class:`ParseError` when the frontmatter is absent or not a YAML
    mapping.
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ParseError("missing YAML frontmatter delimited by '---'")
    try:
        data = yaml.safe_load(match.group("fm"))
    except yaml.YAMLError as exc:
        raise ParseError(f"invalid YAML frontmatter: {exc}") from exc
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ParseError("frontmatter is not a YAML mapping")
    return data, match.group("body")


def _parse_inline_list(raw: str) -> list[str]:
    """Parse a "[a, b, c]" inline array (block-field syntax). Empty -> []."""
    raw = raw.strip()
    if not raw or raw in ("[]", "null", "~"):
        return []
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


def _parse_block_fields(body: str) -> dict[str, object]:
    """Parse the line-based ``key: value`` fields inside one atomic block body.

    Supports ``key: |`` literal blocks whose value is the following indented
    lines. Returns raw string/list values keyed by field name.
    """
    fields: dict[str, object] = {}
    lines = body.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _FIELD_RE.match(line)
        if not match:
            i += 1
            continue
        key = match.group("key")
        rest = match.group("rest").strip()
        if rest == "|":
            # Literal block: consume following more-indented (or blank) lines.
            collected: list[str] = []
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if nxt.strip() == "":
                    collected.append("")
                    i += 1
                    continue
                if nxt.startswith((" ", "\t")):
                    collected.append(nxt.strip())
                    i += 1
                    continue
                break
            while collected and collected[-1] == "":
                collected.pop()
            fields[key] = "\n".join(collected)
            continue
        fields[key] = rest
        i += 1
    return fields


def _iter_blocks(body: str):
    """Yield (heading-dict, block-body) for each ``###`` atomic block in order."""
    matches = list(_BLOCK_HEADING_RE.finditer(body))
    for idx, m in enumerate(matches):
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(body)
        yield {"title": m.group("title"), "tag": m.group("tag")}, body[start:end]
