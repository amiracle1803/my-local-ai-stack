"""Episode quality: markdown scripts, one shot per beat, casting, shared clock (no GPU)."""

import json
import subprocess
import sys
import wave
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline import stages  # noqa: E402
from pipeline.blueprint import create_blueprint  # noqa: E402
from pipeline.identity import canonical_name  # noqa: E402

MD_SCRIPT = """**LANTERNFALL — EPISODE 1: "The Last Lantern"**
*[Opening: Aya’s POV. The tower glints under twilight.]*

**Aya:** (gritting her teeth) “One more step, Toma.”
**Old Toma:** (coughing) “Too steep for me, child.” *He sits down.*

*[She strikes the wick. Every lantern dies.]*
**Rin:** “Oh, look. Fire.”
"""


def _wav(path: Path, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * int(22050 * seconds))


def test_normalize_markdown_screenplay():
    out = stages.normalize_script(MD_SCRIPT).splitlines()
    assert "Aya: (gritting her teeth) One more step, Toma." in out
    assert "Old Toma: (coughing) Too steep for me, child." in out
    assert "He sits down." in out  # trailing action becomes its own line
    assert "The tower glints under twilight." in out  # camera label + POV dropped
    assert not any("*" in line for line in out)


def test_plain_script_passes_through():
    text = "SCENE 1 — Dusk.\n\nKael: We hold tonight.\n\nThe wolf circles."
    assert stages.normalize_script(text) == text


def test_shot_plan_one_shot_per_beat():
    plan = stages.shot_plan(stages.normalize_script(MD_SCRIPT))
    # title, tower(+Aya), Toma close-up, "He sits down.", wick(+Rin)
    assert len(plan) == 5
    assert plan[0]["narration"].startswith("LANTERNFALL — EPISODE 1")
    assert plan[1]["speaker"] == "Aya" and plan[1]["delivery"] == "gritting her teeth"
    assert plan[2]["speaker"] == "Old Toma" and not plan[2]["narration"]
    assert plan[2]["action"]  # close-ups keep the last action as visual context
    assert plan[4]["speaker"] == "Rin" and "wick" in plan[4]["narration"]


def test_long_narration_splits_at_sentences():
    para = " ".join(f"Sentence number {i} walks across the long bridge slowly." for i in range(12))
    plan = stages.shot_plan(para)
    assert len(plan) >= 2
    assert all(len(p["narration"].split()) <= stages.NARRATION_SHOT_WORDS + 9 for p in plan)


def test_names_come_from_speakers():
    text = stages.normalize_script(MD_SCRIPT) + "\nShe holds the Heart Flame. Courage!"
    names = stages.extract_names(text)
    assert set(names) == {"Aya", "Old Toma", "Rin"}


def test_brief_meta_parses_style_cast_voices(tmp_path):
    (tmp_path / "input").mkdir()
    (tmp_path / "input" / "brief.md").write_text(
        "Series: X — a show. Style: hand-painted anime, warm light.\n"
        "Cast: Aya (16, red scarf), Old Toma (white beard), Rin (blue fire fox)\n"
        "Voices: Narrator=Aiden (calm); Aya=Vivian (bright teen); Old Toma=Uncle_Fu\n",
        encoding="utf-8")
    meta = stages.brief_meta(tmp_path)
    assert meta["style"] == "hand-painted anime, warm light"
    assert meta["cast"] == {"Aya": "16, red scarf", "Old Toma": "white beard", "Rin": "blue fire fox"}
    assert meta["voices"]["Aya"] == {"voice": "Vivian", "style": "bright teen"}
    assert meta["voices"]["Old Toma"]["voice"] == "Uncle_Fu"


def _project(tmp_path, slug, shots, brief=""):
    project = tmp_path / slug
    for d in ("input", "audio", "panels", "clips", "screenplay", "video"):
        (project / d).mkdir(parents=True, exist_ok=True)
    (project / "scores.sqlite").touch()
    create_blueprint("source", slug=slug).write(project)
    (project / "input" / "brief.md").write_text(brief, encoding="utf-8")
    (project / "screenplay" / "screenplay.json").write_text(json.dumps(
        {"scenes": [{"heading": "SCENE 1", "location": "Tower", "summary": "", "shots": shots}]}),
        encoding="utf-8")
    return project


def test_audio_slots_casting_and_delivery(tmp_path, monkeypatch):
    calls = []

    def fake_synth(text, dest, voice="", reference=None, style="", **_):
        calls.append((text, voice, style))
        _wav(Path(dest), 1.0)
        return Path(dest), True

    monkeypatch.setattr(stages, "synth", fake_synth)
    shots = [{"id": "sh-001-01", "narration": "The tower.", "character": "Aya",
              "dialogue": "Up!", "delivery": "shouting"},
             {"id": "sh-001-02", "narration": "", "character": "", "dialogue": ""},  # silent shot
             {"id": "sh-001-03", "narration": "", "character": "Toma", "dialogue": "No."}]
    project = _project(tmp_path, "audio_t", shots,
                       brief="Voices: Narrator=Aiden (calm); Aya=Vivian (bright teen); Old Toma=Uncle_Fu")
    stages.run_audio(project)
    tl = json.loads((project / "audio" / "timeline.json").read_text())
    assert [e["shot"] for e in tl] == ["sh-001-01", "sh-001-01", "sh-001-03"]
    # silent shot keeps SHOT_MIN_SECONDS of screen time on the shared clock
    assert tl[2]["start"] == round(2 * 1.3 + stages.SHOT_MIN_SECONDS, 2)
    assert calls[0][1] == "Aiden" and calls[1][1] == "Vivian"
    assert calls[1][2] == "bright teen. Delivery: shouting"
    assert calls[2][1] == "Uncle_Fu"  # "Toma" matched the brief's "Old Toma"
    voices = json.loads((project / "voices.json").read_text())
    assert voices["characters"]["Aya"]["voice"] == "Vivian"
    calls.clear()
    stages.run_audio(project)  # re-run: finished lines are reused, not re-synthesised
    assert calls == []


def test_assembly_matches_audio_clock_and_uses_clips(tmp_path):
    shots = [{"id": "sh-001-01", "narration": "The tower.", "dialogue": ""},
             {"id": "sh-001-02", "narration": "", "character": "Aya", "dialogue": "Up!"}]
    project = _project(tmp_path, "asm_t", shots)
    for i, sid in enumerate(("sh-001-01", "sh-001-02")):
        stages.render_panel(project / "panels" / canonical_name("asm_t", sid, "panel", "png"), "s", seed=str(i))
    clip = project / "clips" / (canonical_name("asm_t", "sh-001-02", "panel", "png")[:-4] + ".mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=1024x576:rate=8",
                    "-t", "1.5", "-pix_fmt", "yuv420p", str(clip)], check=True)
    clip.with_suffix(".json").write_text(json.dumps({"backend": "svd"}))
    _wav(project / "audio" / "narration" / "n.wav", 4.0)
    _wav(project / "audio" / "dialogue" / "d.wav", 3.0)
    (project / "audio" / "timeline.json").write_text(json.dumps([
        {"shot": "sh-001-01", "kind": "narration", "file": "audio/narration/n.wav", "start": 0.0, "dur": 4.0},
        {"shot": "sh-001-02", "kind": "dialogue", "file": "audio/dialogue/d.wav", "start": 4.3, "dur": 3.0}]))
    out = stages.run_assembly(project)
    assert abs(out["seconds"] - 7.6) < 0.01
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "csv=p=0", out["video"]], capture_output=True, text=True).stdout)
    assert abs(dur - 7.6) < 0.2
    srt = (project / "video" / "final.srt").read_text()
    assert "Aya: Up!" in srt and "00:00:04,300" in srt  # subtitle on the line, not the shot


def test_oom_retry_also_unloads_ollama(monkeypatch):
    from pipeline import comfy_client, gpu_lock

    hits = []
    monkeypatch.setattr(comfy_client, "_request", lambda *a, **k: hits.append("comfy"))
    monkeypatch.setattr(gpu_lock, "unload_ollama", lambda *a, **k: hits.append("ollama"))
    monkeypatch.setattr(comfy_client.time, "sleep", lambda s: None)
    comfy_client._free_gpu("http://x")
    assert hits == ["comfy", "ollama"]


def test_writer_goes_scene_by_scene_and_retries_prose(monkeypatch):
    from pipeline.llm import LLMResult

    replies = iter([
        "SCENE 1 — Tower\nAya climbs.\n\nAYA: Up we go.\n\nSCENE 2 — ran on",   # runs on -> trimmed
        'SCENE 7 — Wick\nShe says "it is out" quietly.',                        # prose dialogue -> retry
        "SCENE 2 — Wick\nThe lights die.\n\nOld Toma: (whispering) No...",
    ])
    prompts = []

    def fake(prompt, **kw):
        prompts.append((prompt, kw))
        return LLMResult(text=next(replies), used_llm=True, model="fake")

    monkeypatch.setattr(stages, "ollama_generate", fake)
    brief = ("Cast: Aya (red scarf)\nVoices: Aya=Vivian (bright)\n"
             "SCENE 1 - The Tower. Aya climbs.\nSCENE 2 - The Wick. The lights die.")
    script = stages._write_script(brief, 200)
    scenes = stages.split_scenes(script)
    assert [s["location"] for s in scenes] == ["Tower", "Wick"]
    assert "ran on" not in script and "Old Toma: (whispering) No..." in script
    assert len(prompts) == 3 and all(kw.get("think") is False for _, kw in prompts)
    assert "Voices:" not in prompts[0][0]  # casting notes stay out of the writer's prompt
