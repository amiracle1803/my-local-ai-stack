"""Studio pipeline smoke tests (no GPU/services required)."""

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline.blueprint import STAGE_ORDER, create_blueprint


def test_stage_order_matches_studio_ui():
    # Runtime order is the dependency contract; the UI can display historical IDs.
    ui_order = ["stage0", "stage0_dossier", "stage1", "stage1_world", "stage3",
                "stage2", "stage4", "stage1r", "stage3b", "stage3c",
                "stage_vlm_review", "stage5"]
    assert STAGE_ORDER == ui_order


def test_blueprint_identity():
    bp = create_blueprint("Kael holds the pass. " * 20, slug="t1", fps=25, mode="0a")
    assert bp.fps == 24  # snapped 25 -> 24
    assert bp.mode == "0a"
    assert set(bp.stages) == set(STAGE_ORDER)


def test_scene_split_and_names():
    from pipeline.stages import extract_names, split_scenes

    text = "SCENE 1 — Dusk.\n\nKael sharpens his blade.\n\nKael: We hold tonight.\n\nThe shadow wolf circles."
    scenes = split_scenes(text)
    assert len(scenes) >= 1
    assert "Kael" in extract_names(text)


def test_optimizer_requires_smoke_marker_for_gpu_profiles(tmp_path):
    from pipeline.optimizer import HardwareOptimizer

    optimizer = HardwareOptimizer.default()
    decision = optimizer.decide("stage3b", tmp_path)
    assert not decision.accepted
    assert decision.reason == "validated smoke marker missing"
    marker = tmp_path / "optimizer" / "stage3b_default-panel.json"
    marker.parent.mkdir()
    marker.write_text("{}", encoding="utf-8")
    assert optimizer.decide("stage3b", tmp_path).accepted


def test_gate_enforces_audio_first_order(tmp_path):
    """Plan acceptance: Scores.require_stage() enforces
    stage3 -> stage2 -> stage4 -> stage1r (visuals -> script -> audio -> refs)."""
    from pipeline.scores import Scores, SkippedStageError

    idx = {s: STAGE_ORDER.index(s) for s in STAGE_ORDER}
    assert idx["stage3"] < idx["stage2"] < idx["stage4"] < idx["stage1r"]

    with Scores(tmp_path / "scores.sqlite") as sc:
        sc.require_stage("stage0")  # first stage always allowed
        try:
            sc.require_stage("stage0_dossier")
            raise AssertionError("gate should block stage before its predecessor")
        except SkippedStageError:
            pass
        try:
            sc.require_stage("stage2")
            raise AssertionError("gate should block stage2 before stage3")
        except SkippedStageError:
            pass
        sc.stage_done("stage0")
        sc.require_stage("stage0_dossier")  # now allowed


def test_faithful_intake_is_verbatim(tmp_path):
    """Mode 0s: seed is stored verbatim; stage0 only splits scenes."""
    import run as runmod

    seed = tmp_path / "seed.txt"
    text = "SCENE 1 — Dusk.\n\nKael: We hold tonight.\n\nSCENE 2 — Dawn.\n\nKael: It held."
    seed.write_text(text, encoding="utf-8")
    projects = tmp_path / "projects"
    runmod.new_project("faithful_t", seed, projects_dir=projects, mode="0s")
    pdir = projects / "faithful_t"
    assert (pdir / "input" / "script.txt").read_text(encoding="utf-8") == text
    assert (pdir / "input" / "source.txt").read_text(encoding="utf-8") == text
    out = runmod.run_stage("faithful_t", "stage0", projects_dir=projects)
    assert out["scenes"] >= 2
    import json

    scenes = json.loads((pdir / "stage0_scenes.json").read_text(encoding="utf-8"))
    assert "Kael: We hold tonight." in scenes[0]["content"]


def test_storyboard_enriches_screenplay_shots(tmp_path):
    """Stage 3 must create shot_detail from scenes, without screenplay."""
    import json
    from pipeline.blueprint import create_blueprint
    from pipeline.stages import run_storyboard

    project = tmp_path / "project"
    (project / "worldbible").mkdir(parents=True)
    (project / "scores.sqlite").touch()
    create_blueprint("source", slug="storyboard_t").write(project)
    # Stage3 now runs BEFORE screenplay, reading from scenes + worldbible
    scenes = [{
        "location": "The Pass",
        "summary": "A storm gathers.",
        "content": "Kael sharpens his blade. The storm gathers."
    }]
    (project / "stage0_scenes.json").write_text(json.dumps(scenes), encoding="utf-8")
    (project / "worldbible" / "world_bible.json").write_text(
        json.dumps({"characters": [{"name": "Kael"}]}), encoding="utf-8"
    )

    result = run_storyboard(project)

    storyboard = json.loads(
        (project / "storyboard" / "storyboard.json").read_text(encoding="utf-8")
    )
    assert result == {"shots": 2}  # 2 shots per scene by default
    assert storyboard["shot_detail"][0]["id"] == "sh-001-01"
    assert "storm" in storyboard["shot_detail"][0]["action"].lower()
    # Storyboard stays visual/internal; screenplay owns narration and dialogue.
    assert storyboard["shot_detail"][0]["composition"] == "wide establishing shot"
    assert storyboard["shot_detail"][0]["character_ids"] == ["char"]
    assert storyboard["shot_detail"][0]["reference_assets"] == []


def test_canonical_artifact_identity():
    from pipeline.identity import canonical_name

    assert canonical_name("bloodline", "sh-001-02", "panel", "png") == (
        "bloodline_sc001_sh002_panel_v001.png"
    )


def test_review_unavailable_does_not_pass(monkeypatch, tmp_path):
    from pipeline import stages

    panel_dir = tmp_path / "panels"
    panel_dir.mkdir()
    stages.render_panel(panel_dir / "sh_001_01.png", "shot", seed="test")
    monkeypatch.setattr(
        "pipeline.nim_vision.review_image",
        lambda *_args, **_kwargs: {"available": False, "verdict": "UNAVAILABLE", "score": 0},
    )
    (tmp_path / "scores.sqlite").touch()
    from pipeline.blueprint import create_blueprint

    create_blueprint("source", slug="review_t").write(tmp_path)
    try:
        stages.run_review(tmp_path)
    except RuntimeError as exc:
        assert "blocked" in str(exc)
    else:
        raise AssertionError("unavailable review must block stage5")


def _scaffold_project(tmp_path: Path, slug: str, mode: str = "0b") -> Path:
    from pipeline.blueprint import create_blueprint

    project = tmp_path / slug
    (project / "panels").mkdir(parents=True)
    project.joinpath("scores.sqlite").touch()
    create_blueprint("source", slug=slug, mode=mode).write(project)
    return project


def test_assembly_with_music_mixes_cleanly(tmp_path):
    """stage5 audio/music bed must not break the ffmpeg filtergraph
    (regression: chained one-input sidechaincompress crashed the mix)."""
    import json
    import subprocess
    from pipeline import stages
    from pipeline.identity import canonical_name

    project = _scaffold_project(tmp_path, "music_t")
    nar = project / "audio" / "narration"
    nar.mkdir(parents=True)
    wav = nar / "music_t_sc001_sh001_narration_v001.wav"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=440:duration=3", "-ar", "22050", str(wav)], check=True)
    (project / "audio" / "music").mkdir(parents=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=10", "-ar", "22050",
                    str(project / "audio" / "music" / "theme.wav")], check=True)
    (project / "audio" / "timeline.json").write_text(json.dumps(
        [{"shot": "sh-001-01", "kind": "narration",
          "file": f"audio/narration/{wav.name}", "start": 0.0, "dur": 3.0,
          "text": "Kael holds the pass."}]), encoding="utf-8")
    stages.render_panel(project / "panels" / canonical_name("music_t", "sh-001-01", "panel", "png"),
                        "shot", seed="t")
    (project / "screenplay").mkdir()
    (project / "screenplay" / "screenplay.json").write_text(json.dumps(
        {"scenes": [{"heading": "SCENE 1", "location": "The Pass", "summary": "s",
                     "shots": [{"id": "sh-001-01", "narration": "Kael holds the pass.",
                                 "dialogue": "", "description": "wide"}]}]}), encoding="utf-8")

    out = stages.run_assembly(project)

    final = project / "video" / "final.mp4"
    assert final.exists() and Path(out["video"]) == final
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_name", "-of", "csv=p=0", str(final)],
        capture_output=True, text=True)
    assert probe.stdout.strip()  # audio stream present (music + voice mixed)


def test_review_skips_block_composites(monkeypatch, tmp_path):
    """stage_vlm_review must never treat block_* manga composites as shots."""
    import json
    from pipeline import stages

    project = _scaffold_project(tmp_path, "rev2_t")
    panels = project / "panels"
    stages.render_panel(panels / "rev2_t_sc001_sh001_panel_v001.png", "shot", seed="t")
    (panels / "rev2_t_sc001_sh001_panel_v001.json").write_text(
        json.dumps({"backend": "placeholder"}), encoding="utf-8")
    stages.render_panel(panels / "block_00_manga.png", "composite", seed="t")  # no sidecar
    monkeypatch.setattr(
        "pipeline.nim_vision.review_image",
        lambda *_args, **_kwargs: {"available": False, "verdict": "UNAVAILABLE", "score": 0},
    )

    out = stages.run_review(project)

    payload = json.loads((project / "reviews" / "vlm_review.json").read_text(encoding="utf-8"))
    assert set(payload["reviews"]) == {"rev2_t_sc001_sh001_panel_v001.png"}
    assert out["gate"] == "SKIP"  # only placeholder panel -> nothing real to review


def test_stage3b_imports_uploaded_panels(tmp_path):
    """Mode 0i: uploaded panels are copied to canonical names, not re-rendered."""
    import json
    from pipeline import stages
    from pipeline.identity import canonical_name

    project = _scaffold_project(tmp_path, "imp_t", mode="0i")
    (project / "worldbible").mkdir()
    (project / "worldbible" / "world_bible.json").write_text(
        json.dumps({"characters": []}), encoding="utf-8")
    (project / "storyboard").mkdir()
    (project / "storyboard" / "storyboard.json").write_text(
        json.dumps({"blocks": [], "shot_detail": [{"id": "sh-001-01"}]}), encoding="utf-8")
    (project / "screenplay").mkdir()
    (project / "screenplay" / "screenplay.json").write_text(
        json.dumps({"scenes": [{"shots": [{"id": "sh-001-01"}]}]}), encoding="utf-8")
    uploads = project / "input" / "panels"
    uploads.mkdir(parents=True)
    stages.render_panel(uploads / "user_frame.png", "USER ART", seed="t")

    out = stages.run_images(project)

    canonical = project / "panels" / canonical_name("imp_t", "sh-001-01", "panel", "png")
    sidecar = json.loads(canonical.with_suffix(".json").read_text(encoding="utf-8"))
    assert out["panels"] == 1 and canonical.exists()
    assert sidecar["backend"] == "imported"


def test_tts_provider_manifest_prefers_chatterbox():
    from pipeline.voice_client import provider_status

    status = provider_status()
    assert status["recommended"] == "chatterbox-turbo"
    assert "exclusive lock" in status["gpu_policy"]
