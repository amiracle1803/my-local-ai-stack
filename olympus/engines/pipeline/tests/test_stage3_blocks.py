"""Stage 3 block partitioning: order labels, block budget, duration floor."""

from unittest.mock import MagicMock

from pipeline.stage3_storyboard import estimate_shot_seconds, partition_blocks, assign_motion


def _shot(i, words=30):
    return {
        "id": f"sh-{i:03d}",
        "narration": {"text": " ".join(["word"] * words)},
        "dialogue": [],
    }


def test_duration_floor():
    assert estimate_shot_seconds({"id": "x", "narration": None, "dialogue": []}) == 2.5


def test_pause_adds_time():
    shot = {"id": "x", "narration": None,
            "dialogue": [{"text": "hello there friend of mine", "pause_before_ms": 2000}]}
    assert estimate_shot_seconds(shot) > 2.5


def test_partition_respects_budget_and_orders():
    shots = [_shot(i, words=75) for i in range(12)]  # 30s each at 150wpm
    blocks = partition_blocks(shots, max_block_seconds=90.0)
    assert all(b["est_seconds"] <= 90.0 for b in blocks)
    assert blocks[0]["order"] == "first"
    assert blocks[-1]["order"] == "ending"
    assert all(b["order"] == "infill" for b in blocks[1:-1])
    # every shot lands in exactly one block, in story order
    flat = [s for b in blocks for s in b["shots"]]
    assert flat == [s["id"] for s in shots]


def test_single_block_story():
    blocks = partition_blocks([_shot(1)], max_block_seconds=90.0)
    assert len(blocks) == 1
    assert blocks[0]["order"] == "first"


def test_assign_motion_passes_character_names_to_llm():
    """assign_motion resolves character ids -> names so the motion prompt gets
    a real character action instead of the weak [character: none] (the stage3c
    weak-motion regression)."""
    shots = [{
        "id": "sh-001", "composition": "close-up", "beat": "Kana looks up",
        "characters_in_frame": ["kana"], "dialogue": [], "lipsync": False,
        "shot_type": "medium", "movement": "looks up slowly",
        "positioning": "standing at the shrine", "facial": "focused",
        "narration": None,
    }]
    config = MagicMock()
    config.animation.max_animated_seconds_per_block = 60.0
    config.animation.default_motion_tier = 1
    blocks = [{"shots": ["sh-001"], "est_seconds": 3.0}]

    llm = MagicMock()
    llm.complete_text.return_value = "[camera: slow push-in] [motion: scarf flutters] [character: Kana looks up]"

    class _C:  # minimal WorldBible stand-in
        characters = [type("Ch", (), {"id": "kana", "name": "Kana"})()]

    assign_motion(shots, config, blocks, llm, wb=_C())

    prompt = shots[0]["motion_prompt"]
    assert "Kana looks up" in prompt, prompt
    # the prompt template got the resolved name, not the raw id
    args = llm.complete_text.call_args[0][1]
    assert args["characters"] == "Kana", args["characters"]
    assert args["character_action"] == "looks up slowly"


def test_assign_motion_without_wb_uses_ids():
    """Without a world bible the raw character ids are passed through."""
    shots = [{
        "id": "sh-001", "composition": "wide", "beat": "arrives",
        "characters_in_frame": ["kana"], "dialogue": [], "lipsync": False,
        "shot_type": "medium", "movement": "arrives", "narration": None,
    }]
    config = MagicMock()
    config.animation.max_animated_seconds_per_block = 60.0
    config.animation.default_motion_tier = 1
    blocks = [{"shots": ["sh-001"], "est_seconds": 3.0}]
    llm = MagicMock()
    llm.complete_text.return_value = "[camera: static] [motion: none] [character: kana arrives]"
    assign_motion(shots, config, blocks, llm, wb=None)
    assert llm.complete_text.call_args[0][1]["characters"] == "kana"
