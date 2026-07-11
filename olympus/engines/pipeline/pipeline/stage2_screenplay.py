"""Stage 2 -- SCREENPLAY (original spec Steps 1-5 + v2 deltas; design section 4).

Order of operations, all LLM traffic via :class:`~pipeline.llm.PipelineLLM`:

1. **Scene segmentation** (temp 0.15): per-chunk scene extraction against the
   world bible's location/character ids; edge scenes marked mid-scene are
   merged across chunk boundaries.
2. **Shot plan** (temp 0.15): per scene, structure only. Code enforces: no
   two consecutive identical shot_type; <=2 characters per shot; 20-60 total
   shots warned outside that band.
3. **SD prompt assembly** (NO LLM -- deterministic, design's 120-word budget):
   ``char anchors (<=2) + location anchor + composition + style tail``; when
   over budget, composition is trimmed first, then location -- anchors never.
   No character names in the prompt; the anchor IS the identity.
4. **Narration craft** (temp 0.4/0.6): technique rotation (sensory detail ->
   character interiority -> foreshadow -> plain action -> world texture, never
   twice in a row), 15-45 words, banned-pattern regex filter, one rewrite call
   for failures; an economy narrator-stop is injected when the world bible
   says ``explained_in_story == false`` and a scene first touches trade/money.
5. **Dialogue craft** (temp 0.4, per-scene calls with speech style cards --
   v2 improvement #4), clipped/verbose validation, first-60-chars dedup
   across the episode.
6. **Pacing pauses**: rule table -> ``pause_before_ms``; lipsync flags on
   close-up dialogue shots.
7. **Quality audit** (temp 0.2): every narration scored 0-100; the 3 weakest
   rewritten and re-scored; both scores persisted.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .blueprint import Blueprint
from .chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, chunk_text
from .config import ENGINE_ROOT, PipelineConfig
from .llm import PipelineLLM
from .schemas.worldbible import WorldBible
from .scores import Scores

logger = logging.getLogger(__name__)

PROMPTS_DIR = ENGINE_ROOT / "prompts"

_TECHNIQUES = (
    "sensory detail", "character interiority", "foreshadow",
    "plain action", "world texture",
)
_STYLE_TAIL = "anime 2d illustration, manga panel style, high quality linework, cel shading"
_PROMPT_WORD_BUDGET = 120
_NARRATION_MIN_WORDS, _NARRATION_MAX_WORDS = 15, 45

# Banned narration patterns (original spec seed list; per-project additions
# appended from <project>/banned_patterns.json when present).
_BANNED_PATTERNS_SEED = (
    r"little did (he|she|they) know",
    r"\bin a world where\b",
    r"\bfate had other plans\b",
    r"\bwhat could possibly go wrong\b",
    r"\bonly time (would|will) tell\b",
    r"\bnothing would ever be the same\b",
    r"^\s*(it|there) (was|is) (a )?(dark|quiet|cold) ",
)

_PAUSE_TABLE_MS = {
    "interruption": 0,
    "casual": 300,
    "considered": 750,
    "complex_decision": 1600,
    "dramatic_reveal": 2400,
}

_ECONOMY_WORDS = re.compile(r"\b(coin|gold|silver|money|price|trade|market|pay|debt|tax)\b", re.IGNORECASE)


class Stage2Error(ValueError):
    """Stage2-specific data problems."""


# --------------------------------------------------------------------------
# LLM output schemas
# --------------------------------------------------------------------------
class _SceneOut(BaseModel):
    location_id: str = "loc-other"
    characters: list[str] = Field(default_factory=list)
    summary: str = ""
    time_of_day: str = "unclear"
    opens_mid_scene: bool = False
    ends_mid_scene: bool = False


class _SceneList(BaseModel):
    scenes: list[_SceneOut] = Field(default_factory=list)


class _ShotOut(BaseModel):
    shot_type: str = "medium"
    composition: str = ""
    characters_in_frame: list[str] = Field(default_factory=list)
    positioning: str = ""
    movement: str = "static"
    facial: str = ""
    posture: str = ""
    beat: str = ""


class _ShotList(BaseModel):
    shots: list[_ShotOut] = Field(default_factory=list)


class _DialogueLine(BaseModel):
    shot_id: str = ""
    char_id: str = ""
    text: str = ""
    emotion: str = "neutral"
    pause_class: str = "casual"
    audio_thought: bool = False


class _DialogueList(BaseModel):
    lines: list[_DialogueLine] = Field(default_factory=list)


class _AuditScore(BaseModel):
    score: float = 0.0
    weakest_aspect: str = ""
    note: str = ""


# --------------------------------------------------------------------------
# Step 1 -- scene segmentation
# --------------------------------------------------------------------------
def segment_scenes(script_text: str, wb: WorldBible, llm: PipelineLLM) -> list[dict[str, Any]]:
    chunks = chunk_text(script_text, chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP)
    location_list = ", ".join(f"{l['id']} ({l['name']})" for l in wb.locations) or "loc-other"
    character_list = ", ".join(f"{c.id} ({c.name})" for c in wb.characters)

    raw: list[_SceneOut] = []
    for chunk in chunks:
        result = llm.complete_json(
            "s2_scene_segment.md",
            {"chunk_text": chunk.text, "location_list": location_list,
             "character_list": character_list},
            _SceneList,
            role="script",
            stage_hint=f"stage2_scenes_chunk{chunk.index}",
        )
        raw.extend(result.scenes)

    # Merge chunk-edge fragments: a scene that opens mid-scene continues the
    # previous one (union cast, concatenated summary).
    merged: list[_SceneOut] = []
    for s in raw:
        if merged and s.opens_mid_scene and merged[-1].ends_mid_scene:
            prev = merged[-1]
            prev.summary = (prev.summary + " " + s.summary).strip()
            prev.characters = sorted(set(prev.characters) | set(s.characters))
            prev.ends_mid_scene = s.ends_mid_scene
        else:
            merged.append(s)

    known_chars = {c.id for c in wb.characters}
    known_locs = {l["id"] for l in wb.locations}
    scenes = []
    for i, s in enumerate(merged, 1):
        scenes.append({
            "id": f"sc-{i:03d}",
            "location": s.location_id if s.location_id in known_locs else "loc-other",
            "characters": [c for c in s.characters if c in known_chars],
            "summary": s.summary,
            "time_of_day": s.time_of_day,
            "shots": [],
        })
    return scenes


# --------------------------------------------------------------------------
# Step 2 -- shot plan (+ code-side structure rules)
# --------------------------------------------------------------------------
def _fix_consecutive_types(shots: list[_ShotOut]) -> None:
    """No two consecutive shots with the same shot_type (original spec rule):
    the second of a same-type pair is nudged to the next type in a fixed cycle."""
    cycle = ["wide", "medium", "close_up", "detail", "action", "establishing"]
    for i in range(1, len(shots)):
        if shots[i].shot_type == shots[i - 1].shot_type:
            nxt = cycle[(cycle.index(shots[i].shot_type) + 1) % len(cycle)] \
                if shots[i].shot_type in cycle else "medium"
            shots[i].shot_type = nxt


def plan_shots(scene: dict[str, Any], scene_idx: int, scene_total: int,
               wb: WorldBible, llm: PipelineLLM) -> list[dict[str, Any]]:
    loc = next((l for l in wb.locations if l["id"] == scene["location"]), None)
    chars = {c.id: c for c in wb.characters}
    result = llm.complete_json(
        "s2_shot_plan.md",
        {
            "scene_summary": scene["summary"],
            "location_name": loc["name"] if loc else "unspecified",
            "location_description": loc["description"] if loc else "",
            "character_list": ", ".join(
                f"{cid} ({chars[cid].name})" for cid in scene["characters"] if cid in chars
            ) or "(none)",
            "scene_position": scene_idx,
            "scene_total": scene_total,
        },
        _ShotList,
        role="script",
        stage_hint=f"stage2_shots_{scene['id']}",
    )
    shots = result.shots
    for s in shots:
        s.characters_in_frame = [c for c in s.characters_in_frame if c in chars][:2]
    _fix_consecutive_types(shots)

    return [
        {
            "id": f"sh-{scene['id'][3:]}-{i:02d}",
            "shot_type": s.shot_type, "composition": s.composition,
            "characters_in_frame": s.characters_in_frame,
            "positioning": s.positioning, "movement": s.movement,
            "facial": s.facial, "posture": s.posture, "beat": s.beat,
            "sd_prompt": "", "narration": None, "dialogue": [], "lipsync": False,
        }
        for i, s in enumerate(shots, 1)
    ]


# --------------------------------------------------------------------------
# Step 3 -- deterministic SD prompt assembly (120-word budget)
# --------------------------------------------------------------------------
def assemble_sd_prompt(
    shot: dict[str, Any], scene: dict[str, Any], wb: WorldBible
) -> str:
    """``anchors + location + composition + style`` under the 120-word budget.
    Trim order when over: composition first, then location -- never anchors or
    style (design Stage 2 Step 3). No character names appear in the prompt."""
    chars = {c.id: c for c in wb.characters}
    anchors = [chars[cid].sd_prompt for cid in shot["characters_in_frame"] if cid in chars]
    loc = next((l for l in wb.locations if l["id"] == scene["location"]), None)
    location = loc["sd_prompt"] if loc else ""
    composition = f"{shot['composition']}, {shot['positioning']}".strip(", ")
    time_od = scene.get("time_of_day", "")
    if time_od and time_od != "unclear":
        composition += f", {time_od} lighting"

    anchor_part = ", ".join(anchors)
    fixed_words = len(anchor_part.split()) + len(_STYLE_TAIL.split())
    remaining = _PROMPT_WORD_BUDGET - fixed_words

    comp_words = composition.split()
    loc_words = location.split()
    if len(comp_words) + len(loc_words) > remaining:
        comp_budget = max(0, remaining - len(loc_words))
        comp_words = comp_words[:comp_budget]
        if len(comp_words) + len(loc_words) > remaining:
            loc_words = loc_words[: max(0, remaining - len(comp_words))]

    parts = [p for p in (anchor_part, " ".join(loc_words), " ".join(comp_words), _STYLE_TAIL) if p]
    return ", ".join(parts)


# --------------------------------------------------------------------------
# Step 4 -- narration craft
# --------------------------------------------------------------------------
def _load_banned_patterns(project_dir: Path) -> list[re.Pattern]:
    patterns = list(_BANNED_PATTERNS_SEED)
    extra = project_dir / "banned_patterns.json"
    if extra.exists():
        patterns += json.loads(extra.read_text(encoding="utf-8"))
    return [re.compile(p, re.IGNORECASE) for p in patterns]


def _narration_issues(text: str, banned: list[re.Pattern], recent_openers: list[str]) -> list[str]:
    issues = []
    wc = len(text.split())
    if wc < _NARRATION_MIN_WORDS:
        issues.append(f"too short ({wc} words; need {_NARRATION_MIN_WORDS}-{_NARRATION_MAX_WORDS})")
    elif wc > _NARRATION_MAX_WORDS:
        issues.append(f"too long ({wc} words; need {_NARRATION_MIN_WORDS}-{_NARRATION_MAX_WORDS})")
    for rx in banned:
        if rx.search(text):
            issues.append(f"banned pattern: {rx.pattern}")
    opener = " ".join(text.split()[:3]).lower()
    if opener in recent_openers:
        issues.append(f"repeated opener: {opener!r}")
    return issues


def write_narrations(
    scenes: list[dict[str, Any]], wb: WorldBible, llm: PipelineLLM, project_dir: Path,
) -> int:
    """Technique-rotated narration per shot with the banned-pattern filter and
    one rewrite call max (silence over bad narration: a line that still fails
    after rewrite is dropped to None). Returns rewrite count."""
    banned = _load_banned_patterns(project_dir)
    economy = (wb.world or {}).get("economy", {})
    needs_economy_stop = not economy.get("explained_in_story", True)
    world_note_default = ""

    tech_i = 0
    rewrites = 0
    recent_openers: list[str] = []
    for scene in scenes:
        scene_summary = scene["summary"]
        for shot in scene["shots"]:
            technique = _TECHNIQUES[tech_i % len(_TECHNIQUES)]
            tech_i += 1

            world_note = world_note_default
            if needs_economy_stop and _ECONOMY_WORDS.search(scene_summary + " " + shot["beat"]):
                world_note = (
                    "This shot must briefly and concisely explain the story's "
                    f"economy ({economy.get('system', 'unknown')}) as a narrator stop, <=25 words."
                )
                needs_economy_stop = False  # one stop per episode

            text = llm.complete_text(
                "s2_narration.md",
                {
                    "technique": technique, "beat": shot["beat"],
                    "scene_summary": scene_summary,
                    "recent_openers": "; ".join(recent_openers[-3:]) or "(none)",
                    "world_note": world_note or "(none)",
                },
                role="script",
                stage_hint=f"stage2_narr_{shot['id']}",
            ).strip().strip('"')

            issues = _narration_issues(text, banned, recent_openers[-3:])
            if issues:
                rewrites += 1
                text = llm.complete_text(
                    "s2_narration_rewrite.md",
                    {"technique": technique, "narration": text,
                     "issues": "; ".join(issues), "beat": shot["beat"]},
                    role="script",
                    stage_hint=f"stage2_narrfix_{shot['id']}",
                ).strip().strip('"')
                if _narration_issues(text, banned, recent_openers[-3:]):
                    logger.warning("narration for %s failed after rewrite; dropping (silence)", shot["id"])
                    shot["narration"] = None
                    continue

            recent_openers.append(" ".join(text.split()[:3]).lower())
            shot["narration"] = {"text": text, "technique": technique, "score": None}
    return rewrites


# --------------------------------------------------------------------------
# Step 5 -- dialogue craft (per-scene calls, v2 improvement #4)
# --------------------------------------------------------------------------
def _style_card(c) -> str:
    return (
        f"{c.id} ({c.name}): register={c.speech_style.vocabulary_register or 'plain'}; "
        f"category={c.speech_style.category or 'neutral'}; "
        f"length={c.speech_style.avg_words_per_line or 'medium'}; "
        f"patterns={c.speech_style.distinctive_patterns or 'none'}"
    )


def write_dialogue(scenes: list[dict[str, Any]], wb: WorldBible, llm: PipelineLLM) -> int:
    """Per-scene dialogue with style cards; clipped/verbose validation and a
    global first-60-chars dedup. Returns count of dropped/deduped lines."""
    chars = {c.id: c for c in wb.characters}
    seen_signatures: set[str] = set()
    dropped = 0

    for scene in scenes:
        present = [chars[cid] for cid in scene["characters"] if cid in chars]
        if not present or not scene["shots"]:
            continue
        result = llm.complete_json(
            "s2_dialogue.md",
            {
                "scene_summary": scene["summary"],
                "shot_list": "\n".join(f"{s['id']}: {s['beat']}" for s in scene["shots"]),
                "style_cards": "\n".join(_style_card(c) for c in present),
            },
            _DialogueList,
            role="script",
            stage_hint=f"stage2_dlg_{scene['id']}",
        )
        shots_by_id = {s["id"]: s for s in scene["shots"]}
        for line in result.lines:
            shot = shots_by_id.get(line.shot_id)
            char = chars.get(line.char_id)
            if shot is None or char is None or not line.text.strip():
                dropped += 1
                continue
            wc = len(line.text.split())
            style_len = (char.speech_style.avg_words_per_line or "").lower()
            if style_len == "short" and wc > 20:
                dropped += 1
                continue
            signature = line.text.strip().lower()[:60]
            if signature in seen_signatures:
                dropped += 1
                continue
            seen_signatures.add(signature)

            pause_ms = _PAUSE_TABLE_MS.get(line.pause_class, 300)
            shot["dialogue"].append({
                "char": line.char_id, "text": line.text.strip(),
                "pause_before_ms": pause_ms, "emotion": line.emotion,
                "audio_thought": line.audio_thought,
            })

    # Pacing flags: close-up shots with dialogue get lipsync=true (Step 6).
    for scene in scenes:
        for shot in scene["shots"]:
            shot["lipsync"] = bool(shot["dialogue"]) and shot["shot_type"] == "close_up"
    return dropped


# --------------------------------------------------------------------------
# Step 7 -- quality audit
# --------------------------------------------------------------------------
def audit_narrations(
    scenes: list[dict[str, Any]], llm: PipelineLLM, project_dir: Path,
) -> tuple[float, float]:
    """Score every narration, rewrite the 3 weakest, re-score. Returns
    (avg_before, avg_after)."""
    entries = [
        (scene, shot) for scene in scenes for shot in scene["shots"] if shot["narration"]
    ]
    if not entries:
        return 0.0, 0.0

    def score(shot) -> _AuditScore:
        return llm.complete_json(
            "s2_quality_audit.md",
            {"technique": shot["narration"]["technique"], "narration": shot["narration"]["text"]},
            _AuditScore,
            role="script",
            stage_hint=f"stage2_audit_{shot['id']}",
        )

    banned = _load_banned_patterns(project_dir)
    for _, shot in entries:
        shot["narration"]["score"] = score(shot).score
    avg_before = sum(s["narration"]["score"] for _, s in entries) / len(entries)

    weakest = sorted(entries, key=lambda e: e[1]["narration"]["score"])[:3]
    for _, shot in weakest:
        n = shot["narration"]
        rewritten = llm.complete_text(
            "s2_narration_rewrite.md",
            {"technique": n["technique"], "narration": n["text"],
             "issues": f"audit score {n['score']:.0f}/100 - raise concreteness and freshness",
             "beat": shot["beat"]},
            role="script",
            stage_hint=f"stage2_auditfix_{shot['id']}",
        ).strip().strip('"')
        if not _narration_issues(rewritten, banned, []):
            shot["narration"]["score_before_audit"] = n["score"]
            n["text"] = rewritten
            n["score"] = score(shot).score

    avg_after = sum(s["narration"]["score"] for _, s in entries) / len(entries)
    return avg_before, avg_after


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    llm: PipelineLLM | None = None,
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    wb = WorldBible.model_validate_json(
        (project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8")
    )
    script_text = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")

    scenes = segment_scenes(script_text, wb, llm)
    if not scenes:
        raise Stage2Error("scene segmentation produced no scenes")

    for i, scene in enumerate(scenes, 1):
        scene["shots"] = plan_shots(scene, i, len(scenes), wb, llm)
    total_shots = sum(len(s["shots"]) for s in scenes)
    if not 20 <= total_shots <= 60:
        logger.warning("shot count %d outside the 20-60 band (original spec warns)", total_shots)

    for scene in scenes:
        for shot in scene["shots"]:
            shot["sd_prompt"] = assemble_sd_prompt(shot, scene, wb)

    rewrites = write_narrations(scenes, wb, llm, project_dir)
    dedup_drops = write_dialogue(scenes, wb, llm)
    avg_before, avg_after = audit_narrations(scenes, llm, project_dir)

    bp = Blueprint.load(project_dir)
    screenplay = {"story_id": bp.story_id, "scenes": scenes}
    out_dir = project_dir / "screenplay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "screenplay.json"
    out_path.write_text(json.dumps(screenplay, indent=2, ensure_ascii=False), encoding="utf-8")

    scores.record("stage2", "global", "scenes", float(len(scenes)))
    scores.record("stage2", "global", "shots", float(total_shots))
    scores.record("stage2", "global", "narration_rewrites", float(rewrites))
    scores.record("stage2", "global", "dialogue_dedup_drops", float(dedup_drops))
    scores.record("stage2", "global", "narration_avg_score_before", avg_before)
    scores.record("stage2", "global", "narration_avg_score", avg_after)
    scores.stage_done("stage2")

    bp.stages["stage2"].status = "done"
    bp.stages["stage2"].ts = _now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage2", "status": "done",
        "scenes": len(scenes), "shots": total_shots,
        "narration_avg_score": round(avg_after, 1),
        "narration_avg_before_audit": round(avg_before, 1),
        "screenplay_path": str(out_path),
    }
