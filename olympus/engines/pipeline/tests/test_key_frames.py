"""Panels mode: long shots play as several key frames instead of an LTX clip (2026-11-20)."""

import json
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline import director, stages  # noqa: E402
from tests.test_episode_quality import _project, _wav  # noqa: E402


def test_frame_count_and_names():
    assert [stages.stills_for(s) for s in (2.5, 6.5, 8.4, 11.2, 15.2, 30.0)] == [1, 1, 2, 3, 4, 4]
    p = Path("x/ep_sc004_sh005_panel_v001.png")
    assert stages.frame_name(p, 2).name == "ep_sc004_sh005_panel_f2_v001.png"
    assert stages._is_extra_frame(stages.frame_name(p, 3)) and not stages._is_extra_frame(p)
    assert stages.frame_name(Path("sh_001.png"), 2).name == "sh_001_f2.png"


def _images_project(tmp_path, monkeypatch, seconds=12.0):
    monkeypatch.delenv("OLYMPUS_REAL_COMFY", raising=False)
    monkeypatch.setattr(stages, "_stills_cfg", lambda: (False, 3.5, 4))
    shots = [{"id": "sh-001-01", "narration": "Aya climbs.", "description": "Aya climbs the stairs."}]
    project = _project(tmp_path, "kf_t", shots, brief="Style: painted anime\nCast: Aya (red scarf)")
    (project / "worldbible").mkdir()
    (project / "worldbible" / "world_bible.json").write_text(json.dumps(
        {"characters": [{"id": "aya", "name": "Aya", "appearance": {"clothing_primary": "red scarf"}}]}))
    (project / "storyboard").mkdir()
    (project / "storyboard" / "storyboard.json").write_text(json.dumps(
        {"shot_detail": [{"id": "sh-001-01", "character_ids": ["aya"], "composition": "wide shot"}]}))
    (project / "audio" / "timeline.json").write_text(json.dumps(
        [{"shot": "sh-001-01", "kind": "narration", "file": "x.wav", "start": 0.0, "dur": seconds - 0.3}]))
    return project


def test_long_shot_gets_director_beats_then_fallback_framings(tmp_path, monkeypatch):
    project = _images_project(tmp_path, monkeypatch)
    monkeypatch.setenv("OLYMPUS_DIRECTOR", "1")
    monkeypatch.setattr(director, "direct", lambda *a, **k: {"sh-001-01": {
        "t2i": "painted anime, Aya on the stairs", "by": "groq", "beats": ["close-up of Aya gasping"]}})
    stale = project / "panels" / "kf_t_sc001_sh001_panel_f4_v001.png"
    stale.write_bytes(b"old")
    out = stages.run_images(project)
    assert out == {"panels": 1, "extra_frames": 2}                       # 12 s / 3.5 s -> 3 frames
    side = lambda k: json.loads((project / "panels" / f"kf_t_sc001_sh001_panel_f{k}_v001.json").read_text())
    assert "close-up of Aya gasping" in side(2)["prompt"] and side(2)["frame"] == 2
    assert "Aya (red scarf)" in side(2)["prompt"] and "Tower" in side(2)["prompt"]  # look + set repeated
    assert side(3)["prompt"].startswith(stages.FALLBACK_FRAMINGS[1])  # no 2nd beat -> framing change
    assert not stale.exists()
    main = project / "panels" / "kf_t_sc001_sh001_panel_v001.png"
    assert [f.name for f in stages.shot_frames(main)][1:] == ["kf_t_sc001_sh001_panel_f2_v001.png",
                                                              "kf_t_sc001_sh001_panel_f3_v001.png"]


def test_animation_on_keeps_one_panel_per_shot(tmp_path, monkeypatch):
    project = _images_project(tmp_path, monkeypatch)
    monkeypatch.setattr(stages, "_stills_cfg", lambda: (True, 3.5, 4))
    monkeypatch.setenv("OLYMPUS_DIRECTOR", "0")
    assert stages.run_images(project)["extra_frames"] == 0


def test_assembly_cuts_a_shot_across_its_key_frames(tmp_path):
    project = _project(tmp_path, "kfa_t", [{"id": "sh-001-01", "narration": "The tower."}])
    main = project / "panels" / "kfa_t_sc001_sh001_panel_v001.png"
    for i, f in enumerate((main, stages.frame_name(main, 2), stages.frame_name(main, 3))):
        stages.render_panel(f, "s", seed=str(i))
    _wav(project / "audio" / "narration" / "n.wav", 8.7)
    (project / "audio" / "timeline.json").write_text(json.dumps(
        [{"shot": "sh-001-01", "kind": "narration", "file": "audio/narration/n.wav", "start": 0.0, "dur": 8.7}]))
    out = stages.run_assembly(project)
    assert (project / "video" / "concat.txt").read_text().split() == [
        "file", "'seg_001_1.mp4'", "file", "'seg_001_2.mp4'", "file", "'seg_001_3.mp4'"]
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", out["video"]], capture_output=True, text=True).stdout)
    assert abs(out["seconds"] - 9.0) < 0.01 and abs(dur - 9.0) < 0.2


def test_director_fills_beats_without_rewriting_old_shots(tmp_path):
    path = tmp_path / "director.json"
    path.write_text(json.dumps({
        "a": {"t2i": "old prompt", "negative": "n", "camera": "", "motion": "", "strength": 0.4,
              "t2v": "", "seconds": 4.0, "by": "groq"},
        "b": {"t2i": "done", "beats": ["x"], "by": "groq"}}))
    asked = []

    def llm(messages):
        asked.append(json.loads(messages[1]["content"].split("SHOTS:\n", 1)[1]))
        return json.dumps({"shots": [{"id": "a", "t2i": "NEW", "beats": ['Aya says "hi" smiling', "wide"]}]})

    out = director.direct([{"id": "a"}, {"id": "b"}], {}, {}, path, llm=llm)
    assert [r["id"] for r in asked[0]] == ["a"]                      # b already has beats
    assert out["a"]["t2i"] == "old prompt" and out["a"]["beats"] == ["Aya says  smiling", "wide"]


def test_review_image_is_shrunk_for_the_judge(tmp_path):
    """hq panels (2560x1440) overflowed qwen2.5vl's 4096-token context: every review was HTTP 400."""
    import base64
    import io

    from PIL import Image

    from pipeline import nim_vision
    big = tmp_path / "big.png"
    Image.new("RGB", (2560, 1440), "blue").save(big)
    with Image.open(io.BytesIO(base64.b64decode(nim_vision._base64_image(big)))) as im:
        assert im.size == (1280, 720)
