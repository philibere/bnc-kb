import pytest
from fastapi import HTTPException

from bnc_kb.api.auth import require_role


def _call(dep, key):
    # FastAPI would inject the header; call the inner function directly.
    return dep(x_api_key=key)


def test_read_key_cannot_write():
    dep = require_role("write")
    with pytest.raises(HTTPException) as exc:
        _call(dep, "read-key")
    assert exc.value.status_code == 403


def test_write_key_can_write():
    dep = require_role("write")
    assert _call(dep, "write-key") == "write"


def test_admin_can_do_anything():
    assert _call(require_role("read"), "admin-key") == "admin"


def test_unknown_key_401():
    with pytest.raises(HTTPException) as exc:
        _call(require_role("read"), "nope")
    assert exc.value.status_code == 401
