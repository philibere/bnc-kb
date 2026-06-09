-- Enforce the natural keys that ingestion's SELECT-then-INSERT upserts assume.
-- Without these, a duplicate capability/business_function could be created
-- silently (e.g. under concurrent ingests); with them the second insert fails
-- loudly instead of corrupting the tree.

CREATE UNIQUE INDEX uq_capability_slug
    ON node (slug)
    WHERE kind = 'capability';

CREATE UNIQUE INDEX uq_business_function_parent_slug
    ON node (parent_id, slug)
    WHERE kind = 'business_function';
