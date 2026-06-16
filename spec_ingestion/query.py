"""Read path over the persisted SQLite store (``SqliteSink``).

The store is the durable mirror of one ingestion run; this module is its query
surface, decoupled from ingestion exactly as the sink is decoupled from the
engine. Three capabilities:

* graph traversal -- ``out_edges`` / ``in_edges`` / ``trace`` (BFS over the
  traceability column: Module->Feature->REQ, Capability--serves-->BusinessLine,
  Capability<--realizes--Feature, Capability--governed-by-->Control, ...);
* text search -- ``search_text`` (substring over chunk text, e.g. REQ statements
  and capability summaries);
* vector search -- ``search_vector`` (cosine over chunk embeddings) WHEN the store
  was fed embedded chunks; absent embeddings it reports unavailable rather than
  guessing.

Pure stdlib (sqlite3 + json + math). CLI: ``python -m spec_ingestion.query DB ...``.
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
from dataclasses import dataclass


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def get_node(conn: sqlite3.Connection, node_id: str) -> dict | None:
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        return None
    return _node_row(row)


def _node_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "props": json.loads(row["props"]),
        "content_hash": row["content_hash"],
        "source_path": row["source_path"],
    }


def out_edges(conn: sqlite3.Connection, node_id: str, kind: str | None = None) -> list[dict]:
    """Edges leaving ``node_id`` (``node_id`` is the src)."""
    return _edges(conn, "src_id", node_id, kind)


def in_edges(conn: sqlite3.Connection, node_id: str, kind: str | None = None) -> list[dict]:
    """Edges arriving at ``node_id`` (``node_id`` is the resolved dst)."""
    return _edges(conn, "dst_id", node_id, kind)


def _edges(conn: sqlite3.Connection, col: str, node_id: str, kind: str | None) -> list[dict]:
    sql = f"SELECT src_id, dst_ref, dst_id, kind, pending FROM edges WHERE {col} = ?"
    params: list = [node_id]
    if kind is not None:
        sql += " AND kind = ?"
        params.append(kind)
    sql += " ORDER BY kind, dst_ref, src_id"
    return [
        {
            "src_id": r["src_id"],
            "dst_ref": r["dst_ref"],
            "dst_id": r["dst_id"],
            "kind": r["kind"],
            "pending": bool(r["pending"]),
        }
        for r in conn.execute(sql, params).fetchall()
    ]


@dataclass
class TraceStep:
    depth: int
    src_id: str
    kind: str
    dst_id: str | None
    dst_ref: str
    direction: str  # "out" | "in"


def trace(
    conn: sqlite3.Connection,
    start_id: str,
    *,
    direction: str = "out",
    edge_kinds: set[str] | None = None,
    max_depth: int | None = None,
) -> list[TraceStep]:
    """BFS the traceability tree from ``start_id``.

    ``direction``: ``out`` follows edges where the node is the source, ``in``
    follows edges arriving at the node, ``both`` follows either. ``edge_kinds``
    restricts the walk to those kinds (``None`` = any). Visited nodes are not
    re-expanded, so cycles terminate. Returns steps in BFS order.
    """
    seen = {start_id}
    frontier = [(start_id, 0)]
    steps: list[TraceStep] = []
    while frontier:
        node_id, depth = frontier.pop(0)
        if max_depth is not None and depth >= max_depth:
            continue
        for d in ("out", "in") if direction == "both" else (direction,):
            rows = out_edges(conn, node_id) if d == "out" else in_edges(conn, node_id)
            for e in rows:
                if edge_kinds is not None and e["kind"] not in edge_kinds:
                    continue
                nxt = e["dst_id"] if d == "out" else e["src_id"]
                steps.append(
                    TraceStep(
                        depth=depth,
                        src_id=e["src_id"],
                        kind=e["kind"],
                        dst_id=e["dst_id"],
                        dst_ref=e["dst_ref"],
                        direction=d,
                    )
                )
                if nxt and nxt not in seen:
                    seen.add(nxt)
                    frontier.append((nxt, depth + 1))
    return steps


def search_text(
    conn: sqlite3.Connection, needle: str, *, tier: str | None = None, limit: int = 20
) -> list[dict]:
    """Substring search over chunk text (case-insensitive)."""
    sql = "SELECT node_id, tier, text FROM chunks WHERE text LIKE ?"
    params: list = [f"%{needle}%"]
    if tier is not None:
        sql += " AND tier = ?"
        params.append(tier)
    sql += " ORDER BY node_id LIMIT ?"
    params.append(limit)
    return [
        {"node_id": r["node_id"], "tier": r["tier"], "text": r["text"]}
        for r in conn.execute(sql, params).fetchall()
    ]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def search_vector(
    conn: sqlite3.Connection, query_embedding: list[float], *, limit: int = 10
) -> list[dict]:
    """Cosine-rank chunks against ``query_embedding`` (only those carrying vectors)."""
    scored: list[dict] = []
    for r in conn.execute("SELECT node_id, tier, text, embedding FROM chunks").fetchall():
        emb = json.loads(r["embedding"]) if r["embedding"] else []
        if not emb:
            continue
        scored.append(
            {
                "node_id": r["node_id"],
                "tier": r["tier"],
                "text": r["text"],
                "score": cosine(query_embedding, emb),
            }
        )
    scored.sort(key=lambda c: c["score"], reverse=True)
    return scored[:limit]


def has_vectors(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM chunks WHERE embedding IS NOT NULL AND embedding != '[]' LIMIT 1"
    ).fetchone()
    return row is not None


# --------------------------------------------------------------------------- CLI


def _print_node(conn: sqlite3.Connection, node_id: str) -> int:
    node = get_node(conn, node_id)
    if node is None:
        print(f"node not found: {node_id!r}")
        return 1
    print(f"{node['id']}  [{node['kind']}]")
    for k, v in node["props"].items():
        print(f"  {k}: {v}")
    return 0


def _print_trace(conn: sqlite3.Connection, node_id: str, direction: str, depth: int | None) -> int:
    if get_node(conn, node_id) is None:
        print(f"node not found: {node_id!r}")
        return 1
    steps = trace(conn, node_id, direction=direction, max_depth=depth)
    print(f"trace {direction} from {node_id} ({len(steps)} edges):")
    for s in steps:
        arrow = "->" if s.direction == "out" else "<-"
        tgt = s.dst_id or f"{s.dst_ref} (pending)"
        peer = tgt if s.direction == "out" else s.src_id
        print(f"  {'  ' * s.depth}{arrow} [{s.kind}] {peer}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="spec-query", description="Query a persisted spec store")
    p.add_argument("db", help="path to the SQLite store written by --output sqlite")
    p.add_argument("--node", metavar="ID", help="show a node and its props")
    p.add_argument("--trace", action="store_true", help="BFS the traceability tree from --node")
    p.add_argument("--direction", choices=("out", "in", "both"), default="out")
    p.add_argument("--depth", type=int, default=None, help="max BFS depth")
    p.add_argument("--search", metavar="TEXT", help="substring search over chunk text")
    p.add_argument("--tier", metavar="TIER", help="restrict --search to a chunk tier")
    args = p.parse_args(argv)

    conn = connect(args.db)
    try:
        if args.search is not None:
            hits = search_text(conn, args.search, tier=args.tier)
            print(f"{len(hits)} chunk(s) matching {args.search!r}:")
            for h in hits:
                snippet = h["text"].replace("\n", " ")
                if len(snippet) > 100:
                    snippet = snippet[:100] + "..."
                print(f"  [{h['tier']}] {h['node_id']}: {snippet}")
            return 0
        if args.node and args.trace:
            return _print_trace(conn, args.node, args.direction, args.depth)
        if args.node:
            return _print_node(conn, args.node)
        p.error("nothing to do: pass --node and/or --search")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
