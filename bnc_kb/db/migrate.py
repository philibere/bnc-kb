from __future__ import annotations

from pathlib import Path

import psycopg

SQL_DIR = Path(__file__).parent / "sql"


def apply_migrations(database_url: str) -> list[str]:
    """Apply unapplied .sql files in lexical order. Idempotent."""
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                filename   text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        done = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
        for path in sorted(SQL_DIR.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text())
            conn.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,)
            )
            applied.append(path.name)
    return applied
