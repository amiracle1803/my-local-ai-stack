"""Stage 2 deterministic pieces: SD prompt assembly (120-word budget, trim
order, no names) and the narration-issue filter."""

from pipeline.schemas.worldbible import Appearance, Character, WorldBible
from pipeline.stage2_screenplay import (
    _PROMPT_WORD_BUDGET,
    _load_banned_patterns,
    _narration_issues,
    assemble_sd_prompt,
)


def _wb(anchor_words=50, loc_words=30):
    char = Character(
        id="char-rin", name="Rin",
        appearance=Appearance(hair="red"),
        sd_prompt=" ".join(f"tag{i}" for i in range(anchor_words)),
    )
    return WorldBible(
        story_id="s1",
        characters=[char],
        locations=[{
            "id": "loc-academy", "name": "Academy",
            "description": "old stone school",
            "sd_prompt": " ".join(f"loc{i}" for i in range(loc_words)),
            "recurring": True,
        }],
    )


def _shot(**over):
    shot = {
        "characters_in_frame": ["char-rin"],
        "composition": "wide shot, low angle",
        "positioning": "character left third",
    }
    shot.update(over)
    return shot


def _scene():
    return {"location": "loc-academy", "time_of_day": "night"}


def test_prompt_within_budget_and_nameless():
    wb = _wb()
    prompt = assemble_sd_prompt(_shot(), _scene(), wb)
    assert len(prompt.split()) <= _PROMPT_WORD_BUDGET
    assert "Rin" not in prompt
    assert "cel shading" in prompt  # style tail always survives


def test_overflow_trims_composition_before_location():
    wb = _wb(anchor_words=80, loc_words=30)
    long_comp = " ".join(f"comp{i}" for i in range(40))
    prompt = assemble_sd_prompt(_shot(composition=long_comp, positioning=""), _scene(), wb)
    words = prompt.split()
    assert len(words) <= _PROMPT_WORD_BUDGET + 10  # commas join words; small slack
    assert "tag79" in prompt  # anchors never trimmed
    assert "loc0" in prompt  # location survives before composition does


def test_narration_filter_catches_banned_and_length(tmp_path):
    banned = _load_banned_patterns(tmp_path)
    assert _narration_issues("Little did he know the storm was coming for them all today.", banned, [])
    assert _narration_issues("Too short.", banned, [])
    ok = "The blacksmith hammers the blade flat while sparks scatter across the dark workshop floor around her feet."
    assert not _narration_issues(ok, banned, [])


def test_ltx_clip_segment_loops_short_clip_to_fill_shot():
    """Regression: a ~5s motion clip over a 9-12s shot must loop (not just trim)
    so the video stream no longer runs short against the audio -> av desync."""
    from pathlib import Path
    from pipeline.stage5_assembly import _build_segment_args

    clip = Path("/tmp/opencode/fake_clip.mp4")
    clip.touch()
    args = _build_segment_args(
        panel_path=None,
        seg_path=Path("/tmp/opencode/seg.mp4"),
        dur=10.0,
        fps=24,
        drift={"axis": "vertical", "direction": 1, "pixels": 80},
        audio_paths=[Path("/tmp/opencode/nar.wav")],
        clip_path=clip,
    )
    # clip input must loop so a 5s clip fills a 10s shot
    assert "-stream_loop" in args and "-1" in args
    # exactly one trim bound at the full shot duration
    vf = args[args.index("-filter_complex") + 1]
    assert f"trim=0:10.000" in vf


def test_narration_filter_catches_repeated_opener(tmp_path):
    banned = _load_banned_patterns(tmp_path)
    line = "The morning sun climbs over the ridge as the caravan finally rolls out of the valley."
    assert _narration_issues(line, banned, ["the morning sun"])
