"""Tests for the NVIDIA NIM judge client + local-Ollama fallback.

NIM is the primary output-quality judge; the local Ollama models must stay on
standby and be used whenever NIM is disabled, missing a key, or unreachable.
"""
import base64
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pipeline.nim_client import (
    NIMClient,
    _ENV_KEYS,
    nim_available,
    resolve_api_key,
)
from pipeline.config import NimConfig, PipelineConfig


def _nim_cfg(**kw):
    defaults = {
        "enabled": True,
        "base_url": "https://integrate.api.nvidia.com/v1",
        "model": "nvidia/llama-3.1-nemotron-nano-vl-8b-v1",
        "api_key": "",
        "timeout_seconds": 120,
    }
    defaults.update(kw)
    return NimConfig(**defaults)


def _disable_secret_file(monkeypatch):
    """Point _SECRET_FILE at a nonexistent path so env/config priority tests
    are isolated from any real key stored on this machine."""
    import pipeline.nim_client as nim
    monkeypatch.setattr(nim, "_SECRET_FILE", Path("/nonexistent/nvidia_key"))


def test_resolve_api_key_prefers_env(monkeypatch):
    _disable_secret_file(monkeypatch)
    monkeypatch.setenv("NVIDIA_API_KEY", "env-key")
    monkeypatch.delenv("NVIDIA_NIM_API_KEY", raising=False)
    assert resolve_api_key(_nim_cfg(api_key="cfg-key")) == "env-key"


def test_resolve_api_key_second_env(monkeypatch):
    _disable_secret_file(monkeypatch)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "env2-key")
    assert resolve_api_key(_nim_cfg()) == "env2-key"


def test_resolve_api_key_falls_back_to_config(monkeypatch):
    _disable_secret_file(monkeypatch)
    for v in _ENV_KEYS:
        monkeypatch.delenv(v, raising=False)
    assert resolve_api_key(_nim_cfg(api_key="cfg-key")) == "cfg-key"


def test_resolve_api_key_empty(monkeypatch):
    _disable_secret_file(monkeypatch)
    for v in _ENV_KEYS:
        monkeypatch.delenv(v, raising=False)
    assert resolve_api_key(_nim_cfg()) == ""


def test_resolve_api_key_reads_secret_file(tmp_path, monkeypatch):
    for v in _ENV_KEYS:
        monkeypatch.delenv(v, raising=False)
    import pipeline.nim_client as nim
    secret = tmp_path / "nvidia_key"
    secret.write_text("file-key")
    monkeypatch.setattr(nim, "_SECRET_FILE", secret)
    assert resolve_api_key(_nim_cfg()) == "file-key"


def test_nim_available_requires_key(monkeypatch):
    _disable_secret_file(monkeypatch)
    for v in _ENV_KEYS:
        monkeypatch.delenv(v, raising=False)
    assert not nim_available(_nim_cfg(enabled=True))
    assert not nim_available(_nim_cfg(enabled=False, api_key="k"))
    assert nim_available(_nim_cfg(enabled=True, api_key="k"))


def test_judge_vision_success(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    img = tmp_path / "f.png"
    img.write_bytes(b"\x89PNG")
    client = NIMClient(_nim_cfg())

    def fake_post(url, json=None, headers=None, timeout=None):
        assert url.endswith("/chat/completions")
        assert headers["Authorization"] == "Bearer test-key"
        # vision content: text + image_url data URI carrying the png bytes
        content = json["messages"][1]["content"]
        assert content[1]["type"] == "image_url"
        uri = content[1]["image_url"]["url"]
        assert "data:image/png;base64," in uri
        embedded = base64.b64decode(uri.split(",", 1)[1])
        assert embedded == b"\x89PNG"
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "choices": [{"message": {"content": '{"ok": 1}'}}]
        }
        return resp

    client.session.post = fake_post
    assert client.judge_vision("check", [img]) == '{"ok": 1}'


def test_judge_vision_disabled_returns_none(monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    client = NIMClient(_nim_cfg(enabled=False))
    assert client.judge_vision("check", [b"x"]) is None


def test_judge_vision_transport_error_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    img = tmp_path / "f.png"
    img.write_bytes(b"\x89PNG")
    client = NIMClient(_nim_cfg())

    import requests
    def boom(*a, **k):
        raise requests.RequestException("network down")
    client.session.post = boom
    assert client.judge_vision("check", [img]) is None


# --------------------------------------------------------------------------
# stage3b.vision_judge NIM-first / local-fallback
# --------------------------------------------------------------------------
def test_stage3b_vision_judge_uses_nim_when_available(tmp_path, monkeypatch):
    from pipeline.stage3b_images import vision_judge
    cfg = PipelineConfig()
    cfg.nim = _nim_cfg(api_key="k")  # enabled + key => NIM available
    monkeypatch.setenv("NVIDIA_API_KEY", "k")

    panel = tmp_path / "p.png"
    panel.write_bytes(b"\x89PNG")
    shot = {"id": "sh-1", "characters_in_frame": ["rin"], "composition": "medium shot"}
    scene = {"location": "loc-cafe", "time_of_day": "morning"}

    # NIM returns valid JSON matching exactly 1 expected character
    monkeypatch.setattr(
        "pipeline.stage3b_images._try_nim_judge",
        lambda c, p, pp: json.dumps({"characters_visible": 1, "background_matches": True, "composition_matches": True}),
    )
    passed, detail = vision_judge(panel, shot, scene, cfg)
    assert passed is True
    assert detail["judge"] == "nim"


def test_stage3b_vision_judge_falls_back_to_local(tmp_path, monkeypatch):
    from pipeline.stage3b_images import vision_judge, _OLLAMA_URL
    import pipeline.stage3b_images as m
    cfg = PipelineConfig()
    cfg.nim = _nim_cfg(enabled=False)  # NIM disabled => local only
    cfg.models.llm_vision = "qwen2.5vl:7b"

    panel = tmp_path / "p.png"
    panel.write_bytes(b"\x89PNG")
    shot = {"id": "sh-1", "characters_in_frame": ["rin"], "composition": "medium shot"}
    scene = {"location": "loc-cafe", "time_of_day": "morning"}

    captured = {}
    class FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return {"message": {"content": json.dumps(
                {"characters_visible": 1, "background_matches": True, "composition_matches": True})}}
    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        captured["model"] = json["model"]
        return FakeResp()
    monkeypatch.setattr("pipeline.stage3b_images.requests.post", fake_post)

    passed, detail = vision_judge(panel, shot, scene, cfg)
    assert passed is True
    assert detail["judge"] == "local"
    assert captured["model"] == "qwen2.5vl:7b"


# --------------------------------------------------------------------------
# stage_vlm_review._call_ollama NIM-first / local-fallback
# --------------------------------------------------------------------------
def test_vlm_review_uses_nim_when_available(monkeypatch):
    from pipeline.stage_vlm_review import _call_ollama
    cfg = _nim_cfg(api_key="k")
    monkeypatch.setenv("NVIDIA_API_KEY", "k")

    calls = {"nim": 0}
    def fake_judge(prompt, imgs, system="", temperature=0.0, max_tokens=0):
        calls["nim"] += 1
        return "NIM REVIEW: PASS visual quality 8.0"
    monkeypatch.setattr(
        "pipeline.stage_vlm_review.NIMClient",
        lambda c: MagicMock(available=lambda: True, judge_vision=fake_judge),
    )
    raw = _call_ollama("review", ["aGVsbG8="], nim_cfg=cfg)
    assert raw.startswith("NIM REVIEW")
    assert calls["nim"] == 1


def test_vlm_review_falls_back_to_local_when_nim_none(monkeypatch):
    from pipeline.stage_vlm_review import _call_ollama, _OLLAMA_ENDPOINT
    import pipeline.stage_vlm_review as m
    cfg = _nim_cfg(api_key="k")
    monkeypatch.setenv("NVIDIA_API_KEY", "k")

    # NIM available but returns None => local fallback used
    monkeypatch.setattr(
        "pipeline.stage_vlm_review.NIMClient",
        lambda c: MagicMock(available=lambda: True, judge_vision=lambda *a, **k: None),
    )
    captured = {}
    class FakeResp:
        def raise_for_status(self):
            return None
        def json(self):
            return {"message": {"content": "LOCAL: PASS 8.0"}}
    def fake_post(url, json=None, timeout=None):
        captured["url"] = url
        return FakeResp()
    monkeypatch.setattr("pipeline.stage_vlm_review.requests.post", fake_post)

    raw = _call_ollama("review", ["aGVsbG8="], nim_cfg=cfg)
    assert raw.startswith("LOCAL")
    assert captured["url"] == _OLLAMA_ENDPOINT
