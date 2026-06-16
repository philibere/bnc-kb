"""CLI orchestration + exit codes (the pipeline's entry point).

JSON-only:

* ``spec-ingest <cible> [--output json|none] [--out-dir DIR]`` runs the chain
  (discovery -> parse -> validate -> extract -> embed -> JsonSink snapshot).
  ``<cible>`` is a single ``.md`` file, a directory (recursed) or a corpus root.
* ``--output json`` (default) writes the four-file snapshot into ``--out-dir``
  (default ``./spec-index-json``).
* ``--output none`` is validate-only: it runs the chain up to validation, reports
  faulty artifacts, and writes nothing (no embedder is ever constructed).

Exit codes: ``0`` success, ``2`` validation rejected, ``1`` unexpected error.
"""

from __future__ import annotations

import argparse
import logging

from spec_ingestion import engine
from spec_ingestion.sinks import select_sink

logger = logging.getLogger("spec_ingestion.cli")

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_REJECTED = 2

DEFAULT_OUT_DIR = "./spec-index-json"
DEFAULT_DB_PATH = "./spec-index.sqlite"


def _configure_logging() -> None:
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")


def ingest_corpus(
    corpus_path: str,
    *,
    output: str = "json",
    out_dir: str | None = None,
    db_path: str | None = None,
    dsn: str | None = None,
    incremental: bool = False,
) -> int:
    """Run the ingestion chain over ``corpus_path`` and return an exit code.

    The engine (``engine.ingest``) is store-agnostic; ``--output`` selects the
    adapter: ``json`` (snapshot), ``sqlite`` (durable graph+chunk store, queried
    via ``spec_ingestion.query``), ``postgres`` (graph+chunk store with native
    pgvector), ``bnckb`` (write into the bnc-kb Postgres store so its API serves
    shaper specs) or ``none`` (validate-only NullSink). ``--incremental`` reconciles
    a durable store to the corpus delta instead of rewriting the full snapshot.

    Exit codes: ``0`` success, ``2`` validation rejected, ``1`` unexpected.
    """
    target = {"json": out_dir, "sqlite": db_path, "postgres": dsn, "bnckb": dsn}.get(output, "")
    logger.info(
        "ingest start corpus=%s output=%s target=%s incremental=%s",
        corpus_path,
        output,
        target,
        incremental,
    )

    try:
        sink = _build_sink(output, out_dir=out_dir, db_path=db_path, dsn=dsn)
        report = engine.ingest(corpus_path, sink=sink, incremental=incremental)
        if report.get("status") == "rejected":
            logger.info("validation rejected faulty=%d", len(report["faulty"]))
            return EXIT_REJECTED
        if report.get("delta"):
            logger.info("incremental delta=%s", report["delta"])
        return EXIT_OK
    except Exception:
        logger.exception("unexpected error during ingestion")
        return EXIT_UNEXPECTED


def _build_sink(output: str, *, out_dir: str | None, db_path: str | None = None, dsn: str | None = None):
    if output == "json":
        return select_sink("json", out_dir=out_dir or DEFAULT_OUT_DIR)
    if output == "sqlite":
        return select_sink("sqlite", db_path=db_path or DEFAULT_DB_PATH)
    if output == "postgres":
        return select_sink("postgres", dsn=dsn)
    if output == "bnckb":
        return select_sink("bnckb", dsn=dsn)
    if output == "none":
        return select_sink("none")
    raise ValueError(f"unknown output: {output!r}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="spec-ingest", description="BNC spec ingestion pipeline")
    parser.add_argument("corpus", help="path to a .md file, a directory or a corpus root")
    parser.add_argument(
        "--output",
        choices=("json", "sqlite", "postgres", "bnckb", "none"),
        default="json",
        help="output adapter: json (default, snapshot), sqlite, postgres (pgvector), "
        "bnckb (write into the bnc-kb store) or none (validate-only)",
    )
    parser.add_argument(
        "--out-dir",
        metavar="DIR",
        help=f"target directory for the JSON snapshot (default {DEFAULT_OUT_DIR})",
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help=f"target SQLite file for --output sqlite (default {DEFAULT_DB_PATH})",
    )
    parser.add_argument(
        "--dsn",
        metavar="CONNINFO",
        help="libpq conninfo / URL for --output postgres or bnckb (e.g. postgresql://user:pw@host:port/db)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="reconcile the durable store to the corpus delta (re-embed only changed chunks)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    _configure_logging()
    parser = _build_parser()
    args = parser.parse_args(argv)
    return ingest_corpus(
        args.corpus,
        output=args.output,
        out_dir=args.out_dir,
        db_path=args.db,
        dsn=args.dsn,
        incremental=args.incremental,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
