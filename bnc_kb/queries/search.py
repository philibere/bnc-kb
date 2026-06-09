from __future__ import annotations

from psycopg import Connection
from psycopg.rows import dict_row

from bnc_kb.embeddings import Vector, to_vector_literal

SEARCH_SQL = """
SELECT n.id, n.kind, n.slug, n.dimension_code, n.status, n.version, n.body,
       1 - MIN(e.embedding <=> %(qvec)s::vector) AS score
FROM node_chunk_embedding e
JOIN node n ON n.id = e.node_id
WHERE n.body IS NOT NULL
  AND (%(dimension)s::text IS NULL OR n.dimension_code = %(dimension)s)
  AND n.status = %(status)s
GROUP BY n.id, n.kind, n.slug, n.dimension_code, n.status, n.version, n.body
ORDER BY score DESC
LIMIT %(k)s
"""


def search_specs(
    conn: Connection, qvec: Vector, dimension: str | None, status: str, k: int
) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            SEARCH_SQL,
            {
                "qvec": to_vector_literal(qvec),
                "dimension": dimension,
                "status": status,
                "k": k,
            },
        )
        return cur.fetchall()
