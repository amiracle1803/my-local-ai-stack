"""On-model consistency loop tests: canonical appearance spec + the extract-then-
compare stage3b panel gate + the stage_vlm_review clip gate (no GPU, no live VLM)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from pipeline.schemas.worldbible import Appearance, Character, WorldBible


# --------------------------------------------------------------------------
# appearance_spec / appearance_facts
# --------------------------------------------------------------------------


def test_appearance_spec_from_structured_fields():
    c = Character(
        id="rei", name="Rei",
        appearance=Appearance(hair="silver hair", eyes="cyan", skin="pale",
                              build="slender", clothing_primary="grey cloak",
                              distinguishing_feature="scar over left eyebrow"),
        gender="female", race="human", height="tall",
    )
    spec = c.appearance_spec()
    assert spec.startswith("Rei: ")
    for token in ("hair=silver hair", "eyes=cyan", "skin=pale", "build=slender",
                  "outfit=grey cloak", "distinguishing=scar over left eyebrow",
                  "gender=female", "race=human", "height=tall"):
        assert token in spec


def test_appearance_spec_falls_back_to_sd_prompt():
    c = Character(id="x", name="X", sd_prompt="a silver-haired girl in a red coat")
    assert c.appearance_spec() == "a silver-haired girl in a red coat"


def test_appearance_spec_empty_is_placeholder():
    c = Character(id="x", name="X")
    assert c.appearance_spec() == "X: (no canonical appearance)"


def test_appearance_facts_structured():
    c = Character(
        id="rei", name="Rei",
        appearance=Appearance(hair="silver", eyes="cyan", skin="pale",
                              clothing_primary="grey cloak"),
    )
    assert c.appearance_facts() == {
        "hair": "silver", "eyes": "cyan", "skin": "pale", "outfit": "grey cloak",
    }


# --------------------------------------------------------------------------
# extract-then-compare helpers
# --------------------------------------------------------------------------


def test_shot_appearance_returns_spec_and_facts():
    from pipeline.stage3b_images import _shot_appearance

    wb = WorldBible(story_id="s", characters=[
        Character(id="rei", name="Rei",
                  appearance=Appearance(hair="silver", eyes="cyan", clothing_primary="grey cloak")),
        Character(id="mika", name="Mika", appearance=Appearance(hair="black")),
    ])
    spec, facts = _shot_appearance({"characters_in_frame": ["rei", "mika"]}, wb)
    assert "hair=silver" in spec and "hair=black" in spec and "|" in spec
    assert facts == {"hair": "silver", "eyes": "cyan", "skin": "", "outfit": "grey cloak"}
    assert _shot_appearance({"characters_in_frame": []}, wb) == ("", {})
    assert _shot_appearance({"characters_in_frame": ["ghost"]}, wb) == ("", {})


def test_color_conflict():
    from pipeline.stage3b_images import _color_conflict

    assert _color_conflict("red", "black") is True            # substitution
    assert _color_conflict("black", "black") is False         # match
    assert _color_conflict("black with red highlights", "black") is False  # overlap
    assert _color_conflict("unknown", "black") is False       # no colour extracted
    assert _color_conflict("red", "") is False                # no canonical
    assert _color_conflict("dark", "dark") is False           # match
    assert _color_conflict("dark", "black") is False          # synonym group (black~dark)
    assert _color_conflict("red", "dark") is True             # substitution
    assert _color_conflict("blonde", "golden") is False       # synonym group (blonde~golden)


def test_appearance_verdict():
    from pipeline.stage3b_images import _appearance_verdict

    ok, issue = _appearance_verdict(
        {"hair_color": "black", "eye_color": "dark", "outfit": "dark jacket"},
        {"hair": "black", "eyes": "dark", "outfit": "dark jacket"},
    )
    assert ok and issue == ""
    ok, issue = _appearance_verdict(
        {"hair_color": "red", "eye_color": "red", "outfit": "dark jacket"},
        {"hair": "black", "eyes": "dark", "outfit": "dark jacket"},
    )
    assert not ok and "hair" in issue and "eyes" in issue


# --------------------------------------------------------------------------
# stage3b gate
# --------------------------------------------------------------------------


def test_enhance_prompt_injects_appearance_on_mismatch():
    from pipeline.stage3b_images import _enhance_prompt_for_vision

    detail = {"appearance_matches": False, "appearance_spec": "Rei: hair=silver"}
    shot = {"characters_in_frame": ["rei"]}
    enhanced = _enhance_prompt_for_vision("base prompt", shot, detail, None)
    assert "hair=silver" in enhanced
    # no injection when appearance matched (and other checks pass)
    detail_ok = {
        "characters_visible": 1,
        "background_matches": True,
        "composition_matches": True,
        "appearance_matches": True,
        "appearance_spec": "Rei: hair=silver",
    }
    assert _enhance_prompt_for_vision("base prompt", shot, detail_ok, None) == "base prompt"


def _make_judge_env(tmp_path, monkeypatch, content):
    from pipeline import stage3b_images as s3b

    panel = tmp_path / "panel.png"
    panel.write_bytes(b"fake")
    config = SimpleNamespace(models=SimpleNamespace(llm_vision="qwen2.5vl:7b"))
    shot = {"id": "sh-001-01", "characters_in_frame": ["rei"], "composition": "medium shot"}
    scene = {"location": "loc-x", "time_of_day": "night"}
    monkeypatch.setattr(s3b, "_try_nim_judge", lambda *a, **k: None)

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"message": {"content": content}}

    def fake_post(url, **kw):
        captured["payload"] = kw.get("json")
        return FakeResp()

    monkeypatch.setattr(s3b.requests, "post", fake_post)
    return s3b, panel, shot, scene, config, captured


def test_vision_judge_appearance_mismatch_blocks(tmp_path, monkeypatch):
    s3b, panel, shot, scene, config, captured = _make_judge_env(
        tmp_path, monkeypatch,
        '{"characters_visible":1,"background_matches":true,"composition_matches":true,'
        '"hair_color":"red","eye_color":"red","outfit":"dark jacket"}',
    )
    passed, detail = s3b.vision_judge(
        panel, shot, scene, config,
        appearance_facts={"hair": "black", "eyes": "dark", "outfit": "dark jacket"},
        appearance_spec="Rei: hair=black, eyes=dark",
    )
    assert passed is False
    assert detail["appearance_matches"] is False
    assert "hair" in detail["appearance_issue"] and "eyes" in detail["appearance_issue"]
    # extraction prompt is neutral (does not prime the answer)
    prompt = captured["payload"]["messages"][0]["content"]
    assert "hair_color" in prompt and "eye_color" in prompt


def test_vision_judge_appearance_match_passes(tmp_path, monkeypatch):
    s3b, panel, shot, scene, config, _ = _make_judge_env(
        tmp_path, monkeypatch,
        '{"characters_visible":1,"background_matches":true,"composition_matches":true,'
        '"hair_color":"black","eye_color":"dark","outfit":"dark jacket"}',
    )
    passed, detail = s3b.vision_judge(
        panel, shot, scene, config,
        appearance_facts={"hair": "black", "eyes": "dark", "outfit": "dark jacket"},
        appearance_spec="Rei: hair=black, eyes=dark",
    )
    assert passed is True
    assert detail["appearance_matches"] is True


def test_vision_judge_no_facts_skips_appearance(tmp_path, monkeypatch):
    s3b, panel, shot, scene, config, _ = _make_judge_env(
        tmp_path, monkeypatch,
        '{"characters_visible":1,"background_matches":true,"composition_matches":true,'
        '"hair_color":"","eye_color":"","outfit":""}',
    )
    passed, detail = s3b.vision_judge(panel, shot, scene, config, appearance_facts=None)
    assert passed is True
    assert detail["appearance_matches"] is True


# --------------------------------------------------------------------------
# stage_vlm_review clip gate
# --------------------------------------------------------------------------


def test_review_clip_includes_appearance_spec(tmp_path, monkeypatch):
    from pipeline import stage_vlm_review as svr

    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"fake")
    frames = []
    for i in range(3):
        p = tmp_path / f"kf_{i}.jpg"
        p.write_bytes(b"fake-frame")
        frames.append(p)
    monkeypatch.setattr(svr, "_extract_keyframes", lambda *a, **k: frames)

    captured = {}

    def fake_call(prompt, images, **kw):
        captured["prompt"] = prompt
        return (
            "1. Visual quality 8\n2. Motion smoothness 8\n3. Color consistency 8\n"
            "4. Character consistency 8\n5. Cinematic composition 8\n"
            "6. Physics plausibility 8\n7. Limb continuity 8\n"
            "8. Object permanence 8\n9. Motion logic 8\n10. Narrative continuity 8\n"
            "Verdict: PASS\n"
        )

    monkeypatch.setattr(svr, "_call_ollama", fake_call)
    shot = {"id": "sh-001-01", "sd_prompt": "anime scene", "characters_in_frame": ["rei"]}
    result = svr.review_clip(
        clip, shot, {"keyframes": {"count": 3}}, appearance_spec="Rei: hair=silver"
    )
    assert "hair=silver" in captured["prompt"]
    assert result["verdict"] == "PASS"
