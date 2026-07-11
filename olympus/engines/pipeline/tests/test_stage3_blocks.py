"""Stage 3 block partitioning: order labels, block budget, duration floor."""

from pipeline.stage3_storyboard import estimate_shot_seconds, partition_blocks


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
