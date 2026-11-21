"""Episode writer (2026-11-21): a big cloud model drafts, an editor critiques, the writer revises.

Replaces the local 8B one-scene-at-a-time writer as the first choice for stage0 (that one stays as
the fallback). Models come from stack.toml [writer] models, tried in order, each "provider:model":
groq:<id> (GROQ_API_KEY), nim:<id> (NVIDIA key), ollama:<id> (local).

A brief may carry a source script after a line "SOURCE SCRIPT:". The writer then ADAPTS it: every
scene in order, every event, every spoken line word for word by the same speaker; it adds the
narration, inner voice and short new lines that turn a one-page script into a full episode.
"""
from __future__ import annotations

import difflib
import json
import re
import urllib.error
import urllib.request
from typing import Callable

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
NIM_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
SOURCE_MARK = re.compile(r"(?im)^\s*SOURCE SCRIPT:?\s*$")
SCENE_LINE = re.compile(r"(?im)^\s*SCENE\s+\d+\s*[-—–:.]\s*(.+)$")
SPOKEN = re.compile(r"(?m)^\s*([A-Z][A-Za-z' -]{0,30}):\s*(?:\([^)]*\)\s*)?(.+?)\s*$")

Chat = Callable[[list[dict], float, int], str]

CRAFT = """You are the head writer of a top manhwa-recap animation channel. You write scripts that hold
viewers for the full video. Every narration paragraph becomes one illustrated panel on screen, and
every spoken line is voiced by an actor.

CRAFT RULES
- Concrete and visual: name the exact thing we see (the notch in the blade, rain running off a
  roof, a child's hand pulled from a doorway). No vague adjectives doing the work.
- One paragraph = one picture: 1-3 sentences describing one moment an artist can draw, plus the
  narrator's reaction to it.
- Every scene has a want, an obstacle and a turn. End every scene on a turn or a question that
  makes the next scene necessary.
- Escalate: each scene raises the stakes or the cost.
- Dialogue is short, in character, with subtext. Never repeat in dialogue what narration just said.
- Show, don't explain: no lines like "I felt scared". Show the body, the choice, the action.
- Banned phrases: "little did I know", "a chill ran down my spine", "in that moment", "suddenly",
  "I couldn't believe", "my heart pounded", "deafening silence", "time seemed to stop",
  "everything changed", "for what felt like an eternity", "I let out a breath I didn't know",
  "heart like a drum", "a promise forged in", "ghosts of my ancestors".
- Never describe the same thing twice (weather, light, a sound): each paragraph moves the story.
- Plot over atmosphere: something happens, is decided, or is revealed in most paragraphs.
- Vary sentence length. Mostly short, sometimes one long sentence for a big image.
"""

FORMAT = """FORMAT (plain text only: no markdown, no asterisks, no title line, no notes):
SCENE 1 — <place, time of day>
<narration paragraph>

NAME: <spoken line>
NAME: (short delivery note) <spoken line>

<narration paragraph>

SCENE 2 — <place>
...
Every spoken line is on its own line as NAME: line, never inside narration. Blank line between
paragraphs. Only characters from the Cast speak; NARRATOR never appears as a speaker."""


def _recap(brief: str) -> str:
    m = re.search(r"(?im)^\s*Narration:\s*([^\n]+)", brief or "")
    if not m or "recap" not in m.group(1).lower():
        return "Narration is third person, past tense, cinematic."
    who = re.search(r"(?i)\bas\s+([A-Z][\w' -]{0,30})", m.group(1))
    pov = who.group(1).strip() if who else "the main character"
    return (f"NARRATION: first person as {pov} (I / me / my), present tense, told like a recap channel: "
            "short punchy sentences, inner thoughts, dramatic turns. Scene 1 opens with a one-line hook "
            "that names the biggest stake or twist before anything else.")


def split_source(brief: str) -> tuple[str, str]:
    """(brief without the source, source script or "")."""
    m = SOURCE_MARK.search(brief or "")
    if not m:
        return brief, ""
    return brief[:m.start()].rstrip(), brief[m.end():].strip()


def spoken_lines(text: str) -> list[tuple[str, str]]:
    return [(n.strip().upper(), l.strip()) for n, l in SPOKEN.findall(text or "")
            if n.strip().upper() not in ("SCENE", "NARRATOR", "SOURCE SCRIPT")]


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


def missing_lines(source: str, script: str) -> list[tuple[str, str]]:
    """Source spoken lines the script lost or reworded (same speaker, near-verbatim)."""
    have = [(n, _norm(l)) for n, l in spoken_lines(script)]
    out = []
    for name, line in spoken_lines(source):
        want = _norm(line)
        if not any(n == name and (want in l or difflib.SequenceMatcher(None, want, l).ratio() > 0.9)
                   for n, l in have):
            out.append((name, line))
    return out


def problems(script: str, n_scenes: int, word_target: int, source: str = "") -> list[str]:
    out = []
    got = len(re.findall(r"(?im)^\s*SCENE\s+\d+", script))
    if n_scenes and got != n_scenes:
        out.append(f"has {got} SCENE headings, needs exactly {n_scenes}")
    words = len(script.split())
    if words < word_target * 0.7:
        out.append(f"only {words} words, needs about {word_target}")
    if not spoken_lines(script):
        out.append("no spoken lines in NAME: line format")
    for name, line in missing_lines(source, script)[:8]:
        out.append(f'source line missing or changed: {name}: {line}')
    return out


# ---------------------------------------------------------------- model calls

def _key(name: str) -> str:
    from . import director, nim_vision
    return nim_vision._api_key() if name == "nim" else director._key("GROQ_API_KEY")


def _openai(url: str, key: str, model: str, messages: list[dict], temperature: float, max_tokens: int,
            timeout: int = 300) -> str:
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = "medium"
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}",
        "User-Agent": "olympus-writer/1.0"})
    import time
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return (json.load(r)["choices"][0]["message"].get("content") or "").strip()
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 2:
                raise RuntimeError(f"{model} HTTP {e.code}") from e
            time.sleep(min(60.0, float(e.headers.get("retry-after") or 20)))
    return ""


def make_chat(models: list[str]) -> Chat:
    """A chat fn that tries each "provider:model" in order and remembers the first that works."""
    order = list(models)

    def chat(messages: list[dict], temperature: float = 0.8, max_tokens: int = 6000) -> str:
        errors = []
        for spec in list(order):
            provider, _, model = spec.partition(":")
            try:
                if provider == "groq":
                    text = _openai(GROQ_URL, _key("groq"), model, messages, temperature, max_tokens)
                elif provider == "nim":
                    text = _openai(NIM_URL, _key("nim"), model, messages, temperature, max_tokens)
                elif provider == "ollama":
                    from .llm import ollama_generate
                    res = ollama_generate("\n\n".join(m["content"] for m in messages), model=model,
                                          timeout=900, num_predict=max_tokens, temperature=temperature,
                                          think=False)
                    text = res.text if res else ""
                else:
                    continue
                if text:
                    if order[0] != spec:          # stick with the model that answered
                        order.remove(spec)
                        order.insert(0, spec)
                    chat.used = spec
                    return text
            except Exception as e:  # noqa: BLE001  (try the next model)
                errors.append(f"{spec}: {e}")
        raise RuntimeError("no writer model answered: " + "; ".join(errors))

    chat.used = ""
    return chat


# ---------------------------------------------------------------- the writer

def _clean(text: str) -> str:
    text = re.sub(r"(?s)<think>.*?</think>", "", text)
    text = re.sub(r"(?m)^\s*```\w*\s*$", "", text)
    text = text.replace("**", "").replace("__", "")
    start = re.search(r"(?im)^\s*SCENE\s+1\b", text)
    return (text[start.start():] if start else text).strip()


def write_episode(brief: str, word_target: int, chat: Chat, log: Callable[[str], None] = print) -> str | None:
    """Draft -> editor notes -> revision, checked against the scene list and source lines."""
    from .stages import normalize_script
    head, source = split_source(brief)
    head = "\n".join(l for l in head.splitlines() if not re.match(r"(?i)^\s*voices:", l))
    scenes = SCENE_LINE.findall(source) or SCENE_LINE.findall(head)
    n = len(scenes)
    task = [f"Write the full episode script: about {word_target} words"
            + (f", exactly {n} scenes, in the order given" if n else ", 3-6 scenes") + ".", _recap(head)]
    if source:
        task.append("ADAPT THE SOURCE SCRIPT BELOW. Keep every scene in order, every event, and every "
                    "spoken line WORD FOR WORD by the same speaker (you may add a delivery note). Add the "
                    "narration, inner voice, sensory detail and a few short new lines that make it a full "
                    "episode. Never contradict the source or change its ending.")
    user = "\n\n".join(task) + f"\n\n{FORMAT}\n\nBRIEF:\n{head[:3000]}" + (f"\n\nSOURCE SCRIPT:\n{source}" if source else "")
    system = {"role": "system", "content": CRAFT}
    plan = chat([system, {"role": "user", "content":
                 "Before writing, plan the episode. Answer in short notes:\n"
                 "1. HOOK: the one line that opens scene 1 (biggest stake or twist).\n"
                 "2. STAKES: what the narrator loses if they fail, concretely (a person, a place, a promise).\n"
                 "3. BACKSTORY: the history the material implies but does not say (who was lost before, what "
                 "an oath or name means, why the narrator is alone). Make it specific and personal.\n"
                 "4. SETUPS AND PAYOFFS: 2-3 objects, wounds or words planted early that pay off later.\n"
                 "5. PER SCENE: want, obstacle, turn, the image that ends it.\n"
                 "6. NEW LINES: a few short new spoken lines or moments that would make it hit harder.\n\n"
                 + user}], 0.8, 3000)
    log(f"  writer plan: {len(plan.split())} words")
    user += f"\n\nYOUR STORY PLAN (follow it):\n{plan}"
    draft = _clean(chat([system, {"role": "user", "content": user}], 0.85, 8000))
    log(f"  writer draft: {len(draft.split())} words ({getattr(chat, 'used', '')})")
    notes = chat([{"role": "system", "content": "You are a demanding story editor for a manhwa-recap channel."},
                  {"role": "user", "content":
                   "Give the 6-10 most important concrete fixes for this script, as a numbered list. Check: "
                   "is the hook strong; does every scene have a want, obstacle and turn and end on a pull "
                   "forward; are there vague or clichéd lines (quote them); does dialogue repeat narration; "
                   "can every narration paragraph be drawn as one picture; does it escalate; is the "
                   "narrator's voice distinct. Quote the exact weak lines. No praise.\n\n"
                   + (f"Source lines that must stay word for word: {spoken_lines(source)}\n\n" if source else "")
                   + f"SCRIPT:\n{draft}"}], 0.3, 3000)
    log(f"  writer notes: {len(notes.splitlines())} lines")
    best, best_bad = draft, problems(normalize_script(draft), n, word_target, source)
    fix = notes
    for attempt in range(2):
        rev = _clean(chat([system, {"role": "user", "content":
                          f"{user}\n\nYOUR DRAFT:\n{draft}\n\nEDITOR NOTES:\n{fix}\n\nRewrite the full script "
                          f"applying every note. Keep it about {word_target} words (the draft has "
                          f"{len(draft.split())}): replace weak lines, do not cut scenes short. "
                          "Output only the script."}], 0.7, 8000))
        bad = problems(normalize_script(rev), n, word_target, source)
        log(f"  writer revision {attempt + 1}: {len(rev.split())} words, {len(bad)} problems")
        if len(bad) <= len(best_bad):
            best, best_bad = rev, bad
        if not bad:
            break
        draft, fix = rev, "Fix these hard problems first:\n- " + "\n- ".join(bad) + "\n\nThen:\n" + notes
    if best_bad:
        log("  writer leftover problems: " + "; ".join(best_bad))
    script = normalize_script(best)
    return script if len(script.split()) >= 0.5 * word_target and spoken_lines(script) else None
