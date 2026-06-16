"""Incremental reconciliation: diff a fresh ``IngestionResult`` against the stored
state and apply ONLY the delta (insert / update / delete), so a persisted store
tracks a *living* SDLC instead of being rebuilt from scratch each run.

The expensive operation is embedding. The win here is the chunk composite key
``(node_id, tier, content_hash, model_version, pipeline_version)``: a chunk whose
key already exists in the store is left untouched (NO re-embedding); only chunks
with a new key are embedded and inserted, and chunks whose key vanished are
deleted. Nodes reconcile by ``content_hash`` (added / updated / deleted) and edges
by their identity tuple.

This module is PURE diff logic (no DB import). Each sink (SqliteSink, PostgresSink)
reads its ``StoreState``, calls ``diff``, and applies the resulting ``Delta`` with
its own SQL dialect. Same diff, two backends.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _v(x) -> str:
    """enum-or-str -> str (``NodeKind.Feature`` -> ``"Feature"``)."""
    return x.value if hasattr(x, "value") else x


def chunk_key(chunk) -> tuple:
    """The composite key that decides re-embedding (AC-05/AC-11)."""
    return (
        chunk.node_id,
        _v(chunk.tier),
        chunk.content_hash,
        chunk.embedding_model_version,
        chunk.pipeline_version,
    )


def edge_tuple(edge) -> tuple:
    """An edge's identity: (src, kind, dst_ref, dst_id, pending)."""
    return (
        edge.src_id,
        _v(edge.kind),
        edge.dst_ref,
        edge.dst_id,
        1 if edge.pending else 0,
    )


@dataclass
class StoreState:
    """The store's current content, read before reconciling."""

    node_hashes: dict = field(default_factory=dict)   # id -> content_hash
    edge_tuples: set = field(default_factory=set)      # {edge_tuple}
    chunk_keys: set = field(default_factory=set)       # {chunk_key}


@dataclass
class Delta:
    """What reconcile must apply to move the store to the desired state."""

    node_added: list = field(default_factory=list)      # node objects (new id)
    node_updated: list = field(default_factory=list)    # node objects (changed content_hash)
    node_deleted: list = field(default_factory=list)    # node ids gone from corpus
    edge_inserts: list = field(default_factory=list)    # edge objects to add
    edge_deletes: list = field(default_factory=list)    # edge tuples to remove
    chunk_inserts: list = field(default_factory=list)   # chunk objects with new key (embedded)
    chunk_delete_keys: list = field(default_factory=list)  # composite keys to remove
    chunks_unchanged: int = 0                            # keys present in both (no re-embed)

    @property
    def node_upserts(self) -> list:
        return self.node_added + self.node_updated

    def report(self) -> dict:
        """Human/machine delta summary, merged into the build report."""
        return {
            "mode": "incremental",
            "nodes": {
                "added": len(self.node_added),
                "updated": len(self.node_updated),
                "deleted": len(self.node_deleted),
            },
            "edges": {
                "added": len(self.edge_inserts),
                "deleted": len(self.edge_deletes),
            },
            "chunks": {
                # inserted == re-embedded (only new keys carry a fresh vector)
                "embedded": len(self.chunk_inserts),
                "deleted": len(self.chunk_delete_keys),
                "unchanged": self.chunks_unchanged,
            },
        }


def diff(state: StoreState, result) -> Delta:
    """Compute the delta from ``state`` (current store) to ``result`` (desired)."""
    desired_nodes = {n.id: n for n in result.nodes}
    node_added, node_updated = [], []
    for n in result.nodes:
        if n.id not in state.node_hashes:
            node_added.append(n)
        elif state.node_hashes[n.id] != n.content_hash:
            node_updated.append(n)
    node_deleted = [nid for nid in state.node_hashes if nid not in desired_nodes]

    desired_edges = {edge_tuple(e): e for e in result.edges}
    edge_inserts = [e for t, e in desired_edges.items() if t not in state.edge_tuples]
    edge_deletes = [t for t in state.edge_tuples if t not in desired_edges]

    desired_chunks = {chunk_key(c): c for c in result.chunks}
    chunk_inserts = [c for k, c in desired_chunks.items() if k not in state.chunk_keys]
    chunk_delete_keys = [k for k in state.chunk_keys if k not in desired_chunks]
    chunks_unchanged = len(set(desired_chunks) & state.chunk_keys)

    return Delta(
        node_added=node_added,
        node_updated=node_updated,
        node_deleted=node_deleted,
        edge_inserts=edge_inserts,
        edge_deletes=edge_deletes,
        chunk_inserts=chunk_inserts,
        chunk_delete_keys=chunk_delete_keys,
        chunks_unchanged=chunks_unchanged,
    )
