"""M2 metamodel manifest loader.

The engine's CLOSED VOCABULARY (node/edge/tier kinds), per-artifact-type
frontmatter allow-lists and the glossary-kind -> node-kind map now live in the
manifest, not hardcoded in ``model``/``parsing``/``extraction``.

Canonical manifest: ``bnc-shaper/metamodel/bnc.metamodel.yaml``. Resolution
order: env ``BNC_METAMODEL``, then a vendored ``<repo>/metamodel/...`` copy, then
the sibling ``../bnc-shaper`` checkout (dev convenience). Production should set
``BNC_METAMODEL`` or vendor the file (sync in CI).

Vendored into bnc-kb: this package lives at ``<bnc-kb>/spec_ingestion`` and the
manifest is vendored at ``<bnc-kb>/metamodel/bnc.metamodel.yaml`` (one level up).
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

_HERE = Path(__file__).resolve().parent  # .../<bnc-kb>/spec_ingestion
_REPO = _HERE.parent                      # repo root (<bnc-kb>)
_VENDORED = _REPO / "metamodel" / "bnc.metamodel.yaml"
_SIBLING = _REPO.parent / "bnc-shaper" / "metamodel" / "bnc.metamodel.yaml"


def _resolve_path() -> Path:
    env = os.environ.get("BNC_METAMODEL")
    if env:
        return Path(env)
    if _VENDORED.exists():
        return _VENDORED
    return _SIBLING


MANIFEST_PATH = _resolve_path()


def _load() -> dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"metamodel manifest not found at {MANIFEST_PATH}. "
            "Set BNC_METAMODEL or vendor metamodel/bnc.metamodel.yaml."
        )
    with open(MANIFEST_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


_M = _load()

# Closed vocabularies (on-disk values, in manifest order).
NODE_KINDS: list[str] = [n["name"] for n in _M["node_kinds"]]
EDGE_KINDS: list[str] = [e["name"] for e in _M["edge_kinds"]]
TIERS: list[str] = [t["name"] for t in _M["chunk_tiers"]]


def _spec_type(name: str) -> dict:
    for st in _M.get("spec_types", []):
        if st.get("name") == name:
            return st
    return {}


def _frontmatter_keys(name: str) -> set[str]:
    return set((_spec_type(name).get("frontmatter") or {}).keys())


# Per-spec-type frontmatter allow-lists (keys projected into ``props``).
FEATURE_KEYS: set[str] = _frontmatter_keys("feature")
TECHNICAL_KEYS: set[str] = _frontmatter_keys("technical")
INVARIANT_KEYS: set[str] = _frontmatter_keys("invariant")
GLOSSARY_KEYS: set[str] = _frontmatter_keys("glossary")

# Glossary frontmatter ``kind`` -> node-kind name.
GLOSSARY_KIND_TO_NODE: dict[str, str] = {
    k: v["node"] for k, v in (_spec_type("glossary").get("produces_node_by_kind") or {}).items()
}


def _artifact_kind_tokens() -> list[str]:
    """Frontmatter ``kind`` tokens that classify, derived from the spec types.

    A glossary spec type expands to its ``produces_node_by_kind`` keys; every
    other spec type contributes its ``kind_value``.
    """
    tokens: list[str] = []
    for st in _M.get("spec_types", []):
        by_kind = st.get("produces_node_by_kind")
        if by_kind:
            tokens.extend(by_kind.keys())
        elif st.get("kind_value"):
            tokens.append(st["kind_value"])
    return tokens


ARTIFACT_KIND_TOKENS: list[str] = _artifact_kind_tokens()

# Declarative spec types handled by the generic extractor (manifest
# ``extractor: generic``), keyed by the frontmatter ``kind`` token the engine sees:
# ``kind_value`` for single-kind types, or each ``produces_node_by_kind`` key for a
# Vocab type (glossary => actor/entity/external-system/process all map to its decl).
# Each carries its structured declaration. Adding such a type is a manifest edit.
GENERIC_SPECS: dict[str, dict] = {}
for _st in _M.get("spec_types", []):
    if _st.get("extractor") != "generic":
        continue
    _by_kind = _st.get("produces_node_by_kind")
    if _by_kind:
        for _k in _by_kind:
            GENERIC_SPECS[_k] = _st
    elif _st.get("kind_value"):
        GENERIC_SPECS[_st["kind_value"]] = _st
