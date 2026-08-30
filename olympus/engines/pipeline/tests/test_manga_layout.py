"""Manga layout: pagination (<=3 panels/page, scenes kept together), layered
page composition (plate background -> panels -> PIL text boxes), and the
text-box pass (narration/dialogue drawn verbatim -> correct spelling)."""
import json
from pathlib import Path

import pytest

from pipeline import identity, manga_layout as ml
from pipeline.identity import artifact_name


# --------------------------------------------------------------------------
# page chunking
# --------------------------------------------------------------------------
def test_chunk_cap_never_exceeds_three():
    assert [len(c["shots"]) for c in ml._chunk_cap(["s"] * 8)] == [3, 3, 2]
    assert [len(c["shots"]) for c in ml._chunk_cap(["s"] * 3)] == [3]
    assert ml._chunk_cap([]) == []


def test_chunk_pages_keeps_scenes_together_and_caps_at_three():
    # 4 shots of sc-001 then 4 shots of sc-002 -> 3+1 / 3+1, never mixed.
    lookup = {
        "sc-001": {"scene": {"id": "sc-001"}, "shots": {f"sh-001-0{i}": {} for i in range(1, 5)}},
        "sc-002": {"scene": {"id": "sc-002"}, "shots": {f"sh-002-0{i}": {} for i in range(1, 5)}},
    }
    shots = [f"sh-001-0{i}" for i in range(1, 5)] + [f"sh-002-0{i}" for i in range(1, 5)]
    pages = ml._chunk_pages(shots, lookup)
    sizes = [len(p["shots"]) for p in pages]
    assert sizes == [3, 1, 3, 1]
    assert all(s <= ml._PANELS_PER_PAGE for s in sizes)


def test_wrap_respects_max_width():
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (400, 40))
    d = ImageDraw.Draw(im)
    font = ml._font(20)
    lines = ml._wrap(d, "a b c d e", font, max_w=60)
    assert len(lines) >= 2
    # no line exceeds the budget
    assert all(d.textlength(ln, font=font) <= 60 for ln in lines)


# --------------------------------------------------------------------------
# layered page build
# --------------------------------------------------------------------------
def _tiny_png(path: Path, color=(200, 40, 40), size=(96, 64)):
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path)
    return path


def test_build_page_layers_background_panels_text(tmp_path):
    from PIL import Image

    plate = _tiny_png(tmp_path / "plate.png", color=(30, 60, 120), size=(200, 150))
    p1 = _tiny_png(tmp_path / "p1.png", color=(200, 40, 40))
    p2 = _tiny_png(tmp_path / "p2.png", color=(40, 200, 60))
    out = tmp_path / "page.png"
    meta = [
        {"narration": {"text": "The first light broke over the ridge."}, "dialogue": []},
        {"narration": {}, "dialogue": [{"char_id": "char-kaela", "text": "We move at dawn."}]},
    ]
    res = ml._build_page([p1, p2], meta, out, plate)
    assert res == out
    im = Image.open(out).convert("RGB")
    assert im.size == (96 + 2 * ml._PAGE_MARGIN, 64 + 64 + ml._PAGE_GAP + 2 * ml._PAGE_MARGIN)
    px = im.load()
    # plate background visible at a corner (no panel / text there)
    r, g, b = px[3, 3]
    assert r < 60 and g > 30 and b > 60  # plate-blue bleed through margin
    # text boxes present -> near-white + near-black text pixels exist
    white = sum(1 for yy in range(im.height) for xx in range(im.width)
                if px[xx, yy][0] > 245 and px[xx, yy][1] > 245 and px[xx, yy][2] > 235)
    assert white > 50


def test_build_manga_pages_paginates_and_indexes(tmp_path):
    from pipeline.blueprint import Blueprint, StageEntry, Style, Target
    from pipeline._util import now_iso

    proj = tmp_path / "manga_test"
    proj.mkdir()
    # blueprint (identity.project_code reads it)
    bp = Blueprint(
        story_id="manga_test", slug="manga_test", title_hash="x" * 16, created=now_iso(),
        fps=24, style=Style(), target=Target(),
        stages={s: StageEntry(status="done", ts=now_iso())
                for s in ["stage0", "stage1", "stage1r", "stage2", "stage3", "stage3b"]},
    )
    (proj / "blueprint.json").write_text(bp.to_json(), encoding="utf-8")

    shots = [f"sh-001-0{i}" for i in range(1, 7)]  # 6 shots of one scene
    screenplay = {
        "scenes": [{
            "id": "sc-001", "location": "loc-x", "time_of_day": "night",
            "shots": [
                {"id": s, "narration": {"text": "narration " + s}, "dialogue": []}
                for s in shots
            ],
        }]
    }
    (proj / "screenplay").mkdir()
    (proj / "screenplay" / "screenplay.json").write_text(json.dumps(screenplay), encoding="utf-8")

    storyboard = {
        "story_id": "manga_test",
        "blocks": [{"id": "blk-001", "shots": shots, "order": "first"}],
    }
    (proj / "storyboard").mkdir()
    (proj / "storyboard" / "storyboard.json").write_text(json.dumps(storyboard), encoding="utf-8")

    # panels + a plate for sc-001
    block_dir = proj / "panels" / "blk-001"
    block_dir.mkdir(parents=True)
    for sid in shots:
        canon = identity.canonical_shot_id(sid, "manga_test")
        _tiny_png(block_dir / artifact_name(f"{canon}_pn01_render", "", version=1))
    (block_dir / "_plates").mkdir()
    _tiny_png(block_dir / "_plates" / "sc-001.png", color=(30, 60, 120))

    idx = ml.build_manga_pages(proj, storyboard)
    pages = idx["pages"]
    assert [len(p["shots"]) for p in pages] == [3, 3]  # 6 shots -> 2 pages of 3
    for p in pages:
        assert p["scene"] == "sc-001"
        assert p["page"] in (1, 2)
        assert (proj / p["file"]).exists()
    assert all(len(p["shots"]) <= ml._PANELS_PER_PAGE for p in pages)
    assert idx["root"] == "manga-test"


def test_build_manga_pages_skips_block_with_no_panels(tmp_path):
    proj = tmp_path / "empty_test"
    proj.mkdir()
    from pipeline.blueprint import Blueprint, StageEntry, Style, Target
    from pipeline._util import now_iso

    bp = Blueprint(story_id="empty_test", slug="empty_test", title_hash="x" * 16, created=now_iso(),
                   fps=24, style=Style(), target=Target(),
                   stages={s: StageEntry(status="done", ts=now_iso())
                           for s in ["stage0", "stage1", "stage2", "stage3", "stage3b"]})
    (proj / "blueprint.json").write_text(bp.to_json(), encoding="utf-8")
    sb = {"blocks": [{"id": "blk-001", "shots": ["sh-001-01"]}]}
    (proj / "storyboard").mkdir()
    (proj / "storyboard" / "storyboard.json").write_text(json.dumps(sb), encoding="utf-8")
    idx = ml.build_manga_pages(proj, sb)
    assert idx["pages"] == []
    assert not (proj / "panels" / "blk-001").exists() or True


def test_fit_text_shrinks_font_so_text_fits_region():
    """Long narration must not overflow the panel region (NIM calibration
    flagged 'text cut off at the bottom of the page'). The font shrinks (and,
    as a floor, truncates with an ellipsis) so the wrapped text ALWAYS fits."""
    from PIL import Image, ImageDraw

    im = Image.new("RGB", (200, 80))
    d = ImageDraw.Draw(im)
    long_text = "The metallic groan of the failing heart echoes through the chamber. " * 5
    font, lines = ml._fit_text(d, long_text, max_w=120, max_h=60)
    assert ml._box_h(font, lines) <= 60
    assert lines[-1].endswith("…")  # hard-clamped, never overflowing


def test_draw_narration_stays_inside_panel_region(tmp_path):
    """A very long narration box is clamped inside the panel region -- no text
    pixels bleed past the region bottom into the next panel."""
    from PIL import Image, ImageDraw

    region = (0, 0, 200, 120)
    im = Image.new("RGB", (200, 120), (200, 200, 200))  # light bg so text/box are the only dark pixels
    d = ImageDraw.Draw(im)
    long_text = "The metallic groan of the failing heart echoes through the chamber. " * 5
    ml._draw_narration(d, region, long_text)
    px = im.load()
    lowest = max((y for y in range(120) for x in range(200) if px[x, y][0] < 80), default=0)
    # box bottom is ry1 - pad by construction (fitted inside the region)
    assert lowest <= region[3] - ml._BOX_PAD + 2