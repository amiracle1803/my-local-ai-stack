"""Kernel /api/pipeline endpoints (pipeline_api.py) via FastAPI TestClient.

Puts ``olympus/`` on sys.path so ``kernel.app`` imports as a package (mirrors
how uvicorn runs it, cwd=olympus/). Every project-creating test points the
router at an isolated tmp_path projects root via
``pipeline_api.set_projects_root`` so nothing touches the real
``olympus/engines/pipeline/projects/`` tree. No test hits Ollama: stage runs
either exercise the pure 404/409/not_built mechanics, or monkeypatch
``pipeline_api.pipeline_run.run_stage`` directly.
"""

from __future__ import annotations

import sys
import time
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

OLYMPUS_DIR = Path(__file__).resolve().parents[3]
if str(OLYMPUS_DIR) not in sys.path:
    sys.path.insert(0, str(OLYMPUS_DIR))

from kernel.app import app  # noqa: E402
from kernel import pipeline_api  # noqa: E402

BRIEF = """---
word_target: 300
---
A short creative brief about a hero setting out on a journey.
"""


@pytest.fixture(autouse=True)
def _isolated_projects_root(tmp_path):
    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    pipeline_api.set_projects_root(projects_root)
    pipeline_api.reset_runtime_state()
    yield projects_root
    pipeline_api.set_projects_root(None)
    pipeline_api.reset_runtime_state()


@pytest.fixture
def client():
    return TestClient(app)


def _wait_until_not_running(slug: str, stage: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    key = (slug, stage)
    while time.time() < deadline:
        with pipeline_api._lock:
            t = pipeline_api._running.get(key)
        if t is None or not t.is_alive():
            return
        time.sleep(0.05)


# --------------------------------------------------------------------------
# no regression on unrelated endpoints
# --------------------------------------------------------------------------
def test_health_no_regression(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_index_still_serves(client):
    r = client.get("/")
    assert r.status_code == 200


# --------------------------------------------------------------------------
# POST /projects
# --------------------------------------------------------------------------
def test_create_project_brief_mode(client, _isolated_projects_root):
    r = client.post(
        "/api/pipeline/projects",
        json={"slug": "studiodemo", "brief_text": BRIEF, "fps": 30},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["slug"] == "studiodemo"
    assert body["fps"] == 30
    assert body["stages"]["stage0"] == "pending"

    proj_dir = _isolated_projects_root / "studiodemo"
    assert (proj_dir / "blueprint.json").exists()
    assert (proj_dir / "scores.sqlite").exists()
    assert (proj_dir / "input" / "brief.md").read_text(encoding="utf-8") == BRIEF
    assert (proj_dir / "input" / "script.txt").read_text(encoding="utf-8") == BRIEF


def test_create_project_script_mode(client, _isolated_projects_root):
    script = "Rin walked into the academy at dawn. " * 30
    r = client.post(
        "/api/pipeline/projects",
        json={"slug": "scripttest", "script_text": script, "fps": 24},
    )
    assert r.status_code == 201, r.text
    proj_dir = _isolated_projects_root / "scripttest"
    assert (proj_dir / "input" / "script.txt").read_text(encoding="utf-8") == script
    assert not (proj_dir / "input" / "brief.md").exists()


def test_create_project_duplicate_409(client):
    client.post("/api/pipeline/projects", json={"slug": "dup", "brief_text": BRIEF, "fps": 24})
    r = client.post("/api/pipeline/projects", json={"slug": "dup", "brief_text": BRIEF, "fps": 24})
    assert r.status_code == 409


def test_create_project_requires_exactly_one_source(client):
    r = client.post("/api/pipeline/projects", json={"slug": "bad", "fps": 24})
    assert r.status_code == 422

    r2 = client.post(
        "/api/pipeline/projects",
        json={"slug": "bad2", "brief_text": BRIEF, "script_text": "x" * 200, "fps": 24},
    )
    assert r2.status_code == 422


def test_fps_snapped(client):
    r = client.post(
        "/api/pipeline/projects", json={"slug": "fpstest", "brief_text": BRIEF, "fps": 45}
    )
    assert r.status_code == 201
    assert r.json()["fps"] == 30  # 45 is equidistant from 30/60; ties -> lower


# --------------------------------------------------------------------------
# GET /projects
# --------------------------------------------------------------------------
def test_list_projects(client):
    client.post("/api/pipeline/projects", json={"slug": "listme", "brief_text": BRIEF, "fps": 24})
    r = client.get("/api/pipeline/projects")
    assert r.status_code == 200
    slugs = [p["slug"] for p in r.json()]
    assert "listme" in slugs


def test_list_projects_empty_root(client):
    r = client.get("/api/pipeline/projects")
    assert r.status_code == 200
    assert r.json() == []


# --------------------------------------------------------------------------
# GET /{slug}/status
# --------------------------------------------------------------------------
def test_status_unknown_project_404(client):
    r = client.get("/api/pipeline/nope/status")
    assert r.status_code == 404


def test_status_not_built_for_stage1(client):
    client.post(
        "/api/pipeline/projects", json={"slug": "statustest", "brief_text": BRIEF, "fps": 24}
    )
    r = client.get("/api/pipeline/statustest/status")
    assert r.status_code == 200
    body = r.json()
    assert body["stages"]["stage0"]["status"] == "pending"
    assert body["stages"]["stage1"]["status"] == "not_built"
    assert body["stages"]["stage5"]["status"] == "not_built"
    assert "stages" in body["scores"]
    assert body["flags"] == []


# --------------------------------------------------------------------------
# POST /{slug}/run/{stage}
# --------------------------------------------------------------------------
def test_run_unknown_project_404(client):
    r = client.post("/api/pipeline/nope/run/stage0")
    assert r.status_code == 404


def test_run_unknown_stage_404(client):
    client.post(
        "/api/pipeline/projects", json={"slug": "stagetest", "brief_text": BRIEF, "fps": 24}
    )
    r = client.post("/api/pipeline/stagetest/run/stageX")
    assert r.status_code == 404


def test_run_started_then_409_while_running_then_recovers(client, monkeypatch):
    client.post(
        "/api/pipeline/projects", json={"slug": "runtest", "brief_text": BRIEF, "fps": 24}
    )

    release = threading.Event()
    entered = threading.Event()

    def fake_run_stage(slug, stage, *, projects_dir=None, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return {"stage": stage, "status": "done"}

    monkeypatch.setattr(pipeline_api.pipeline_run, "run_stage", fake_run_stage)

    r1 = client.post("/api/pipeline/runtest/run/stage0")
    assert r1.status_code == 200
    assert r1.json() == {"started": True}

    assert entered.wait(timeout=5)

    r2 = client.post("/api/pipeline/runtest/run/stage0")
    assert r2.status_code == 409

    status_body = client.get("/api/pipeline/runtest/status").json()
    assert status_body["stages"]["stage0"]["status"] == "running"

    release.set()
    _wait_until_not_running("runtest", "stage0")

    r3 = client.post("/api/pipeline/runtest/run/stage0")
    assert r3.status_code == 200
    assert r3.json() == {"started": True}
    release.set()
    _wait_until_not_running("runtest", "stage0")


def test_run_records_failed_status(client, monkeypatch):
    client.post(
        "/api/pipeline/projects", json={"slug": "failtest", "brief_text": BRIEF, "fps": 24}
    )

    def boom(slug, stage, *, projects_dir=None, **kwargs):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(pipeline_api.pipeline_run, "run_stage", boom)
    r = client.post("/api/pipeline/failtest/run/stage0")
    assert r.status_code == 200

    _wait_until_not_running("failtest", "stage0")
    body = client.get("/api/pipeline/failtest/status").json()
    st = body["stages"]["stage0"]
    assert st["status"] == "failed"
    assert "kaboom" in st["error"]


def test_run_notimplemented_records_not_built(client, monkeypatch):
    client.post(
        "/api/pipeline/projects", json={"slug": "nbtest", "brief_text": BRIEF, "fps": 24}
    )

    def stub(slug, stage, *, projects_dir=None, **kwargs):
        raise NotImplementedError(f"{stage} built in M1+")

    monkeypatch.setattr(pipeline_api.pipeline_run, "run_stage", stub)
    r = client.post("/api/pipeline/nbtest/run/stage0")
    assert r.status_code == 200

    _wait_until_not_running("nbtest", "stage0")
    body = client.get("/api/pipeline/nbtest/status").json()
    assert body["stages"]["stage0"]["status"] == "not_built"
