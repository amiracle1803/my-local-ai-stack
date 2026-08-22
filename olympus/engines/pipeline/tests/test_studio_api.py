"""Kernel /api/pipeline bridge (kernel/app.py) via FastAPI TestClient.

The bridge lives in ``olympus/kernel/app.py`` and operates against a hardcoded
projects root (``PIPELINE_ENGINE / "projects"``). Every test points that root
at an isolated ``tmp_path`` by monkeypatching ``kernel.app.PIPELINE_ENGINE`` so
nothing touches the real ``olympus/engines/pipeline/projects/`` tree. No stage
run hits Ollama/ComfyUI: the concurrency/recovery tests monkeypatch
``run.run_stage`` directly.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import run

OLYMPUS_DIR = Path(__file__).resolve().parents[3]
import sys  # noqa: E402

if str(OLYMPUS_DIR) not in sys.path:
    sys.path.insert(0, str(OLYMPUS_DIR))

import kernel.app as ka  # noqa: E402

BRIEF = """---
word_target: 300
---
A short creative brief about a hero setting out on a journey.
"""


@pytest.fixture(autouse=True)
def _isolated_projects_root(tmp_path, monkeypatch):
    monkeypatch.setattr(ka, "PIPELINE_ENGINE", tmp_path / "engine")
    yield tmp_path / "engine" / "projects"


def _csrf_client(base: TestClient) -> TestClient:
    """Wrap TestClient to auto-send x-csrf-token header from the olympus_csrf cookie."""
    orig_post = base.post
    orig_put = base.put
    orig_patch = base.patch
    orig_delete = base.delete

    def _add_csrf(method):
        def wrapper(url, *args, **kwargs):
            headers = kwargs.get("headers", {})
            cookie = base.cookies.get("olympus_csrf", "")
            if cookie:
                headers["x-csrf-token"] = cookie
            kwargs["headers"] = headers
            return method(url, *args, **kwargs)
        return wrapper

    base.post = _add_csrf(orig_post)
    base.put = _add_csrf(orig_put)
    base.patch = _add_csrf(orig_patch)
    base.delete = _add_csrf(orig_delete)
    return base


@pytest.fixture
def client():
    c = TestClient(ka.app)
    c.get("/")  # prime CSRF cookie
    return _csrf_client(c)


def _wait_until_not_running(slug: str, stage: str, timeout: float = 5.0) -> None:
    deadline = time.time() + timeout
    key = (slug, stage)
    while time.time() < deadline:
        with ka._lock_map:
            t = ka._locks.get(key)
        if t is None or not t.is_alive():
            return
        time.sleep(0.05)
    raise AssertionError(f"{slug}/{stage} still running after {timeout}s")


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
    assert body["story_id"]

    proj_dir = _isolated_projects_root / "studiodemo"
    assert (proj_dir / "blueprint.json").exists()
    assert (proj_dir / "scores.sqlite").exists()
    # the kernel seeds the source script with the brief text
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


def test_status_fresh_project_all_pending(client):
    client.post(
        "/api/pipeline/projects", json={"slug": "statustest", "brief_text": BRIEF, "fps": 24}
    )
    r = client.get("/api/pipeline/statustest/status")
    assert r.status_code == 200
    body = r.json()
    # a freshly created project has no stage ledger -> every stage pending
    for stage, info in body["stages"].items():
        assert info["status"] == "pending", stage


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

    monkeypatch.setattr(run, "run_stage", fake_run_stage)

    r1 = client.post("/api/pipeline/runtest/run/stage0")
    assert r1.status_code == 200
    assert r1.json() == {"slug": "runtest", "stage": "stage0", "status": "running"}

    assert entered.wait(timeout=10)

    r2 = client.post("/api/pipeline/runtest/run/stage0")
    assert r2.status_code == 409

    release.set()
    _wait_until_not_running("runtest", "stage0")

    r3 = client.post("/api/pipeline/runtest/run/stage0")
    assert r3.status_code == 200
    release.set()
    _wait_until_not_running("runtest", "stage0")


def test_run_lock_recovers_after_stage_failure(client, monkeypatch):
    client.post(
        "/api/pipeline/projects", json={"slug": "failtest", "brief_text": BRIEF, "fps": 24}
    )
    entered = threading.Event()

    def boom(slug, stage, *, projects_dir=None, **kwargs):
        entered.set()
        raise RuntimeError("kaboom")

    monkeypatch.setattr(run, "run_stage", boom)
    r = client.post("/api/pipeline/failtest/run/stage0")
    assert r.status_code == 200

    assert entered.wait(timeout=10)
    _wait_until_not_running("failtest", "stage0")

    # the kernel dedupes concurrent runs; after the worker exits the lock is
    # freed so a subsequent run is accepted again (no crash, no deadlock).
    r2 = client.post("/api/pipeline/failtest/run/stage0")
    assert r2.status_code == 200
    _wait_until_not_running("failtest", "stage0")


# --------------------------------------------------------------------------
# intake persistence + run-all + panels upload + stage log
# --------------------------------------------------------------------------
def test_create_project_0b_persists_brief_md(client, _isolated_projects_root):
    r = client.post(
        "/api/pipeline/projects",
        json={"slug": "briefproj", "brief_text": BRIEF, "fps": 24, "mode": "0b"},
    )
    assert r.status_code == 201, r.text
    brief_md = _isolated_projects_root / "briefproj" / "input" / "brief.md"
    assert brief_md.exists()
    assert "word_target: 300" in brief_md.read_text(encoding="utf-8")


def test_create_project_0a_persists_source(client, _isolated_projects_root):
    r = client.post(
        "/api/pipeline/projects",
        json={"slug": "sourceproj", "script_text": "A source story. " * 20, "fps": 24, "mode": "0a"},
    )
    assert r.status_code == 201, r.text
    src = _isolated_projects_root / "sourceproj" / "input" / "source.txt"
    assert src.exists()
    assert "A source story" in src.read_text(encoding="utf-8")


def test_run_all_starts_and_releases_lock(client, _isolated_projects_root, monkeypatch):
    client.post("/api/pipeline/projects", json={"slug": "alltest", "brief_text": BRIEF, "fps": 24})
    release = threading.Event()

    def fake_run_all(slug, *, projects_dir=None, run_critique=True, retry_on_critique=True,
                     brief_path=None, source_path=None, panel_upload=None, word_target=None):
        release.wait(timeout=5)
        return []

    monkeypatch.setattr(run, "run_all", fake_run_all)
    r = client.post("/api/pipeline/alltest/run-all")
    assert r.status_code == 200
    assert r.json()["status"] == "running"

    r2 = client.post("/api/pipeline/alltest/run-all")
    assert r2.status_code == 409  # dedupe while running

    release.set()
    _wait_until_not_running("alltest", "_all")
    r3 = client.post("/api/pipeline/alltest/run-all")
    assert r3.status_code == 200
    release.set()
    _wait_until_not_running("alltest", "_all")


def test_run_all_forwards_intake_inputs(client, _isolated_projects_root, monkeypatch):
    client.post("/api/pipeline/projects", json={"slug": "intaketest", "script_text": "seed", "fps": 24, "mode": "0a"})
    seen = {}

    def fake_run_all(slug, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(run, "run_all", fake_run_all)
    r = client.post(
        "/api/pipeline/intaketest/run-all",
        json={"source_text": "A source story. " * 10, "word_target": 600},
    )
    assert r.status_code == 200
    _wait_until_not_running("intaketest", "_all")
    # source_text was persisted to input/source.txt and its path forwarded.
    src = _isolated_projects_root / "intaketest" / "input" / "source.txt"
    assert src.exists()
    assert "A source story" in src.read_text(encoding="utf-8")
    assert seen.get("source_path") == src
    assert seen.get("word_target") == 600


def test_stage_log_endpoint(client, _isolated_projects_root):
    client.post("/api/pipeline/projects", json={"slug": "logproj", "brief_text": BRIEF, "fps": 24})
    proj = _isolated_projects_root / "logproj"
    (proj / "logs").mkdir(parents=True, exist_ok=True)
    (proj / "logs" / "stage1.error").write_text("boom", encoding="utf-8")
    r = client.get("/api/pipeline/logproj/log/stage1")
    assert r.status_code == 200
    body = r.json()
    assert body["exists"] is True
    assert "boom" in body["log"]


def test_stage_log_endpoint_empty(client, _isolated_projects_root):
    client.post("/api/pipeline/projects", json={"slug": "nolog", "brief_text": BRIEF, "fps": 24})
    r = client.get("/api/pipeline/nolog/log/stage3")
    assert r.status_code == 200
    assert r.json()["exists"] is False


def test_upload_panels_image(client, _isolated_projects_root):
    client.post("/api/pipeline/projects", json={"slug": "panelproj", "script_text": "seed", "fps": 24, "mode": "0i"})
    r = client.post(
        "/api/pipeline/panelproj/panels",
        files={"file": ("panel_1.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.json()["written"] == 1
    assert (_isolated_projects_root / "panelproj" / "input" / "panels" / "panel_1.png").exists()