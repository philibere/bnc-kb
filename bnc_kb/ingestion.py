"""Ingestion operations over the vendored ``spec_ingestion`` engine.

Two ways to write into the bnc-kb store via ``BncKbSink``:

* ``run_corpus_ingest`` — WHOLE-corpus: full snapshot (``write``) or incremental
  reconcile (``reconcile``). The corpus is the complete spec set; nodes absent from
  it are deleted.
* ``run_merge`` — PARTIAL: upsert one or several specs (``merge``), leaving the rest
  of the store intact. Selective re-embedding still applies (incremental build).
"""

from __future__ import annotations

import psycopg

from spec_ingestion import engine
from spec_ingestion import metamodel as _mm
from spec_ingestion.sinks import BncKbSink


def ensure_link_types(dsn: str) -> None:
    """Align the ``link_type`` whitelist with the active metamodel (idempotent).

    ``spec_link.rel`` has a FK to ``link_type``. Migration 0006 seeds a fixed set of
    edge kinds, but the metamodel manifest is the authoritative whitelist, so we seed
    every ``EDGE_KINDS`` value here: any corpus edge kind then has its FK target,
    whatever manifest is in use.
    """
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO link_type (code, label) VALUES (%s, %s) ON CONFLICT (code) DO NOTHING",
            [(k, k) for k in _mm.EDGE_KINDS],
        )


def run_corpus_ingest(corpus, dsn: str, *, incremental: bool = False) -> dict:
    """Whole-corpus ingest: reconcile (incremental) or full snapshot (write)."""
    ensure_link_types(dsn)
    return engine.ingest(corpus, sink=BncKbSink(dsn), incremental=incremental)


def run_merge(corpus, dsn: str) -> dict:
    """Partial ingest: upsert the specs under ``corpus`` without deleting the rest.

    Runs the engine with selective re-embedding (incremental build) then applies
    ``BncKbSink.merge``. On validation rejection nothing is written.
    """
    sink = BncKbSink(dsn)
    result = engine.build(corpus, sink=sink, incremental=True)
    if result.rejected:
        return result.report
    ensure_link_types(dsn)
    return sink.merge(result)
