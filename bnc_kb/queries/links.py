from __future__ import annotations

from uuid import UUID

from psycopg import Connection
from psycopg.rows import dict_row

LINKS_SQL = """
SELECT l.rel, COALESCE(n.slug, l.dst_urn) AS target
FROM spec_link l
LEFT JOIN node n ON n.id = l.dst_id
WHERE l.src_id = %(src)s
  AND (%(rel)s::text IS NULL OR l.rel = %(rel)s)
ORDER BY l.rel, target
"""


def get_links(conn: Connection, src: UUID, rel: str | None) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(LINKS_SQL, {"src": src, "rel": rel})
        return cur.fetchall()
