"""Untrusted (non-loopback, non-tailnet) clients can't start pipeline work without the token."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
for p in (ROOT, ROOT / "olympus"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from fastapi.testclient import TestClient  # noqa: E402

from olympus.kernel import app as kernel  # noqa: E402


def _client(host):
    return TestClient(kernel.app, client=(host, 50000))


def test_trusted_hosts():
    assert kernel._trusted_client("127.0.0.1") and kernel._trusted_client("::1")
    assert kernel._trusted_client("100.103.246.96")  # tailnet
    assert not kernel._trusted_client("192.168.1.50") and not kernel._trusted_client("testclient")


def test_lan_write_refused_without_token(monkeypatch):
    monkeypatch.setenv("STUDIO_TOKEN", "t0k")
    r = _client("192.168.1.50").post("/api/pipeline/quick-test", json={})
    assert r.status_code == 401


def test_lan_write_with_token_passes_the_gate(monkeypatch):
    monkeypatch.setenv("STUDIO_TOKEN", "t0k")
    r = _client("192.168.1.50").post("/api/pipeline/nope/stop", headers={"Authorization": "Bearer t0k"})
    assert r.status_code != 401


def test_lan_reads_and_local_writes_unchanged(monkeypatch):
    monkeypatch.setenv("STUDIO_TOKEN", "t0k")
    assert _client("192.168.1.50").get("/api/pipeline/projects").status_code == 200
    assert _client("127.0.0.1").post("/api/pipeline/nope/stop").status_code != 401
