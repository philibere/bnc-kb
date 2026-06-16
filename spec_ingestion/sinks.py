"""Output adapters (OutputSink port + adapters) for the ingestion engine.

The engine (``engine.build``) produces a backend-independent ``IngestionResult``;
a *sink* turns that into a concrete output. This is the port/adapter boundary that
keeps the engine decoupled from any backend (AC-19).

* ``JsonSink`` (``--output json``, default; target = a directory) writes a
  regenerable snapshot: ``nodes.json``, ``edges.json`` (including pending),
  ``chunks.json`` (with 1024-d vectors) and ``report.json``; faithful and
  reloadable (AC-21). ``needs_vectors=True``.
* ``SqliteSink`` (``--output sqlite``; target = a file) writes a queryable
  relational store (stdlib, zero new deps). ``needs_vectors=False``.
* ``PostgresSink`` (``--output postgres``; target = a DSN) writes the same graph +
  chunk store to Postgres with native ``pgvector`` vectors (optional ``postgres``
  extra). ``needs_vectors=True``.
* ``NullSink`` (``--output none``, validate-only) writes NOTHING and loads no
  embedding model: ``needs_vectors=False``.

The two durable sinks support full-snapshot ``write`` AND incremental ``reconcile``
(shared pure diff in ``incremental``): a living SDLC store re-embeds ONLY the chunks
whose composite key changed. Core has no database import; Postgres deps are
lazy-imported behind the ``postgres`` extra.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid as _uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

from spec_ingestion.incremental import StoreState, diff

logger = logging.getLogger("spec_ingestion.sinks")


def _kv(x):
    """enum-or-str -> str (``NodeKind.Feature`` -> ``"Feature"``)."""
    return x.value if hasattr(x, "value") else x


@runtime_checkable
class OutputSink(Protocol):
    """The output port: where an ``IngestionResult`` is materialized."""

    needs_vectors: bool

    def write(self, result) -> dict:
        """Persist/emit ``result`` and return the build report dict."""
        ...


class JsonSink:
    """Regenerable JSON snapshot (AC-21). ``needs_vectors=True``.

    Writes four files into ``out_dir`` each run (full snapshot, not appended):
    ``nodes.json``, ``edges.json`` (including pending), ``chunks.json`` (vectors
    1024-d) and ``report.json``. Faithful and reloadable; reconciliation is trivial
    because the snapshot IS the complete state.
    """

    needs_vectors = True

    def __init__(self, out_dir: str) -> None:
        self.out_dir = Path(out_dir)

    def write(self, result) -> dict:
        self.out_dir.mkdir(parents=True, exist_ok=True)

        nodes = [self._node_dict(n) for n in result.nodes]
        edges = [self._edge_dict(e) for e in result.edges]
        chunks = [self._chunk_dict(c) for c in result.chunks]
        report = result.report

        self._dump("nodes.json", nodes)
        self._dump("edges.json", edges)
        self._dump("chunks.json", chunks)
        self._dump("report.json", report)
        logger.info(
            "json snapshot written dir=%s nodes=%d edges=%d chunks=%d",
            self.out_dir,
            len(nodes),
            len(edges),
            len(chunks),
        )
        return report

    @staticmethod
    def _node_dict(node) -> dict:
        return {
            "id": node.id,
            "kind": _kv(node.kind),
            "props": node.props,
            "content_hash": node.content_hash,
            "source_path": node.source_path,
        }

    @staticmethod
    def _edge_dict(edge) -> dict:
        return {
            "src_id": edge.src_id,
            "dst_ref": edge.dst_ref,
            "dst_id": edge.dst_id,
            "kind": _kv(edge.kind),
            "pending": bool(edge.pending),
        }

    @staticmethod
    def _chunk_dict(chunk) -> dict:
        return {
            "node_id": chunk.node_id,
            "tier": _kv(chunk.tier),
            "text": chunk.text,
            "content_hash": chunk.content_hash,
            "embedding_model_version": chunk.embedding_model_version,
            "pipeline_version": chunk.pipeline_version,
            "embedding": [float(x) for x in chunk.embedding],
        }

    def _dump(self, name: str, payload) -> None:
        path = self.out_dir / name
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


class SqliteSink:
    """Durable graph+chunk store in a single SQLite file (stdlib, zero new deps).

    Materializes the ``IngestionResult`` into a queryable relational store: one row
    per node / edge / chunk, with the traceability edges (contains, realizes,
    serves, governed-by, ...) indexed for traversal.

    Two write modes share one schema:
    * ``write`` — full snapshot (tables dropped + recreated): the DB mirrors the
      corpus exactly.
    * ``reconcile`` — incremental delta (insert/update/delete only): nodes by
      content_hash, edges by identity tuple, chunks by composite key, so an
      unchanged chunk is never re-embedded. See ``incremental``.

    ``needs_vectors=False`` so the snapshot path never forces the embedder to load;
    embeddings are stored verbatim when the chunks carry them, else the column holds
    ``[]`` and vector search degrades to unavailable while graph + text search stay
    functional. See ``query`` for the read path.
    """

    needs_vectors = False

    def __init__(self, db_path: str) -> None:
        self.db_path = Path(db_path)

    # --- full snapshot --------------------------------------------------------
    def write(self, result) -> dict:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            self._schema(conn, reset=True)
            conn.executemany(
                "INSERT OR REPLACE INTO nodes(id, kind, props, content_hash, source_path) "
                "VALUES (?,?,?,?,?)",
                [self._node_row(n) for n in result.nodes],
            )
            conn.executemany(
                "INSERT INTO edges(src_id, dst_ref, dst_id, kind, pending) VALUES (?,?,?,?,?)",
                [self._edge_row(e) for e in result.edges],
            )
            conn.executemany(
                "INSERT INTO chunks(node_id, tier, text, content_hash, embedding, "
                "embedding_model_version, pipeline_version) VALUES (?,?,?,?,?,?,?)",
                [self._chunk_row(c) for c in result.chunks],
            )
            conn.commit()
        finally:
            conn.close()
        logger.info(
            "sqlite store written db=%s nodes=%d edges=%d chunks=%d",
            self.db_path,
            len(result.nodes),
            len(result.edges),
            len(result.chunks),
        )
        return result.report

    # --- incremental ----------------------------------------------------------
    def existing_chunk_keys(self) -> set:
        """Composite keys already stored (drives selective re-embedding)."""
        if not self.db_path.exists():
            return set()
        conn = sqlite3.connect(self.db_path)
        try:
            self._schema(conn, reset=False)
            return {
                tuple(r)
                for r in conn.execute(
                    "SELECT node_id, tier, content_hash, embedding_model_version, "
                    "pipeline_version FROM chunks"
                )
            }
        finally:
            conn.close()

    def reconcile(self, result) -> dict:
        """Apply only the delta vs the current store; return report + ``delta``."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        try:
            self._schema(conn, reset=False)
            state = StoreState(
                node_hashes={r[0]: r[1] for r in conn.execute("SELECT id, content_hash FROM nodes")},
                edge_tuples={
                    (r[0], r[1], r[2], r[3], r[4])
                    for r in conn.execute("SELECT src_id, kind, dst_ref, dst_id, pending FROM edges")
                },
                chunk_keys={
                    tuple(r)
                    for r in conn.execute(
                        "SELECT node_id, tier, content_hash, embedding_model_version, "
                        "pipeline_version FROM chunks"
                    )
                },
            )
            d = diff(state, result)

            if d.node_upserts:
                conn.executemany(
                    "INSERT OR REPLACE INTO nodes(id, kind, props, content_hash, source_path) "
                    "VALUES (?,?,?,?,?)",
                    [self._node_row(n) for n in d.node_upserts],
                )
            if d.node_deleted:
                conn.executemany("DELETE FROM nodes WHERE id = ?", [(nid,) for nid in d.node_deleted])
            # SQLite `IS` is null-safe equality: matches NULL dst_ref/dst_id correctly.
            for t in d.edge_deletes:
                conn.execute(
                    "DELETE FROM edges WHERE src_id IS ? AND kind IS ? AND dst_ref IS ? "
                    "AND dst_id IS ? AND pending IS ?",
                    t,
                )
            if d.edge_inserts:
                conn.executemany(
                    "INSERT INTO edges(src_id, dst_ref, dst_id, kind, pending) VALUES (?,?,?,?,?)",
                    [self._edge_row(e) for e in d.edge_inserts],
                )
            for k in d.chunk_delete_keys:
                conn.execute(
                    "DELETE FROM chunks WHERE node_id IS ? AND tier IS ? AND content_hash IS ? "
                    "AND embedding_model_version IS ? AND pipeline_version IS ?",
                    k,
                )
            if d.chunk_inserts:
                conn.executemany(
                    "INSERT INTO chunks(node_id, tier, text, content_hash, embedding, "
                    "embedding_model_version, pipeline_version) VALUES (?,?,?,?,?,?,?)",
                    [self._chunk_row(c) for c in d.chunk_inserts],
                )
            conn.commit()
        finally:
            conn.close()
        report = dict(result.report)
        report["delta"] = d.report()
        logger.info("sqlite reconcile db=%s delta=%s", self.db_path, report["delta"])
        return report

    # --- row mappers ----------------------------------------------------------
    @staticmethod
    def _node_row(n) -> tuple:
        return (n.id, _kv(n.kind), json.dumps(n.props, ensure_ascii=False, sort_keys=True),
                n.content_hash, n.source_path)

    @staticmethod
    def _edge_row(e) -> tuple:
        return (e.src_id, e.dst_ref, e.dst_id, _kv(e.kind), 1 if e.pending else 0)

    @staticmethod
    def _chunk_row(c) -> tuple:
        return (c.node_id, _kv(c.tier), c.text, c.content_hash,
                json.dumps([float(x) for x in c.embedding]),
                c.embedding_model_version, c.pipeline_version)

    @staticmethod
    def _schema(conn: sqlite3.Connection, *, reset: bool) -> None:
        if reset:
            conn.executescript(
                "DROP TABLE IF EXISTS nodes; DROP TABLE IF EXISTS edges; DROP TABLE IF EXISTS chunks;"
            )
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS nodes (
                id TEXT PRIMARY KEY, kind TEXT NOT NULL, props TEXT NOT NULL,
                content_hash TEXT, source_path TEXT
            );
            CREATE TABLE IF NOT EXISTS edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                src_id TEXT NOT NULL, dst_ref TEXT, dst_id TEXT, kind TEXT NOT NULL,
                pending INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id TEXT NOT NULL, tier TEXT NOT NULL, text TEXT,
                content_hash TEXT, embedding TEXT,
                embedding_model_version TEXT, pipeline_version TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind);
            CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id);
            CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id);
            CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind);
            CREATE INDEX IF NOT EXISTS idx_chunks_node ON chunks(node_id);
            CREATE INDEX IF NOT EXISTS idx_chunks_tier ON chunks(tier);
            """
        )


class PostgresSink:
    """Durable graph + chunk store in Postgres with native ``pgvector`` vectors.

    Mirrors ``SqliteSink``'s schema (nodes / edges / chunks) but stores embeddings
    in a real ``vector(1024)`` column, so cosine search runs IN the database
    (``embedding <=> query``) instead of in Python. ``needs_vectors=True``: the
    persistence path embeds, so the store is query-ready for vector search.

    Requires the optional ``postgres`` extra (``psycopg`` + ``pgvector``), both
    lazy-imported so importing this module never needs them. Supports full-snapshot
    ``write`` and incremental ``reconcile`` (the SAME ``incremental.diff`` as the
    SQLite sink: one delta, two backends).
    """

    needs_vectors = True
    DIM = 1024

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _connect(self):
        import psycopg
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(self.dsn)
        self._ensure_schema(conn)  # creates the vector extension + tables if absent
        register_vector(conn)       # AFTER the extension exists
        return conn

    def _ensure_schema(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS nodes (id TEXT PRIMARY KEY, kind TEXT NOT NULL, "
                "props JSONB NOT NULL, content_hash TEXT, source_path TEXT)"
            )
            cur.execute(
                "CREATE TABLE IF NOT EXISTS edges (id BIGSERIAL PRIMARY KEY, src_id TEXT NOT NULL, "
                "dst_ref TEXT, dst_id TEXT, kind TEXT NOT NULL, pending BOOLEAN NOT NULL DEFAULT FALSE)"
            )
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS chunks (id BIGSERIAL PRIMARY KEY, node_id TEXT NOT NULL, "
                f"tier TEXT NOT NULL, text TEXT, content_hash TEXT, embedding vector({self.DIM}), "
                f"embedding_model_version TEXT, pipeline_version TEXT)"
            )
            cur.execute("CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(kind)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_edges_kind ON edges(kind)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_chunks_node ON chunks(node_id)")
        conn.commit()

    # --- full snapshot --------------------------------------------------------
    def write(self, result) -> dict:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE nodes, edges, chunks")
                self._insert_nodes(cur, result.nodes)
                self._insert_edges(cur, result.edges)
                self._insert_chunks(cur, result.chunks)
            conn.commit()
        finally:
            conn.close()
        logger.info(
            "postgres store written nodes=%d edges=%d chunks=%d",
            len(result.nodes),
            len(result.edges),
            len(result.chunks),
        )
        return result.report

    # --- incremental ----------------------------------------------------------
    def existing_chunk_keys(self) -> set:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT node_id, tier, content_hash, embedding_model_version, "
                    "pipeline_version FROM chunks"
                )
                return {tuple(r) for r in cur.fetchall()}
        finally:
            conn.close()

    def reconcile(self, result) -> dict:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id, content_hash FROM nodes")
                node_hashes = dict(cur.fetchall())
                cur.execute("SELECT src_id, kind, dst_ref, dst_id, pending FROM edges")
                edge_tuples = {
                    (r[0], r[1], r[2], r[3], 1 if r[4] else 0) for r in cur.fetchall()
                }
                cur.execute(
                    "SELECT node_id, tier, content_hash, embedding_model_version, "
                    "pipeline_version FROM chunks"
                )
                chunk_keys = {tuple(r) for r in cur.fetchall()}
                state = StoreState(
                    node_hashes=node_hashes, edge_tuples=edge_tuples, chunk_keys=chunk_keys
                )
                d = diff(state, result)

                if d.node_upserts:
                    self._insert_nodes(cur, d.node_upserts, upsert=True)
                if d.node_deleted:
                    cur.executemany(
                        "DELETE FROM nodes WHERE id = %s", [(nid,) for nid in d.node_deleted]
                    )
                for t in d.edge_deletes:
                    cur.execute(
                        "DELETE FROM edges WHERE src_id IS NOT DISTINCT FROM %s AND kind IS NOT "
                        "DISTINCT FROM %s AND dst_ref IS NOT DISTINCT FROM %s AND dst_id IS NOT "
                        "DISTINCT FROM %s AND pending IS NOT DISTINCT FROM %s",
                        (t[0], t[1], t[2], t[3], bool(t[4])),
                    )
                if d.edge_inserts:
                    self._insert_edges(cur, d.edge_inserts)
                for k in d.chunk_delete_keys:
                    cur.execute(
                        "DELETE FROM chunks WHERE node_id IS NOT DISTINCT FROM %s AND tier IS NOT "
                        "DISTINCT FROM %s AND content_hash IS NOT DISTINCT FROM %s AND "
                        "embedding_model_version IS NOT DISTINCT FROM %s AND pipeline_version IS "
                        "NOT DISTINCT FROM %s",
                        k,
                    )
                if d.chunk_inserts:
                    self._insert_chunks(cur, d.chunk_inserts)
            conn.commit()
        finally:
            conn.close()
        report = dict(result.report)
        report["delta"] = d.report()
        logger.info("postgres reconcile delta=%s", report["delta"])
        return report

    # --- row inserters --------------------------------------------------------
    @staticmethod
    def _insert_nodes(cur, nodes, *, upsert: bool = False) -> None:
        from psycopg.types.json import Json

        sql = (
            "INSERT INTO nodes(id, kind, props, content_hash, source_path) VALUES (%s,%s,%s,%s,%s)"
        )
        if upsert:
            sql += (
                " ON CONFLICT (id) DO UPDATE SET kind=EXCLUDED.kind, props=EXCLUDED.props, "
                "content_hash=EXCLUDED.content_hash, source_path=EXCLUDED.source_path"
            )
        cur.executemany(
            sql,
            [(n.id, _kv(n.kind), Json(n.props), n.content_hash, n.source_path) for n in nodes],
        )

    @staticmethod
    def _insert_edges(cur, edges) -> None:
        cur.executemany(
            "INSERT INTO edges(src_id, dst_ref, dst_id, kind, pending) VALUES (%s,%s,%s,%s,%s)",
            [(e.src_id, e.dst_ref, e.dst_id, _kv(e.kind), bool(e.pending)) for e in edges],
        )

    @staticmethod
    def _insert_chunks(cur, chunks) -> None:
        cur.executemany(
            "INSERT INTO chunks(node_id, tier, text, content_hash, embedding, "
            "embedding_model_version, pipeline_version) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            [
                (
                    c.node_id,
                    _kv(c.tier),
                    c.text,
                    c.content_hash,
                    [float(x) for x in c.embedding] if c.embedding else None,
                    c.embedding_model_version,
                    c.pipeline_version,
                )
                for c in chunks
            ],
        )


# Identity bridge for the bnc-kb store: a shaper business id (FEAT-CARTE-001) maps to
# bnc-kb's surrogate uuid PK via a STABLE uuid5, so internal edge targets and parent
# links resolve deterministically across runs. The business id is kept verbatim in
# node.slug, so bnc-kb's queries still surface human ids.
_BNC_KB_NS = _uuid.uuid5(_uuid.NAMESPACE_DNS, "bnc-kb.shaper.vooban")
# Tier-name fragments, in preference order, that yield a node's bnc-kb ``body`` (the
# text its body-centric vector search returns). A node with none falls back to its
# first chunk; a node with no chunk at all gets a NULL body (excluded from search).
_BODY_TIER_HINTS = ("summary", "definition", "REQ")


def _nid(biz_id: str) -> str:
    return str(_uuid.uuid5(_BNC_KB_NS, biz_id))


def _ord(tier: str) -> int:
    """Stable per-node ordinal from the tier name (each node has <=1 chunk per tier),
    so an incremental re-insert reuses the same (node_id, ord) slot the delete freed."""
    return int(hashlib.sha1(tier.encode("utf-8")).hexdigest(), 16) % 1_000_000


def _bnckb_bodies(chunks) -> dict:
    by_node: dict = {}
    for c in chunks:
        by_node.setdefault(c.node_id, []).append(c)
    out: dict = {}
    for nid, cs in by_node.items():
        pick = None
        for hint in _BODY_TIER_HINTS:
            pick = next((c for c in cs if hint in _kv(c.tier)), None)
            if pick is not None:
                break
        out[nid] = (pick or cs[0]).text
    return out


def _bnckb_parents(edges) -> dict:
    """child business id -> parent business id, from the resolved ``contains`` graph
    (Module->Feature->REQ). bnc-kb's recursive spec traversal walks ``parent_id``."""
    return {e.dst_id: e.src_id for e in edges if _kv(e.kind) == "contains" and e.dst_id}


class BncKbSink:
    """Convergence adapter (strategy A): write the shaper ``IngestionResult`` into the
    bnc-kb Postgres store (``node`` / ``node_chunk_embedding`` / ``spec_link``) so
    bnc-kb's API (search / spec / links) serves shaper specs WITHOUT rewriting bnc-kb's
    ingestion. One ingestion engine, bnc-kb's store + query surface.

    Requires the bnc-kb convergence migration (``0006_shaper_convergence.sql``) and the
    optional ``postgres`` extra (``psycopg`` + ``pgvector``), both lazy-imported.

    Mappings (shaper -> bnc-kb):
    * node.kind <- shaper kind (text); node.slug <- business id; node.attrs <- props;
      node.content_hash <- hash; node.status='approved' (default search filter keeps
      it); node.body <- the node's summary/definition/REQ tier text (bnc-kb search is
      body-centric); node.parent_id <- the ``contains`` graph (set in a second pass so
      insert order is FK-safe).
    * spec_link <- typed edges: rel = edge kind, dst_id = resolved uuid, dst_ref =
      textual ref, pending flag.
    * node_chunk_embedding <- one row per tier chunk: vector(1024) + tier + chunk_text
      + composite-key columns; ord derived stably from the tier.

    Full-snapshot ``write`` (TRUNCATE + insert) and incremental ``reconcile`` share the
    same ``incremental.diff`` as the other durable sinks. ``reconcile`` applies the
    delta in FK-safe order (edges/chunks/nodes deleted before nodes upserted before
    edges/chunks inserted), because bnc-kb's edges carry REAL foreign keys to ``node``.
    """

    needs_vectors = True
    DIM = 1024

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def _connect(self):
        import psycopg
        from pgvector.psycopg import register_vector

        conn = psycopg.connect(self.dsn)
        register_vector(conn)  # the bnc-kb migration already created the extension
        return conn

    # --- full snapshot --------------------------------------------------------
    def write(self, result) -> dict:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("TRUNCATE node, node_chunk_embedding, spec_link RESTART IDENTITY CASCADE")
                self._insert_nodes(cur, result.nodes, result.chunks)
                self._insert_edges(cur, result.edges)
                self._insert_chunks(cur, result.chunks)
                self._link_parents(cur, result.edges)
            conn.commit()
        finally:
            conn.close()
        logger.info(
            "bnckb store written nodes=%d edges=%d chunks=%d",
            len(result.nodes),
            len(result.edges),
            len(result.chunks),
        )
        return result.report

    # --- incremental ----------------------------------------------------------
    def existing_chunk_keys(self) -> set:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT n.slug, c.tier, c.content_hash, c.embedding_model_version, "
                    "c.pipeline_version FROM node_chunk_embedding c JOIN node n ON n.id = c.node_id "
                    "WHERE c.tier IS NOT NULL"
                )
                return {tuple(r) for r in cur.fetchall()}
        finally:
            conn.close()

    def reconcile(self, result) -> dict:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT slug, content_hash FROM node")
                node_hashes = dict(cur.fetchall())
                cur.execute(
                    "SELECT s.slug, l.rel, l.dst_ref, d.slug, l.pending FROM spec_link l "
                    "JOIN node s ON s.id = l.src_id LEFT JOIN node d ON d.id = l.dst_id"
                )
                edge_tuples = {
                    (r[0], r[1], r[2], r[3], 1 if r[4] else 0) for r in cur.fetchall()
                }
                cur.execute(
                    "SELECT n.slug, c.tier, c.content_hash, c.embedding_model_version, "
                    "c.pipeline_version FROM node_chunk_embedding c JOIN node n ON n.id = c.node_id "
                    "WHERE c.tier IS NOT NULL"
                )
                chunk_keys = {tuple(r) for r in cur.fetchall()}
                state = StoreState(
                    node_hashes=node_hashes, edge_tuples=edge_tuples, chunk_keys=chunk_keys
                )
                d = diff(state, result)

                # FK-safe order: dependents (edges, chunks) deleted, then nodes deleted,
                # then nodes upserted (so new edge/chunk targets exist), then edges +
                # chunks inserted, then parent_id relinked.
                for t in d.edge_deletes:
                    cur.execute(
                        "DELETE FROM spec_link WHERE src_id = %s AND rel = %s "
                        "AND dst_ref IS NOT DISTINCT FROM %s AND dst_id IS NOT DISTINCT FROM %s "
                        "AND pending IS NOT DISTINCT FROM %s",
                        (_nid(t[0]), t[1], t[2], _nid(t[3]) if t[3] else None, bool(t[4])),
                    )
                for k in d.chunk_delete_keys:
                    cur.execute(
                        "DELETE FROM node_chunk_embedding WHERE node_id = %s "
                        "AND tier IS NOT DISTINCT FROM %s AND content_hash IS NOT DISTINCT FROM %s "
                        "AND embedding_model_version IS NOT DISTINCT FROM %s "
                        "AND pipeline_version IS NOT DISTINCT FROM %s",
                        (_nid(k[0]), k[1], k[2], k[3], k[4]),
                    )
                if d.node_deleted:
                    cur.executemany(
                        "DELETE FROM node WHERE id = %s", [(_nid(nid),) for nid in d.node_deleted]
                    )
                if d.node_upserts:
                    self._insert_nodes(cur, d.node_upserts, result.chunks, upsert=True)
                if d.edge_inserts:
                    self._insert_edges(cur, d.edge_inserts)
                if d.chunk_inserts:
                    self._insert_chunks(cur, d.chunk_inserts)
                self._link_parents(cur, result.edges)
            conn.commit()
        finally:
            conn.close()
        report = dict(result.report)
        report["delta"] = d.report()
        logger.info("bnckb reconcile delta=%s", report["delta"])
        return report

    # --- partial merge (one or several specs, NOT the whole corpus) ------------
    def merge(self, result) -> dict:
        """Upsert ONLY the batch's specs; delete nothing outside their footprint.

        Unlike ``reconcile`` (whole-corpus: it deletes any node/edge/chunk absent from
        ``result``), ``merge`` scopes the store state it diffs against to the batch's
        node ids, so the rest of the store is untouched. Use it to ingest one or a few
        specs at a time. Pending edges (refs to specs outside the batch) whose target
        already exists in the store are then resolved (forward references fulfilled).

        Edges are matched by ``(src, rel, dst_ref)`` identity (dst_id/pending ignored),
        so a previously-resolved edge is NOT churned back to pending on re-merge: the
        operation is idempotent on a stable corpus.
        """
        batch_ids = [n.id for n in result.nodes]
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT slug, content_hash FROM node WHERE slug = ANY(%s)", (batch_ids,)
                )
                node_hashes = dict(cur.fetchall())
                cur.execute(
                    "SELECT s.slug, l.rel, l.dst_ref FROM spec_link l "
                    "JOIN node s ON s.id = l.src_id WHERE s.slug = ANY(%s)",
                    (batch_ids,),
                )
                stored_edge_keys = {(r[0], r[1], r[2]) for r in cur.fetchall()}
                cur.execute(
                    "SELECT n.slug, c.tier, c.content_hash, c.embedding_model_version, "
                    "c.pipeline_version FROM node_chunk_embedding c JOIN node n ON n.id = c.node_id "
                    "WHERE n.slug = ANY(%s) AND c.tier IS NOT NULL",
                    (batch_ids,),
                )
                chunk_keys = {tuple(r) for r in cur.fetchall()}
                # diff handles nodes + chunks; edges are matched on (src, rel, dst_ref).
                state = StoreState(node_hashes=node_hashes, edge_tuples=set(), chunk_keys=chunk_keys)
                d = diff(state, result)

                desired_edges = {(e.src_id, _kv(e.kind), e.dst_ref): e for e in result.edges}
                edge_inserts = [e for k, e in desired_edges.items() if k not in stored_edge_keys]
                edge_delete_keys = [k for k in stored_edge_keys if k not in desired_edges]

                # FK-safe order, scoped to the batch (state held only batch-owned rows).
                for k in edge_delete_keys:
                    cur.execute(
                        "DELETE FROM spec_link WHERE src_id = %s AND rel = %s "
                        "AND dst_ref IS NOT DISTINCT FROM %s",
                        (_nid(k[0]), k[1], k[2]),
                    )
                for ck in d.chunk_delete_keys:
                    cur.execute(
                        "DELETE FROM node_chunk_embedding WHERE node_id = %s "
                        "AND tier IS NOT DISTINCT FROM %s AND content_hash IS NOT DISTINCT FROM %s "
                        "AND embedding_model_version IS NOT DISTINCT FROM %s "
                        "AND pipeline_version IS NOT DISTINCT FROM %s",
                        (_nid(ck[0]), ck[1], ck[2], ck[3], ck[4]),
                    )
                if d.node_deleted:
                    cur.executemany(
                        "DELETE FROM node WHERE id = %s", [(_nid(nid),) for nid in d.node_deleted]
                    )
                if d.node_upserts:
                    self._insert_nodes(cur, d.node_upserts, result.chunks, upsert=True)
                if edge_inserts:
                    self._insert_edges(cur, edge_inserts)
                if d.chunk_inserts:
                    self._insert_chunks(cur, d.chunk_inserts)
                self._link_parents(cur, result.edges)
                resolved = self._resolve_pending(cur)
            conn.commit()
        finally:
            conn.close()
        report = dict(result.report)
        report["delta"] = {
            "mode": "merge",
            "nodes": {
                "added": len(d.node_added),
                "updated": len(d.node_updated),
                "deleted": len(d.node_deleted),
            },
            "edges": {
                "added": len(edge_inserts),
                "deleted": len(edge_delete_keys),
                "resolved_pending": resolved,
            },
            "chunks": {
                "embedded": len(d.chunk_inserts),
                "deleted": len(d.chunk_delete_keys),
                "unchanged": d.chunks_unchanged,
            },
        }
        logger.info("bnckb merge delta=%s", report["delta"])
        return report

    @staticmethod
    def _resolve_pending(cur) -> int:
        """Link pending edges whose textual ref now matches an existing node slug.

        Forward references fulfilled by a later partial ingest become real links. Skips
        a resolution that would collide with an already-resolved identical edge."""
        cur.execute(
            "UPDATE spec_link l SET dst_id = n.id, pending = false "
            "FROM node n WHERE l.dst_id IS NULL AND l.dst_ref IS NOT NULL "
            "AND n.slug = l.dst_ref AND NOT EXISTS ("
            "    SELECT 1 FROM spec_link x WHERE x.src_id = l.src_id AND x.rel = l.rel "
            "    AND x.dst_id = n.id)"
        )
        return cur.rowcount

    # --- row inserters --------------------------------------------------------
    @staticmethod
    def _insert_nodes(cur, nodes, chunks, *, upsert: bool = False) -> None:
        from psycopg.types.json import Json

        bodies = _bnckb_bodies(chunks)
        sql = (
            "INSERT INTO node (id, kind, slug, body, version, status, source_commit, "
            "content_hash, attrs) VALUES (%s,%s,%s,%s,1,'approved',%s,%s,%s)"
        )
        if upsert:
            sql += (
                " ON CONFLICT (id) DO UPDATE SET kind=EXCLUDED.kind, body=EXCLUDED.body, "
                "source_commit=EXCLUDED.source_commit, content_hash=EXCLUDED.content_hash, "
                "attrs=EXCLUDED.attrs"
            )
        cur.executemany(
            sql,
            [
                (_nid(n.id), _kv(n.kind), n.id, bodies.get(n.id), n.source_path,
                 n.content_hash, Json(n.props))
                for n in nodes
            ],
        )

    @staticmethod
    def _insert_edges(cur, edges) -> None:
        cur.executemany(
            "INSERT INTO spec_link (src_id, dst_id, dst_ref, rel, pending) "
            "VALUES (%s,%s,%s,%s,%s) ON CONFLICT ON CONSTRAINT uq_edge DO NOTHING",
            [
                (_nid(e.src_id), _nid(e.dst_id) if e.dst_id else None, e.dst_ref,
                 _kv(e.kind), bool(e.pending))
                for e in edges
            ],
        )

    @staticmethod
    def _insert_chunks(cur, chunks) -> None:
        cur.executemany(
            "INSERT INTO node_chunk_embedding (node_id, ord, embedding, tier, chunk_text, "
            "content_hash, embedding_model_version, pipeline_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
            [
                (
                    _nid(c.node_id),
                    _ord(_kv(c.tier)),
                    [float(x) for x in c.embedding] if c.embedding else None,
                    _kv(c.tier),
                    c.text,
                    c.content_hash,
                    c.embedding_model_version,
                    c.pipeline_version,
                )
                for c in chunks
            ],
        )

    @staticmethod
    def _link_parents(cur, edges) -> None:
        parents = _bnckb_parents(edges)
        if parents:
            cur.executemany(
                "UPDATE node SET parent_id = %s WHERE id = %s",
                [(_nid(p), _nid(c)) for c, p in parents.items()],
            )


class NullSink:
    """Validate-only sink (AC-20). ``needs_vectors=False`` -> no embedder is built.

    ``write`` is a no-op that returns the validity report. The engine never
    constructs an embedding model when the sink is a ``NullSink``, so bge-m3 is
    never loaded and the pass stays fast (lint/CI).
    """

    needs_vectors = False

    def write(self, result) -> dict:
        return result.report


def select_sink(name: str = "json", **opts):
    """Factory: ``json`` -> JsonSink, ``sqlite`` -> SqliteSink, ``postgres`` ->
    PostgresSink, ``bnckb`` -> BncKbSink, ``none`` -> NullSink.

    ``opts`` for ``json``: ``out_dir``; for ``sqlite``: ``db_path``; for ``postgres``
    and ``bnckb``: ``dsn`` (libpq conninfo / URL).
    """
    if name == "json":
        out_dir = opts.get("out_dir")
        if not out_dir:
            raise ValueError("--output json requires --out-dir <dir>")
        return JsonSink(out_dir)
    if name == "sqlite":
        db_path = opts.get("db_path")
        if not db_path:
            raise ValueError("--output sqlite requires --db <path>")
        return SqliteSink(db_path)
    if name == "postgres":
        dsn = opts.get("dsn")
        if not dsn:
            raise ValueError("--output postgres requires --dsn <conninfo>")
        return PostgresSink(dsn)
    if name == "bnckb":
        dsn = opts.get("dsn")
        if not dsn:
            raise ValueError("--output bnckb requires --dsn <conninfo>")
        return BncKbSink(dsn)
    if name == "none":
        return NullSink()
    raise ValueError(f"unknown output sink: {name!r}")
