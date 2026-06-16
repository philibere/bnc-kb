"""Backend-independent ingestion engine (OutputSink decoupling, BNC-17).

The pipeline is split into a *pure engine* (no storage dependency) and pluggable
*output adapters* (``sinks``). JSON-only: the engine runs

    discovery -> parsing -> validation -> extraction -> embedding
    (only if ``sink.needs_vectors``)

and produces a backend-independent ``IngestionResult{nodes, edges, chunks,
versions, report}``. ``ingest(...)`` then hands that result to the sink (a
``JsonSink`` snapshot or a validate-only ``NullSink``) and returns the report.

No database import anywhere; the engine is store-agnostic. The embedder is
built lazily and ONLY when the chosen sink needs vectors, so the validate-only
path (``NullSink``) never constructs or loads an embedding model (AC-20).

Validation: unresolved cross-references become ``pending`` edges (emitted to the
JSON snapshot and reported); the batch is rejected (CLI exit 2) ONLY on a
duplicate id, an out-of-vocabulary node/edge kind, or unreadable frontmatter
(AC-02 format validity).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from spec_ingestion import config, metamodel, report as report_mod
from spec_ingestion.discovery import ArtifactType, discover
from spec_ingestion.extraction import ExtractionResult, extract_generic
from spec_ingestion.lineage import file_lineage
from spec_ingestion.model import NodeKind
from spec_ingestion.parsing import ParseError
from spec_ingestion.validation import FaultyArtifact, validate

logger = logging.getLogger("spec_ingestion.engine")

# Bespoke extractors for bnc's legacy types. EMPTY: feature/technical/glossary/invariant
# all migrated to the manifest-driven generic extractor (extractor: generic), so the
# engine carries ZERO per-type extraction code -- every spec type, bnc or client, is
# projected to the graph by ``extract_generic`` from its manifest declaration alone.
# Kept as a (now-empty) defensive map so a future bespoke type could still be wired.
_BESPOKE_EXTRACTORS: list[tuple[str, object]] = []
_EXTRACTORS = {
    ArtifactType.__members__[name]: fn
    for name, fn in _BESPOKE_EXTRACTORS
    if name in ArtifactType.__members__
}

# bnc emits one Module node per feature (same id repeated): exempt from dup-id
# detection. Manifest-defensive: None for an SDLC without a Module kind => no exemption.
_MODULE_KIND = NodeKind.__members__.get("Module")


@dataclass
class IngestionResult:
    """The backend-independent product of one engine run.

    ``chunks`` carry their tier text always; their ``embedding`` is filled only
    when the run embedded (i.e. the sink needed vectors). ``versions`` are the
    lineage records (``{artifact_id, content_hash, lineage}``). ``report`` is the
    validity / stats report (status, faulty, pending, etc.).
    """

    nodes: list = field(default_factory=list)
    edges: list = field(default_factory=list)
    chunks: list = field(default_factory=list)
    versions: list = field(default_factory=list)
    report: dict = field(default_factory=dict)

    @property
    def rejected(self) -> bool:
        return self.report.get("status") == "rejected"


def build(sources, *, sink, lineage_override=None, incremental=False) -> IngestionResult:
    """Run the pure engine over ``sources`` and return an ``IngestionResult``.

    Steps: discovery -> parse + extract -> validation -> embedding (ONLY if
    ``sink.needs_vectors``). On validation rejection the result carries a
    ``rejected`` report, NO embedding is attempted, and the caller must not write.
    ``sources`` is a path, a list of paths, a single ``.md`` file or a directory
    (AC-14/AC-15).

    Unresolved cross-references are emitted as ``pending`` edges (not broken), so a
    partial / on-demand target never fails on a forward reference. ``lineage_override``
    (a ``FileLineage``) is the caller's provenance for off-git entries; it PRIMES
    over git per file (AC-18).
    """
    roots = [sources] if isinstance(sources, (str, Path)) else list(sources)

    def lineage_fn(path):
        return file_lineage(path, override=lineage_override)

    discovered = discover(roots)
    logger.info(
        "discovered artifacts=%d ignored=%d",
        len(discovered.artifacts),
        len(discovered.ignored),
    )

    nodes_by_id: dict = {}
    edges: list = []
    chunks: list = []
    version_seen: set[str] = set()
    versions: list = []
    parse_errors: list[FaultyArtifact] = []
    # Genuine duplicate ids: the SAME id declared by two distinct artifact files.
    # Structural ``Module`` nodes are intentionally shared across features and never
    # count as duplicates (every feature of a module re-declares it).
    id_origin: dict[str, str] = {}
    dup_faults: list[FaultyArtifact] = []

    for artifact in discovered.artifacts:
        # Bespoke extractor for the legacy core types; generic (manifest-driven)
        # for any declarative spec type. Unknown types are skipped.
        extractor = _EXTRACTORS.get(artifact.artifact_type)
        try:
            if extractor is not None:
                result: ExtractionResult = extractor(artifact.path)
            elif artifact.artifact_type.value in metamodel.GENERIC_SPECS:
                result = extract_generic(artifact.path)
            else:
                continue
        except (ParseError, ValueError) as exc:
            parse_errors.append(
                FaultyArtifact(
                    artifact_id=str(artifact.path),
                    path=str(artifact.path),
                    reason=f"unreadable artifact: {exc}",
                )
            )
            continue

        for node in result.nodes:
            if node.kind is not _MODULE_KIND:
                prior = id_origin.get(node.id)
                if prior is not None and prior != node.source_path:
                    dup_faults.append(
                        FaultyArtifact(
                            artifact_id=node.id,
                            path=node.source_path,
                            reason=f"duplicate id {node.id!r} declared in {prior!r} and "
                            f"{node.source_path!r}",
                        )
                    )
                id_origin.setdefault(node.id, node.source_path)
            nodes_by_id.setdefault(node.id, node)
            if node.id not in version_seen:
                version_seen.add(node.id)
                versions.append(
                    {
                        "artifact_id": node.id,
                        "content_hash": node.content_hash,
                        "lineage": lineage_fn(node.source_path),
                    }
                )
        edges.extend(result.edges)
        chunks.extend(result.chunks)

    nodes = list(nodes_by_id.values())

    # Validation (fail-fast, BEFORE any write or embedding). An unresolved ref is
    # ``pending`` (emitted to JSON), never broken: the batch is rejected only on a
    # duplicate id, an out-of-vocabulary kind or unreadable frontmatter (AC-02).
    declared_ids = set(nodes_by_id)
    verdict = validate(
        nodes,
        edges,
        declared_ids=declared_ids,
        parse_errors=parse_errors + dup_faults,
        partial=True,
    )
    if verdict.status == "rejected":
        logger.info("validation rejected faulty=%d", len(verdict.faulty))
        rejected_report = report_mod.build_report(status="rejected", faulty=verdict.faulty)
        return IngestionResult(report=rejected_report)

    # The emitted edge set: resolved + pending.
    edges = verdict.resolved_edges + _pending_edges(edges)

    # Embedding ONLY if the sink needs vectors. validate-only (NullSink) never
    # constructs an embedder, so bge-m3 is never loaded (AC-20).
    if sink.needs_vectors:
        # Lazy: import here so importing the engine never pulls torch.
        from spec_ingestion.embedding import embed_chunks, select_embedder, stamp_versions

        embedder = select_embedder()
        pv = config.pipeline_version()
        if incremental and hasattr(sink, "existing_chunk_keys"):
            # Selective re-embed: stamp every desired chunk's composite key, then
            # embed ONLY the chunks whose key is absent from the store (AC-05/AC-11).
            from spec_ingestion.incremental import chunk_key

            existing = sink.existing_chunk_keys()
            stamped = stamp_versions(chunks, embedder.model_version, pv)
            fresh_idx = [i for i, c in enumerate(stamped) if chunk_key(c) not in existing]
            for i, ec in zip(fresh_idx, embed_chunks([stamped[i] for i in fresh_idx], embedder, pv)):
                stamped[i] = ec
            chunks = stamped
            logger.info(
                "incremental: %d/%d chunks need (re-)embedding model=%s",
                len(fresh_idx),
                len(chunks),
                embedder.model_version,
            )
        else:
            chunks = embed_chunks(chunks, embedder, pv)
            logger.info(
                "extracted nodes=%d edges=%d chunks=%d model=%s",
                len(nodes),
                len(edges),
                len(chunks),
                embedder.model_version,
            )
    else:
        logger.info(
            "validate-only: nodes=%d edges=%d chunks=%d (no embedding)",
            len(nodes),
            len(edges),
            len(chunks),
        )

    ok_report = report_mod.build_report(
        status="success",
        stats={"nodes": len(nodes), "edges": len(edges), "chunks": len(chunks)},
        pending_edges=list(verdict.pending_edges),
    )
    return IngestionResult(
        nodes=nodes,
        edges=edges,
        chunks=chunks,
        versions=versions,
        report=ok_report,
    )


def ingest(sources, *, lineage_override=None, sink, incremental=False) -> dict:
    """Run the engine and hand the result to ``sink``; return the sink's report.

    On validation rejection NOTHING is written: the rejected report is returned as
    is (exit-code-2 semantics are the CLI's job). On success the sink materializes
    the ``IngestionResult``: a full snapshot (``sink.write``) by default, or only
    the delta (``sink.reconcile``) when ``incremental`` and the sink supports it.
    """
    result = build(sources, sink=sink, lineage_override=lineage_override, incremental=incremental)
    if result.rejected:
        return result.report
    if incremental and hasattr(sink, "reconcile"):
        return sink.reconcile(result)
    return sink.write(result)


def _pending_edges(edges: list) -> list:
    """Edges marked pending by validation are NOT in ``resolved_edges``; collect them."""
    return [e for e in edges if getattr(e, "pending", False)]
