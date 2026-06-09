CREATE TABLE spec_dimension (
    code        text PRIMARY KEY,
    label       text NOT NULL,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE link_type (
    code        text PRIMARY KEY,
    label       text NOT NULL,
    description text,
    directed    boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TYPE node_kind AS ENUM (
    'capability', 'business_function', 'document', 'decision_record', 'risk'
);

CREATE TABLE node (
    id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    kind           node_kind NOT NULL,
    parent_id      uuid REFERENCES node(id),
    slug           text NOT NULL,
    dimension_code text REFERENCES spec_dimension(code),
    body           text,
    version        int,
    supersedes_id  uuid REFERENCES node(id),
    source_commit  text,
    status         text,
    effective      tstzrange,
    attrs          jsonb NOT NULL DEFAULT '{}',
    created_at     timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT container_vs_document CHECK (
        (kind IN ('capability','business_function')
            AND body IS NULL AND version IS NULL AND source_commit IS NULL)
        OR (kind IN ('document','decision_record','risk')
            AND body IS NOT NULL AND dimension_code IS NOT NULL)
    ),
    CONSTRAINT capability_is_root CHECK (kind <> 'capability' OR parent_id IS NULL)
);

CREATE INDEX idx_node_parent    ON node (parent_id);
CREATE INDEX idx_node_kind      ON node (kind);
CREATE INDEX idx_node_dimension ON node (dimension_code);

CREATE TABLE node_chunk_embedding (
    chunk_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    node_id   uuid NOT NULL REFERENCES node(id) ON DELETE CASCADE,
    ord       int NOT NULL,
    embedding vector(1024),
    UNIQUE (node_id, ord)
);

CREATE TABLE spec_link (
    id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    src_id     uuid NOT NULL REFERENCES node(id),
    dst_id     uuid REFERENCES node(id),
    dst_urn    text,
    rel        text NOT NULL REFERENCES link_type(code),
    attrs      jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT dst_internal_xor_external CHECK (
        (dst_id IS NOT NULL AND dst_urn IS NULL)
        OR (dst_id IS NULL AND dst_urn IS NOT NULL)
    ),
    CONSTRAINT no_self_loop CHECK (dst_id IS NULL OR dst_id <> src_id),
    -- NULLS NOT DISTINCT (PG15+): a NULL dst_id (external edge) or NULL dst_urn
    -- (internal edge) must not defeat dedup; without it duplicate edges slip past.
    CONSTRAINT uq_edge UNIQUE NULLS NOT DISTINCT (src_id, dst_id, dst_urn, rel)
);

CREATE INDEX idx_spec_link_src ON spec_link (src_id);
CREATE INDEX idx_spec_link_dst ON spec_link (dst_id);
CREATE INDEX idx_spec_link_rel ON spec_link (rel);

-- POC operational table: idempotency + audit of archive ingests.
CREATE TABLE ingestion (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    capability_slug text NOT NULL,
    source_commit   text NOT NULL,
    summary         jsonb NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (capability_slug, source_commit)
);
