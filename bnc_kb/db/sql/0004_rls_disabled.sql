-- RLS-ready: policy scaffolding written now, intentionally NOT enabled in the POC.
-- Per-capability cloisonnement can be turned on later with no migration:
--   ALTER TABLE node ENABLE ROW LEVEL SECURITY;
--   ALTER TABLE node_chunk_embedding ENABLE ROW LEVEL SECURITY;

CREATE POLICY node_capability_scope ON node
    USING (true);  -- placeholder predicate; real predicate keys off a session GUC

CREATE POLICY chunk_capability_scope ON node_chunk_embedding
    USING (true);

-- NOTE: ENABLE ROW LEVEL SECURITY is deliberately omitted so policies are inert.
