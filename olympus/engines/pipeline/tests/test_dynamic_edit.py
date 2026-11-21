"""[edit] dynamic = manhwa-recap editing (2026-11-20): moves, cuts, overlays, SFX, score, thumbnail."""

import json
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from stack.config import EditConfig  # noqa: E402
from pipeline import director, edit, music, stages  # noqa: E402
from tests.test_episode_quality import _project, _wav  # noqa: E402


def _dur(f: Path) -> float:
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(f)], capture_output=True, text=True).stdout)


def test_every_director_move_has_an_expression():
    for m in director.MOVES:
        assert edit.zoompan(m, 48).startswith("z='")
    assert edit.zoompan("nonsense", 48) == edit.zoompan("push", 48)
    assert "color=white" in edit.transition("punch", 24) and "gblur" in edit.transition("pan_left", 24)
    assert edit.transition("push", 24) == ""


def test_plan_puts_overlays_and_sfx_on_the_right_frames(tmp_path):
    stills = []
    for i in range(3):
        stages.render_panel(tmp_path / f"s{i}.png", "s", seed=str(i))
        stills.append(tmp_path / f"s{i}.png")
    d = {"moves": ["drift", "punch", "pan_left"], "ui": "[Quest] Find the flame", "caption": "IT DIED"}
    plan = edit.plan_shot(stills, 150, 24, d, tmp_path / "fx", size=(640, 360), seed=0)
    assert sum(f.frames for f in plan.frames) == 150 and [f.move for f in plan.frames] == d["moves"]
    names = lambda f: [o[0].name.split("_")[0] for o in f.overlays]
    assert names(plan.frames[0]) == ["ui"] and names(plan.frames[1]) == ["speed", "ui", "cap"]
    assert names(plan.frames[2]) == []                                   # window only on 2 frames
    assert {n for _, n in plan.sfx} == {"chime", "impact", "riser"}             # no whoosh on cuts


def test_dynamic_assembly_end_to_end(tmp_path, monkeypatch):
    monkeypatch.delenv("OLYMPUS_REAL_COMFY", raising=False)
    monkeypatch.setattr(stages, "_edit_cfg", lambda: EditConfig(dynamic=True, music=False))
    monkeypatch.setattr(stages, "_out_size", lambda: (640, 360))
    project = _project(tmp_path, "dyn_t", [{"id": "sh-001-01", "narration": "The tower."}],
                       brief='EPISODE 1 — "The Last Lantern"')
    main = project / "panels" / "dyn_t_sc001_sh001_panel_v001.png"
    for i, f in enumerate((main, stages.frame_name(main, 2))):
        stages.render_panel(f, "s", seed=str(i))
    (project / "storyboard").mkdir()
    (project / "storyboard" / "director.json").write_text(json.dumps({"sh-001-01": {
        "moves": ["punch", "pan_right"], "ui": "[System] Lantern lost", "caption": "DARK", "mood": "tension"}}))
    _wav(project / "audio" / "narration" / "n.wav", 5.7)
    (project / "audio" / "timeline.json").write_text(json.dumps(
        [{"shot": "sh-001-01", "kind": "narration", "file": "audio/narration/n.wav", "start": 0.0, "dur": 5.7}]))
    out = stages.run_assembly(project)
    assert out["sfx"] >= 3 and not out["score"] and Path(out["thumbnail"]).exists()
    assert abs(_dur(Path(out["video"])) - 6.0) < 0.2
    assert (project / "video" / "sfx.wav").exists() and (project / "video" / "fx").is_dir()
    page = Path(out["storyboard"])                     # local storyboard page with relative links
    assert page.exists() and (project / "video" / "scenes" / "dyn_t_scene01.mp4").exists()
    assert '"video": "scenes/dyn_t_scene01.mp4"' in page.read_text() and "fonts.googleapis" not in page.read_text()


def test_score_loops_short_cues_to_the_episode_length(tmp_path):
    cues = []
    for i, secs in enumerate((2.0, 1.5)):
        f = tmp_path / f"c{i}.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency={300 + 100 * i}:duration={secs}",
                        str(f)], check=True)
        cues.append((i * 5.0, f))
    out = music.build_score(cues, 11.0, tmp_path / "score.wav")
    assert abs(_dur(out) - 11.0) < 0.1
    assert music.scene_mood(["calm", "action", "action"]) == "action" and music.scene_mood([]) == "mystery"
    g = music.graph("tags", 30, 1, "ace.safetensors")
    assert g["6"]["inputs"]["steps"] == 8 and g["5"]["inputs"]["shift"] == 3.0


def test_recap_brief_switches_the_writer_to_first_person():
    brief = "Narration: recap, first person as Aya\nSCENE 1 - Tower."
    assert "Aya's point of view" in stages._script_prompt(brief, 300)
    assert stages._recap_rules("Style: anime") == ""


def test_director_dynamic_pass_keeps_rendered_beats(tmp_path):
    path = tmp_path / "director.json"
    path.write_text(json.dumps({"a": {"t2i": "keep", "beats": ["b1", "b2", "b3"], "beats_n": 3}}))
    reply = json.dumps({"shots": [{"id": "a", "t2i": "x", "beats": ["n1"], "moves": ["punch", "zoom"],
                                   "ui": "[Quest] go", "caption": "now", "mood": "action"}]})
    out = director.direct([{"id": "a"}], {}, {}, path, llm=lambda m: reply, n_beats=3, dynamic=True)["a"]
    assert out["beats"] == ["b1", "b2", "b3"] and out["moves"] == ["punch", "push"]
    assert (out["ui"], out["caption"], out["mood"]) == ("[Quest] go", "NOW", "action")
    out = director.direct([{"id": "a"}], {}, {}, path, llm=lambda m: reply, n_beats=7, dynamic=True)["a"]
    assert out["beats"] == ["n1"] and out["beats_n"] == 7 and out["t2i"] == "keep"   # more beats asked


def test_changed_prompt_forces_a_new_render(tmp_path):
    f = tmp_path / "p.png"
    f.write_bytes(b"x")
    f.with_suffix(".json").write_text(json.dumps({"prompt": "old"}))
    stages._fresh(f, "old")
    assert f.exists()
    stages._fresh(f, "new")
    assert not f.exists()


def test_image_prompts_lose_negations():
    p = ("Toma, left eye clouded milky white (no glasses, no monocle), patched grey robe, no weapons, "
         "single full-frame illustration, no text")
    assert stages.positive_only(p) == ("Toma, left eye clouded milky white, patched grey robe, "
                                       "single full-frame illustration, no text")
