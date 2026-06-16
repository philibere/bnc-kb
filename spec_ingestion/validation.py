"""Phase 4 validation gate (AC-02) + reference resolution / pending (AC-12).

A fail-fast gate that runs BEFORE any write and returns a structured verdict.
Any one rejection reason fails the whole batch atomically; faulty artifacts are
collected with identifiers + paths only (NEVER raw artifact content).

Rejection reasons:
  * duplicate ``id`` across the batch
  * broken link: an edge ``dst_ref`` resolvable in NO declared source -- not by
    id, not by glossary name/alias, neither in the current batch nor in
    ``stored_ids`` nor declared elsewhere (``declared_ids``)
  * a node/edge kind outside the closed taxonomy (defense-in-depth even though
    extraction emits closed vocab only)
  * unreadable frontmatter -- a ``ParseError`` surfaced by parsing is passed in
    as a faulty entry (``parse_errors``), never crashing the gate

Pending (NOT a rejection): an edge whose ``dst_ref`` is absent from the current
batch but IS a declared-but-not-yet-ingested target (``declared_ids``) ->
``edge.pending = True`` and added to ``pending_edges``. Distinguished from broken
(resolvable nowhere). Persistence of pending edges is a later slice (P7).

Resolution side effect: a resolvable edge gets its ``dst_id`` set on the Edge
(dst_ref -> dst_id). Pending and broken edges leave ``dst_id`` unset.

Pure-Python, no DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from spec_ingestion import metamodel as _mm
from spec_ingestion.model import Edge, EdgeKind, Node, NodeKind

# Glossary node kinds carry name + aliases usable as name-hint resolution keys.
# Manifest-driven: the kinds a glossary spec type produces (``produces_node_by_kind``).
# bnc => {Actor, Entity, ExternalSystem, Process}; a client SDLC without a glossary
# spec type => empty (no name-hint resolution, no hardcoded bnc vocabulary).
_GLOSSARY_KINDS = frozenset(
    NodeKind.__members__[name]
    for name in _mm.GLOSSARY_KIND_TO_NODE.values()
    if name in NodeKind.__members__
)

_VALID_NODE_KINDS = frozenset(NodeKind)
_VALID_EDGE_KINDS = frozenset(EdgeKind)


@dataclass
class FaultyArtifact:
    """A rejected artifact: identifiers + path only, never raw content."""

    artifact_id: str
    path: str
    reason: str

    def as_dict(self) -> dict:
        return {"artifact_id": self.artifact_id, "path": self.path, "reason": self.reason}


@dataclass
class ValidationResult:
    status: str = "ok"  # "ok" | "rejected"
    faulty: list[dict] = field(default_factory=list)
    pending_edges: list[dict] = field(default_factory=list)
    resolved_edges: list[Edge] = field(default_factory=list)


def _build_name_index(nodes: list[Node]) -> dict[str, str]:
    """name/alias -> canonical node id, for glossary name-hint resolution."""
    index: dict[str, str] = {}
    for node in nodes:
        if node.kind not in _GLOSSARY_KINDS:
            continue
        props = node.props or {}
        name = props.get("name")
        if name:
            index[str(name)] = node.id
        for alias in props.get("aliases") or []:
            index[str(alias)] = node.id
    return index


def validate(
    nodes: list[Node],
    edges: list[Edge],
    *,
    stored_ids: set[str] | None = None,
    declared_ids: set[str] | None = None,
    parse_errors: list[FaultyArtifact] | None = None,
    partial: bool = False,
) -> ValidationResult:
    """Run the fail-fast gate over an extracted batch.

    ``stored_ids``   ids already ingested (resolvable -> ok).
    ``declared_ids`` ids declared across all sources but not in this batch and
                     not yet stored -> a ref to one of these is ``pending``.
    ``parse_errors`` ParseError-derived faulty entries surfaced by parsing.
    ``partial``      ``incremental`` (file-scoped) mode: not all sources are present
                     in this batch, so a ref resolvable nowhere here is ``pending``
                     (the rest of the corpus may already be in the store or arrive
                     later), NOT a broken link. The ``broken`` verdict (rejection,
                     AC-02) is rendered only for a full ``reconcile`` batch (default,
                     where every source IS present), keeping backward-compat strict.
    """
    stored_ids = stored_ids or set()
    declared_ids = declared_ids or set()

    result = ValidationResult()
    faulty: list[FaultyArtifact] = list(parse_errors or [])

    # source_path per node id, for faulty-entry paths.
    path_by_id: dict[str, str] = {n.id: n.source_path for n in nodes}

    # Duplicate ids across the batch.
    seen: set[str] = set()
    for node in nodes:
        if node.id in seen:
            faulty.append(
                FaultyArtifact(
                    artifact_id=node.id,
                    path=node.source_path,
                    reason=f"duplicate id {node.id!r} in batch",
                )
            )
        seen.add(node.id)

    # Out-of-taxonomy node kinds (defense-in-depth).
    for node in nodes:
        if node.kind not in _VALID_NODE_KINDS:
            faulty.append(
                FaultyArtifact(
                    artifact_id=node.id,
                    path=node.source_path,
                    reason=f"node kind {node.kind!r} outside closed taxonomy",
                )
            )

    name_index = _build_name_index(nodes)
    batch_ids = {n.id for n in nodes}

    for edge in edges:
        # Out-of-taxonomy edge kind (defense-in-depth).
        if edge.kind not in _VALID_EDGE_KINDS:
            faulty.append(
                FaultyArtifact(
                    artifact_id=edge.src_id,
                    path=path_by_id.get(edge.src_id, ""),
                    reason=f"edge kind {edge.kind!r} outside closed taxonomy",
                )
            )
            continue

        # Resolve dst_ref: by id (batch), glossary name/alias, then stored_ids.
        if edge.dst_ref in batch_ids:
            edge.dst_id = edge.dst_ref
            edge.pending = False
            result.resolved_edges.append(edge)
        elif edge.dst_ref in name_index:
            edge.dst_id = name_index[edge.dst_ref]
            edge.pending = False
            result.resolved_edges.append(edge)
        elif edge.dst_ref in stored_ids:
            edge.dst_id = edge.dst_ref
            edge.pending = False
            result.resolved_edges.append(edge)
        elif edge.dst_ref in declared_ids or partial:
            # Declared elsewhere but not yet ingested -> pending, not broken. In
            # ``partial`` (incremental) mode the same holds for ANY unresolved ref:
            # the rest of the corpus is out of this batch, so it is pending, not a
            # broken link (the broken verdict is reserved for full reconcile).
            edge.pending = True
            edge.dst_id = None
            result.pending_edges.append(
                {"src": edge.src_id, "dst_ref": edge.dst_ref, "kind": edge.kind.value}
            )
        else:
            # Full reconcile batch + resolvable in no source -> broken link.
            faulty.append(
                FaultyArtifact(
                    artifact_id=edge.src_id,
                    path=path_by_id.get(edge.src_id, ""),
                    reason=f"broken link: dst_ref {edge.dst_ref!r} unresolvable in all sources",
                )
            )

    if faulty:
        result.status = "rejected"
        result.faulty = [f.as_dict() for f in faulty]
        # On rejection, pending classification is moot (the batch is not written).
        result.pending_edges = []
    return result
