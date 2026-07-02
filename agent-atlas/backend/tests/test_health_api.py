"""Integration test: FastAPI /health endpoint."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import app
    return TestClient(app)


def test_health_returns_ok(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "models_loaded" in data
    assert "agents_loaded" in data


def test_jobs_list_empty(client):
    resp = client.get("/api/jobs/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_create_and_get_job(client):
    resp = client.post("/api/jobs/", json={"type": "test_job", "payload": {"x": 1}})
    assert resp.status_code == 201
    job_id = resp.json()["id"]

    resp2 = client.get(f"/api/jobs/{job_id}")
    assert resp2.status_code == 200
    assert resp2.json()["type"] == "test_job"


def test_job_stop(client):
    resp = client.post("/api/jobs/", json={"type": "stoppable"})
    job_id = resp.json()["id"]
    stop = client.post(f"/api/jobs/{job_id}/stop")
    assert stop.status_code == 200
    assert stop.json()["status"] == "stopped"


def test_agents_list(client):
    resp = client.get("/api/agents/")
    assert resp.status_code == 200
    agents = resp.json()
    assert isinstance(agents, list)
    ids = [a["id"] for a in agents]
    assert "orchestrator" in ids


def test_llm_models(client):
    resp = client.get("/api/llm/models")
    assert resp.status_code == 200
    models = resp.json()
    assert any(m["name"] == "hermes_local" for m in models)
