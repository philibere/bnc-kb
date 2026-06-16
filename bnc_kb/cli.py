"""CLI d'ingestion bnc-kb : pilote le moteur vendore ``spec_ingestion`` vers le
store bnc-kb.

``bnc-kb-ingest <corpus> [--incremental | --merge]`` lance la chaine
discovery -> parse -> validate -> extract -> embed -> ``BncKbSink(DATABASE_URL)``.
Le DSN par defaut vient de la config bnc-kb (``DATABASE_URL``).

Modes :
* (defaut)       snapshot complet du CORPUS (TRUNCATE + insert).
* ``--incremental``  reconcilie le CORPUS complet au delta (re-embed les chunks changes ;
                     supprime les noeuds absents du corpus).
* ``--merge``        ingestion PARTIELLE : upsert une ou plusieurs specs sans toucher au
                     reste du store (rien n'est supprime hors du perimetre du batch).

Codes de sortie : ``0`` succes, ``2`` validation rejetee, ``1`` erreur inattendue.
"""

from __future__ import annotations

import argparse
import logging

from bnc_kb.config import load_settings
from bnc_kb.ingestion import run_corpus_ingest, run_merge

logger = logging.getLogger("bnc_kb.cli")

EXIT_OK = 0
EXIT_UNEXPECTED = 1
EXIT_REJECTED = 2


def ingest_corpus(
    corpus_path: str, *, dsn: str | None = None, incremental: bool = False, merge: bool = False
) -> int:
    """Ingere ``corpus_path`` dans le store bnc-kb ; renvoie un code de sortie."""
    dsn = dsn or load_settings().database_url
    logger.info(
        "ingest start corpus=%s incremental=%s merge=%s", corpus_path, incremental, merge
    )
    try:
        if merge:
            report = run_merge(corpus_path, dsn)
        else:
            report = run_corpus_ingest(corpus_path, dsn, incremental=incremental)
        if report.get("status") == "rejected":
            logger.error("validation rejected faulty=%d", len(report.get("faulty", [])))
            return EXIT_REJECTED
        logger.info("ingest ok stats=%s delta=%s", report.get("stats"), report.get("delta"))
        return EXIT_OK
    except Exception:
        logger.exception("unexpected error during ingestion")
        return EXIT_UNEXPECTED


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(
        prog="bnc-kb-ingest",
        description="Ingere un corpus (ou quelques specs) shaper dans le store bnc-kb",
    )
    parser.add_argument("corpus", help="chemin d'un .md, d'un repertoire ou d'une racine de corpus")
    parser.add_argument("--dsn", metavar="CONNINFO", help="surcharge DATABASE_URL")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--incremental",
        action="store_true",
        help="reconcilie le CORPUS complet au delta (re-embed uniquement les chunks changes)",
    )
    mode.add_argument(
        "--merge",
        action="store_true",
        help="ingestion PARTIELLE : upsert ces specs sans supprimer le reste du store",
    )
    args = parser.parse_args(argv)
    return ingest_corpus(
        args.corpus, dsn=args.dsn, incremental=args.incremental, merge=args.merge
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
