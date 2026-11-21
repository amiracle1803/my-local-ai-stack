"""stage0 cloud writer (2026-11-21): plan -> draft -> editor notes -> revision; source scripts adapted."""

import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline import writer  # noqa: E402

SOURCE = ("SCENE 1 - The Hill\n\nKael sharpens a blade.\n\nKael: We hold the pass tonight.\n\n"
          "SCENE 2 - Dawn\n\nThe sun rises.\n\nKael: The bloodline holds.")
BRIEF = "Style: manhwa\nNarration: recap, first person as Kael\nCast: Kael (swordsman)\n\nSOURCE SCRIPT:\n" + SOURCE


def _script(words: int, lines=("We hold the pass tonight.", "The bloodline holds.")) -> str:
    filler = " ".join(["The storm turns."] * (words // 6))
    return (f"SCENE 1 — Hill, dusk\n{filler}\n\nKAEL: {lines[0]}\n\n"
            f"SCENE 2 — Valley, dawn\n{filler}\n\nKAEL: (quiet) {lines[1]}")


def test_split_source_and_missing_lines():
    head, src = writer.split_source(BRIEF)
    assert "SOURCE" not in head and src.startswith("SCENE 1")
    assert writer.missing_lines(src, _script(100)) == []
    assert writer.missing_lines(src, _script(100, ("We hold the pass.", "The bloodline holds."))) == [
        ("KAEL", "We hold the pass tonight.")]


def test_write_episode_keeps_the_best_valid_revision():
    calls = []

    def chat(messages, temperature=0.8, max_tokens=6000):
        calls.append(messages[-1]["content"])
        n = len(calls)
        if n == 1:
            return "plan notes"
        if n == 2:
            return _script(300)
        if n == 3:
            return "1. fix the hook"
        if n == 4:          # revision lost a source line -> rejected, fixed on the next pass
            return _script(300, ("We hold it.", "The bloodline holds."))
        return "```\n" + _script(320) + "\n```"

    out = writer.write_episode(BRIEF, 300, chat, log=lambda m: None)
    assert out and "We hold the pass tonight." in out and "```" not in out
    assert "first person as Kael" in calls[1] and "WORD FOR WORD" in calls[1]
    assert "source line missing or changed: KAEL: We hold the pass tonight." in calls[4]


def test_chat_falls_through_to_the_next_model(monkeypatch):
    seen = []

    def fake(url, key, model, messages, temperature, max_tokens, timeout=300):
        seen.append(model)
        if model == "bad":
            raise RuntimeError("HTTP 500")
        return "ok"

    monkeypatch.setattr(writer, "_openai", fake)
    monkeypatch.setattr(writer, "_key", lambda name: "k")
    chat = writer.make_chat(["groq:bad", "groq:good"])
    assert chat([{"role": "user", "content": "x"}]) == "ok" and chat.used == "groq:good"
    chat([{"role": "user", "content": "x"}])
    assert seen == ["bad", "good", "good"]          # the working model moves to the front
