from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    api_key_read: str
    api_key_write: str
    api_key_admin: str
    embedding_dim: int = 1024
    chunk_size_words: int = 200
    chunk_overlap_words: int = 40


def load_settings() -> Settings:
    return Settings(
        database_url=os.environ.get(
            "DATABASE_URL", "postgresql://kb:kb@localhost:5433/kb"
        ),
        api_key_read=os.environ.get("API_KEY_READ", "read-key"),
        api_key_write=os.environ.get("API_KEY_WRITE", "write-key"),
        api_key_admin=os.environ.get("API_KEY_ADMIN", "admin-key"),
    )
