"""Ingestion operations over the vendored ``spec_ingestion`` engine.

Two ways to write into the bnc-kb store via ``BncKbSink``:

* ``run_corpus_ingest`` — WHOLE-corpus: full snapshot (``write``) or incremental
  reconcile (``reconcile``). The corpus is the complete spec set; nodes absent from
  it are deleted.
* ``run_merge`` — PARTIAL: upsert one or several specs (``merge``), leaving the rest
  of the store intact. Selective re-embedding still applies (incremental build).
"""

from __future__ import annotations

from spec_ingestion import engine
from spec_ingestion.sinks import BncKbSink


def run_corpus_ingest(corpus, dsn: str, *, incremental: bool = False) -> dict:
    """Whole-corpus ingest: reconcile (incremental) or full snapshot (write)."""
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
    return sink.merge(result)
