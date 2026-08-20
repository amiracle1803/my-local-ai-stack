"""Stage 1 (WORLD BIBLE) tests, part 1 of 2 (M2a): full-script character scan
(chunk-merge dedup, fuzzy + prefix merge) and per-character profile extraction
(sentence-context gathering, appearance completeness/repair, sd_prompt 40-60
word enforcement, LLM-suggested voice with code-enforced uniqueness, single-
protagonist role integrity, schema round-trip, ``bible_coverage``). No network
-- ``PipelineLLM`` is replaced by a small in-test fake implementing the two
methods stage1 calls (``complete_json`` / ``complete_text``).
"""

from __future__ import annotations

import json

import pytest

import run
from pipeline.config import PipelineConfig
from pipeline.scores import Scores
from pipeline.schemas.worldbible import (
    Appearance,
    Character,
    Personality,
    SpeechStyle,
    WorldBible,
)
from pipeline.stage1_worldbible import (
    Stage1Error,
    _empty_appearance_fields,
    _enforce_sd_prompt,
    _gather_context,
    _merge_names,
    _resolve_protagonists,
    _sd_prompt_issues,
    extract_profiles,
    run as run_stage1,
    scan_characters,
    voice_for,
)

# A clean, appearance-only sd_prompt of ~51 words (within 40-60, no forbidden
# terms) so happy-path profiles trigger no repair calls.
_CLEAN_SD = (
    "Short black hair swept to one side, sharp brown eyes, tan weathered skin, "
    "athletic muscular build, wearing a worn brown traveler's cloak over dark "
    "leather armor, a faded scar across the right cheek, fingerless gloves, and "
    "sturdy boots laced to the knee, a calm and guarded expression on the young face"
)


# --------------------------------------------------------------------------
# fixtures / fake data
# --------------------------------------------------------------------------
def _profile_data(
    name,
    *,
    role="ally",
    traits=None,
    core_drive="protect the village",
    core_fear="losing control",
    speech_category="plain",
    aliases=None,
    voice_id_suggestion="am_adam",
    appearance=None,
    appearance_invented=False,
    sd_prompt=_CLEAN_SD,
):
    return {
        "name": name,
        "aliases": aliases or [],
        "appearance": appearance
        or {
            "hair": "short black",
            "eyes": "brown",
            "skin": "tan",
            "build": "athletic",
            "clothing_primary": "worn traveler's cloak",
            "distinguishing_feature": "scar across the right cheek",
        },
        "appearance_invented": appearance_invented,
        "sd_prompt": sd_prompt,
        "voice_id_suggestion": voice_id_suggestion,
        "speech_style": {
            "category": speech_category,
            "avg_words_per_line": "medium",
            "vocabulary_register": "plain",
            "distinctive_patterns": "none",
        },
        "personality": {
            "traits": traits or ["stubborn", "loyal", "quick-tempered", "guarded", "determined"],
            "core_drive": core_drive,
            "core_fear": core_fear,
        },
        "role": role,
        "arc_this_episode": {"starts": "afraid to act", "ends": "commits to the fight"},
        "first_episode": "episode 1",
    }


class FakeLLM:
    """Stands in for PipelineLLM: ``complete_json`` (scan/profile/appearance
    repair) and ``complete_text`` (sd_prompt repair)."""

    def __init__(
        self,
        scan_names_by_chunk=None,
        profiles_by_name=None,
        appearance_repair=None,
        sd_repair_text=None,
    ):
        self.scan_names_by_chunk = scan_names_by_chunk or {}
        self.profiles_by_name = profiles_by_name or {}
        self.appearance_repair = appearance_repair or {
            "hair": "short brown",
            "eyes": "hazel",
            "skin": "fair",
            "build": "lean",
            "clothing_primary": "simple tunic and trousers",
            "distinguishing_feature": "a small mole below the left eye",
        }
        self.sd_repair_text = sd_repair_text or _CLEAN_SD
        self.calls: list[str] = []

    def complete_json(self, prompt_file, context, schema, *, role="script", stage_hint="stage"):
        self.calls.append(stage_hint)
        if prompt_file == "s1_character_scan.md":
            idx = int(stage_hint.rsplit("chunk", 1)[1])
            return schema.model_validate({"names": self.scan_names_by_chunk.get(idx, [])})
        if prompt_file == "s1_character_profile.md":
            name = context["character_name"]
            data = self.profiles_by_name.get(name.lower())
            if data is None:
                data = _profile_data(name)
            return schema.model_validate(data)
        if prompt_file == "s1_appearance_repair.md":
            return schema.model_validate(self.appearance_repair)
        raise AssertionError(f"unexpected json prompt file {prompt_file!r}")

    def complete_text(self, prompt_file, context, *, role="script", stage_hint="stage"):
        self.calls.append(stage_hint)
        if prompt_file == "s1_sd_prompt_repair.md":
            return self.sd_repair_text
        raise AssertionError(f"unexpected text prompt file {prompt_file!r}")


_SCRIPT = (
    "--- [SCENE 1: The Last Echo] ---\n\n"
    "Kaito's sword clashed with the beast's claw. \"Its strength is growing,\" "
    "Eldrin shouted over the noise. He gritted his teeth as the beast forced "
    "him back. \"I won't use echo magic,\" Kaito growled.\n\n"
    "--- [SCENE 2: The Village's Choice] ---\n\n"
    "Mira stepped forward, but Eldrin barked at Kaito. She whispered, "
    "\"You're not alone.\" Kaito's grip faltered.\n"
)


def _make_project(tmp_path, script_text=_SCRIPT, slug="stage1test"):
    projects_dir = tmp_path / "projects"
    script_file = tmp_path / "script.txt"
    script_file.write_text(script_text, encoding="utf-8")
    return run.new_project(slug, script_file, fps=24, projects_dir=projects_dir)


# --------------------------------------------------------------------------
# Step 1 -- name merging (FIX 5)
# --------------------------------------------------------------------------
def test_merge_names_case_insensitive_dedup():
    merged = _merge_names(["Kaito", "kaito", "KAITO", "Eldrin"])
    assert merged == ["Kaito", "Eldrin"]


def test_merge_names_fuzzy_merges_near_duplicates():
    # "Mira" vs "Mirra": SequenceMatcher ratio = 2*4/9 = 0.888... >= 0.88.
    merged = _merge_names(["Mira", "Mirra"])
    assert merged == ["Mirra"]  # longer form kept as canonical


def test_merge_names_prefix_merges_truncated_name():
    # "Eld" is a case-insensitive prefix of "Eldrin" (shorter >= 3) -> merge,
    # keeping the longer canonical. (FIX 5.)
    assert _merge_names(["Eld", "Eldrin"]) == ["Eldrin"]
    assert _merge_names(["Eldrin", "Eld"]) == ["Eldrin"]


def test_merge_names_prefix_below_min_len_not_merged():
    # 2-char prefix is below the >= 3 floor -> not merged.
    assert sorted(_merge_names(["Ka", "Kaito"])) == ["Ka", "Kaito"]


def test_merge_names_does_not_merge_unrelated_names():
    merged = _merge_names(["Kaito", "Eldrin", "Mira"])
    assert sorted(merged) == ["Eldrin", "Kaito", "Mira"]


def test_scan_characters_merges_across_chunks(tmp_path):
    long_script = ("Kaito walked through the ruined village. " * 250) + (
        "Eldrin followed close behind, watching the treeline. " * 50
    )
    proj_dir = _make_project(tmp_path, script_text=long_script, slug="longscan")
    llm = FakeLLM(scan_names_by_chunk={0: ["Kaito", "kaito"], 1: ["KAITO", "Eldrin"]})
    names = scan_characters(proj_dir, llm)
    assert sorted(n.lower() for n in names) == ["eldrin", "kaito"]
    assert llm.calls == ["stage1_scan_chunk0", "stage1_scan_chunk1"]


# --------------------------------------------------------------------------
# Step 2 -- sentence-context gathering
# --------------------------------------------------------------------------
def test_gather_context_includes_pronoun_continuation():
    text = (
        "Kaito raised his sword. He glared at the beast. Mira watched from "
        "the ridge, unrelated to this sentence."
    )
    ctx = _gather_context(text, "Kaito")
    assert "Kaito raised his sword." in ctx
    assert "He glared at the beast." in ctx
    assert "Mira watched" not in ctx


def test_gather_context_word_cap():
    text = "Kaito ran. " * 500
    ctx = _gather_context(text, "Kaito", word_cap=50)
    assert len(ctx.split()) <= 50


def test_gather_context_no_mentions_returns_empty():
    assert _gather_context("Nothing here about them.", "Kaito") == ""


# --------------------------------------------------------------------------
# FIX 1 -- appearance completeness
# --------------------------------------------------------------------------
def test_empty_appearance_fields_detects_none_and_blank():
    app = Appearance(
        hair="black", eyes="none", skin="", build="unknown",
        clothing_primary="cloak", distinguishing_feature="scar",
    )
    assert set(_empty_appearance_fields(app)) == {"eyes", "skin", "build"}


def test_extract_profiles_repairs_empty_appearance_and_flags_invented(tmp_path):
    proj_dir = _make_project(tmp_path, slug="apprepair")
    sparse = _profile_data(
        "Eldrin",
        appearance={
            "hair": "none", "eyes": "none", "skin": "none",
            "build": "none", "clothing_primary": "none", "distinguishing_feature": "none",
        },
        appearance_invented=False,
    )
    llm = FakeLLM(profiles_by_name={"eldrin": sparse})
    chars = extract_profiles(proj_dir, ["Eldrin"], llm)
    c = chars[0]
    assert _empty_appearance_fields(c.appearance) == []  # 6/6 filled
    assert c.appearance_invented is True
    assert "stage1_appfix_eldrin" in llm.calls  # a repair call happened


def test_extract_profiles_raises_if_appearance_still_empty(tmp_path):
    proj_dir = _make_project(tmp_path, slug="appfail")
    sparse = _profile_data(
        "Ghost",
        appearance={k: "none" for k in
                    ("hair", "eyes", "skin", "build", "clothing_primary", "distinguishing_feature")},
    )
    bad_repair = {k: "none" for k in
                  ("hair", "eyes", "skin", "build", "clothing_primary", "distinguishing_feature")}
    llm = FakeLLM(profiles_by_name={"ghost": sparse}, appearance_repair=bad_repair)
    with pytest.raises(Stage1Error):
        extract_profiles(proj_dir, ["Ghost"], llm)


# --------------------------------------------------------------------------
# FIX 2 -- sd_prompt enforcement
# --------------------------------------------------------------------------
def test_sd_prompt_issues_flags_short_long_and_forbidden():
    assert _sd_prompt_issues(_CLEAN_SD) == []  # clean
    assert _sd_prompt_issues("black hair, brown eyes")  # too short
    long_txt = " ".join(["word"] * 80)
    assert any("too long" in i for i in _sd_prompt_issues(long_txt))
    bad = _CLEAN_SD + " dramatic cinematic lighting, detailed background"
    assert any("forbidden terms" in i for i in _sd_prompt_issues(bad))


def _appearance():
    return Appearance(
        hair="short black", eyes="brown", skin="tan", build="athletic",
        clothing_primary="worn cloak", distinguishing_feature="scar",
    )


def test_enforce_sd_prompt_clean_makes_no_call():
    llm = FakeLLM()
    out, applied = _enforce_sd_prompt(_CLEAN_SD, _appearance(), "Kaito", llm, "hint")
    assert applied is None
    assert out == _CLEAN_SD
    assert llm.calls == []


def test_enforce_sd_prompt_too_short_triggers_one_repair():
    llm = FakeLLM(sd_repair_text=_CLEAN_SD)
    out, applied = _enforce_sd_prompt("black hair, brown eyes", _appearance(), "Kaito", llm, "hint")
    assert applied == "revised"
    assert out == _CLEAN_SD
    assert llm.calls == ["hint"]  # exactly one call


def test_enforce_sd_prompt_forbidden_terms_triggers_repair():
    dirty = _CLEAN_SD + " cinematic dramatic lighting"
    llm = FakeLLM(sd_repair_text=_CLEAN_SD)
    out, applied = _enforce_sd_prompt(dirty, _appearance(), "Kaito", llm, "hint")
    assert applied == "revised"
    assert _sd_prompt_issues(out) == []
    assert llm.calls == ["hint"]


def test_enforce_sd_prompt_clamps_overshooting_repair():
    # The one repair call overshoots (140 comma-separated words); the
    # deterministic clamp must bring it back to <= 60 without a second call.
    overshoot = ", ".join([f"detail{i}" for i in range(140)])
    llm = FakeLLM(sd_repair_text=overshoot)
    too_short = "black hair, brown eyes"  # forces the repair path
    out, applied = _enforce_sd_prompt(too_short, _appearance(), "Kaito", llm, "hint")
    assert applied == "revised"
    assert len(out.split()) <= 60
    assert llm.calls == ["hint"]  # still exactly one call


# --------------------------------------------------------------------------
# FIX 4 -- voice: LLM suggestion honored, uniqueness enforced
# --------------------------------------------------------------------------
class _FakeProfile:
    def __init__(self, role="ally", traits=None, core_drive="", core_fear="", speech_category=""):
        self.role = role
        self.personality = Personality(
            traits=traits or [], core_drive=core_drive, core_fear=core_fear
        )
        self.speech_style = SpeechStyle(category=speech_category)


def test_voice_for_honors_valid_free_suggestion():
    vid, collided = voice_for("am_adam", _FakeProfile(), "male", set())
    assert vid == "am_adam"
    assert collided is False


def test_voice_for_resolves_collision_when_suggestion_taken():
    taken = {"am_adam"}
    vid, collided = voice_for("am_adam", _FakeProfile(), "male", taken)
    assert vid == "bm_lewis"  # same-category alternative (young_energetic)
    assert collided is True


def test_voice_for_invalid_suggestion_falls_back_by_category():
    vid, collided = voice_for("not_a_voice", _FakeProfile(role="protagonist"), "male", set())
    assert vid in ("am_adam", "bm_lewis")
    assert collided is True


def test_voice_for_uniqueness_under_pressure():
    taken: set[str] = set()
    ids = []
    for _ in range(3):
        vid, _c = voice_for(
            "am_adam", _FakeProfile(role="antagonist", traits=["ruthless"]), "male", taken
        )
        taken.add(vid)
        ids.append(vid)
    assert len(set(ids)) == 3
    # villain_grave candidates: bm_george, am_michael; then fallback
    assert all(v in {"bm_george", "am_michael", "bm_lewis", "am_adam"} for v in ids)


def test_extract_profiles_unique_voice_ids(tmp_path):
    proj_dir = _make_project(tmp_path, slug="voices")
    llm = FakeLLM(
        profiles_by_name={
            "kaito": _profile_data("Kaito", role="protagonist", voice_id_suggestion="am_adam"),
            "eldrin": _profile_data("Eldrin", role="mentor", voice_id_suggestion="am_adam"),
            "mira": _profile_data("Mira", role="ally", voice_id_suggestion="am_adam"),
        }
    )
    chars = extract_profiles(proj_dir, ["Kaito", "Eldrin", "Mira"], llm)
    voice_ids = [c.voice_id_suggestion for c in chars]
    assert len(voice_ids) == len(set(voice_ids))
    assert chars[0].voice_id_suggestion == "am_adam"  # first keeps the suggestion


# --------------------------------------------------------------------------
# FIX 3 -- role integrity (at most one protagonist)
# --------------------------------------------------------------------------
def test_resolve_protagonists_keeps_most_mentioned():
    script = "Kaito Kaito Kaito fought. Eldrin watched once."
    chars = [
        Character(id="kaito", name="Kaito", role="protagonist"),
        Character(id="eldrin", name="Eldrin", role="protagonist"),
    ]
    _resolve_protagonists(chars, script)
    roles = {c.name: c.role for c in chars}
    assert roles["Kaito"] == "protagonist"
    assert roles["Eldrin"] == "ally"  # demoted


def test_resolve_protagonists_tie_breaks_on_first_appearance():
    script = "Bea entered. Later, Ana arrived."
    chars = [
        Character(id="ana", name="Ana", role="protagonist"),
        Character(id="bea", name="Bea", role="protagonist"),
    ]
    _resolve_protagonists(chars, script)
    roles = {c.name: c.role for c in chars}
    assert roles["Bea"] == "protagonist"  # appears first
    assert roles["Ana"] == "ally"


def test_extract_profiles_enforces_single_protagonist(tmp_path):
    proj_dir = _make_project(tmp_path, slug="oneprotag")
    llm = FakeLLM(
        profiles_by_name={
            "kaito": _profile_data("Kaito", role="protagonist"),
            "eldrin": _profile_data("Eldrin", role="protagonist"),
            "mira": _profile_data("Mira", role="ally"),
        }
    )
    chars = extract_profiles(proj_dir, ["Kaito", "Eldrin", "Mira"], llm)
    protags = [c for c in chars if c.role == "protagonist"]
    assert len(protags) == 1
    assert protags[0].name == "Kaito"  # more mentions in _SCRIPT


# --------------------------------------------------------------------------
# schema round-trip
# --------------------------------------------------------------------------
def test_character_and_worldbible_schema_round_trip():
    char = Character(
        id="kaito", name="Kaito", aliases=["the swordsman"],
        appearance_invented=True, sd_prompt="short appearance prompt",
        voice_id_suggestion="am_adam", role="protagonist",
    )
    wb = WorldBible(story_id="abc123", characters=[char])
    restored = WorldBible.model_validate_json(wb.model_dump_json())
    assert restored == wb
    assert restored.characters[0].appearance_invented is True


# --------------------------------------------------------------------------
# full run()
# --------------------------------------------------------------------------
def test_run_writes_partial_world_bible_and_records_bible_coverage(tmp_path):
    proj_dir = _make_project(tmp_path, slug="runtest")
    scores = Scores(proj_dir / "scores.sqlite")
    cfg = PipelineConfig.load()
    llm = FakeLLM(
        scan_names_by_chunk={0: ["Kaito", "Eldrin", "Mira"]},
        profiles_by_name={
            "kaito": _profile_data("Kaito", role="protagonist", voice_id_suggestion="am_adam"),
            "eldrin": _profile_data("Eldrin", role="mentor", voice_id_suggestion="am_eric"),
            "mira": _profile_data("Mira", role="ally", voice_id_suggestion="af_heart"),
        },
    )

    result = run_stage1(proj_dir, cfg, scores, llm=llm)

    assert result["status"] == "partial"
    assert result["profiles_count"] == 3
    assert not scores.is_done("stage1")
    assert scores.metrics_for("stage1")["bible_coverage"] == 1.0

    data = json.loads((proj_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8"))
    assert len(data["characters"]) == 3
    for c in data["characters"]:
        assert _empty_appearance_fields(Appearance(**c["appearance"])) == []  # 6/6
        assert 40 <= len(c["sd_prompt"].split()) <= 60
    voice_ids = [c["voice_id_suggestion"] for c in data["characters"]]
    assert len(voice_ids) == len(set(voice_ids))
    assert sum(1 for c in data["characters"] if c["role"] == "protagonist") == 1

    from pipeline.blueprint import Blueprint

    assert Blueprint.load(proj_dir).stages["stage1"].status == "running"
    scores.close()


def test_run_stage_cli_wires_stage1(tmp_path, monkeypatch):
    proj_dir = _make_project(tmp_path, slug="clitest")
    gate_scores = Scores(proj_dir / "scores.sqlite")
    gate_scores.record("stage0", "global", "structure_completeness", 1.0)
    gate_scores.stage_done("stage0")
    gate_scores.close()

    fake = FakeLLM(
        scan_names_by_chunk={0: ["Kaito"]},
        profiles_by_name={"kaito": _profile_data("Kaito", role="protagonist")},
    )
    monkeypatch.setattr("pipeline.stage1_worldbible.PipelineLLM", lambda *a, **k: fake)
    # stage1 now chains M2a -> M2b (stage1_world); stub M2b -- its logic has
    # its own tests and would otherwise call the live LLM here.
    monkeypatch.setattr(
        "pipeline.stage1_world.run",
        lambda project_dir, cfg, scores, **kw: {"stage": "stage1", "status": "done"},
    )

    result = run.run_stage("clitest", "stage1", projects_dir=proj_dir.parent)
    assert result["m2a"]["status"] == "partial"
    assert result["m2a"]["profiles_count"] == 1
    assert result["m2b"]["status"] == "done"
