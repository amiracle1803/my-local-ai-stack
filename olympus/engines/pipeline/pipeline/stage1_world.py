"""Stage 1 -- WORLD BIBLE, part 2 of 2 (M2b; original spec STAGE 1 Steps 3-5
plus the v2 deltas from design section 4 / Stage 1).

Runs after :mod:`stage1_worldbible` (M2a) has written the character-only
partial bible. Adds, in order:

1. **World inference** (Step 3 + v2 era heuristics): one call over evidence
   assembled from the script's first/last chunks -> era (with evidence +
   confidence), technology, magic system, government/class, daily life,
   economy (+``explained_in_story`` flag), locations, recurring assets.
2. **Relationship web** (v2 delta): pairwise calls ONLY for character pairs
   that co-occur in at least one chunk (avoids the N-squared blowup).
3. **Contradiction detection** (Step 4): self-consistency over character
   appearance -- the same character's appearance fields re-extracted per
   provenance chunk; conflicting values are auto-resolved by a majority-
   evidence tie-break call (design 0.2 auto_resolve_contradictions), all
   logged to ``contradictions.json`` with ``auto_resolved: true``.
4. **Creative expansion** (Step 5): thin entries (empty personality fields,
   one-line locations) enriched; everything marked ``expanded: true``.
5. **Location sd_prompts**: deterministic template from the location's
   description (same 40-60-word discipline as characters, code-clamped).
6. **VoiceSpec registry** (design 4.4.1): deterministic assignment written to
   ``voices.json`` -- characters ranked by mention count, M2a voice ids kept,
   ``_narrator`` reserved (default ``af_bella``), distinctness enforced by
   speed offsets when bases collide.

Marks ``stage1`` done (the M2a module deliberately does not).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, RootModel

from .blueprint import Blueprint
from .chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, chunk_text
from .config import ENGINE_ROOT, PipelineConfig
from .llm import PipelineLLM
from .schemas.worldbible import WorldBible, Location
from .scores import Scores
from ._util import now_iso

logger = logging.getLogger(__name__)

PROMPTS_DIR = ENGINE_ROOT / "prompts"

_NARRATOR_VOICE = "af_bella"  # design 4.4.1: reserved, default per original spec


# --------------------------------------------------------------------------
# LLM output schemas
# --------------------------------------------------------------------------
class _Era(BaseModel):
    value: str = "other"
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.0


class _MagicSystem(BaseModel):
    exists: bool = False
    rules: str = ""


class _DailyLife(BaseModel):
    food: str = ""
    sleep: str = ""
    professions: list[str] = Field(default_factory=list)


class _Economy(BaseModel):
    system: str = ""
    explained_in_story: bool = False


class _LocationOut(BaseModel):
    name: str
    description: str = ""
    recurring: bool = False
    evidence: str = ""
    sd_prompt: str = ""
    angles: list[str] = Field(default_factory=list)
    connections: list[dict] = Field(default_factory=list)  # Spatial relationships to other locations


class _AssetOut(BaseModel):
    name: str
    category: str = "other"
    description: str = ""
    evidence: str = ""


class _WorldInference(BaseModel):
    era: _Era = Field(default_factory=_Era)
    technology: list[str] = Field(default_factory=list)
    magic_system: _MagicSystem = Field(default_factory=_MagicSystem)
    government: str = ""
    class_structure: list[str] = Field(default_factory=list)
    daily_life: _DailyLife = Field(default_factory=_DailyLife)
    economy: _Economy = Field(default_factory=_Economy)
    locations: list[_LocationOut] = Field(default_factory=list)
    recurring_assets: list[_AssetOut] = Field(default_factory=list)


class _RelEvolution(BaseModel):
    at: str = "middle"
    becomes: str = ""


class _Relationship(BaseModel):
    type: str = "unclear"
    notes: str = ""
    evolves: list[_RelEvolution] = Field(default_factory=list)


class _Resolution(BaseModel):
    winner: int = 1
    resolved_value: str = ""
    reason: str = ""


# --------------------------------------------------------------------------
# Step 3 -- world inference
# --------------------------------------------------------------------------
def _slug(text: str, prefix: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.strip().lower()).strip("-") or "x"
    return f"{prefix}-{s}"


def infer_world(
    script_text: str,
    wb: WorldBible,
    llm: PipelineLLM,
    *,
    known_locations: list[str] | None = None,
) -> _WorldInference:
    """Infer the world from the script.

    ``known_locations`` seeds the location list from the Stage 0 blueprint's
    scene plan (e.g. "The Courier's House", "The Geothermal Vault", "The
    Town's Edge"). These scene names are the authoritative world-space the
    markers/story went through: without them the LLM collapses every scene to
    the single most-mentioned location (the "weak world / one room" complaint)
    because evidence from the middle of the script is sparse. The prompt
    instructs the model to keep every known name and only drop one if the text
    gives no trace of it.
    """
    chunks = chunk_text(script_text, chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP)
    # Evidence pack: first two + last chunk (openings confirm arcs) -- the
    # token-budget guard trims further. known_locations covers the mid-story
    # world names that the sparse evidence would otherwise lose.
    picked = chunks[:2] + (chunks[-1:] if len(chunks) > 2 else [])
    evidence = "\n---\n".join(c.text for c in picked)
    character_summary = ", ".join(f"{c.name} ({c.role or 'unknown'})" for c in wb.characters)
    return llm.complete_json(
        "s1_world_inference.md",
        {
            "evidence_text": evidence,
            "character_summary": character_summary,
            "known_locations": ", ".join(known_locations) if known_locations else "",
        },
        _WorldInference,
        role="script",
        stage_hint="stage1_world",
    )


_LOCATION_SD_TAIL = "detailed environment, consistent architecture"


def _location_sd_prompt(name: str, description: str, era: str) -> str:
    """Deterministic location anchor: description + era + tail, clamped to 60 words."""
    words = f"{name}, {description}, {era} setting, {_LOCATION_SD_TAIL}".split()
    return " ".join(words[:60])


# --------------------------------------------------------------------------
# v2 delta -- relationship web (co-occurring pairs only)
# --------------------------------------------------------------------------
def build_relationships(
    script_text: str, wb: WorldBible, llm: PipelineLLM
) -> list[dict[str, Any]]:
    chunks = chunk_text(script_text, chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP)
    by_chunk: dict[int, set[str]] = {}
    for c in chunks:
        low = c.text.lower()
        by_chunk[c.index] = {ch.id for ch in wb.characters if ch.name.lower() in low}

    edges: list[dict[str, Any]] = []
    chars = {c.id: c for c in wb.characters}
    for a_id, b_id in combinations(sorted(chars), 2):
        shared = [i for i, ids in by_chunk.items() if a_id in ids and b_id in ids]
        if not shared:
            continue
        a, b = chars[a_id], chars[b_id]
        sentences = [
            s for s in re.split(r"(?<=[.!?])\s+", script_text)
            if a.name.lower() in s.lower() and b.name.lower() in s.lower()
        ]
        evidence = " ".join(sentences[:20]) or "(no direct co-occurring sentences)"
        rel = llm.complete_json(
            "s1_relationship_web.md",
            {
                "char_a": a.name, "role_a": a.role or "unknown",
                "char_b": b.name, "role_b": b.role or "unknown",
                "evidence_text": evidence,
            },
            _Relationship,
            role="script",
            stage_hint=f"stage1_rel_{a_id}_{b_id}",
        )
        edges.append({
            "a": a_id, "b": b_id, "type": rel.type, "notes": rel.notes,
            "evolves": [e.model_dump() for e in rel.evolves],
            "provenance": {"chunk_indexes": shared},
        })
    return edges


# --------------------------------------------------------------------------
# Step 4 -- contradiction detection + auto-resolution
# --------------------------------------------------------------------------
_APPEARANCE_FIELDS = ("hair", "eyes", "skin", "build", "clothing_primary", "distinguishing_feature")

# Per-field regex extractors over evidence sentences; a contradiction is two
# different extracted values for the same character+field in the script text.
_FIELD_RES = {
    "hair": re.compile(r"\b(\w+(?:-\w+)?)\s+hair\b", re.IGNORECASE),
    "eyes": re.compile(r"\b(\w+(?:-\w+)?)\s+eyes\b", re.IGNORECASE),
}


def detect_contradictions(
    script_text: str, wb: WorldBible, llm: PipelineLLM, *, auto_resolve: bool
) -> list[dict[str, Any]]:
    """Self-consistency pass: for hair/eyes, compare script-attested values in
    the sentences that mention each character against the profile value. Two
    distinct attested values (or an attested value differing from the profile)
    is a contradiction; blocking (appearance) contradictions are auto-resolved
    by a majority-evidence tie-break call when ``auto_resolve``."""
    findings: list[dict[str, Any]] = []
    sentences = re.split(r"(?<=[.!?])\s+", script_text)

    for char in wb.characters:
        mentions = [s for s in sentences if char.name.lower() in s.lower()]
        for field, rx in _FIELD_RES.items():
            attested: dict[str, str] = {}
            for s in mentions:
                for m in rx.finditer(s):
                    value = m.group(1).lower()
                    if value not in ("her", "his", "their", "the", "long", "short"):
                        attested.setdefault(value, s)
            profile_value = (getattr(char.appearance, field) or "").lower()
            profile_head = profile_value.split()[0] if profile_value else ""
            values = set(attested)
            if profile_head:
                values.add(profile_head)
            if len(values) <= 1:
                continue

            claims = sorted(values)
            finding: dict[str, Any] = {
                "subject": char.id, "field": field, "claims": claims,
                "evidence": {v: attested.get(v, f"(profile) {profile_value}") for v in claims},
                "blocking": True,  # appearance conflicts are blocking (design 0.2)
                "auto_resolved": False,
            }
            if auto_resolve:
                resolution = llm.complete_json(
                    "s1_contradiction_resolve.md",
                    {
                        "subject": char.name, "field": field,
                        "claim_1": claims[0], "claim_2": claims[1],
                        "evidence_text": " ".join(mentions[:15]),
                    },
                    _Resolution,
                    role="script",
                    stage_hint=f"stage1_contra_{char.id}_{field}",
                )
                idx = max(0, min(resolution.winner - 1, len(claims) - 1))
                resolved = resolution.resolved_value or claims[idx]
                setattr(char.appearance, field, resolved)
                finding.update(auto_resolved=True, resolved_value=resolved, reason=resolution.reason)
            findings.append(finding)
    return findings


# --------------------------------------------------------------------------
# Step 5 -- creative expansion of thin entries
# --------------------------------------------------------------------------
def expand_thin_entries(wb: WorldBible, llm: PipelineLLM) -> int:
    """Enrich thin character personality fields; returns how many entries were
    expanded (each marked in ``lore_entries`` for canon-vs-invented tracing)."""
    world_summary = json.dumps(wb.world or {}, ensure_ascii=False)[:2000]
    expanded = 0
    for char in wb.characters:
        thin = [
            f for f, v in (
                ("core_drive", char.personality.core_drive),
                ("core_fear", char.personality.core_fear),
            ) if not (v or "").strip()
        ]
        if not thin:
            continue
        enriched = llm.complete_json(
            "s1_creative_expansion.md",
            {
                "world_summary": world_summary,
                "entry_type": "character",
                "entry_name": char.name,
                "existing_facts": char.model_dump_json(),
                "thin_fields": ", ".join(thin),
            },
            _FreeformDict,
            role="script",
            stage_hint=f"stage1_expand_{char.id}",
        )
        for f in thin:
            value = enriched.root.get(f, "")
            if value:
                setattr(char.personality, f, value)
        wb.lore_entries.append({"entry": char.id, "expanded": True, "fields": thin})
        expanded += 1
    return expanded



class _FreeformDict(RootModel[dict[str, str]]):
    pass


# --------------------------------------------------------------------------
# VoiceSpec registry (design 4.4.1)
# --------------------------------------------------------------------------
def write_voice_registry(project_dir: Path, wb: WorldBible, script_text: str) -> dict[str, Any]:
    """Deterministic ``voices.json``: keep M2a's unique voice ids as bases,
    rank by mention count, derive speed from a stable hash (0.97-1.07), and
    enforce the distinctness gate with 0.05 speed offsets on base collisions."""
    def mentions(name: str) -> int:
        return len(re.findall(re.escape(name), script_text, re.IGNORECASE))

    ranked = sorted(wb.characters, key=lambda c: mentions(c.name), reverse=True)
    voices: dict[str, Any] = {}
    used_bases: dict[str, int] = {}
    for char in ranked:
        base = char.voice_id_suggestion or "am_adam"
        speed = 0.97 + (int(hashlib.sha256(char.id.encode()).hexdigest(), 16) % 11) / 100.0
        collisions = used_bases.get(base, 0)
        if collisions:
            speed = round(min(1.15, speed + 0.05 * collisions), 3)
        used_bases[base] = collisions + 1
        voices[char.id] = {
            "base": base, "blend": None, "speed": round(speed, 3),
            "pitch_semitones": 0.0, "assigned_by": "auto", "audition": None,
        }
    voices["_narrator"] = {
        "base": _NARRATOR_VOICE, "blend": None, "speed": 1.0,
        "pitch_semitones": 0.0, "assigned_by": "auto", "audition": None,
    }
    (project_dir / "voices.json").write_text(
        json.dumps(voices, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return voices


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------


def merge_dossier_locations(wb: WorldBible, project_dir: Path) -> int:
    """Merge rich location fields (360 views, season, environment) from
    ``intake/dossier.json`` into the world bible's :class:`Location` records.

    Matching is best-effort (case-insensitive exact, then substring) because
    the dossier derives location names from scene dossiers while the world
    bible infers them from the script + stage0 scene plan. Returns the number
    of locations enriched.
    """
    from .schemas.dossier import load_dossier

    dossier = load_dossier(project_dir)
    if dossier is None:
        return 0

    def match(name: str):
        n = name.lower()
        for d in dossier.locations:
            dn = d.name.lower()
            if dn == n or dn in n or n in dn:
                return d
        return None

    merged = 0
    for loc in wb.locations:
        d = match(loc.name)
        if d is None:
            continue
        changed = False
        views = [v.model_dump() for v in d.views_360 if v.angle]
        if views and not loc.views:
            loc.views = views
            changed = True
        angle_names = [v["angle"] for v in views]
        if angle_names and not loc.angles:
            loc.angles = angle_names
            changed = True
        if d.season and d.season.lower() not in ("", "unspecified", "varies") and not loc.season:
            loc.season = d.season
            changed = True
        if d.environment_features and not loc.environment_features:
            loc.environment_features = list(d.environment_features)
            changed = True
        if changed:
            merged += 1
    return merged


def run(
    project_dir: str | Path,
    config: PipelineConfig,
    scores: Scores,
    *,
    llm: PipelineLLM | None = None,
) -> dict[str, Any]:
    """Complete Stage 1 (M2b) for a project that already has the M2a partial
    bible. Writes the full ``world_bible.json``, ``contradictions.json``, and
    ``voices.json``; records metrics; marks ``stage1`` done."""
    project_dir = Path(project_dir)
    wb_path = project_dir / "worldbible" / "world_bible.json"
    if not wb_path.exists():
        raise FileNotFoundError(
            f"no partial world bible at {wb_path} - run stage1 (M2a) first."
        )
    wb = WorldBible.model_validate_json(wb_path.read_text(encoding="utf-8"))
    script_text = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")

    # Step 3: world inference.
    # Seed the location list from the Stage 0 blueprint's scene plan so the
    # full story world (Courier's House, Vault, Town's Edge, Town's Center,
    # ...) survives; the LLM collapses to one location when left to sparse
    # middle-script evidence alone (the "single room world" complaint).
    known_locations: list[str] = []
    bp_path = project_dir / "stage0_blueprint.json"
    if bp_path.exists():
        bp = json.loads(bp_path.read_text(encoding="utf-8"))
        known_locations = sorted(
            s.get("location") for s in bp.get("scene_list", []) if s.get("location")
        )
    world = infer_world(script_text, wb, llm, known_locations=known_locations)
    wb.world = {
        "era": world.era.model_dump(),
        "technology": world.technology,
        "magic_system": world.magic_system.model_dump(),
        "government": world.government,
        "class_structure": world.class_structure,
        "daily_life": world.daily_life.model_dump(),
        "economy": world.economy.model_dump(),
    }
    wb.locations = [
        Location(
            id=_slug(loc.name, "loc"), name=loc.name,
            description=loc.description, recurring=loc.recurring,
            sd_prompt=_location_sd_prompt(loc.name, loc.description, world.era.value),
            evidence=loc.evidence,
            angles=loc.angles or ["wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"],
            connections=loc.connections or [],
        )
        for loc in world.locations
    ]
    wb.recurring_assets = [
        {
            "id": _slug(a.name, "asset"), "name": a.name, "category": a.category,
            "description": a.description, "evidence": a.evidence,
        }
        for a in world.recurring_assets
    ]

    merged_locations = merge_dossier_locations(wb, project_dir)
    if merged_locations:
        logger.info("[stage1_world] merged stage0 dossier 360-views into %d locations", merged_locations)

    # v2 delta: relationship web.
    wb.relationships = build_relationships(script_text, wb, llm)

    # Step 4: contradictions (+ auto-resolution per [automation]).
    findings = detect_contradictions(
        script_text, wb, llm, auto_resolve=config.automation.auto_resolve_contradictions
    )
    (project_dir / "worldbible" / "contradictions.json").write_text(
        json.dumps(findings, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    open_contradictions = sum(1 for f in findings if not f["auto_resolved"])

    # Step 5: creative expansion.
    expanded = expand_thin_entries(wb, llm)

    # VoiceSpec registry.
    write_voice_registry(project_dir, wb, script_text)

    wb.meta.generated_at = now_iso()
    wb_path.write_text(wb.model_dump_json(indent=2), encoding="utf-8")

    scores.record("stage1", "global", "relationships", float(len(wb.relationships)))
    scores.record("stage1", "global", "locations", float(len(wb.locations)))
    scores.record("stage1", "global", "contradictions_open", float(open_contradictions))
    scores.record("stage1", "global", "entries_expanded", float(expanded))
    scores.record("stage1", "global", "era_confidence", world.era.confidence)
    scores.stage_done("stage1")

    # M2b standalone completion: stage1_world is its own stage in STAGE_ORDER
    # with a mandatory ``world_coverage`` metric -- record it and its done
    # marker here so run_all/gates resolve (design: stage1_world runs as part
    # of the stage1 dispatch AND can be gated/run individually).
    world_coverage = (
        0.25 * min(len(wb.locations) / 3.0, 1.0)
        + 0.25 * min(len(wb.relationships) / 5.0, 1.0)
        + 0.25 * float(world.era.confidence)
        + 0.25 * (1.0 if open_contradictions == 0 else 0.0)
    )
    scores.record("stage1_world", "global", "world_coverage", world_coverage)
    scores.stage_done("stage1_world")

    bp = Blueprint.load(project_dir)
    bp.stages["stage1"].status = "done"
    bp.stages["stage1"].ts = now_iso()
    bp.stages["stage1_world"].status = "done"
    bp.stages["stage1_world"].ts = now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage1", "status": "done",
        "era": world.era.value, "era_confidence": world.era.confidence,
        "locations": len(wb.locations), "relationships": len(wb.relationships),
        "contradictions": {"found": len(findings), "open": open_contradictions},
        "entries_expanded": expanded,
        "world_bible_path": str(wb_path),
    }
