"""Stage 1 -- WORLD BIBLE, part 1 of 2 (M2a; original spec
`aether-studio-original-spec-stages0-2.md` STAGE 1, Steps 1-2 only). World/lore
extraction, contradiction detection, and creative expansion (Steps 3-5) are
M2b -- this module writes a *partial* world bible (characters only) and does
not call ``scores.stage_done("stage1")``.

Two passes, both through :class:`~pipeline.llm.PipelineLLM`:

- **Step 1 -- Full-script character scan** (:func:`scan_characters`): the
  script is chunked 8000/400 (same chunking as Stage 0's world-bible context,
  `chunking.py`), one temp-0.1 JSON call per chunk asks for every character
  name mentioned. Results are merged case-insensitively, then near-duplicate
  spellings are fuzzy-merged (``difflib.SequenceMatcher`` ratio >= 0.88).
- **Step 2 -- Per-character profile extraction** (:func:`extract_profiles`):
  for each scanned name, every sentence mentioning the character (plus an
  immediately-following pronoun-led sentence) is gathered into a context
  block, one temp-0.1 JSON call per character produces the profile. Voice IDs
  are *not* requested from the model -- the spec's rule table is implemented
  as the deterministic :func:`voice_for` helper so uniqueness can be enforced
  across the whole cast, which a per-character LLM call cannot see.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .blueprint import Blueprint
from .chunking import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE, TextChunk, chunk_text
from .config import ENGINE_ROOT, PipelineConfig
from .llm import PipelineLLM
from .schemas.worldbible import (
    ArcThisEpisode,
    Appearance,
    Character,
    Personality,
    Provenance,
    SpeechStyle,
    WorldBible,
    WorldBibleMeta,
)
from .scores import Scores

logger = logging.getLogger(__name__)

PROMPTS_DIR = ENGINE_ROOT / "prompts"

# Step 1 near-duplicate merge threshold (work order M2a).
_FUZZY_MERGE_RATIO = 0.88

# Step 2 context-gathering cap (original spec: "200-800 word context block").
_CONTEXT_WORD_CAP = 800

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PRONOUN_START_RE = re.compile(
    r"^[\"'“”]*\b(he|she|his|her|him|hers|they|their|them|it|its)\b", re.IGNORECASE
)


# --------------------------------------------------------------------------
# Step 1 -- full-script character scan
# --------------------------------------------------------------------------
class _NameScanResult(BaseModel):
    names: list[str] = Field(default_factory=list)


def _merge_names(raw_names: list[str]) -> list[str]:
    """Case-insensitive dedup (first-seen casing wins), then fuzzy-merge
    near-duplicate spellings. When two names merge, the longer one is kept as
    canonical (the more complete form is more likely the "real" name)."""
    seen: dict[str, str] = {}
    for raw in raw_names:
        name = raw.strip()
        if not name:
            continue
        key = name.lower()
        if key not in seen:
            seen[key] = name

    merged: list[str] = []
    for name in seen.values():
        match_idx = None
        for i, existing in enumerate(merged):
            ratio = SequenceMatcher(None, name.lower(), existing.lower()).ratio()
            if ratio >= _FUZZY_MERGE_RATIO:
                match_idx = i
                break
        if match_idx is None:
            merged.append(name)
        elif len(name) > len(merged[match_idx]):
            merged[match_idx] = name
    return merged


def scan_characters(project_dir: str | Path, llm: PipelineLLM) -> list[str]:
    """Step 1: chunk ``input/script.txt`` (8000/400) and ask once per chunk
    for every character name mentioned, then merge the results."""
    project_dir = Path(project_dir)
    script_text = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
    chunks = chunk_text(
        script_text, chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
    )

    raw_names: list[str] = []
    for chunk in chunks:
        result = llm.complete_json(
            "s1_character_scan.md",
            {"chunk_text": chunk.text},
            _NameScanResult,
            role="script",
            stage_hint=f"stage1_scan_chunk{chunk.index}",
        )
        raw_names.extend(result.names)

    return _merge_names(raw_names)


# --------------------------------------------------------------------------
# Step 2 -- per-character profile extraction
# --------------------------------------------------------------------------
class _ProfileLLMOutput(BaseModel):
    """The subset of :class:`Character` the model is asked for -- ``id``,
    ``voice_id_suggestion``, and ``provenance`` are computed in code."""

    name: str
    aliases: list[str] = Field(default_factory=list)
    appearance: Appearance = Field(default_factory=Appearance)
    sd_prompt: str = ""
    speech_style: SpeechStyle = Field(default_factory=SpeechStyle)
    personality: Personality = Field(default_factory=Personality)
    role: str = ""
    arc_this_episode: ArcThisEpisode = Field(default_factory=ArcThisEpisode)
    first_episode: str = ""


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _gather_context(script_text: str, name: str, *, word_cap: int = _CONTEXT_WORD_CAP) -> str:
    """Every sentence mentioning ``name`` (case-insensitive substring), plus
    the following sentence when it opens with a pronoun, capped at
    ``word_cap`` words."""
    sentences = _split_sentences(script_text)
    name_lower = name.lower()
    picked: list[str] = []
    i = 0
    while i < len(sentences):
        if name_lower in sentences[i].lower():
            picked.append(sentences[i])
            if i + 1 < len(sentences) and _PRONOUN_START_RE.match(sentences[i + 1]):
                picked.append(sentences[i + 1])
                i += 1
        i += 1

    context = " ".join(picked)
    words = context.split()
    if len(words) > word_cap:
        context = " ".join(words[:word_cap])
    return context


def _slugify(name: str, taken_ids: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_") or "character"
    if slug not in taken_ids:
        return slug
    n = 2
    while f"{slug}_{n}" in taken_ids:
        n += 1
    return f"{slug}_{n}"


def _provenance_for(name: str, chunks: list[TextChunk]) -> list[Provenance]:
    name_lower = name.lower()
    return [Provenance(chunk_index=c.index) for c in chunks if name_lower in c.text.lower()]


# ---- voice assignment (original spec Step 2 "Voice ID assignment logic") --
# Deterministic, code-driven per the M2a work order (not requested from the
# LLM) so uniqueness can be enforced across the whole cast.
_VOICE_CANDIDATES: dict[tuple[str, str], tuple[str, ...]] = {
    ("male", "formal_deep"): ("am_eric", "am_onyx"),
    ("male", "young_energetic"): ("am_adam", "am_puck"),
    ("male", "villain_grave"): ("am_michael", "am_fenrir"),
    ("female", "protagonist_warm"): ("af_heart", "af_nova"),
    ("female", "cool_analytical"): ("af_jessica", "af_kore"),
    ("female", "narrator_style"): ("af_bella", "af_nicole"),
    ("male", "british"): ("bm_george", "bm_lewis"),
    ("female", "british"): ("bf_emma", "bf_isabella"),
}

# Category keyword hints, checked in this order (first match wins). Only
# consulted for categories valid for the character's inferred gender.
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "villain_grave": ("villain", "antagonist", "grave", "menacing", "ruthless", "cruel", "sinister"),
    "cool_analytical": ("analytical", "calculating", "logical", "detached", "composed", "strategic"),
    "young_energetic": ("energetic", "young", "eager", "impulsive", "brash", "playful", "reckless"),
    "narrator_style": ("narrator", "wise", "reflective", "omniscient"),
    "formal_deep": ("formal", "authoritative", "stern", "commanding", "measured"),
    "protagonist_warm": ("warm", "caring", "brave", "hopeful", "kind", "protective"),
}

_MALE_PRONOUN_RE = re.compile(r"\bhe\b|\bhis\b|\bhim\b", re.IGNORECASE)
_FEMALE_PRONOUN_RE = re.compile(r"\bshe\b|\bher\b|\bhers\b", re.IGNORECASE)


def _infer_gender(context: str) -> str:
    """Pronoun-count heuristic. This is a local signal only for voice
    assignment -- it is not part of the persisted :class:`Character` schema
    (not requested by the work order's field list)."""
    male = len(_MALE_PRONOUN_RE.findall(context))
    female = len(_FEMALE_PRONOUN_RE.findall(context))
    return "female" if female > male else "male"


def _infer_category(character: _ProfileLLMOutput, gender: str) -> str:
    blob = " ".join(
        [
            character.role,
            character.personality.core_drive,
            character.personality.core_fear,
            " ".join(character.personality.traits),
            character.speech_style.category,
            character.speech_style.vocabulary_register,
            character.speech_style.distinctive_patterns,
        ]
    ).lower()

    if any(k in blob for k in ("british", "posh accent", "proper english accent")):
        return "british"

    for category, keywords in _CATEGORY_KEYWORDS.items():
        if (gender, category) not in _VOICE_CANDIDATES:
            continue
        if any(k in blob for k in keywords):
            return category

    role = character.role.lower()
    if role in ("antagonist", "obstacle"):
        return "villain_grave" if gender == "male" else "cool_analytical"
    if role in ("protagonist", "ally", "mentor"):
        return "young_energetic" if gender == "male" else "protagonist_warm"
    return "formal_deep" if gender == "male" else "narrator_style"


def voice_for(
    character: _ProfileLLMOutput, gender: str, taken: set[str]
) -> tuple[str, bool]:
    """Resolve a unique voice id for ``character``. Returns
    ``(voice_id, collided)`` -- ``collided`` is True if the first-choice
    category's candidates were already taken and a fallback had to be used."""
    category = _infer_category(character, gender)
    candidates = _VOICE_CANDIDATES[(gender, category)]
    for vid in candidates:
        if vid not in taken:
            return vid, False

    # first-choice category exhausted -- try any other candidate for this
    # gender, in table order.
    for (g, _cat), cands in _VOICE_CANDIDATES.items():
        if g != gender:
            continue
        for vid in cands:
            if vid not in taken:
                return vid, True

    # total exhaustion (more cast members of one gender than voice slots) --
    # suffix a numbered variant of the gender's first table entry.
    base = next(cands[0] for (g, _cat), cands in _VOICE_CANDIDATES.items() if g == gender)
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}", True


def extract_profiles(
    project_dir: str | Path, names: list[str], llm: PipelineLLM
) -> list[Character]:
    """Step 2: one profile-extraction call per scanned name, plus code-side
    id/voice/provenance assignment."""
    project_dir = Path(project_dir)
    script_text = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
    chunks = chunk_text(
        script_text, chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
    )

    characters: list[Character] = []
    taken_ids: set[str] = set()
    taken_voice_ids: set[str] = set()

    for name in names:
        context_block = _gather_context(script_text, name)
        profile = llm.complete_json(
            "s1_character_profile.md",
            {"character_name": name, "context_block": context_block or "(no context found)"},
            _ProfileLLMOutput,
            role="script",
            stage_hint=f"stage1_profile_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}",
        )

        char_id = _slugify(profile.name or name, taken_ids)
        taken_ids.add(char_id)

        gender = _infer_gender(context_block)
        voice_id, collided = voice_for(profile, gender, taken_voice_ids)
        taken_voice_ids.add(voice_id)
        if collided:
            logger.warning(
                "voice_for: collision for character %r (gender=%s) -- fell back to %s",
                profile.name or name,
                gender,
                voice_id,
            )

        characters.append(
            Character(
                id=char_id,
                name=profile.name or name,
                aliases=profile.aliases,
                appearance=profile.appearance,
                sd_prompt=profile.sd_prompt,
                voice_id_suggestion=voice_id,
                speech_style=profile.speech_style,
                personality=profile.personality,
                role=profile.role,
                arc_this_episode=profile.arc_this_episode,
                first_episode=profile.first_episode,
                provenance=_provenance_for(name, chunks),
            )
        )

    return characters


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
    """Run Stage 1 Steps 1-2 (M2a) for the project at ``project_dir``.

    Writes a *partial* ``worldbible/world_bible.json`` (characters only) and
    records ``bible_coverage``/``characters_found``. Does not call
    ``scores.stage_done("stage1")`` -- M2b (world/lore extraction,
    contradiction detection, creative expansion) completes the stage.
    """
    project_dir = Path(project_dir)
    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")

    scanned_names = scan_characters(project_dir, llm)
    profiles = extract_profiles(project_dir, scanned_names, llm)

    bp = Blueprint.load(project_dir)
    wb = WorldBible(
        story_id=bp.story_id,
        characters=profiles,
        meta=WorldBibleMeta(generated_at=_now_iso(), scanned_names=scanned_names),
    )

    out_dir = project_dir / "worldbible"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "world_bible.json"
    out_path.write_text(wb.model_dump_json(indent=2), encoding="utf-8")

    bible_coverage = (len(profiles) / len(scanned_names)) if scanned_names else 0.0
    scores.record("stage1", "global", "bible_coverage", bible_coverage)
    scores.record("stage1", "global", "characters_found", float(len(profiles)))

    bp.stages["stage1"].status = "running"
    bp.stages["stage1"].ts = _now_iso()
    bp.write(project_dir)

    print(
        "[stage1] partial world bible written (characters only) -- world/lore "
        "extraction, contradiction detection, and creative expansion (M2b) are "
        "still pending; stage1 is not yet marked done."
    )

    return {
        "stage": "stage1",
        "status": "partial",
        "scanned_names": scanned_names,
        "profiles_count": len(profiles),
        "bible_coverage": bible_coverage,
        "world_bible_path": str(out_path),
    }
