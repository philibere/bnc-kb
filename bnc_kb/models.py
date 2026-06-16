from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class IngestResult(BaseModel):
    """Outcome of one ingestion run (shaper engine -> bnc-kb store).

    Mirrors the engine build report: counts from ``stats``, the number of
    unresolved cross-references (``pending_edges``), validation faults (when
    ``status == "rejected"``) and the incremental ``delta`` when reconciling.
    """

    status: str
    nodes: int = 0
    edges: int = 0
    chunks: int = 0
    pending_edges: int = 0
    faulty: list[dict] = Field(default_factory=list)
    delta: dict | None = None


class Coverage(BaseModel):
    partial: bool = False
    denied_scopes: list[str] = Field(default_factory=list)
    sources_unreached: list[str] = Field(default_factory=list)


class NodeHit(BaseModel):
    id: UUID
    kind: str
    slug: str
    dimension_code: str | None = None
    status: str | None = None
    version: int | None = None
    score: float | None = None
    body: str | None = None


class SearchRequest(BaseModel):
    query: str
    dimension: str | None = None
    status: str = "approved"
    k: int = 12


class SearchResponse(BaseModel):
    rows: list[NodeHit]
    coverage: Coverage


class SpecResponse(BaseModel):
    rows: list[NodeHit]
    coverage: Coverage


class LinkHit(BaseModel):
    rel: str
    target: str


class DimensionIn(BaseModel):
    code: str
    label: str
    description: str | None = None


class LinkTypeIn(BaseModel):
    code: str
    label: str
    description: str | None = None
    directed: bool = True
