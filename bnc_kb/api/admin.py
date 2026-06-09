from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from bnc_kb.api.auth import require_role
from bnc_kb.db.connection import get_pool
from bnc_kb.embeddings import StubEmbedder, chunk_text, to_vector_literal
from bnc_kb.models import DimensionIn, LinkTypeIn

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/health")
def health() -> dict:
    with get_pool().connection() as conn:
        conn.execute("SELECT 1")
    return {"status": "ok"}


@router.get("/stats")
def stats(_role: str = Depends(require_role("admin"))) -> dict:
    with get_pool().connection() as conn:
        nodes = conn.execute("SELECT count(*) FROM node").fetchone()[0]
        dims = conn.execute("SELECT count(*) FROM spec_dimension").fetchone()[0]
    return {"nodes": nodes, "dimensions": dims}


@router.get("/dimensions")
def list_dimensions(_role: str = Depends(require_role("admin"))) -> list[dict]:
    with get_pool().connection() as conn:
        rows = conn.execute("SELECT code, label FROM spec_dimension ORDER BY code").fetchall()
    return [{"code": c, "label": label} for c, label in rows]


@router.post("/dimensions", status_code=201)
def add_dimension(body: DimensionIn, _role: str = Depends(require_role("admin"))) -> dict:
    with get_pool().connection() as conn:
        try:
            conn.execute(
                "INSERT INTO spec_dimension (code, label, description) VALUES (%s, %s, %s)",
                (body.code, body.label, body.description),
            )
        except psycopg.errors.UniqueViolation:
            raise HTTPException(status_code=409, detail=f"dimension {body.code!r} already exists")
    return {"code": body.code}


@router.delete("/dimensions/{code}")
def delete_dimension(code: str, _role: str = Depends(require_role("admin"))) -> dict:
    with get_pool().connection() as conn:
        conn.execute("DELETE FROM spec_dimension WHERE code = %s", (code,))
    return {"deleted": code}


@router.post("/link-types", status_code=201)
def add_link_type(body: LinkTypeIn, _role: str = Depends(require_role("admin"))) -> dict:
    with get_pool().connection() as conn:
        try:
            conn.execute(
                "INSERT INTO link_type (code, label, description, directed) "
                "VALUES (%s, %s, %s, %s)",
                (body.code, body.label, body.description, body.directed),
            )
        except psycopg.errors.UniqueViolation:
            raise HTTPException(status_code=409, detail=f"link type {body.code!r} already exists")
    return {"code": body.code}


@router.post("/reembed")
def reembed(_role: str = Depends(require_role("admin"))) -> dict:
    """Recompute embeddings for every document node (e.g. after swapping embedder)."""
    embedder = StubEmbedder()
    rewritten = 0
    with get_pool().connection() as conn:
        with conn.transaction():
            docs = conn.execute(
                "SELECT id, body FROM node WHERE body IS NOT NULL"
            ).fetchall()
            conn.execute("TRUNCATE node_chunk_embedding")
            for node_id, body in docs:
                for ord_, vec in enumerate(embedder.embed(chunk_text(body))):
                    conn.execute(
                        "INSERT INTO node_chunk_embedding (node_id, ord, embedding) "
                        "VALUES (%s, %s, %s::vector)",
                        (node_id, ord_, to_vector_literal(vec)),
                    )
                    rewritten += 1
    return {"chunks": rewritten}
