from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query

from bnc_kb.api.auth import require_role
from bnc_kb.db.connection import get_pool
from bnc_kb.embeddings import StubEmbedder
from bnc_kb.models import (
    Coverage,
    LinkHit,
    NodeHit,
    SearchRequest,
    SearchResponse,
    SpecResponse,
)
from bnc_kb.queries.links import get_links
from bnc_kb.queries.search import search_specs
from bnc_kb.queries.spec import get_spec

router = APIRouter(tags=["search"])


@router.post("/search", response_model=SearchResponse)
def search(req: SearchRequest, _role: str = Depends(require_role("read"))) -> SearchResponse:
    qvec = StubEmbedder().embed([req.query])[0]
    with get_pool().connection() as conn:
        rows = search_specs(conn, qvec, req.dimension, req.status, req.k)
    hits = [NodeHit(**r) for r in rows]
    # `partial`: the result count hit the k limit, so more matches may exist beyond
    # this page. A conservative flag (can be a false positive when the true count
    # equals k exactly) — the point is to never silently truncate.
    return SearchResponse(rows=hits, coverage=Coverage(partial=len(hits) >= req.k))


@router.get("/spec/{head_id}", response_model=SpecResponse)
def spec(
    head_id: UUID,
    dimension: str | None = Query(default=None),
    status: str = Query(default="approved"),
    _role: str = Depends(require_role("read")),
) -> SpecResponse:
    with get_pool().connection() as conn:
        rows = get_spec(conn, head_id, dimension, status)
    return SpecResponse(rows=[NodeHit(**r) for r in rows], coverage=Coverage())


@router.get("/spec/{node_id}/links", response_model=list[LinkHit])
def links(
    node_id: UUID,
    rel: str | None = Query(default=None),
    _role: str = Depends(require_role("read")),
) -> list[LinkHit]:
    with get_pool().connection() as conn:
        return [LinkHit(**r) for r in get_links(conn, node_id, rel)]
