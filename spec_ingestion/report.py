"""Build report assembly (pure).

The report mirrors the spec shape:

    {status, stats:{nodes, edges, chunks, reembeds},
     faulty:[{artifact_id, path, reason}], pending_edges:[{src, dst_ref, kind}],
     orphans:[id]}

It carries only artifact identifiers, paths and counts. Persisting / reading back
runs was a DB concern (``ingestion_run``) and is deferred with the Postgres layer.
"""

from __future__ import annotations

_EMPTY_STATS = {"nodes": 0, "edges": 0, "chunks": 0, "reembeds": 0}


def build_report(
    *,
    status: str,
    stats: dict | None = None,
    faulty: list | None = None,
    pending_edges: list | None = None,
    orphans: list | None = None,
) -> dict:
    """Assemble the canonical build-report dict (spec shape).

    ``status`` is ``success`` | ``rejected`` | ``failed``. Missing sections default
    to empty so the shape is always complete.
    """
    merged = dict(_EMPTY_STATS)
    merged.update(stats or {})
    return {
        "status": status,
        "stats": merged,
        "faulty": list(faulty or []),
        "pending_edges": list(pending_edges or []),
        "orphans": list(orphans or []),
    }
