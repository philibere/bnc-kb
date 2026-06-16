"""Phase 3 extraction: parsed artifacts -> typed ``Node`` + ``Edge`` + ``Chunk``.

Maps the parsed structures onto the closed vocabulary in ``model``. Applies the
ID grammar (Feature ``FEAT-MOD-NNN``; REQ composite ``{FEAT-id}/REQ-NNN``; INV
``INV-NNN-slug``; glossary/module = slug). Emits closed-vocab edges only;
``derive(...)`` sentinels (implemented-by / verified-by) and ``candidate-*``
edges are excluded by construction. Computes a per-node ``content_hash`` and
identifies embeddable tiers (REQ, feature_summary, glossary_definition).

Edge ``dst_ref`` stays the declared token (ID or name-hint). Resolution to
``dst_id`` and pending classification are the next slice's job.

Pure-Python, no DB.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from spec_ingestion.metamodel import GENERIC_SPECS
from spec_ingestion.model import Chunk, Edge, EdgeKind, Node, NodeKind, Tier
from spec_ingestion.parsing import (
    _iter_blocks,
    _parse_block_fields,
    _parse_inline_list,
    parse_frontmatter,
)

# Chunks carry no embedding yet (Phase 5); use a zero-length placeholder so the
# dataclass field is satisfied without implying a real vector.
_NO_EMBEDDING: list[float] = []


@dataclass
class ExtractionResult:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    chunks: list[Chunk] = field(default_factory=list)


def _content_hash(payload: dict) -> str:
    blob = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _field_transform(raw, how: str | None):
    """Normalize a declared field value: ``list``, ``inline_list``, ``stripped``, ``text``, raw."""
    if how == "list":
        return _as_list(raw)
    if how == "inline_list":
        return _parse_inline_list(str(raw if raw is not None else ""))
    if how == "stripped":
        return str(raw if raw is not None else "").strip()
    if how == "text":
        return str(raw) if raw is not None else ""
    return raw


def _compose_ref(token: str, mode: str | None, base: str) -> str:
    """Compose a local block reference to a composite id, per the declared mode.

    ``feature``  : a REQ peer ref inside a feature -> ``{base}/{token}`` unless it
                   is already a foreign feature ref (``FEAT-...``).
    ``technical``: a CONTRACT/DEC ref to a feature REQ -> ``{base}/{token}`` only for
                   a bare local ``REQ-NNN`` (else left as-is: CONTRACT/INV targets).
    """
    if mode == "feature":
        return token if token.startswith("FEAT-") else f"{base}/{token}"
    if mode == "technical":
        if base and token.startswith("REQ-") and "/" not in token:
            return f"{base}/{token}"
        return token
    return token


def _render_req_context(parent_id: str, parent_props: dict, fields: dict) -> str:
    """Composed REQ chunk: ``{feat} {title} | actors: .. | entities: ..`` + statement + acceptance.

    REQ-level ``actors``/``entities`` override the feature's; else they are inherited.
    """
    title = str(parent_props.get("title", "") or "")
    header = f"{parent_id} {title}".strip()
    actors = _parse_inline_list(str(fields.get("actors", ""))) or _as_list(parent_props.get("actors"))
    entities = _parse_inline_list(str(fields.get("entities", ""))) or _as_list(parent_props.get("entities"))
    context = f"{header} | actors: {', '.join(actors)} | entities: {', '.join(entities)}"
    parts = [context, str(fields.get("statement", ""))]
    acceptance = str(fields.get("acceptance", ""))
    if acceptance:
        parts.append(acceptance)
    return "\n".join(p for p in parts if p)


# Composed-chunk renderers are procedural (cross-field text), selected BY NAME from
# the manifest (``chunk_renderer``). The graph STRUCTURE stays fully declarative;
# only the retrieval-text composition lives here.
_CHUNK_RENDERERS = {"req_context": _render_req_context}


def _resolve_top_kind(decl: dict, fm: dict) -> NodeKind | None:
    """Top node kind: ``produces_node``, or ``produces_node_by_kind[fm.kind]``, or None."""
    if decl.get("produces_node"):
        return NodeKind(decl["produces_node"])
    by_kind = decl.get("produces_node_by_kind")
    if by_kind:
        entry = by_kind.get(str(fm.get("kind", "")))
        if entry is None:
            raise ValueError(f"unknown kind for produces_node_by_kind: {fm.get('kind')!r}")
        return NodeKind(entry["node"])
    return None


def _select_top_props(decl: dict, fm: dict) -> dict:
    """Top-node props. ``node_props`` (ordered subset + transforms) else all declared frontmatter."""
    node_props = decl.get("node_props")
    if node_props:
        return {spec["field"]: _field_transform(fm.get(spec["field"]), spec.get("as")) for spec in node_props}
    # Default (unchanged): every declared frontmatter key present, grouped refs flattened.
    fields = decl.get("frontmatter") or {}
    props: dict = {}
    for k, v in fm.items():
        if k not in fields:
            continue
        groups = (fields[k] or {}).get("groups")
        if groups and isinstance(v, dict):
            for sub in groups:
                props[f"{k}_{sub}"] = v.get(sub, [])
        else:
            props[k] = v
    return props


def _emit_secondary_nodes(decl: dict, fm: dict, node_id: str, result: ExtractionResult, source: str) -> None:
    """Scalar frontmatter fields that spawn an extra node + edge (feature ``module`` -> Module)."""
    for fname, fspec in (decl.get("frontmatter") or {}).items():
        sec = (fspec or {}).get("secondary_node")
        if not sec:
            continue
        value = fm.get(fname)
        if not value:
            continue
        sid = str(value)
        result.nodes.append(
            Node(
                id=sid,
                kind=NodeKind(sec["kind"]),
                props={sec["prop"]: value},
                content_hash=_content_hash({fname: value}),
                source_path=source,
            )
        )
        edge_kind = EdgeKind(sec["edge"])
        if sec.get("dir") == "inbound":
            result.edges.append(Edge(src_id=sid, dst_ref=node_id, kind=edge_kind))
        else:
            result.edges.append(Edge(src_id=node_id, dst_ref=sid, kind=edge_kind))


def _emit_frontmatter_edges(decl: dict, fm: dict, node_id: str, result: ExtractionResult) -> None:
    """One edge per frontmatter ``ref`` field carrying an ``edge`` (dir-aware, groups-aware)."""
    for fname, fspec in (decl.get("frontmatter") or {}).items():
        fspec = fspec or {}
        edge_kind = fspec.get("edge")
        if not edge_kind:
            continue
        inbound = fspec.get("dir") == "inbound"
        groups = fspec.get("groups")
        if groups:
            value = fm.get(fname) or {}
            refs: list[str] = []
            for sub in groups:
                refs.extend(_as_list(value.get(sub) if isinstance(value, dict) else None))
        else:
            refs = _as_list(fm.get(fname))
        for ref in refs:
            if inbound:
                result.edges.append(Edge(src_id=ref, dst_ref=node_id, kind=EdgeKind(edge_kind)))
            else:
                result.edges.append(Edge(src_id=node_id, dst_ref=ref, kind=EdgeKind(edge_kind)))


def _emit_summary_chunk(decl: dict, props: dict, node_id: str, result: ExtractionResult) -> None:
    """The ``summary_field`` chunk (tier ``chunk_tier``), stripped, if non-empty."""
    summary_field = decl.get("summary_field")
    tier_name = decl.get("chunk_tier")
    if not (summary_field and tier_name):
        return
    summary = str(props.get(summary_field, "") or "").strip()
    if summary:
        result.chunks.append(
            Chunk(
                node_id=node_id,
                tier=Tier(tier_name),
                text=summary,
                content_hash=_content_hash({"tier": tier_name, "text": summary}),
                embedding_model_version="",
                pipeline_version="",
                embedding=_NO_EMBEDDING,
            )
        )


def _emit_blocks(
    block_decl: dict, fm: dict, body: str, parent_id: str, parent_props: dict,
    result: ExtractionResult, source: str,
) -> None:
    """Atomic ``### MARKER-`` body blocks -> nodes + edges + (optional) composed chunk.

    All declarative: ``block_id`` (composite ``{parent}/{title}`` or verbatim title),
    ``prop_fields`` (block fields -> props, with transforms), ``tag_prop`` (heading
    ``[TAG]`` -> a prop), ``inherit_fm`` (frontmatter keys copied into block props),
    ``parent_prop`` (parent id under a key), ``contains_edge`` (parent->block),
    ``edges`` (block field -> edge, with ref composition) and ``chunk_renderer``.
    """
    prefix = block_decl["marker"].replace("#", "").strip()
    base_self, base_spec = parent_id, str(fm.get("spec", "") or "")
    for heading, block_body in _iter_blocks(body):
        title = heading["title"]
        if not title.startswith(prefix):
            continue
        fields = _parse_block_fields(block_body)
        node_id = f"{parent_id}/{title}" if block_decl.get("block_id") == "composite" else title

        props: dict = {}
        for pf in block_decl.get("prop_fields", []):
            props[pf["field"]] = _field_transform(fields.get(pf["field"]), pf.get("as"))
        tag_prop = block_decl.get("tag_prop")
        if tag_prop:
            tag = heading.get("tag")
            props[tag_prop] = tag.split("|")[0].strip() if tag else None
        for k in block_decl.get("inherit_fm", []):
            props[k] = fm.get(k)
        parent_prop = block_decl.get("parent_prop")
        if parent_prop:
            props[parent_prop] = parent_id

        result.nodes.append(
            Node(
                id=node_id,
                kind=NodeKind(block_decl["produces_node"]),
                props=props,
                content_hash=_content_hash(props),
                source_path=source,
            )
        )
        contains_edge = block_decl.get("contains_edge")
        if contains_edge:
            result.edges.append(Edge(src_id=parent_id, dst_ref=node_id, kind=EdgeKind(contains_edge)))

        for fname, espec in (block_decl.get("edges") or {}).items():
            compose = espec.get("compose") or {}
            mode = compose.get("mode")
            base = base_self if compose.get("base") == "self" else base_spec
            for ref in _parse_inline_list(str(fields.get(fname, ""))):
                result.edges.append(
                    Edge(src_id=node_id, dst_ref=_compose_ref(ref, mode, base), kind=EdgeKind(espec["edge"]))
                )

        tier_name = block_decl.get("chunk_tier")
        renderer = _CHUNK_RENDERERS.get(block_decl.get("chunk_renderer", ""))
        if tier_name and renderer:
            text = renderer(parent_id, parent_props, fields)
            if text:
                result.chunks.append(
                    Chunk(
                        node_id=node_id,
                        tier=Tier(tier_name),
                        text=text,
                        content_hash=_content_hash({"tier": tier_name, "text": text}),
                        embedding_model_version="",
                        pipeline_version="",
                        embedding=_NO_EMBEDDING,
                    )
                )


def extract_generic(path: Path) -> ExtractionResult:
    """Extractor for spec types whose graph projection is DECLARED in the manifest.

    Fully manifest-driven, no per-type code. The declaration may carry, in emission
    order: secondary scalar nodes (``module`` -> Module), a top node (``produces_node``
    or ``produces_node_by_kind``) with props (all frontmatter, or an ordered
    ``node_props`` subset with transforms), a ``summary_field`` chunk, frontmatter
    ``ref`` edges (dir/groups-aware) and atomic body ``blocks`` (REQ / CONTRACT / DEC)
    each yielding node + edges + an optional composed chunk. Adding such a type is a
    manifest edit. Composed-chunk text and ref composition are the only procedural
    hooks (selected by name).
    """
    text = Path(path).read_text(encoding="utf-8")
    fm, body = parse_frontmatter(text)
    kind = str(fm.get("kind", ""))
    decl = GENERIC_SPECS.get(kind)
    if decl is None:
        raise ValueError(f"no generic spec_type declared for kind {kind!r}")

    node_id = str(fm.get("id", ""))
    source = str(Path(path))
    result = ExtractionResult()

    top_kind = _resolve_top_kind(decl, fm)
    props: dict = {}
    if top_kind is not None:
        props = _select_top_props(decl, fm)
        # Order matches the legacy extractors: secondary node + its edge, then the
        # top node, then its summary chunk, then frontmatter ref edges, then blocks.
        _emit_secondary_nodes(decl, fm, node_id, result, source)
        result.nodes.append(
            Node(id=node_id, kind=top_kind, props=props, content_hash=_content_hash(props), source_path=source)
        )
        _emit_summary_chunk(decl, props, node_id, result)
        _emit_frontmatter_edges(decl, fm, node_id, result)

    for block_decl in decl.get("blocks") or []:
        _emit_blocks(block_decl, fm, body, node_id, props, result, source)

    return result
