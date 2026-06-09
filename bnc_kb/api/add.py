from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from bnc_kb.api.auth import require_role
from bnc_kb.db.connection import get_pool
from bnc_kb.embeddings import StubEmbedder
from bnc_kb.models import IngestSummary
from bnc_kb.queries.ingest import ingest_archive

router = APIRouter(tags=["add"])


@router.post("/ingest", response_model=IngestSummary)
def ingest(
    file: UploadFile = File(...),
    _role: str = Depends(require_role("write")),
) -> IngestSummary:
    data = file.file.read()
    with get_pool().connection() as conn:
        try:
            return ingest_archive(conn, data, StubEmbedder())
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
