"""stage0 cloud writer (2026-11-21): plan -> draft -> editor notes -> revision; source scripts adapted."""

import json
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent.parent
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline import models, writer  # noqa: E402

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

    def fake(url, key, model, messages, temperature, max_tokens, timeout=300, json_mode=False):
        seen.append(model)
        if model == "bad":
            raise RuntimeError("HTTP 500")
        return "ok"

    monkeypatch.setattr(models, "_openai", fake)
    monkeypatch.setattr(models, "_key", lambda name: "k")
    chat = writer.make_chat(["groq:bad", "groq:good"])
    assert chat([{"role": "user", "content": "x"}]) == "ok" and chat.used == "groq:good"
    chat([{"role": "user", "content": "x"}])
    assert seen == ["bad", "good", "good"]          # the working model moves to the front


def test_wat_gateway_groups_are_usable(monkeypatch):
    """wat:<group> = the owner's W.A.T. gateway (all their keys); an empty reply falls through."""
    calls = []
    monkeypatch.setattr(models, "_wat", lambda g, m, t, n: calls.append(g) or ("" if g == "xpl-smart" else "story"))
    monkeypatch.setattr(models, "_openai", lambda *a, **k: calls.append("groq") or "groq story")
    chat = models.make_chat(["wat:xpl-smart", "wat:reasoning", "groq:openai/gpt-oss-120b"])
    assert chat([{"role": "user", "content": "x"}]) == "story" and chat.used == "wat:reasoning"
    assert calls == ["xpl-smart", "reasoning"]
    from stack.config import cfg
    assert any(m.startswith("wat:") for m in cfg.writer.models) and any(m.startswith("wat:") for m in cfg.director.models)


def test_director_tries_the_next_model_when_a_reply_is_not_json(monkeypatch, tmp_path):
    from pipeline import director
    replies = {"wat:a": "not json", "wat:b": json.dumps({"shots": [{"id": "s1", "t2i": "a tower at dusk"}]})}
    monkeypatch.setattr(director, "_model_chain", lambda: [(k, (lambda m, k=k: replies[k])) for k in replies])
    out = director.direct([{"id": "s1"}], {}, {}, tmp_path / "d.json")
    assert out["s1"]["t2i"].startswith("a tower") and out["s1"]["by"] == "wat:b"


def test_notes_after_a_spoken_line_move_in_front():
    out = writer._clean("SCENE 1 — Hill\nKael: We hold the pass tonight. (My knuckles whiten as I grip the hilt; voice hollow)\n"
                        "Kael: (quiet) Not again. (blood on my arm)")
    assert "Kael: (My knuckles whiten as I grip) We hold the pass tonight." in out
    assert "Kael: (quiet) Not again." in out and "blood" not in out


def test_echoed_lines_are_dropped_and_run_ons_flagged():
    out = writer._clean("SCENE 1 — Hill\nKael: The bloodline holds.\n(Kael exhales slowly) The bloodline holds.\n\nThe sun rises.")
    assert out.count("The bloodline holds.") == 1 and "The sun rises." in out
    long = "SCENE 1 — Hill\n" + " ".join(["word"] * 40) + ".\n\nKAEL: We hold the pass tonight."
    assert any("average" in p for p in writer.problems(long, 1, 5))
