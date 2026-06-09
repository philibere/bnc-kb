from __future__ import annotations

from psycopg_pool import ConnectionPool

from bnc_kb.config import load_settings

_pool: ConnectionPool | None = None


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(load_settings().database_url, open=True)
    return _pool
