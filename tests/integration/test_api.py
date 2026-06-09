import pytest
from fastapi.testclient import TestClient

from bnc_kb.api.app import create_app

pytestmark = pytest.mark.integration

READ = {"X-API-Key": "read-key"}
WRITE = {"X-API-Key": "write-key"}
ADMIN = {"X-API-Key": "admin-key"}


@pytest.fixture
def client(db):  # db fixture truncates tables first
    return TestClient(create_app())


def test_ingest_then_search_and_spec(client, sample_zip):
    r = client.post("/ingest", files={"file": ("cap.zip", sample_zip, "application/zip")}, headers=WRITE)
    assert r.status_code == 200, r.text
    summary = r.json()
    assert summary["nodes_created"] >= 1

    s = client.post("/search", json={"query": "overtime"}, headers=READ)
    assert s.status_code == 200
    body = s.json()
    assert "coverage" in body
    assert body["rows"], "search should return at least one hit"

    # exercise GET /spec/{id} on a returned node, with the coverage envelope
    node_id = body["rows"][0]["id"]
    sp = client.get(f"/spec/{node_id}", headers=READ)
    assert sp.status_code == 200, sp.text
    spec_body = sp.json()
    assert "coverage" in spec_body
    assert isinstance(spec_body["rows"], list)


def test_read_key_cannot_ingest(client, sample_zip):
    r = client.post("/ingest", files={"file": ("cap.zip", sample_zip, "application/zip")}, headers=READ)
    assert r.status_code == 403


def test_admin_add_dimension_governed(client):
    r = client.post(
        "/admin/dimensions", json={"code": "new-dim", "label": "New"}, headers=ADMIN
    )
    assert r.status_code == 201
    dup = client.post(
        "/admin/dimensions", json={"code": "new-dim", "label": "New"}, headers=ADMIN
    )
    assert dup.status_code == 409


def test_health_open(client):
    assert client.get("/admin/health").status_code == 200
