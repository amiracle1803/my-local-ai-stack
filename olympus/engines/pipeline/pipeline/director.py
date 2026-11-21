"""Director pass: per shot, the detail the renderers need, written by an LLM "director".

For every storyboard shot it writes (storyboard/director.json, keyed by shot id):
  t2i       - a full text-to-image prompt: subject + exact cast looks, pose, expression, composition,
              lens/angle, lighting, palette, background detail, mood, style
  negative  - what to keep out of the frame
  camera    - the camera move for the clip (push-in, pan left, static, orbit...)
  motion    - the image-to-video motion beat: what moves in the frame and how, in one clip
  strength  - motion strength 0.0-1.0 (SVD motion bucket / LTX image strength)
  t2v       - a single chronological paragraph for text-to-video (LTX style: visible subject + action,
              exact appearance, unobstructed composition, background, camera, lighting)
  seconds   - suggested clip length (2-6 s)
  beats     - up to n_beats follow-up key frames (full t2i prompts) for panels mode, where a long
              shot plays as a sequence of stills instead of a clip
  dynamic edit only ([edit] dynamic = true, manhwa-recap style):
  moves     - one camera move per frame (t2i frame first, then each beat), see MOVES
  ui        - "" or one short game-style SYSTEM window text for this shot
  caption   - "" or a 1-4 word dramatic on-screen caption
  mood      - the shot's music mood, see MOODS

Cloud first (Groq, OpenAI-compatible, key GROQ_API_KEY from the environment or ~/.hermes/.env),
then the local Ollama script model. A shot the LLM leaves out or garbles falls back to the
template prompt, so the pipeline never does worse than before the director existed.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = os.environ.get("OLYMPUS_DIRECTOR_MODEL", "openai/gpt-oss-120b")
BATCH = 10            # shots per LLM call (one scene at a time, split if longer)

SYSTEM = (
    "You are the director and cinematographer of an anime series. For each shot you receive, write "
    "the production prompts the renderers need. Rules:\n"
    "- Keep every character's look EXACTLY as given in CAST (hair, clothing, colors) in every shot.\n"
    "- Only the characters listed for that shot appear; never add others.\n"
    "- Never put spoken words, captions, speech bubbles or text in an image prompt.\n"
    "- One single 16:9 frame per shot (no comic panels, no split screen).\n"
    "- Be concrete and visual: pose, expression, composition, lens/angle, lighting, palette, background.\n"
    "- motion = what moves during a 2-6 second clip starting from that frame (subject + camera). "
    "Never let smoke, fog, breath, steam, particles, hair or hands drift across a face; faces stay "
    "clearly visible. Keep camera moves gentle for wide shots where faces are small.\n"
    "- t2v = one chronological paragraph (60-120 words) for text-to-video. Lead with the main subject "
    "and concrete action; retain exact hair, clothing, and colors while specifying an unobstructed, "
    "fully visible subject and keeping foreground objects out of the sightline. Then describe background, "
    "camera, and lighting. Never drop identity details when tightening composition.\n"
    "- beats = __N__ follow-up key frames of the same shot, in story order, each a full text-to-image prompt "
    "(same exact cast looks, location, lighting and style as t2i). Each one moves the action a moment "
    "forward AND changes the framing: e.g. a reaction close-up, a detail insert of hands or a key "
    "object, an over-the-shoulder or reverse angle, a wide. The shot plays as a sequence of stills, "
    "so every beat must read clearly on its own. Keep each beat under 45 words.\n"
    "Reply with JSON only: {\"shots\": [{\"id\": \"...\", \"t2i\": \"...\", \"negative\": \"...\", "
    "\"camera\": \"...\", \"motion\": \"...\", \"strength\": 0.0, \"t2v\": \"...\", \"seconds\": 4, "
    "\"beats\": [\"...\"]__DYN_JSON__}]}"
)
MOVES = ("push", "pull", "pan_left", "pan_right", "tilt_up", "tilt_down", "drift", "punch", "shake")
MOODS = ("calm", "mystery", "tension", "action", "sad", "triumph", "wonder")
DYNAMIC_RULES = (
    "- This is a fast manhwa-recap edit: every frame is on screen ~2 seconds.\n"
    "- moves = one camera move per frame (the t2i frame first, then each beat, so len(beats)+1 "
    "moves) from: " + ", ".join(MOVES) + ". punch = fast zoom-in for a reveal, shock or power "
    "moment; shake = impact, slam, explosion, scream. Use punch/shake only at real peaks (about one "
    "frame in five); calm frames drift, push or pan.\n"
    "- ui = \"\" or ONE short game-style SYSTEM window (max 14 words, e.g. \"[Quest] Find the stolen "
    "Heart Flame. Reward: ???\") at key story moments only, about one shot in five.\n"
    "- caption = \"\" or a 1-4 word dramatic caption in capitals for the biggest beats only (about "
    "one shot in six), e.g. \"EVERY LANTERN DIED\". Never repeat the spoken line.\n"
    "- mood = the music under this shot, one of: " + ", ".join(MOODS) + ".\n")
DYNAMIC_JSON = ', \"moves\": [\"push\"], \"ui\": \"\", \"caption\": \"\", \"mood\": \"calm\"'


def system_prompt(n_beats: int = 3, dynamic: bool = False) -> str:
    text = SYSTEM.replace("__N__", str(n_beats))
    if dynamic:
        text = text.replace("Reply with JSON only:", DYNAMIC_RULES + "Reply with JSON only:")
    return text.replace("__DYN_JSON__", DYNAMIC_JSON if dynamic else "")


DEFAULT_NEGATIVE = ("low quality, blurry, text, watermark, signature, deformed hands, extra limbs, "
                    "comic page, multiple panels, split screen, speech bubble")


def _key(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    env = Path.home() / ".hermes" / ".env"
    if env.exists():
        for line in env.read_text(errors="replace").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _groq(messages: list[dict], timeout: int = 90) -> str:
    key = _key("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    body = {"model": GROQ_MODEL, "messages": messages, "temperature": 0.6,
            "response_format": {"type": "json_object"}, "max_tokens": 8000}
    req = urllib.request.Request(GROQ_URL, data=json.dumps(body).encode(), headers={
        "Content-Type": "application/json", "Authorization": f"Bearer {key}",
        "User-Agent": "olympus-director/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)["choices"][0]["message"]["content"] or ""
        except urllib.error.HTTPError as e:
            # free-tier tokens-per-minute limit: wait it out (Retry-After), then retry
            if e.code != 429 or attempt == 2:
                raise RuntimeError(f"groq HTTP {e.code}") from e
            time.sleep(min(60.0, float(e.headers.get("retry-after") or 20)))
    return ""


def _ollama(messages: list[dict]) -> str:
    from .llm import ollama_generate
    prompt = messages[0]["content"] + "\n\n" + messages[1]["content"]
    res = ollama_generate(prompt, think=False, timeout=600, num_predict=6000, temperature=0.5)
    return (getattr(res, "text", None) or "") if res is not None else ""


def _parse(text: str) -> list[dict]:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return []
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return []
    shots = d.get("shots") if isinstance(d, dict) else None
    return [s for s in shots or [] if isinstance(s, dict) and s.get("id")]


def _clean(s: dict, fallback: dict, n_beats: int = 3) -> dict:
    def txt(k: str, n: int) -> str:
        v = re.sub(r"\s+", " ", str(s.get(k) or "")).strip()
        return v[:n] if v else fallback.get(k, "")
    try:
        strength = min(1.0, max(0.0, float(s.get("strength", fallback["strength"]))))
    except (TypeError, ValueError):
        strength = fallback["strength"]
    try:
        seconds = min(6.0, max(2.0, float(s.get("seconds", 4))))
    except (TypeError, ValueError):
        seconds = 4.0
    t2i = txt("t2i", 900)
    # quoted speech in an image prompt gets painted as text
    t2i = re.sub(r"[\"“”][^\"“”]*[\"“”]", "", t2i)
    beats = [re.sub(r"[\"“”][^\"“”]*[\"“”]", "", re.sub(r"\s+", " ", b)).strip()[:900]
             for b in (s.get("beats") if isinstance(s.get("beats"), list) else []) if isinstance(b, str)]
    beats = [b for b in beats if b][:n_beats]
    out = {"t2i": t2i, "negative": txt("negative", 400) or DEFAULT_NEGATIVE, "camera": txt("camera", 160),
           "motion": txt("motion", 500), "strength": round(strength, 2), "t2v": txt("t2v", 1400),
           "seconds": seconds, "beats": beats, "beats_n": n_beats, "by": s.get("_by", "")}
    if "moves" in s or "ui" in s or "caption" in s or "mood" in s:
        moves = [str(m).strip().lower().replace("-", "_").replace(" ", "_")
                 for m in (s.get("moves") if isinstance(s.get("moves"), list) else [])]
        out["moves"] = [m if m in MOVES else "push" for m in moves][:len(beats) + 1]
        strip = lambda v, n: re.sub(r"[\"“”]", "", re.sub(r"\s+", " ", str(v or ""))).strip()[:n]
        out["ui"] = strip(s.get("ui"), 120)
        out["caption"] = strip(s.get("caption"), 40).upper()
        mood = str(s.get("mood") or "").strip().lower()
        out["mood"] = mood if mood in MOODS else ""
    return out


EDIT_KEYS = ("beats", "beats_n", "moves", "ui", "caption", "mood")


def shot_requests(scenes: list[dict], storyboard_by_id: dict, cast_looks: dict, style: str) -> list[dict]:
    """The shots as the director sees them (scene, who is in it, what happens, the board's hint)."""
    out = []
    for scene in scenes:
        for shot in scene.get("shots", []):
            plan = storyboard_by_id.get(shot.get("id"), {})
            action = re.sub(r"[\"“”][^\"“”]*[\"“”]", "", shot.get("description", "") or plan.get("action", ""))
            out.append({
                "id": shot.get("id"),
                "location": scene.get("location", "")[:120],
                "characters": [cast_looks.get(c, c) for c in plan.get("character_ids", [])][:4],
                "speaker": shot.get("character") or "",
                "delivery": shot.get("delivery") or "",
                "action": action[:400],
                "board": {"composition": plan.get("composition", ""), "camera": plan.get("camera", ""),
                          "lighting": (plan.get("continuity") or {}).get("lighting", "")},
                "style": style,
            })
    return out


def direct(requests: list[dict], cast_looks: dict, fallbacks: dict, out_path: Path,
           llm=None, n_beats: int = 3, dynamic: bool = False) -> dict:
    """Write director.json for the shots that don't have an entry yet (resumable)."""
    out_path = Path(out_path)
    done = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    # Entries from before beats existed get only their beats filled in (their t2i — and so the
    # rendered panel — stays as it was).
    def stale(e: dict) -> bool:
        asked = e.get("beats_n", 3 if "beats" in e else -1)
        return asked < n_beats or (dynamic and "moves" not in e)
    todo = [r for r in requests if r["id"] not in done or stale(done[r["id"]])]
    batch_size = BATCH if n_beats <= 3 else 5     # 7 beats/shot: keep each reply well under max_tokens
    cast_block = "\n".join(f"- {k}: {v}" for k, v in cast_looks.items()) or "- (none given)"
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i + batch_size]
        messages = [{"role": "system", "content": system_prompt(n_beats, dynamic)},
                    {"role": "user", "content": "CAST (exact looks):\n" + cast_block + "\n\nSHOTS:\n"
                     + json.dumps(batch, ensure_ascii=False, indent=1)}]
        got, by = [], ""
        for name, fn in ((llm and [("custom", llm)]) or [("groq", _groq), ("ollama", _ollama)]):
            try:
                got = _parse(fn(messages))
            except Exception as e:  # noqa: BLE001 - any LLM failure: next one, then the template
                print(f"  director: {name} failed ({type(e).__name__}: {str(e)[:80]}); next", flush=True)
                continue
            if got:
                by = name
                break
        if not got:
            continue  # every LLM failed: leave these shots out so the next run retries them
        by_id = {s["id"]: s for s in got}
        for r in batch:
            s = by_id.get(r["id"]) or {}
            new = _clean({**s, "_by": by if s else "template"}, fallbacks.get(r["id"], {
                "t2i": "", "negative": DEFAULT_NEGATIVE, "camera": "", "motion": "", "strength": 0.4, "t2v": ""}),
                n_beats)
            old = done.get(r["id"])
            # an existing shot keeps its t2i (so its rendered panel); only the edit plan is redone
            if old:
                # beats already written at this count stay (their frames are rendered)
                keep = old.get("beats_n", 3 if "beats" in old else -1) >= n_beats
                done[r["id"]] = {**old, **{k: new[k] for k in EDIT_KEYS
                                           if k in new and not (keep and k in ("beats", "beats_n"))}}
            else:
                done[r["id"]] = new
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(done, indent=2, ensure_ascii=False), encoding="utf-8")
    return done


def svd_motion_bucket(strength: float) -> int:
    """SVD motion_bucket_id from the director's 0-1 strength (SVD's useful range is ~40-180)."""
    return int(round(40 + 140 * min(1.0, max(0.0, strength))))
