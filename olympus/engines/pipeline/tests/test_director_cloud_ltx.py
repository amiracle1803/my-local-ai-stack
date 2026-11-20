"""Director pass, cloud image fallback and LTX-Video 2B graph (no GPU / network)."""

import json
import sys
import urllib.error
from io import BytesIO
from pathlib import Path

import pytest

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline import cloud_images, director, ltx2b, ltx_director, stages  # noqa: E402


# ── director ────────────────────────────────────────────────────────────────

def _reqs():
    return [{"id": "sh-1"}, {"id": "sh-2"}]


def test_direct_writes_entries_and_is_resumable(tmp_path):
    calls = []

    def llm(messages):
        calls.append(messages)
        return json.dumps({"shots": [{"id": "sh-1", "t2i": 'Aya says "hello" on a bridge', "negative": "",
                                      "camera": "push-in", "motion": "scarf flutters", "strength": 3,
                                      "t2v": "Aya walks.", "seconds": 9}]})

    out = tmp_path / "director.json"
    fb = {"sh-2": {"t2i": "template prompt", "negative": "", "camera": "", "motion": "", "strength": 0.4, "t2v": ""}}
    d = director.direct(_reqs(), {"aya": "Aya (red scarf)"}, fb, out, llm=llm)
    assert d["sh-1"]["by"] == "custom"
    assert '"' not in d["sh-1"]["t2i"]                       # quoted speech removed from image prompt
    assert d["sh-1"]["strength"] == 1.0 and d["sh-1"]["seconds"] == 6.0   # clamped
    assert d["sh-1"]["negative"] == director.DEFAULT_NEGATIVE
    assert d["sh-2"]["by"] == "template" and d["sh-2"]["t2i"] == "template prompt"
    assert "Aya (red scarf)" in calls[0][1]["content"]
    assert "unobstructed" in calls[0][0]["content"]
    assert "Never drop identity details" in calls[0][0]["content"]
    director.direct(_reqs(), {}, fb, out, llm=llm)            # resume: nothing left to ask
    assert len(calls) == 1


def test_direct_skips_batch_when_every_llm_fails(tmp_path):
    def broken(messages):
        raise RuntimeError("down")

    out = tmp_path / "director.json"
    assert director.direct(_reqs(), {}, {}, out, llm=broken) == {}
    assert not out.exists() or json.loads(out.read_text()) == {}


def test_parse_tolerates_prose_and_garbage():
    assert director._parse('Sure! {"shots": [{"id": "a"}, {"x": 1}]} done') == [{"id": "a"}]
    assert director._parse("no json") == []
    assert director._parse("{broken") == []


def test_svd_motion_bucket_range():
    assert director.svd_motion_bucket(0) == 40
    assert director.svd_motion_bucket(1) == 180
    assert director.svd_motion_bucket(7) == 180


# ── stages helpers ──────────────────────────────────────────────────────────

def test_motion_prompt_prefers_director():
    m = stages.motion_prompt({"director": {"motion": "lanterns rise", "camera": "tilt up", "by": "groq"}})
    assert "lanterns rise" in m and "tilt up" in m
    m = stages.motion_prompt({"prompt": "Aya on a bridge", "director": {"motion": "x", "by": "template"}})
    assert m.startswith("cinematic anime motion") and "Aya on a bridge" in m


def test_render_with_cloud_fallback(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cloud_images, "generate", lambda *a, **k: seen.append(a) or "pollinations")
    monkeypatch.delenv("OLYMPUS_IMAGE_SOURCE", raising=False)
    assert stages.render_with_cloud_fallback(lambda: None, "p", "n", tmp_path / "a.png", 1) == "comfyui"
    assert not seen

    def boom():
        raise RuntimeError("comfy down")
    assert stages.render_with_cloud_fallback(boom, "p", "n", tmp_path / "a.png", 1) == "pollinations"
    monkeypatch.setattr(cloud_images, "generate", lambda *a, **k: "")
    with pytest.raises(RuntimeError):
        stages.render_with_cloud_fallback(boom, "p", "n", tmp_path / "a.png", 1)


# ── cloud images ────────────────────────────────────────────────────────────

def _png(w=1015, h=580) -> bytes:
    from PIL import Image
    import random
    im = Image.new("RGB", (w, h))
    im.putdata([(random.randrange(256), random.randrange(256), random.randrange(256)) for _ in range(w * h)])
    b = BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def test_flux_size_keeps_aspect_in_allowed_box():
    assert cloud_images.flux_size(1280, 720) == (1344, 768)
    w, h = cloud_images.flux_size(720, 1280)
    assert h == 1344 and 768 <= w <= 1344 and w % 64 == 0


def test_generate_falls_through_and_breaks_circuit(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_images, "_failures", {})
    hits = {"a": 0, "b": 0}

    def a(*_):
        hits["a"] += 1
        raise urllib.error.HTTPError("u", 429, "quota", {}, None)

    def b(*_):
        hits["b"] += 1
        return _png()

    monkeypatch.setattr(cloud_images, "PROVIDERS", {"a": a, "b": b})
    dest = tmp_path / "p.png"
    assert cloud_images.generate("x", dest, 1, providers=["a", "b"]) == "b"
    assert cloud_images.generate("x", dest, 2, providers=["a", "b"]) == "b"
    assert hits == {"a": 1, "b": 2}          # 429 opens the breaker after one try
    from PIL import Image
    assert Image.open(dest).size == (1280, 720)


def test_generate_rejects_non_images(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud_images, "_failures", {})
    monkeypatch.setattr(cloud_images, "PROVIDERS", {"a": lambda *_: b"<html>blocked</html>"})
    assert cloud_images.generate("x", tmp_path / "p.png", 1, providers=["a"]) == ""
    assert not (tmp_path / "p.png").exists()


def test_order_env(monkeypatch):
    monkeypatch.setenv("OLYMPUS_CLOUD_IMAGES", "0")
    assert cloud_images.order() == []
    monkeypatch.setenv("OLYMPUS_CLOUD_IMAGES", "pollinations, bogus")
    assert cloud_images.order() == ["pollinations"]


# ── LTX-Video 2B graph ──────────────────────────────────────────────────────

def test_ltx_frames_rule():
    for s in (2, 4, 6):
        assert (ltx2b.frames_for(s) - 1) % 8 == 0
    assert ltx2b.frames_for(4) == 97


def test_ltx_graph_i2v_and_t2v():
    i2v = ltx2b.graph("motion", 1, image="in.png", strength=0.8)
    kinds = {n["class_type"] for n in i2v.values()}
    assert {"LTXVImgToVideo", "LoadImage", "LTXVConditioning", "VHS_VideoCombine"} <= kinds
    assert i2v["6"]["inputs"]["strength"] == 0.8
    assert i2v["8"]["inputs"]["latent_image"] == ["6", 2]
    t2v = ltx2b.graph("a paragraph", 1)
    kinds = {n["class_type"] for n in t2v.values()}
    assert "EmptyLTXVLatentVideo" in kinds and "LoadImage" not in kinds
    assert t2v["7"]["inputs"]["positive"] == ["3", 0]
    assert t2v["3"]["inputs"]["text"].startswith(ltx2b.ANIME_STYLE)
    assert "occluded subject" in t2v["4"]["inputs"]["text"]


def test_ltx_director_graph_i2v_and_t2v():
    i2v = ltx_director._graph("panel.png", "motion", 7, "anime", 97, 768, 512)
    segments = json.loads(i2v["100"]["inputs"]["timeline_data"])["segments"]
    assert [s["type"] for s in segments] == ["image", "text"]
    assert segments[0]["imageFile"] == "panel.png"

    t2v = ltx_director._graph(None, "full chronological action", 7, "anime", 49, 768, 512)
    data = t2v["100"]["inputs"]
    segments = json.loads(data["timeline_data"])["segments"]
    assert segments == [{"start": 0, "length": 49, "type": "text",
                         "prompt": "full chronological action"}]
    assert data["local_prompts"] == "full chronological action"
    assert data["segment_lengths"] == "49" and data["duration_frames"] == 49


@pytest.mark.parametrize("mode", ["t2v", "i2v"])
def test_stage3c_routes_director_mode(tmp_path, monkeypatch, mode):
    panels = tmp_path / "panels"
    panels.mkdir()
    panel = panels / "shot.png"
    panel.write_bytes(b"panel")
    directed = {"t2v": "full chronological action", "motion": "scarf flutters",
                "camera": "push in", "seconds": 4, "by": "custom"}
    panel.with_suffix(".json").write_text(json.dumps({"director": directed}), encoding="utf-8")
    monkeypatch.setenv("OLYMPUS_REAL_COMFY", "1")
    monkeypatch.setenv("OLYMPUS_ANIM_ENGINE", "ltx_director")
    monkeypatch.setenv("OLYMPUS_LTX_MODE", mode)
    monkeypatch.setenv("OLYMPUS_MAX_CLIPS", "1")
    calls = {}

    def render(panel_path, destination, **kwargs):
        calls.update(panel_path=panel_path, **kwargs)
        destination.write_bytes(b"video")
        return destination

    monkeypatch.setattr(ltx_director, "render_director_clip", render)
    monkeypatch.setattr(stages, "validate_media", lambda path: Path(path).exists())
    monkeypatch.setattr(stages, "_mark_done", lambda *args: None)
    result = stages.run_animation(tmp_path, enabled=True)

    assert result["failed"] == 0 and result["mode"] == "ltx_director"
    if mode == "i2v":
        assert calls["panel_path"] == panel
    else:
        assert calls["panel_path"] is None
    assert calls["motion_prompt"] == (directed["t2v"] if mode == "t2v" else stages.motion_prompt({"director": directed}))
    assert calls["frames"] == 97


@pytest.mark.parametrize("mode", ["t2v", "i2v"])
def test_stage3c_routes_ltx2b_mode_and_resumes(tmp_path, monkeypatch, mode):
    panels = tmp_path / "panels"
    panels.mkdir()
    panel = panels / "shot.png"
    panel.write_bytes(b"panel")
    directed = {"t2v": "full chronological action", "motion": "scarf flutters",
                "camera": "push in", "seconds": 2, "by": "custom"}
    panel.with_suffix(".json").write_text(json.dumps({"director": directed}), encoding="utf-8")
    monkeypatch.setenv("OLYMPUS_REAL_COMFY", "1")
    monkeypatch.setenv("OLYMPUS_ANIM_ENGINE", "ltx2b")
    monkeypatch.setenv("OLYMPUS_LTX_MODE", mode)
    monkeypatch.setenv("OLYMPUS_MAX_CLIPS", "1")
    calls = []

    def render(prompt, destination, seed, **kwargs):
        calls.append({"prompt": prompt, "seed": seed, **kwargs})
        destination.write_bytes(b"video")
        return destination

    monkeypatch.setattr(ltx2b, "render_clip", render)
    monkeypatch.setattr(stages, "validate_media", lambda path: Path(path).exists())
    monkeypatch.setattr(stages, "_mark_done", lambda *args: None)
    result = stages.run_animation(tmp_path, enabled=True)

    assert result["failed"] == 0 and result["mode"] == "ltx2b"
    assert len(calls) == 1 and calls[0]["frames"] == 49
    assert calls[0]["panel"] == (None if mode == "t2v" else panel)
    expected = directed["t2v"] if mode == "t2v" else stages.motion_prompt({"director": directed})
    assert calls[0]["prompt"] == expected

    resumed = stages.run_animation(tmp_path, enabled=True)
    assert resumed["clips"] == 1 and len(calls) == 1


def test_klein_graph_chains_character_references():
    from pipeline.comfy_client import _graph
    plain = _graph("p", 1, "x")
    assert plain["18"]["inputs"]["positive"] == ["11", 0]
    g = _graph("p", 1, "x", refs=["aya.png", "toma.png", "mei.png", "fourth.png"])
    loads = [n["inputs"]["image"] for n in g.values() if n["class_type"] == "LoadImage"]
    assert loads == ["aya.png", "toma.png", "mei.png"]          # at most three characters
    node, hops = g["18"]["inputs"]["positive"], 0              # chained: ref3 <- ref2 <- ref1 <- text
    while node != ["11", 0]:
        assert g[node[0]]["class_type"] == "ReferenceLatent"
        node, hops = g[node[0]]["inputs"]["conditioning"], hops + 1
    assert hops == 3


def test_sheet_prompt_one_figure_and_animals_stay_animals():
    p, n = stages.sheet_prompt("anime key visual, Aya, 16-year-old girl, red scarf, clean lineart, cel shaded")
    assert "one single person" in p and "reference sheet" not in p and "turnaround" in n
    assert "anime key visual" not in p
    p, n = stages.sheet_prompt("anime key visual, Rin, small male fox spirit made of blue flame")
    assert "four legs" in p and "not a person" in p and "humanoid" in n
