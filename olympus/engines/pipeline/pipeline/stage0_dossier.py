"""Stage 0 dossier -- rich intake extraction (``intake/dossier.json``).

Reads the finished ``input/script.txt`` (READ-ONLY -- this module never writes
it) and extracts a :class:`~pipeline.schemas.dossier.StoryDossier`: rich
character profiles (appearance, race, age, height, build, gender, hair, family,
skills, behavior, background, friends, relationships), location dossiers with a
360-degree view, per-scene setting facts, and a per-line dialogue + body-
movement log.

The dossier is the structured story bible that stage 1 (world bible) and the
screenplay/storyboard stages consume. The script itself is protected by the
story-pollution guard (``blueprint.verify_story_guard``), and this module records
the script's sha256 in ``meta.source_hash`` so the extraction provenance is
verifiable.

Passes (all through :class:`~pipeline.llm.PipelineLLM`):

- **A -- characters**: reuse stage1's full-script name scan, then one
  :class:`CharacterDossier` call per name.
- **B -- scenes**: split the script on its ``--- [SCENE n: title] ---`` markers
  and extract a :class:`SceneDossier` per scene.
- **C -- locations**: unique location names from the scene dossiers; one
  :class:`LocationDossier` (with 360 views) call per location.
- **D -- dialogue**: one call per scene producing a list of
  :class:`DialogueEntry` (speaker, addressee, text, body movement, tone).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .blueprint import Blueprint
from .config import ENGINE_ROOT, PipelineConfig
from .llm import PipelineLLM
from .scores import Scores
from .schemas.dossier import (
    CharacterDossier,
    DialogueEntry,
    LocationDossier,
    SceneDossier,
    StoryDossier,
    StoryDossierMeta,
)
from .stage1_worldbible import scan_characters
from ._util import now_iso, read_script

logger = logging.getLogger(__name__)

PROMPTS_DIR = ENGINE_ROOT / "prompts"

# Scene markers written by stage0 Pass 3: ``--- [SCENE n: title] ---``
_SCENE_MARKER_RE = re.compile(
    r"^\s*---\s*\[SCENE\s+(\d+)\s*:\s*(.*?)\]\s*---\s*$", re.IGNORECASE
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_PRONOUN_START_RE = re.compile(
    r"^[\"'“”]*\b(he|she|his|her|him|hers|they|their|them|it|its)\b", re.IGNORECASE
)


class DossierError(ValueError):
    """Raised for stage0_dossier-specific data problems."""


# --------------------------------------------------------------------------
# small pure helpers
# --------------------------------------------------------------------------


def _script_hash(script_text: str) -> str:
    return hashlib.sha256(script_text.encode("utf-8")).hexdigest()


def _split_scenes(script_text: str) -> list[tuple[int, str, str]]:
    """Split the script on ``--- [SCENE n: title] ---`` markers.

    Returns ``[(number, title, text), ...]``. When no markers exist the whole
    script is returned as a single scene numbered 1 with an empty title.
    """
    lines = script_text.splitlines()
    markers: list[tuple[int, int, str]] = []  # (line_idx, number, title)
    for idx, line in enumerate(lines):
        m = _SCENE_MARKER_RE.match(line)
        if m:
            markers.append((idx, int(m.group(1)), m.group(2).strip()))

    if not markers:
        return [(1, "", script_text.strip())]

    scenes: list[tuple[int, str, str]] = []
    for i, (idx, number, title) in enumerate(markers):
        end = markers[i + 1][0] if i + 1 < len(markers) else len(lines)
        body = "\n".join(lines[idx + 1 : end]).strip()
        scenes.append((number, title, body))
    return scenes


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]


def _gather_context(script_text: str, name: str, *, word_cap: int = 800) -> str:
    """Every sentence mentioning ``name`` (case-insensitive), plus the following
    sentence when it opens with a pronoun, capped at ``word_cap`` words."""
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
    return " ".join(words[:word_cap]) if len(words) > word_cap else context


def _unique_preserving_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


_QUOTE_PAIRS = (('"', '"'), ("“", "”"))


def _extract_quoted_spans(text: str) -> list[str]:
    """Every dialogue span wrapped in straight or curly quotes."""
    spans: list[str] = []
    for open_q, close_q in _QUOTE_PAIRS:
        start = 0
        while True:
            i = text.find(open_q, start)
            if i == -1:
                break
            j = text.find(close_q, i + 1)
            if j == -1:
                break
            spans.append(text[i + 1 : j])
            start = j + 1
    return spans


def _norm_dialogue(s: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace -- for quote matching."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", s.lower())).strip()


def _title_logline(project_dir: Path) -> tuple[str, str]:
    """Pull title/logline from the stage0 blueprint if it exists."""
    bp_path = project_dir / "stage0_blueprint.json"
    if not bp_path.exists():
        return "", ""
    try:
        data = json.loads(bp_path.read_text(encoding="utf-8"))
        return data.get("title", ""), data.get("logline", "")
    except (json.JSONDecodeError, OSError):
        return "", ""


class _DialogueLines(BaseModel):
    lines: list[DialogueEntry] = Field(default_factory=list)


# --------------------------------------------------------------------------
# passes
# --------------------------------------------------------------------------


def extract_characters(
    project_dir: Path, llm: PipelineLLM, script_text: str
) -> list[CharacterDossier]:
    names = scan_characters(project_dir, llm)
    characters: list[CharacterDossier] = []
    for name in names:
        name_slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "character"
        context_block = _gather_context(script_text, name)
        dossier = llm.complete_json(
            "s0d_character.md",
            {"character_name": name, "context_block": context_block or "(no context found)"},
            CharacterDossier,
            role="script",
            stage_hint=f"stage0d_char_{name_slug}",
        )
        characters.append(dossier)
    return characters


def extract_scenes(project_dir: Path, llm: PipelineLLM, script_text: str) -> list[SceneDossier]:
    scenes: list[SceneDossier] = []
    for number, title, text in _split_scenes(script_text):
        dossier = llm.complete_json(
            "s0d_scene.md",
            {"scene_number": number, "scene_title": title or f"scene {number}", "scene_text": text},
            SceneDossier,
            role="script",
            stage_hint=f"stage0d_scene{number}",
        )
        dossier.number = number  # trust the marker, not the model
        scenes.append(dossier)
    return scenes


def extract_locations(
    project_dir: Path, llm: PipelineLLM, script_text: str, scenes: list[SceneDossier]
) -> list[LocationDossier]:
    names = _unique_preserving_order([s.location for s in scenes if s.location])
    locations: list[LocationDossier] = []
    for name in names:
        name_slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "location"
        context_block = _gather_context(script_text, name)
        dossier = llm.complete_json(
            "s0d_location.md",
            {"location_name": name, "context_block": context_block or "(no context found)"},
            LocationDossier,
            role="script",
            stage_hint=f"stage0d_loc_{name_slug}",
        )
        if not dossier.id:
            dossier.id = name_slug
        locations.append(dossier)
    return locations


def extract_dialogue(
    project_dir: Path, llm: PipelineLLM, script_text: str
) -> list[DialogueEntry]:
    lines: list[DialogueEntry] = []
    for number, title, text in _split_scenes(script_text):
        result = llm.complete_json(
            "s0d_dialogue.md",
            {"scene_number": number, "scene_text": text},
            _DialogueLines,
            role="script",
            stage_hint=f"stage0d_dialogue{number}",
        )
        # Post-filter: only keep lines whose text is actually inside quotes in
        # the scene. The LLM otherwise reports narration ("Her breath hitched",
        # "She dropped to her knees") -- and pure-narration scenes with no
        # quoted dialogue produce zero lines, never hallucinated "narrator"
        # lines. Dialogue == quoted spoken words only.
        quoted = [q for q in _extract_quoted_spans(text) if q.strip()]
        if not quoted:
            continue  # no quoted dialogue in this scene -> no dialogue lines
        quoted_norms = [_norm_dialogue(q) for q in quoted]
        for line in result.lines:
            norm = _norm_dialogue(line.text)
            if norm and not any(norm in qn for qn in quoted_norms if qn):
                continue  # narration leakage, not a quoted line
            line.scene_number = number  # trust the marker, not the model
            lines.append(line)
    return lines


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
    """Run stage0_dossier: extract ``intake/dossier.json`` from the read-only
    script, record metrics, and mark the stage done."""
    project_dir = Path(project_dir)
    if llm is None:
        llm = PipelineLLM(config, prompts_dir=PROMPTS_DIR, logs_dir=project_dir / "logs")

    script_text = read_script(project_dir)

    # Pass A/B/C/D -- the script is read, never written.
    characters = extract_characters(project_dir, llm, script_text)
    scenes = extract_scenes(project_dir, llm, script_text)
    locations = extract_locations(project_dir, llm, script_text, scenes)
    dialogue = extract_dialogue(project_dir, llm, script_text)

    title, logline = _title_logline(project_dir)
    dossier = StoryDossier(
        title=title,
        logline=logline,
        characters=characters,
        locations=locations,
        scenes=scenes,
        dialogue=dialogue,
        meta=StoryDossierMeta(generated_at=now_iso(), source_hash=_script_hash(script_text)),
    )

    out_dir = project_dir / "intake"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "dossier.json"
    out_path.write_text(dossier.model_dump_json(indent=2), encoding="utf-8")

    # Metrics for the stage gate.
    total_views = sum(len(loc.views_360) for loc in locations)
    scores.record("stage0_dossier", "global", "characters_found", float(len(characters)))
    scores.record("stage0_dossier", "global", "locations_found", float(len(locations)))
    scores.record("stage0_dossier", "global", "scenes_analyzed", float(len(scenes)))
    scores.record("stage0_dossier", "global", "dialogue_lines", float(len(dialogue)))
    scores.record(
        "stage0_dossier", "global", "views_360_total", float(total_views),
    )
    scores.record(
        "stage0_dossier", "global", "views_360_avg",
        round(total_views / len(locations), 3) if locations else 0.0,
    )
    scores.stage_done("stage0_dossier")

    bp = Blueprint.load(project_dir)
    bp.stages["stage0_dossier"].status = "done"
    bp.stages["stage0_dossier"].ts = now_iso()
    bp.write(project_dir)

    logger.info(
        "[stage0_dossier] wrote intake/dossier.json: %d characters, %d locations "
        "(%d 360-view angles), %d scenes, %d dialogue lines",
        len(characters), len(locations), total_views, len(scenes), len(dialogue),
    )

    return {
        "stage": "stage0_dossier",
        "status": "done",
        "characters": len(characters),
        "locations": len(locations),
        "views_360_total": total_views,
        "scenes": len(scenes),
        "dialogue_lines": len(dialogue),
        "dossier_path": str(out_path),
    }
