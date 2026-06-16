from __future__ import annotations

import io
import tempfile
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile

from bnc_kb.api.auth import require_role
from bnc_kb.config import load_settings
from bnc_kb.ingestion import run_corpus_ingest, run_merge
from bnc_kb.models import IngestResult

router = APIRouter(tags=["add"])


def _report_to_result(report: dict) -> IngestResult:
    stats = report.get("stats", {})
    return IngestResult(
        status=report.get("status", "unknown"),
        nodes=stats.get("nodes", 0),
        edges=stats.get("edges", 0),
        chunks=stats.get("chunks", 0),
        pending_edges=len(report.get("pending_edges", [])),
        faulty=report.get("faulty", []),
        delta=report.get("delta"),
    )


def _reject_if_rejected(report: dict) -> None:
    # 422: the corpus reached the pipeline but failed validation
    # (duplicate id / out-of-vocabulary kind / unreadable frontmatter).
    if report.get("status") == "rejected":
        raise HTTPException(
            status_code=422,
            detail={"status": "rejected", "faulty": report.get("faulty", [])},
        )


@router.post("/ingest", response_model=IngestResult)
def ingest(
    file: UploadFile = File(...),
    incremental: bool = Query(default=True),
    _role: str = Depends(require_role("write")),
) -> IngestResult:
    """Whole-corpus ingest of a .zip of shaper .md specs into the bnc-kb store.

    The zip carries the COMPLETE spec set (the engine reconciles to it: nodes absent
    from the zip are deleted). ``incremental=true`` (default) re-embeds only changed
    chunks; ``incremental=false`` rewrites the store in full (TRUNCATE + insert). To
    ingest a subset without touching the rest, use ``POST /ingest/specs``.
    """
    data = file.file.read()
    with tempfile.TemporaryDirectory(prefix="bnc-kb-ingest-") as tmp:
        root = Path(tmp)
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                zf.extractall(root)
        except zipfile.BadZipFile:
            raise HTTPException(status_code=400, detail="upload must be a .zip of shaper .md specs")
        report = run_corpus_ingest(root, load_settings().database_url, incremental=incremental)
    _reject_if_rejected(report)
    return _report_to_result(report)


@router.post("/ingest/specs", response_model=IngestResult)
def ingest_specs(
    files: list[UploadFile] = File(...),
    _role: str = Depends(require_role("write")),
) -> IngestResult:
    """Partial ingest of one or several spec files (.md): upsert ONLY these specs and
    leave the rest of the store intact (unlike ``POST /ingest``, which reconciles the
    whole corpus). Cross-references to specs already stored are resolved when possible;
    refs to specs not yet present stay pending until they arrive.
    """
    if not files:
        raise HTTPException(status_code=400, detail="no spec files uploaded")
    with tempfile.TemporaryDirectory(prefix="bnc-kb-specs-") as tmp:
        root = Path(tmp)
        for i, f in enumerate(files):
            name = Path(f.filename or f"spec-{i}.md").name
            if not name.endswith(".md"):
                name += ".md"
            (root / f"{i:03d}-{name}").write_bytes(f.file.read())
        report = run_merge(root, load_settings().database_url)
    _reject_if_rejected(report)
    return _report_to_result(report)
