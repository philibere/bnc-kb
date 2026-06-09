from __future__ import annotations

import re

from bnc_kb.models import IngestManifest, NodeSpec
from bnc_kb.parser.adoc import extract_adoc_attrs
from bnc_kb.parser.dimensions import dimension_for

ADR_RE = re.compile(r"ADR-\d+", re.IGNORECASE)
RISK_RE = re.compile(r"RISK-\d+", re.IGNORECASE)
BF_RE = re.compile(r"requirements/(business-fct-[^/]+)/")


def build_nodes(
    files: dict[str, str], manifest: IngestManifest
) -> tuple[list[NodeSpec], list[str]]:
    """Map a flat {path: content} archive into a parent-linked node list.

    Returns (nodes, unreached_paths). Nodes are ordered parents-before-children.
    """
    cap = NodeSpec(
        local_id="cap",
        kind="capability",
        slug=manifest.capability_slug,
        parent_local_id=None,
        attrs={"category": manifest.category, "domain": manifest.domain},
    )
    nodes: list[NodeSpec] = [cap]
    bf_nodes: dict[str, NodeSpec] = {}
    unreached: list[str] = []

    for path in sorted(files):
        base = path.rsplit("/", 1)[-1]
        if base == "kb-manifest.yaml":
            continue
        dim = dimension_for(path)
        if dim is None:
            unreached.append(path)
            continue

        parent_local = cap.local_id
        m = BF_RE.search(path)
        if m:
            bf_slug = m.group(1)
            if bf_slug not in bf_nodes:
                bf = NodeSpec(
                    local_id=f"bf:{bf_slug}",
                    kind="business_function",
                    slug=bf_slug,
                    parent_local_id=cap.local_id,
                )
                bf_nodes[bf_slug] = bf
                nodes.append(bf)
            parent_local = bf_nodes[bf_slug].local_id

        if ADR_RE.search(base):
            kind = "decision_record"
        elif RISK_RE.search(base):
            kind = "risk"
        else:
            kind = "document"

        body = files[path]
        attrs = extract_adoc_attrs(body) if base.endswith(".adoc") else {}
        nodes.append(
            NodeSpec(
                local_id=f"doc:{path}",
                kind=kind,
                slug=base.rsplit(".", 1)[0],
                parent_local_id=parent_local,
                dimension_code=dim,
                body=body,
                source_path=path,
                attrs=attrs,
            )
        )

    return nodes, unreached
