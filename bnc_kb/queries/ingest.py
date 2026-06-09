from __future__ import annotations

import json
from uuid import UUID

from psycopg import Connection

from bnc_kb.embeddings import Embedder, chunk_text, to_vector_literal
from bnc_kb.models import IngestManifest, IngestSummary, NodeSpec
from bnc_kb.parser.archive import find_manifest, read_archive
from bnc_kb.parser.manifest import parse_manifest
from bnc_kb.parser.tree import build_nodes

CONTAINER_KINDS = {"capability", "business_function"}


def ingest_archive(conn: Connection, data: bytes, embedder: Embedder) -> IngestSummary:
    """End-to-end: read ZIP -> manifest -> node tree -> persist."""
    files = read_archive(data)
    raw_manifest = find_manifest(files)
    if raw_manifest is None:
        raise ValueError("kb-manifest.yaml not found at archive root")
    manifest = parse_manifest(raw_manifest.encode("utf-8"))
    nodes, unreached = build_nodes(files, manifest)
    return persist_nodes(conn, manifest, nodes, unreached, embedder)


def persist_nodes(
    conn: Connection,
    manifest: IngestManifest,
    nodes: list[NodeSpec],
    unreached: list[str],
    embedder: Embedder,
) -> IngestSummary:
    hit = conn.execute(
        "SELECT summary FROM ingestion WHERE capability_slug = %s AND source_commit = %s",
        (manifest.capability_slug, manifest.source_commit),
    ).fetchone()
    if hit is not None:
        return IngestSummary.model_validate({**hit[0], "idempotent_hit": True})

    summary = IngestSummary(
        capability_slug=manifest.capability_slug,
        source_commit=manifest.source_commit,
        sources_unreached=unreached,
    )
    dims: set[str] = set()
    local_to_id: dict[str, UUID] = {}

    with conn.transaction():
        cap_id = _upsert_capability(conn, manifest)
        local_to_id["cap"] = cap_id

        for spec in nodes:
            if spec.kind == "capability":
                continue
            parent_id = local_to_id[spec.parent_local_id]
            if spec.kind == "business_function":
                bf_id = _upsert_business_function(conn, parent_id, spec.slug)
                local_to_id[spec.local_id] = bf_id
                continue

            # leaf
            dims.add(spec.dimension_code)
            outcome, node_id = _upsert_leaf(conn, parent_id, manifest.source_commit, spec)
            local_to_id[spec.local_id] = node_id
            if outcome == "created":
                summary.nodes_created += 1
            elif outcome == "versioned":
                summary.nodes_versioned += 1
            else:
                summary.nodes_skipped += 1
                continue
            _embed_node(conn, node_id, spec.body or "", embedder)

        summary.dimensions_seen = sorted(dims)
        conn.execute(
            "INSERT INTO ingestion (capability_slug, source_commit, summary) VALUES (%s, %s, %s)",
            (manifest.capability_slug, manifest.source_commit,
             json.dumps(summary.model_dump(mode="json"))),
        )
    return summary


def _upsert_capability(conn: Connection, manifest: IngestManifest) -> UUID:
    row = conn.execute(
        "SELECT id FROM node WHERE kind = 'capability' AND slug = %s",
        (manifest.capability_slug,),
    ).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO node (kind, slug, attrs) VALUES ('capability', %s, %s) RETURNING id",
        (manifest.capability_slug,
         json.dumps({"category": manifest.category, "domain": manifest.domain})),
    ).fetchone()[0]


def _upsert_business_function(conn: Connection, parent_id: UUID, slug: str) -> UUID:
    row = conn.execute(
        "SELECT id FROM node WHERE kind = 'business_function' AND parent_id = %s AND slug = %s",
        (parent_id, slug),
    ).fetchone()
    if row:
        return row[0]
    return conn.execute(
        "INSERT INTO node (kind, parent_id, slug) "
        "VALUES ('business_function', %s, %s) RETURNING id",
        (parent_id, slug),
    ).fetchone()[0]


def _upsert_leaf(
    conn: Connection, parent_id: UUID, source_commit: str, spec: NodeSpec
) -> tuple[str, UUID]:
    existing = conn.execute(
        """
        SELECT id, body, version FROM node
        WHERE parent_id = %s AND slug = %s AND dimension_code = %s
          AND status <> 'superseded'
        ORDER BY version DESC LIMIT 1
        """,
        (parent_id, spec.slug, spec.dimension_code),
    ).fetchone()

    if existing and existing[1] == spec.body:
        return "skipped", existing[0]

    version = 1
    supersedes_id = None
    outcome = "created"
    if existing:
        version = existing[2] + 1
        supersedes_id = existing[0]
        outcome = "versioned"
        conn.execute("UPDATE node SET status = 'superseded' WHERE id = %s", (existing[0],))

    node_id = conn.execute(
        """
        INSERT INTO node (kind, parent_id, slug, dimension_code, body, version,
                          supersedes_id, source_commit, status, attrs)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'approved', %s)
        RETURNING id
        """,
        (spec.kind, parent_id, spec.slug, spec.dimension_code, spec.body, version,
         supersedes_id, source_commit, json.dumps(spec.attrs)),
    ).fetchone()[0]
    return outcome, node_id


def _embed_node(conn: Connection, node_id: UUID, body: str, embedder: Embedder) -> None:
    chunks = chunk_text(body)
    if not chunks:
        return
    vectors = embedder.embed(chunks)
    for ord_, vec in enumerate(vectors):
        conn.execute(
            "INSERT INTO node_chunk_embedding (node_id, ord, embedding) "
            "VALUES (%s, %s, %s::vector)",
            (node_id, ord_, to_vector_literal(vec)),
        )
