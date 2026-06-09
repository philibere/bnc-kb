from __future__ import annotations

from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row

GET_SPEC_SQL = """
WITH RECURSIVE subtree AS (
    SELECT id, parent_id, kind, dimension_code, body, status, version, slug
    FROM node WHERE id = %(head)s
    UNION ALL
    SELECT n.id, n.parent_id, n.kind, n.dimension_code, n.body, n.status, n.version, n.slug
    FROM node n JOIN subtree s ON n.parent_id = s.id
)
SELECT id, kind, slug, dimension_code, body, version, status
FROM subtree
WHERE body IS NOT NULL
  AND (%(dimension)s::text IS NULL OR dimension_code = %(dimension)s)
  AND status = COALESCE(%(status)s, 'approved')
ORDER BY dimension_code, slug, version DESC
"""


def get_spec(
    conn: Connection, head: UUID, dimension: str | None, status: str | None
) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(GET_SPEC_SQL, {"head": head, "dimension": dimension, "status": status})
        return cur.fetchall()
