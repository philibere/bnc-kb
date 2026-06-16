from __future__ import annotations

import io
import zipfile

import pytest
from _corpus import FEATURE2_MD, VALID_FILES
from fastapi.testclient import TestClient

from bnc_kb.api.app import create_app

pytestmark = pytest.mark.integration

READ = {"X-API-Key": "read-key"}
WRITE = {"X-API-Key": "write-key"}
ADMIN = {"X-API-Key": "admin-key"}


def _zip(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


@pytest.fixture
def client(db):  # db fixture truncates tables first
    return TestClient(create_app())


@pytest.fixture
def shaper_zip() -> bytes:
    return _zip(VALID_FILES)


def test_ingest_then_search_and_spec(client, shaper_zip):
    r = client.post(
        "/ingest", files={"file": ("corpus.zip", shaper_zip, "application/zip")}, headers=WRITE
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["status"] == "success"
    assert result["nodes"] >= 1
    assert result["chunks"] >= 1

    s = client.post("/search", json={"query": "gerer les joueurs"}, headers=READ)
    assert s.status_code == 200
    body = s.json()
    assert "coverage" in body
    assert body["rows"], "search should return at least one hit"

    node_id = body["rows"][0]["id"]
    sp = client.get(f"/spec/{node_id}", headers=READ)
    assert sp.status_code == 200, sp.text
    spec_body = sp.json()
    assert "coverage" in spec_body
    assert isinstance(spec_body["rows"], list)


def test_ingest_specs_partial_upsert(client, shaper_zip):
    # whole corpus first, then a partial merge of one new spec via /ingest/specs
    client.post(
        "/ingest", files={"file": ("corpus.zip", shaper_zip, "application/zip")}, headers=WRITE
    )
    r = client.post(
        "/ingest/specs",
        files=[("files", ("FEAT-T-009.md", FEATURE2_MD.encode(), "text/markdown"))],
        headers=WRITE,
    )
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["status"] == "success"
    assert result["delta"]["mode"] == "merge"

    # the new feature is present; the original corpus is untouched
    s = client.post("/search", json={"query": "equipes"}, headers=READ)
    assert s.status_code == 200
    assert s.json()["rows"]


def test_ingest_specs_requires_write_role(client):
    r = client.post(
        "/ingest/specs",
        files=[("files", ("FEAT-T-009.md", FEATURE2_MD.encode(), "text/markdown"))],
        headers=READ,
    )
    assert r.status_code == 403


def test_read_key_cannot_ingest(client, shaper_zip):
    r = client.post(
        "/ingest", files={"file": ("corpus.zip", shaper_zip, "application/zip")}, headers=READ
    )
    assert r.status_code == 403


def test_ingest_non_zip_returns_400(client):
    r = client.post(
        "/ingest",
        files={"file": ("notazip.bin", b"not a zip payload", "application/octet-stream")},
        headers=WRITE,
    )
    assert r.status_code == 400


def test_admin_add_dimension_governed(client):
    r = client.post("/admin/dimensions", json={"code": "new-dim", "label": "New"}, headers=ADMIN)
    assert r.status_code == 201
    dup = client.post("/admin/dimensions", json={"code": "new-dim", "label": "New"}, headers=ADMIN)
    assert dup.status_code == 409


def test_health_open(client):
    assert client.get("/admin/health").status_code == 200
