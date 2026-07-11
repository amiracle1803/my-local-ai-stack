"""Stage 1 M2b deterministic pieces: voice registry determinism + location
sd_prompt clamp."""

import json

from pipeline.schemas.worldbible import Character, WorldBible
from pipeline.stage1_world import _location_sd_prompt, write_voice_registry


def _wb():
    return WorldBible(
        story_id="s1",
        characters=[
            Character(id="char-rin", name="Rin", voice_id_suggestion="af_heart", role="protagonist"),
            Character(id="char-kai", name="Kai", voice_id_suggestion="am_adam", role="ally"),
        ],
    )


def test_voice_registry_deterministic(tmp_path):
    script = "Rin ran. Kai followed. Rin won."
    v1 = write_voice_registry(tmp_path, _wb(), script)
    v2 = write_voice_registry(tmp_path, _wb(), script)
    assert v1 == v2
    assert v1["_narrator"]["base"] == "af_bella"
    assert set(v1) == {"char-rin", "char-kai", "_narrator"}
    on_disk = json.loads((tmp_path / "voices.json").read_text())
    assert on_disk == v2


def test_voice_base_collision_gets_speed_offset(tmp_path):
    wb = _wb()
    wb.characters[1].voice_id_suggestion = "af_heart"  # force base collision
    voices = write_voice_registry(tmp_path, wb, "Rin and Kai.")
    speeds = {voices["char-rin"]["speed"], voices["char-kai"]["speed"]}
    assert len(speeds) == 2  # distinctness gate: same base -> different speed


def test_location_prompt_clamped_to_60_words():
    prompt = _location_sd_prompt("Academy", " ".join(["word"] * 100), "fantasy-medieval")
    assert len(prompt.split()) <= 60
    assert prompt.startswith("Academy")
