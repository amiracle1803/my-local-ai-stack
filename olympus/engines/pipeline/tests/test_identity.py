"""VFX-style identity standard: canonical ids, version/take tokens, resolver."""
from pathlib import Path

from pipeline import identity


def test_canonical_shot_id_legacy_to_canonical():
    assert identity.canonical_shot_id("sh-001-01", "olympusdemo") == "olympusdemo_sc001_sh001"
    assert identity.canonical_shot_id("sh-001-01") == "sc001_sh001"  # no project prefix


def test_canonical_shot_id_passthrough_unknown():
    assert identity.canonical_shot_id("already_sc001_sh001") == "already_sc001_sh001"


def test_panel_and_clip_ids():
    canonical = "olympusdemo_sc001_sh001"
    assert identity.panel_id(canonical, 1) == "olympusdemo_sc001_sh001_pn01"
    assert identity.clip_id(canonical, 1) == "olympusdemo_sc001_sh001_cl01"


def test_version_and_take_tokens():
    assert identity.version_name(1) == "v001"
    assert identity.version_name(4) == "v004"
    assert identity.take_name(1) == "tk01"
    assert identity.take_name(3) == "tk03"


def test_artifact_name_plain():
    name = identity.artifact_name("olympusdemo_sc001_sh001", "pn01", variant="render", version=1)
    assert name == "olympusdemo_sc001_sh001_pn01_render_v001.png"


def test_artifact_name_with_take():
    name = identity.artifact_name(
        "olympusdemo_sc001_sh001", "cl01", variant="ltx-director", version=2, take=3, ext="mp4")
    assert name == "olympusdemo_sc001_sh001_cl01_ltx-director_tk03_v002.mp4"


def test_canonical_id_from_filename_roundtrip():
    name = "olympusdemo_sc001_sh001_pn01_render_v001.png"
    assert identity.canonical_id_from_filename(name) == "olympusdemo_sc001_sh001"
    assert identity.canonical_id_from_filename("sh-001-01.png") is None


def test_legacy_sid_from_filename():
    assert identity.legacy_sid_from_filename("sh-001-01_director_00001.mp4") == "sh-001-01"
    assert identity.legacy_sid_from_filename("olympusdemo_sc001_sh001_cl01.mp4") is None


def test_version_and_take_from_filename():
    name = "olympusdemo_sc001_sh001_cl01_ltx-director_tk03_v002.mp4"
    assert identity.version_from_filename(name) == "v002"
    assert identity.take_from_filename(name) == "tk03"


def test_sid_from_panel_name_both_styles():
    assert identity.sid_from_panel_name("sh-001-01.png") == "sh-001-01"
    assert identity.sid_from_panel_name("olympusdemo_sc001_sh001_pn01_render_v001.png") == "sh-001-01"


def test_panel_path_legacy_fallback(tmp_path):
    block = tmp_path / "blk-001"
    block.mkdir()
    # no project prefix -> legacy name
    assert identity.panel_path(block, "sh-001-01", "") == block / "sh-001-01.png"
    # with project prefix -> canonical name
    assert identity.panel_path(block, "sh-001-01", "olympusdemo").name == \
        "olympusdemo_sc001_sh001_pn01_render_v001.png"


def test_resolve_panel_prefers_canonical_then_legacy(tmp_path):
    block = tmp_path / "blk-001"
    block.mkdir()
    # canonical preferred (never stale for a regenerated shot)
    canonical = block / "olympusdemo_sc001_sh001_pn01_render_v001.png"
    canonical.write_bytes(b"x")
    assert identity.resolve_panel(block, "sh-001-01", "olympusdemo") == canonical
    # legacy is the fallback for untouched projects
    legacy = block / "sh-001-01.png"
    legacy.write_bytes(b"x")
    assert identity.resolve_panel(block, "sh-001-01", "") == legacy


def test_audio_and_dialogue_paths(tmp_path):
    adir = tmp_path
    assert identity.audio_path(adir, "sh-001-01", "olympusdemo", "audio_narration").name == \
        "olympusdemo_sc001_sh001_audio_narration_v001.wav"
    assert identity.audio_path(adir, "sh-001-01", "olympusdemo", "audio_narration", ext="align.json").name == \
        "olympusdemo_sc001_sh001_audio_narration_v001.align.json"
    assert identity.dialogue_path(adir, "sh-001-01", "olympusdemo", 0).name == \
        "olympusdemo_sc001_sh001_dialogue_dl00_v001.wav"
    # legacy project
    assert identity.audio_path(adir, "sh-001-01", "olympusdemo", "audio_narration").parent == adir


def test_project_code_slugifies():
    assert identity.slugify_project("My Story") == "my-story"
    assert identity.slugify_project("Aether Echoes!") == "aether-echoes"


def test_master_deliverable_name():
    assert identity.artifact_name("river-shrine", "master", version=1, ext="mp4") == \
        "river-shrine_master_v001.mp4"
    assert identity.artifact_name("river-shrine", "master", version=1, ext="srt") == \
        "river-shrine_master_v001.srt"