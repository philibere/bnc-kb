from __future__ import annotations

from typing import Callable

from fastapi import Header, HTTPException

from bnc_kb.config import load_settings

ROLE_READ, ROLE_WRITE, ROLE_ADMIN = "read", "write", "admin"
_RANK = {ROLE_READ: 1, ROLE_WRITE: 2, ROLE_ADMIN: 3}


def role_for_key(key: str) -> str | None:
    s = load_settings()
    table = {
        s.api_key_read: ROLE_READ,
        s.api_key_write: ROLE_WRITE,
        s.api_key_admin: ROLE_ADMIN,
    }
    return table.get(key)


def require_role(minimum: str) -> Callable[..., str]:
    """FastAPI dependency factory. Roles are hierarchical: admin > write > read."""

    def dep(x_api_key: str = Header(default="")) -> str:
        role = role_for_key(x_api_key)
        if role is None:
            raise HTTPException(status_code=401, detail="invalid api key")
        if _RANK[role] < _RANK[minimum]:
            raise HTTPException(status_code=403, detail="insufficient role")
        return role

    return dep
