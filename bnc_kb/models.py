from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class IngestManifest(BaseModel):
    capability_slug: str
    category: str
    domain: str
    source_commit: str


class IngestSummary(BaseModel):
    capability_slug: str
    source_commit: str
    nodes_created: int = 0
    nodes_versioned: int = 0
    nodes_skipped: int = 0
    dimensions_seen: list[str] = Field(default_factory=list)
    sources_unreached: list[str] = Field(default_factory=list)
    idempotent_hit: bool = False


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


@dataclass
class NodeSpec:
    """An intermediate, pre-persistence node produced by the parser."""

    local_id: str
    kind: str
    slug: str
    parent_local_id: str | None = None
    dimension_code: str | None = None
    body: str | None = None
    source_path: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
