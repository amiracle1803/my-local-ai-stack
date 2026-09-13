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
from .scores import Scores
from ._util import now_iso
from .schemas.worldbible import WorldBible
from .schemas.dossier import StoryDossier, load_dossier
from .story_contract import write_beats, write_source_manifest
from .source_fidelity import _load_rules, repair_screenplay_from_rules, remove_prohibited_terms

logger = logging.getLogger(__name__)

PROMPTS_DIR = ENGINE_ROOT / "prompts"

_TECHNIQUES = (
    "sensory detail", "character interiority", "foreshadow",
    "plain action", "world texture",
)
_STYLE_TAIL = "anime 2d illustration, modern comic style, clean linework, cel shading"
# No-text suppression: krea2/qwen frequently render readable Japanese
# lettering (speech bubbles, signs, menus) into the panel even when
# instructed otherwise. There is no real negative conditioning on this
# CFG-distilled model, so we append explicit JP-banned tokens to the
# POSITIVE prompt (krea2 follows positive style tokens well, and explicit
# language exclusions are stronger than "no text" alone). Shared by the
# panel AND the location master plate prompts so plates don't bake
# signage into the background either.
_NO_TEXT_TAIL = (
    "no text, no letters, no subtitles, no captions, no signage, no writing, "
    "no speech bubble, no words, no speech, no dialogue, no watermark, "
    "clean illustration, english only"
)
# Bumped from 120 -> 180 to keep the location descriptor (critical for
# background consistency across the world's 4 locations) and the expanded
# JP-ban tail when the shot includes 1-2 characters (their sd_prompt
# anchors alone can run 50-100 words).
_PROMPT_WORD_BUDGET = 180
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


def _dossier_context(dossier: StoryDossier) -> tuple[str, str]:
    """(scene_settings, dialogue_log) prompt context derived from the intake
    dossier -- the extracted scene facts and the verbatim dialogue log, so the
    screenplay/storyboard stay grounded in what the script actually says."""
    scene_facts = []
    for s in dossier.scenes:
        env = ", ".join(s.environment_features) or "unspecified"
        scene_facts.append(
            f"Scene {s.number} ({s.location or '?'}): time={s.time_of_day or 'unspecified'}, "
            f"season={s.season or 'unspecified'}, environment={env}"
        )
    dialogue_lines = []
    for line in dossier.dialogue:
        addr = f" to {line.addressee}" if line.addressee else ""
        move = f" [{line.body_movement}]" if line.body_movement else ""
        dialogue_lines.append(
            f"Scene {line.scene_number}: {line.speaker}{addr}: \"{line.text}\"{move}"
        )
    return (
        "\n".join(scene_facts) or "(none)",
        "\n".join(dialogue_lines) or "(none)",
    )


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
    camera_angle: str = "wide_establishing"


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
def segment_scenes(script_text: str, wb: WorldBible, llm: PipelineLLM, references: dict | None = None, dossier: StoryDossier | None = None) -> list[dict[str, Any]]:
    chunks = chunk_text(script_text, chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP)
    location_list = ", ".join(f"{l.id} ({l.name})" for l in wb.locations) or "loc-other"
    character_list = ", ".join(f"{c.id} ({c.name})" for c in wb.characters)

    # Add reference context to scene segmentation
    ref_context = ""
    if references:
        loc_refs = references.get("locations", {})
        if loc_refs:
            ref_context += "\nLocation reference images available for: " + ", ".join(loc_refs.keys())

    scene_settings, _ = _dossier_context(dossier) if dossier else ("(none)", "(none)")

    raw: list[_SceneOut] = []
    for chunk in chunks:
        result = llm.complete_json(
            "s2_scene_segment.md",
            {"chunk_text": chunk.text, "location_list": location_list,
             "character_list": character_list, "reference_context": ref_context,
             "scene_settings": scene_settings},
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
    known_locs = {l.id for l in wb.locations}
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


def _expand_shot_density(shots: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    """Split long compound beats when a local model under-plans a scene."""
    out = list(shots)
    index = 0
    while len(out) < target and index < len(out) * 3:
        original = out[index % len(out)]
        words = str(original.get("beat", "")).split()
        if len(words) >= 10:
            midpoint = len(words) // 2
            first = dict(original)
            second = dict(original)
            first["beat"] = " ".join(words[:midpoint]).rstrip(".,") + "."
            second["beat"] = "reaction and consequence: " + " ".join(words[midpoint:]).rstrip(".,") + "."
            out[index % len(out)] = first
            out.insert((index % len(out)) + 1, second)
        index += 1
    return out


def plan_shots(scene: dict[str, Any], scene_idx: int, scene_total: int,
                wb: WorldBible, llm: PipelineLLM, references: dict | None = None,
                target_shots: int | None = None) -> list[dict[str, Any]]:
    loc = next((l for l in wb.locations if l.id == scene["location"]), None)
    chars = {c.id: c for c in wb.characters}
    
    # Build reference context for the LLM
    ref_context = ""
    if references:
        char_refs = references.get("characters", {})
        loc_refs = references.get("locations", {})
        style_refs = references.get("style", {})
        if char_refs:
            ref_context += "\nCharacter reference images available for: " + ", ".join(char_refs.keys())
        if loc_refs:
            ref_context += "\nLocation reference images available for: " + ", ".join(loc_refs.keys())
        if style_refs:
            ref_context += "\nStyle reference images available: " + str(len(style_refs)) + " style refs"

    result = llm.complete_json(
        "s2_shot_plan.md",
        {
            "scene_summary": scene["summary"],
            "location_name": loc.name if loc else "unspecified",
            "location_description": loc.description if loc else "",
            "character_list": ", ".join(
                f"{cid} ({chars[cid].name})" for cid in scene["characters"] if cid in chars
            ) or "(none)",
            "scene_position": scene_idx,
            "scene_total": scene_total,
            "target_shots": target_shots or "at least one shot per distinct action/dialogue beat",
            "reference_context": ref_context,
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
            "camera_angle": getattr(s, "camera_angle", "wide_establishing"),
            "sd_prompt": "", "narration": None, "dialogue": [], "lipsync": False,
        }
        for i, s in enumerate(shots, 1)
    ]


# --------------------------------------------------------------------------
# Step 3 -- deterministic SD prompt assembly (120-word budget)
# --------------------------------------------------------------------------
def assemble_sd_prompt(
    shot: dict[str, Any], scene: dict[str, Any], wb: WorldBible, references: dict | None = None
) -> str:
    """``composition + location + trimmed character + style + reference_context``
    under the word budget.

    ORDER FIX (quality): the previous layout led with the full multi-character
    appearance (~120+ words) and pushed the shot's composition/framing to the
    very end, trimming it FIRST when over budget. flux-2-klein weights the front
    of the prompt, so it produced a character portrait for every shot -- all
    close-ups, and the vision judge kept flagging ``composition_matches:false``
    (the framing it asked for never reached the model). Now the shot composition
    + camera framing + positioning + environment lead the prompt and are always
    kept; character appearance is trimmed to fit. Ref/consistency anchors are
    unaffected. No character names appear in the prompt body (refs carry them).
    """
    chars = {c.id: c for c in wb.characters}
    in_frame_ids = shot.get("characters_in_frame", [])
    anchors = [chars[cid].sd_prompt for cid in in_frame_ids if cid in chars]
    loc = next((l for l in wb.locations if l.id == scene["location"]), None)
    location = loc.sd_prompt if loc else ""
    # Guard: location descriptions must never bleed "no people" into character
    # shots (design Stage 2). Empty plates add it themselves in stage3b.
    if in_frame_ids:
        location = location.replace(", no people", "").replace("no people,", "")

    # Lead with the shot itself: composition/framing + positioning + time lighting.
    composition = f"{shot['composition']}, {shot['positioning']}".strip(", ")
    time_od = scene.get("time_of_day", "")
    if time_od and time_od != "unclear":
        composition += f", {time_od} lighting"

    # Reference context for visual consistency (character refs, location refs).
    ref_context = ""
    if references:
        char_refs = references.get("characters", {})
        loc_refs = references.get("locations", {})
        if in_frame_ids:
            for cid in in_frame_ids:
                if cid in char_refs:
                    ref_context += f" [ref: {cid}]"
        if scene.get("location") in loc_refs:
            ref_context += f" [loc_ref: {scene['location']}]"

    # Composition + location + refs + style + no-text are NEVER trimmed.
    fixed = (
        len(composition.split()) + len(location.split()) + len(ref_context.split())
        + len(_STYLE_TAIL.split()) + len(_NO_TEXT_TAIL.split())
    )
    anchor_budget = max(25, _PROMPT_WORD_BUDGET - fixed)

    # Trim character appearance to fit (front of each sd_prompt = most
    # distinctive; drop the verbose tail). Order of appearance in the prompt is
    # now AFTER the framing + environment, so the model follows the shot.
    anchor_parts: list[str] = []
    used = 0
    for a in anchors:
        aw = a.split()
        take = max(0, anchor_budget - used)
        if take <= 0:
            break
        anchor_parts.append(" ".join(aw[:take]))
        used += min(take, len(aw))
    anchor_part = ", ".join(anchor_parts)

    parts = [
        p for p in (
            composition,
            " ".join(location.split()),
            anchor_part,
            ref_context,
            _STYLE_TAIL,
            _NO_TEXT_TAIL,
        ) if p
    ]
    return ", ".join(parts)


def assemble_sd_prompt_simple(shot: dict[str, Any], scene: dict[str, Any], wb: WorldBible) -> str:
    """One subject + explicit camera framing for weak text-to-image fallbacks.

    flux-2-klein-4b cannot hold multi-constraint spatial prompts ("over-the-
    shoulder from B toward A, east gate beyond"). Collapse to: primary character
    appearance + explicit camera label + location + style + no-text tail.
    """
    chars = {c.id: c for c in wb.characters}
    in_frame = [chars[cid] for cid in shot.get("characters_in_frame", []) if cid in chars]
    loc = next((l for l in wb.locations if l.id == scene.get("location")), None)

    char_desc = ""
    if in_frame:
        a = in_frame[0].appearance
        char_desc = f"{a.hair}, {a.eyes}, {a.skin}, {a.build}, {a.clothing_primary}"

    camera = shot.get("camera_angle") or shot.get("composition") or "medium shot"
    time_od = scene.get("time_of_day", "")
    tod = f", {time_od} lighting" if time_od and time_od != "unclear" else ""

    # Camera framing leads (fixes all-close-up panels): the model reads the front.
    parts = [p for p in (
        str(camera),
        loc.sd_prompt if loc else "",
        char_desc,
        f"anime 2d illustration, clean linework, cel shading{tod}",
        _NO_TEXT_TAIL,
    ) if p]
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
    references: dict | None = None,
) -> int:
    """Technique-rotated narration per shot with the banned-pattern filter and
    one rewrite call max (silence over bad narration: a line that still fails
    after rewrite is dropped to None). Returns rewrite count.
    Uses reference images (character, location, style) for visual context in narration."""
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

            # Add reference context for visual consistency
            ref_context = ""
            if references:
                char_refs = references.get("characters", {})
                loc_refs = references.get("locations", {})
                style_refs = references.get("style", {})
                if shot.get("characters_in_frame"):
                    for cid in shot["characters_in_frame"]:
                        if cid in char_refs:
                            ref_context += f" [Character ref: {cid}]"
                if scene.get("location") in loc_refs:
                    ref_context += f" [Location ref: {scene['location']}]"
                if style_refs:
                    ref_context += f" [Style refs: {len(style_refs)}]"

            text = llm.complete_text(
                "s2_narration.md",
                {
                    "technique": technique, "beat": shot["beat"],
                    "scene_summary": scene_summary,
                    "recent_openers": "; ".join(recent_openers[-3:]) or "(none)",
                    "world_note": world_note or "(none)",
                    "reference_context": ref_context or "(none)",
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
                    # Never silently convert a story beat into dead air. Keep a
                    # deterministic, script-grounded fallback so Stage 4 and
                    # final assembly retain audio coverage even when the local
                    # model fails the prose rewrite contract.
                    fallback = f"{shot['beat'].strip().rstrip('.')} ."
                    if len(fallback.split()) < _NARRATION_MIN_WORDS:
                        fallback = f"{fallback} {scene_summary.strip().rstrip('.')} ."
                    text = fallback
                    logger.warning("narration for %s failed after rewrite; using beat-grounded fallback", shot["id"])

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


def write_dialogue(scenes: list[dict[str, Any]], wb: WorldBible, llm: PipelineLLM, references: dict | None = None, dossier: StoryDossier | None = None) -> int:
    """Per-scene dialogue with style cards; clipped/verbose validation and a
    global first-60-chars dedup. Returns count of dropped/deduped lines.
    Uses reference images for visual context in dialogue."""
    chars = {c.id: c for c in wb.characters}
    seen_signatures: set[str] = set()
    dropped = 0

    _, dialogue_log = _dossier_context(dossier) if dossier else ("(none)", "(none)")

    for scene in scenes:
        present = [chars[cid] for cid in scene["characters"] if cid in chars]
        if not present or not scene["shots"]:
            continue
        
        # Add reference context for visual consistency
        ref_context = ""
        if references:
            char_refs = references.get("characters", {})
            loc_refs = references.get("locations", {})
            style_refs = references.get("style", {})
            if char_refs:
                ref_context += "\nCharacter reference images: " + ", ".join(char_refs.keys())
            if scene.get("location") in loc_refs:
                ref_context += f"\nLocation ref: {scene['location']}"
            if style_refs:
                ref_context += f"\nStyle refs: {len(style_refs)} available"

        result = llm.complete_json(
            "s2_dialogue.md",
            {
                "scene_summary": scene["summary"],
                "shot_list": "\n".join(f"{s['id']}: {s['beat']}" for s in scene["shots"]),
                "style_cards": "\n".join(_style_card(c) for c in present),
                "reference_context": ref_context or "(none)",
                "dialogue_log": dialogue_log,
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


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    llm: PipelineLLM | None = None,
) -> dict[str, Any]:
    """Stage 2 (SWAPPED ORDER -- now runs SECOND, after stage3/storyboard).

    Reads:  storyboard/storyboard.json, references/references.json, worldbible/world_bible.json
    Writes: screenplay/screenplay.json  (adds narration + dialogue + SFX)

    Now that the block structure is already established by stage3 (storyboard),
    the narration and dialogue are written ON TOP of that structure, using
    reference images (character, location, style) as visual context. This
    ensures the story logic + visual consistency are locked before any prose
    is generated, improving consistency.
    """
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    manifest = write_source_manifest(project_dir)
    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")
    existing_screenplay = project_dir / "screenplay" / "screenplay.json"
    manifest_path = project_dir / "input" / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else manifest.model_dump()
    existing_data = json.loads(existing_screenplay.read_text(encoding="utf-8")) if existing_screenplay.exists() else {}
    if (
        existing_screenplay.exists()
        and existing_data.get("source_manifest_sha256") == manifest.get("sha256")
        and existing_data.get("structure_version") == 4
    ):
        storyboard = existing_data
    else:
        # Audio-first mode: create the structural shot plan before narration.
        # Stage 3 will enrich this same structure later with references, blocks,
        # camera prompts, and motion tiers.
        from .schemas.worldbible import WorldBible as _WorldBible
        script_text = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
        wb = _WorldBible.model_validate_json((project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8"))
        dossier = load_dossier(project_dir)
        scenes = segment_scenes(script_text, wb, llm, references={}, dossier=dossier)
        manifest = json.loads((project_dir / "input" / "source_manifest.json").read_text(encoding="utf-8")) if (project_dir / "input" / "source_manifest.json").exists() else {}
        fidelity_rules = _load_rules(project_dir, script_text)
        required_story_beats = "; ".join(
            str(beat.get("label", "")) for beat in fidelity_rules.beats
        ) or "preserve every source action, reveal, reaction, and dialogue exchange"
        total_target = max(len(scenes), int(manifest.get("estimated_beat_count", len(scenes))))
        for index, scene in enumerate(scenes, 1):
            remaining = max(1, len(scenes) - index + 1)
            target = max(2, round((total_target - sum(len(s.get("shots", [])) for s in scenes[:index - 1])) / remaining))
            scene["shots"] = plan_shots(scene, index, len(scenes), wb, llm, references={}, target_shots=f"{target}; required story beats: {required_story_beats}")
            # One bounded expansion pass prevents a local model from collapsing
            # a long chapter into a handful of shots. Never loop indefinitely.
            if len(scene["shots"]) < target:
                expanded = plan_shots(
                    scene, index, len(scenes), wb, llm, references={},
                    target_shots=f"exactly {target}; required story beats: {required_story_beats}",
                )
                if len(expanded) > len(scene["shots"]):
                    scene["shots"] = expanded
            if len(scene["shots"]) < target:
                scene["shots"] = _expand_shot_density(scene["shots"], target)
        storyboard = {"story_id": bp.story_id, "fps": bp.fps, "scenes": scenes}
    # Load references for visual context in narration/dialogue
    refs_path = project_dir / "references" / "references.json"
    references = {}
    if refs_path.exists():
        references = json.loads(refs_path.read_text(encoding="utf-8"))
    else:
        logger.warning("references/references.json not found - running without visual context")
    scenes = storyboard["scenes"]
    if not scenes:
        raise Stage2Error("source produced no scenes for screenplay")

    from .stage3_storyboard import tag_sfx  # local import avoids circular dep
    wb = WorldBible.model_validate_json(
        (project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8")
    )
    dossier = load_dossier(project_dir)  # intake dossier for dialogue grounding
    rules = _load_rules(project_dir, (project_dir / "input" / "script.txt").read_text(encoding="utf-8"))
    repair_screenplay_from_rules({"scenes": scenes}, rules)
    remove_prohibited_terms({"scenes": scenes}, rules)
    rewrites = write_narrations(scenes, wb, llm, project_dir, references=references)
    dedup_drops = write_dialogue(scenes, wb, llm, references=references, dossier=dossier)
    # LLM prose can reintroduce a project-prohibited prop after the initial
    # structure repair; scrub only explicit project rules before persisting.
    remove_prohibited_terms({"scenes": scenes}, rules)
    avg_before, avg_after = audit_narrations(scenes, llm, project_dir)
    remove_prohibited_terms({"scenes": scenes}, rules)

    shots = [shot for scene in scenes for shot in scene["shots"]]
    sfx = tag_sfx(shots)

    screenplay = {"story_id": bp.story_id, "structure_version": 4, "source_manifest_sha256": manifest.get("sha256", ""), "scenes": scenes, "sfx": sfx}
    # Final project-rule scrub after all narration/audit rewrites and before the
    # screenplay is persisted or evaluated.
    remove_prohibited_terms(screenplay, rules)
    out_dir = project_dir / "screenplay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "screenplay.json"
    out_path.write_text(json.dumps(screenplay, indent=2, ensure_ascii=False), encoding="utf-8")
    beats = write_beats(project_dir, screenplay)

    # Stop expensive audio/visual work when the generated screenplay has lost
    # the source story. The report is retained for editor/agent repair loops.
    from .source_fidelity import run_gate
    fidelity = run_gate(project_dir, scores)
    scores.record("stage2", "global", "story_beats", float(len(beats)))

    total_shots = len(shots)
    scores.record("stage2", "global", "scenes", float(len(scenes)))
    scores.record("stage2", "global", "shots", float(total_shots))
    scores.record("stage2", "global", "narration_rewrites", float(rewrites))
    scores.record("stage2", "global", "dialogue_dedup_drops", float(dedup_drops))
    scores.record("stage2", "global", "narration_avg_score_before", avg_before)
    scores.record("stage2", "global", "narration_avg_score", avg_after)
    scores.record("stage2", "global", "sfx_tags", float(len(sfx)))
    scores.stage_done("stage2")

    bp.stages["stage2"].status = "done"
    bp.stages["stage2"].ts = now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage2", "status": "done",
        "scenes": len(scenes), "shots": total_shots,
        "narration_avg_score": round(avg_after, 1),
        "source_fidelity_score": fidelity.score,
        "narration_avg_before_audit": round(avg_before, 1),
        "screenplay_path": str(out_path),
    }
