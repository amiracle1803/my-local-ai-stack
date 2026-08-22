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
  spellings are fuzzy-merged (``difflib.SequenceMatcher`` ratio >= 0.88 OR a
  case-insensitive prefix with the shorter name >= 3 chars, so "Eld" folds
  into "Eldrin").
- **Step 2 -- Per-character profile extraction** (:func:`extract_profiles`):
  for each scanned name, every sentence mentioning the character (plus an
  immediately-following pronoun-led sentence) is gathered into a context
  block, one temp-0.1 JSON call per character produces the profile. Then three
  code-side quality gates run:

  1. **Appearance** -- every appearance field must be a concrete value. Any
     empty/"none"/"unknown" field triggers ONE repair call (invent grounded in
     role/world); still-empty afterwards raises :class:`Stage1Error`.
  2. **sd_prompt** -- deterministically enforced to 40-60 words with no
     camera/lighting/scene/quality terms; one repair call max.
  3. **Voice** -- the LLM suggests a ``voice_id`` from the spec's table (baked
     into the profile prompt); code then enforces uniqueness/collision
     resolution across the whole cast (:func:`voice_for`).

  Finally a role-integrity pass guarantees at most one protagonist.
"""

from __future__ import annotations

import json
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
from ._util import now_iso

logger = logging.getLogger(__name__)

PROMPTS_DIR = ENGINE_ROOT / "prompts"

# Step 1 near-duplicate merge threshold (work order M2a).
_FUZZY_MERGE_RATIO = 0.88
# Prefix-merge floor: a shorter name is folded into a longer one it prefixes
# only if it is at least this long (avoids merging 1-2 letter noise).
_PREFIX_MERGE_MIN = 3

# Step 2 context-gathering cap (original spec: "200-800 word context block").
_CONTEXT_WORD_CAP = 800

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PRONOUN_START_RE = re.compile(
    r"^[\"'“”]*\b(he|she|his|her|him|hers|they|their|them|it|its)\b", re.IGNORECASE
)


class Stage1Error(ValueError):
    """Raised for stage1-specific data problems (e.g. an appearance field that
    stays empty even after a repair call)."""


# --------------------------------------------------------------------------
# Step 1 -- full-script character scan
# --------------------------------------------------------------------------
class _NameScanResult(BaseModel):
    names: list[str] = Field(default_factory=list)


def _is_prefix_match(a: str, b: str) -> bool:
    """True if the shorter of ``a``/``b`` (>= 3 chars) is a case-insensitive
    prefix of the longer -- e.g. "Eld" / "Eldrin" (FIX 5)."""
    al, bl = a.lower(), b.lower()
    shorter, longer = (al, bl) if len(al) <= len(bl) else (bl, al)
    return len(shorter) >= _PREFIX_MERGE_MIN and longer.startswith(shorter)


def _merge_names(raw_names: list[str]) -> list[str]:
    """Case-insensitive dedup (first-seen casing wins), then merge
    near-duplicate spellings: ``SequenceMatcher`` ratio >= 0.88 OR one name is
    a case-insensitive prefix of the other (shorter >= 3 chars). When two names
    merge, the longer one is kept as canonical (the more complete form is more
    likely the "real" name)."""
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
            if ratio >= _FUZZY_MERGE_RATIO or _is_prefix_match(name, existing):
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
    ``provenance`` are computed in code; ``voice_id_suggestion`` is suggested
    by the model then uniqueness-checked in code."""

    name: str
    aliases: list[str] = Field(default_factory=list)
    appearance: Appearance = Field(default_factory=Appearance)
    appearance_invented: bool = False
    sd_prompt: str = ""
    voice_id_suggestion: str = ""
    speech_style: SpeechStyle = Field(default_factory=SpeechStyle)
    personality: Personality = Field(default_factory=Personality)
    role: str = ""
    arc_this_episode: ArcThisEpisode = Field(default_factory=ArcThisEpisode)
    first_episode: str = ""


class _AppearanceRepair(BaseModel):
    """Full appearance returned by the repair call (all six fields)."""

    hair: str = ""
    eyes: str = ""
    skin: str = ""
    build: str = ""
    clothing_primary: str = ""
    distinguishing_feature: str = ""


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


# ---- FIX 1: appearance completeness ---------------------------------------
_APPEARANCE_FIELDS = (
    "hair", "eyes", "skin", "build", "clothing_primary", "distinguishing_feature",
)
_EMPTY_APPEARANCE_VALUES = {"", "none", "n/a", "na", "unknown", "-", "null"}


def _empty_appearance_fields(appearance: Appearance) -> list[str]:
    """Appearance field names whose value is missing/empty/'none'/'unknown'."""
    out = []
    for f in _APPEARANCE_FIELDS:
        value = (getattr(appearance, f) or "").strip().lower()
        if value in _EMPTY_APPEARANCE_VALUES:
            out.append(f)
    return out


def _repair_appearance(
    profile: _ProfileLLMOutput, name: str, context_block: str, llm: PipelineLLM, stage_hint: str
) -> bool:
    """Fill any empty appearance field with ONE repair call. Returns True if a
    repair was performed. Raises :class:`Stage1Error` if a field is still empty
    after the repair. (FIX 1.)"""
    missing = _empty_appearance_fields(profile.appearance)
    if not missing:
        return False

    repaired = llm.complete_json(
        "s1_appearance_repair.md",
        {
            "character_name": name,
            "context_block": context_block or "(no context found)",
            "current_appearance": json.dumps(profile.appearance.model_dump(), indent=2),
            "missing_fields": ", ".join(missing),
        },
        _AppearanceRepair,
        role="script",
        stage_hint=stage_hint,
    )
    for f in missing:
        setattr(profile.appearance, f, getattr(repaired, f))

    still_empty = _empty_appearance_fields(profile.appearance)
    if still_empty:
        raise Stage1Error(
            f"character {name!r}: appearance field(s) {still_empty} still "
            f"empty after repair -- cannot build a usable character design."
        )
    return True


# ---- FIX 2: sd_prompt enforcement -----------------------------------------
_SD_MIN_WORDS = 40
_SD_MAX_WORDS = 60

# Camera / lighting / scene / quality terms that must NOT appear in an
# appearance-only sd_prompt.
_FORBIDDEN_SD_TERMS = (
    "camera", "angle", "close-up", "closeup", "wide shot", "lens", "bokeh",
    "depth of field", "lighting", "backlit", "backlight", "cinematic",
    "atmosphere", "atmospheric", "render", "rendered", "4k", "8k", "uhd",
    "masterpiece", "best quality", "high quality", "low quality", "detailed",
    "ultra-detailed", "photorealistic", "concept art", "digital art",
    "anime style", "illustration", "trending", "sharp focus", "vignette",
    "dramatic", "dynamic pose", "high contrast", "background", "scene",
    "sunlight", "sunset", "moody", "glowing",
)
_FORBIDDEN_SD_RE = re.compile(
    "|".join(r"\b" + re.escape(t) + r"\b" for t in _FORBIDDEN_SD_TERMS),
    re.IGNORECASE,
)


def _sd_prompt_issues(sd_prompt: str) -> list[str]:
    """Word-count + forbidden-term problems with an sd_prompt (empty list == OK)."""
    issues: list[str] = []
    wc = len(sd_prompt.split())
    if wc < _SD_MIN_WORDS:
        issues.append(f"too short ({wc} words; need {_SD_MIN_WORDS}-{_SD_MAX_WORDS})")
    elif wc > _SD_MAX_WORDS:
        issues.append(f"too long ({wc} words; need {_SD_MIN_WORDS}-{_SD_MAX_WORDS})")
    bad = sorted({m.group(0).lower() for m in _FORBIDDEN_SD_RE.finditer(sd_prompt)})
    if bad:
        issues.append("forbidden terms: " + ", ".join(bad))
    return issues


def _clamp_sd_words(text: str) -> str:
    """Deterministically cap ``text`` at 60 words, preferring a clean comma
    boundary when that still leaves at least 40 words. Guarantees the upper
    bound even when the model's one repair call overshoots (appearance-only
    text, so trimming the tail keeps it valid)."""
    words = text.split()
    if len(words) <= _SD_MAX_WORDS:
        return text
    clipped = " ".join(words[:_SD_MAX_WORDS]).rstrip(" ,;")
    comma = clipped.rfind(",")
    if comma != -1 and len(clipped[:comma].split()) >= _SD_MIN_WORDS:
        clipped = clipped[:comma]
    return clipped.strip().rstrip(" ,;")


def _enforce_sd_prompt(
    sd_prompt: str, appearance: Appearance, name: str, llm: PipelineLLM, stage_hint: str
) -> tuple[str, str | None]:
    """40-60 words, no camera/lighting/scene terms; ONE repair call max (mirrors
    stage0's ``_enforce_word_count`` one-extra-call pattern), then a
    deterministic 60-word clamp so the upper bound always holds. Returns
    ``(sd_prompt, applied)`` where ``applied`` is "revised" or None. (FIX 2.)"""
    issues = _sd_prompt_issues(sd_prompt)
    if not issues:
        return sd_prompt, None

    facts = "; ".join(f"{f}: {getattr(appearance, f)}" for f in _APPEARANCE_FIELDS)
    rewritten = llm.complete_text(
        "s1_sd_prompt_repair.md",
        {
            "character_name": name,
            "appearance_facts": facts,
            "sd_prompt": sd_prompt,
            "issues": "; ".join(issues),
        },
        role="script",
        stage_hint=stage_hint,
    )
    return _clamp_sd_words(rewritten.strip()), "revised"


# ---- FIX 4: voice assignment (LLM-suggested, code-enforced uniqueness) -----
# Original spec Step 2 "Voice ID assignment logic". The LLM suggests a voice id
# from the table (baked into the profile prompt); code guarantees uniqueness.
# Voice IDs must be drawn only from the Kokoro catalog installed in Voice
# Studio (/api/voices): af_heart af_bella af_nicole af_sarah af_sky,
# am_adam am_michael, bf_emma bf_isabella, bm_george bm_lewis.
_VOICE_CANDIDATES: dict[tuple[str, str], tuple[str, ...]] = {
    ("male", "formal_deep"): ("am_michael", "bm_george"),
    ("male", "young_energetic"): ("am_adam", "bm_lewis"),
    ("male", "villain_grave"): ("bm_george", "am_michael"),
    ("female", "protagonist_warm"): ("af_heart", "af_sky"),
    ("female", "cool_analytical"): ("af_sarah", "af_nicole"),
    ("female", "narrator_style"): ("af_bella", "af_nicole"),
    ("male", "british"): ("bm_george", "bm_lewis"),
    ("female", "british"): ("bf_emma", "bf_isabella"),
}
_VOICE_TO_KEY: dict[str, tuple[str, str]] = {
    vid: key for key, cands in _VOICE_CANDIDATES.items() for vid in cands
}
_ALL_VOICE_IDS = set(_VOICE_TO_KEY)

# Category keyword hints, checked in this order (first match wins). Only used
# for the fallback path when the model's suggestion is missing/invalid.
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
    """Pronoun-count heuristic (local voice-assignment signal only; not a
    persisted field). On ties, defaults to 'male' -- voice candidates require
    a gender key; this is a logged deviation, not a semantic claim."""
    male = len(_MALE_PRONOUN_RE.findall(context))
    female = len(_FEMALE_PRONOUN_RE.findall(context))
    if male == female and male == 0:
        logger.debug("_infer_gender: no pronouns found, defaulting to male")
    elif male == female:
        logger.debug("_infer_gender: tie (%d each), defaulting to male", male)
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


def _first_free(candidates: tuple[str, ...], taken: set[str]) -> str | None:
    for vid in candidates:
        if vid not in taken:
            return vid
    return None


def _fallback_voice(gender: str, taken: set[str]) -> str:
    """Any free voice id for ``gender`` in table order; if the whole gender is
    exhausted, a numbered variant of its first id."""
    for (g, _cat), cands in _VOICE_CANDIDATES.items():
        if g != gender:
            continue
        free = _first_free(cands, taken)
        if free:
            return free
    base = next(cands[0] for (g, _cat), cands in _VOICE_CANDIDATES.items() if g == gender)
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


def voice_for(
    suggested: str, character: _ProfileLLMOutput, gender: str, taken: set[str]
) -> tuple[str, bool]:
    """Resolve a UNIQUE voice id, honoring the model's ``suggested`` id when it
    is valid and free. Returns ``(voice_id, collided)`` -- ``collided`` is True
    whenever the model's exact suggestion could not be used as-is (taken,
    missing, or not a table id). (FIX 4.)"""
    s = (suggested or "").strip().lower()
    if s in _ALL_VOICE_IDS:
        if s not in taken:
            return s, False
        g, cat = _VOICE_TO_KEY[s]
        alt = _first_free(_VOICE_CANDIDATES[(g, cat)], taken)
        return (alt, True) if alt else (_fallback_voice(g, taken), True)

    # Missing/invalid suggestion: derive the category from the character.
    cat = _infer_category(character, gender)
    chosen = _first_free(_VOICE_CANDIDATES[(gender, cat)], taken)
    return (chosen, True) if chosen else (_fallback_voice(gender, taken), True)


# ---- FIX 3: role integrity (at most one protagonist) ----------------------
def _resolve_protagonists(characters: list[Character], script_text: str) -> None:
    """Enforce at most one protagonist. Winner = most name mentions in the
    script; ties -> earliest first appearance. Losers are demoted to "ally".
    Mutates ``characters`` in place. (FIX 3.)"""
    protagonists = [c for c in characters if c.role.lower() == "protagonist"]
    if len(protagonists) <= 1:
        return

    def mentions(c: Character) -> int:
        return len(re.findall(re.escape(c.name), script_text, re.IGNORECASE))

    def first_idx(c: Character) -> int:
        m = re.search(re.escape(c.name), script_text, re.IGNORECASE)
        return m.start() if m else len(script_text)

    winner = max(protagonists, key=lambda c: (mentions(c), -first_idx(c)))
    for c in protagonists:
        if c is winner:
            continue
        logger.warning(
            "role integrity: demoting %r protagonist->ally (winner=%r, "
            "mentions self=%d vs winner=%d)",
            c.name, winner.name, mentions(c), mentions(winner),
        )
        c.role = "ally"


def extract_profiles(
    project_dir: str | Path, names: list[str], llm: PipelineLLM
) -> list[Character]:
    """Step 2: one profile call per name, then appearance repair, sd_prompt
    enforcement, unique-voice resolution, and a role-integrity pass."""
    project_dir = Path(project_dir)
    script_text = (project_dir / "input" / "script.txt").read_text(encoding="utf-8")
    chunks = chunk_text(
        script_text, chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP
    )

    characters: list[Character] = []
    taken_ids: set[str] = set()
    taken_voice_ids: set[str] = set()

    for name in names:
        name_slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "character"
        context_block = _gather_context(script_text, name)
        profile = llm.complete_json(
            "s1_character_profile.md",
            {"character_name": name, "context_block": context_block or "(no context found)"},
            _ProfileLLMOutput,
            role="script",
            stage_hint=f"stage1_profile_{name_slug}",
        )

        # FIX 1: appearance completeness (may invent + set appearance_invented).
        repaired = _repair_appearance(
            profile, name, context_block, llm, f"stage1_appfix_{name_slug}"
        )
        appearance_invented = profile.appearance_invented or repaired

        # FIX 2: sd_prompt 40-60 words, no camera/lighting/scene terms.
        sd_prompt, _applied = _enforce_sd_prompt(
            profile.sd_prompt, profile.appearance, name, llm, f"stage1_sdfix_{name_slug}"
        )

        char_id = _slugify(profile.name or name, taken_ids)
        taken_ids.add(char_id)

        # FIX 4: honor the model's voice suggestion, enforce uniqueness.
        gender = _infer_gender(context_block)
        voice_id, collided = voice_for(
            profile.voice_id_suggestion, profile, gender, taken_voice_ids
        )
        taken_voice_ids.add(voice_id)
        if collided:
            logger.warning(
                "voice: suggestion %r for %r not used as-is (gender=%s) -> %s",
                profile.voice_id_suggestion, profile.name or name, gender, voice_id,
            )

        characters.append(
            Character(
                id=char_id,
                name=profile.name or name,
                aliases=profile.aliases,
                appearance=profile.appearance,
                appearance_invented=appearance_invented,
                sd_prompt=sd_prompt,
                voice_id_suggestion=voice_id,
                speech_style=profile.speech_style,
                personality=profile.personality,
                role=profile.role,
                arc_this_episode=profile.arc_this_episode,
                first_episode=profile.first_episode,
                provenance=_provenance_for(name, chunks),
            )
        )

    # FIX 3: at most one protagonist.
    _resolve_protagonists(characters, script_text)
    return characters


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------


def merge_dossier_characters(wb: WorldBible, project_dir: Path) -> int:
    """Merge rich character fields from ``intake/dossier.json`` into the world
    bible's :class:`Character` profiles (matched by name, case-insensitive).

    The dossier is the stage0 rich extraction (race, age, height, gender, key
    skills, family/general background, friends). It grounds the world bible
    with facts that the M2a profile call does not ask for, so downstream
    character design and prompt assembly see the full dossier. Returns the
    number of characters enriched.
    """
    from .schemas.dossier import load_dossier

    dossier = load_dossier(project_dir)
    if dossier is None:
        return 0
    by_name = {c.name.lower(): c for c in dossier.characters}
    merged = 0
    for char in wb.characters:
        d = by_name.get(char.name.lower())
        if d is None:
            continue
        changed = False
        for field in ("gender", "race", "age", "height", "family_background", "general_background"):
            val = getattr(d, field, "")
            if val and val.lower() not in ("", "unknown", "none", "n/a"):
                setattr(char, field, val)
                changed = True
        if d.key_skills and not char.key_skills:
            char.key_skills = list(d.key_skills)
            changed = True
        if d.friends and not char.friends:
            char.friends = list(d.friends)
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
        meta=WorldBibleMeta(generated_at=now_iso(), scanned_names=scanned_names),
    )

    merged = merge_dossier_characters(wb, project_dir)
    if merged:
        logger.info("[stage1] merged stage0 dossier into %d character profiles", merged)

    out_dir = project_dir / "worldbible"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "world_bible.json"
    out_path.write_text(wb.model_dump_json(indent=2), encoding="utf-8")

    bible_coverage = (len(profiles) / len(scanned_names)) if scanned_names else 0.0
    scores.record("stage1", "global", "bible_coverage", bible_coverage)
    scores.record("stage1", "global", "characters_found", float(len(profiles)))

    bp.stages["stage1"].status = "running"
    bp.stages["stage1"].ts = now_iso()
    bp.write(project_dir)

    logger.info(
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
