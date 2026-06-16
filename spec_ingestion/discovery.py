"""AC-01/AC-14/AC-15: discovery + classification of corpus artifacts.

Accepts a target that is a single ``.md`` file, a directory (recurse for all
``.md``) or a corpus root. Classification is ``kind``-FIRST: the frontmatter
``kind`` is authoritative; the path is only a hint, so a file outside the corpus
tree still classifies. Unknown / unrecognized ``kind`` (``intake/*``, ``runs/*``,
anything else) are ignored and logged via structured logging; they never fail the
batch. No manual step is required.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from spec_ingestion import metamodel as _mm

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---", re.DOTALL)
_KIND_RE = re.compile(r"^kind:\s*(\S+)\s*$", re.MULTILINE)


# Discoverable artifact types come from the M2 manifest (one per frontmatter
# ``kind`` token). Built dynamically as a ``str`` enum so a new declarative type
# (e.g. capability) is discoverable from data; member ids hyphen -> underscore.
ArtifactType = Enum(
    "ArtifactType",
    {tok.replace("-", "_"): tok for tok in _mm.ARTIFACT_KIND_TOKENS},
    type=str,
)


def _at(name: str) -> "ArtifactType | None":
    """ArtifactType member by name, or None if THIS SDLC's manifest lacks it.

    Path hints below are a bnc-convention FALLBACK (used only when a file has no
    readable frontmatter ``kind``). A different client SDLC has its own kinds and
    typically no such paths, so a missing member must degrade to None, never crash.
    """
    return ArtifactType.__members__.get(name)


# Map glossary path segment -> ArtifactType, restricted to kinds this SDLC defines.
_GLOSSARY_SEGMENTS = {
    seg: _at(name)
    for seg, name in (
        ("actors", "actor"),
        ("entities", "entity"),
        ("external-systems", "external_system"),
        ("processes", "process"),
    )
    if _at(name) is not None
}

# Frontmatter ``kind`` token -> ArtifactType (kind-first, authoritative). The
# frontmatter value mirrors ``ArtifactType.value`` for every classified type.
_KIND_TO_TYPE = {t.value: t for t in ArtifactType}


@dataclass
class Artifact:
    path: Path
    artifact_type: ArtifactType
    frontmatter_kind: str | None


@dataclass
class DiscoveryResult:
    artifacts: list[Artifact] = field(default_factory=list)
    ignored: list[Path] = field(default_factory=list)


def _read_frontmatter_kind(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    block = _FRONTMATTER_RE.match(text)
    if not block:
        return None
    match = _KIND_RE.search(block.group(0))
    return match.group(1) if match else None


def _path_hint(path: Path) -> ArtifactType | None:
    """A path-segment HINT for the artifact type. Only a hint: the frontmatter
    ``kind`` is authoritative. Returns ``None`` for unrecognized locations."""
    parts = path.parts

    # invariants/INV-*.md
    if "invariants" in parts:
        return _at("invariant")

    # modules/<module>/features/*.md
    if "modules" in parts and "features" in parts:
        return _at("technical" if path.name.endswith(".technical.md") else "feature")

    # glossary/<segment>/*.md
    if "glossary" in parts:
        idx = parts.index("glossary")
        if idx + 1 < len(parts):
            return _GLOSSARY_SEGMENTS.get(parts[idx + 1])

    return None


def _classify(path: Path) -> tuple[ArtifactType | None, str | None]:
    """Classify a markdown file KIND-FIRST. Returns ``(type, frontmatter_kind)``.

    The frontmatter ``kind`` is authoritative (so a file outside the corpus tree
    still classifies); the path is only a hint and is used only as a fallback when
    no usable ``kind`` is present. An unrecognized ``kind`` is ignored even when the
    path would otherwise hint a type, so out-of-scope artifacts never sneak in.
    """
    fm_kind = _read_frontmatter_kind(path)
    if fm_kind is not None:
        return _KIND_TO_TYPE.get(fm_kind), fm_kind
    # No readable frontmatter kind: fall back to the path-derived hint.
    return _path_hint(path), None


def _md_files(target: Path) -> list[Path]:
    """The ``.md`` files under ``target``: just itself if a file, recursive if a dir."""
    if target.is_file():
        return [target] if target.suffix == ".md" else []
    return [p for p in sorted(target.rglob("*.md")) if p.is_file()]


def discover(roots: list[Path] | list[str]) -> DiscoveryResult:
    """Discover + classify ``.md`` targets (AC-01/AC-14/AC-15).

    Each root is a single ``.md`` file, a directory (recursed for all ``.md``), or
    a corpus root. Classification is KIND-FIRST: the frontmatter ``kind`` decides
    the type, the path is only a hint. An unrecognized ``kind`` is ignored + logged
    and never fails the batch.
    """
    result = DiscoveryResult()
    for root in roots:
        root_path = Path(root)
        for path in _md_files(root_path):
            artifact_type, fm_kind = _classify(path)
            if artifact_type is None:
                result.ignored.append(path)
                logger.info(
                    "ignored unrecognized artifact: %s (kind=%r)", path, fm_kind
                )
                continue
            result.artifacts.append(Artifact(path, artifact_type, fm_kind))
    return result
