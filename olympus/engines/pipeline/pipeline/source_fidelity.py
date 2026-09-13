"""Deterministic source-to-screenplay fidelity gate.

This gate protects expensive audio/image/video work from a screenplay that has
lost the source story. It is intentionally domain-light: explicit anchors are
derived from source text, while project-specific required/prohibited anchors can
be declared in ``fidelity_rules.json``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .scores import Scores


class FidelityRule(BaseModel):
    required: list[str] = Field(default_factory=list)
    ordered: list[str] = Field(default_factory=list)
    prohibited: list[str] = Field(default_factory=list)
    min_score: float = 0.65
    hard_fail: bool = False
    beats: list[dict[str, Any]] = Field(default_factory=list)


class FidelityReport(BaseModel):
    score: float
    passed: bool
    required_missing: list[str] = Field(default_factory=list)
    ordered_missing: list[str] = Field(default_factory=list)
    prohibited_found: list[str] = Field(default_factory=list)
    source_entities: list[str] = Field(default_factory=list)
    output_entities: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    repair_actions: list[str] = Field(default_factory=list)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_text(v) for v in value.values())
    return str(value)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower()).strip()


def _source_entities(source: str) -> list[str]:
    # Named entities are conservative: title-cased multiword names and explicit
    # capitalized tokens, excluding sentence-leading stopwords.
    stop = {
        "The", "Chapter", "Three", "In", "A", "An", "He", "His", "Her",
        "When", "However", "Unfortunately", "Characters", "System", "Scene",
    }
    found: list[str] = []
    for match in re.findall(r"(?<![.!?])\b[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2}\b", source):
        if match.split()[0] in stop or len(match) < 3:
            continue
        if match not in found:
            found.append(match)
    return found


def _load_rules(project_dir: Path, source: str) -> FidelityRule:
    path = project_dir / "fidelity_rules.json"
    if path.exists():
        return FidelityRule.model_validate_json(path.read_text(encoding="utf-8"))
    # Strong project-specific checks belong in a project-owned rules file, not
    # in the pipeline. This keeps the gate reusable for every scripted story.
    return FidelityRule()


def analyze(project_dir: str | Path, *, fail_hard: bool = True) -> FidelityReport:
    project_dir = Path(project_dir)
    source_path = project_dir / "input" / "source.txt"
    if not source_path.exists():
        source_path = project_dir / "input" / "script.txt"
    screenplay_path = project_dir / "screenplay" / "screenplay.json"
    source = source_path.read_text(encoding="utf-8") if source_path.exists() else ""
    screenplay = json.loads(screenplay_path.read_text(encoding="utf-8")) if screenplay_path.exists() else {}
    output = _normalize(_text(screenplay))
    source_norm = _normalize(source)
    rules = _load_rules(project_dir, source)

    derived_entities = _source_entities(source)
    # Require recurring or multiword named entities only when no explicit rules
    # exist. Single-occurrence title words are too noisy for a generic gate.
    source_counts = {entity: len(re.findall(re.escape(entity.lower()), source_norm)) for entity in derived_entities}
    derived_required = [entity for entity in derived_entities if source_counts[entity] >= 2 or " " in entity]
    required = rules.required
    required_missing = [item for item in required if item.lower() not in output]
    prohibited_found = [item for item in rules.prohibited if item.lower() in output]
    ordered_missing: list[str] = []
    cursor = 0
    for item in rules.ordered:
        pos = output.find(item.lower(), cursor)
        if pos < 0:
            ordered_missing.append(item)
        else:
            cursor = pos + len(item)
    beat_missing: list[str] = []
    beat_contradictions: list[str] = []
    for beat in rules.beats:
        label = str(beat.get("label", "")).strip()
        required_terms = [str(x).lower() for x in beat.get("terms", [])]
        if label and required_terms and not all(term in output for term in required_terms):
            beat_missing.append(label)
        for forbidden in beat.get("forbidden", []):
            if str(forbidden).lower() in output:
                beat_contradictions.append(f"{label}: {forbidden}")
    ordered_beats = [b for b in rules.beats if b.get("order") is not None]
    beat_cursor = 0
    for beat in sorted(ordered_beats, key=lambda x: int(x.get("order", 0))):
        terms = [str(x).lower() for x in beat.get("terms", [])]
        positions = [output.find(t, beat_cursor) for t in terms if output.find(t, beat_cursor) >= 0]
        if terms and len(positions) < max(1, len(terms) // 2):
            beat_missing.append(str(beat.get("label", f"beat-{beat.get('order')}")))
        elif positions:
            beat_cursor = max(positions) + 1
    entities = _source_entities(source)
    output_entities = [entity for entity in entities if entity.lower() in output]
    entity_score = len(output_entities) / len(entities) if entities else 1.0
    required_score = 1.0 - (len(required_missing) / len(required) if required else 0.0)
    order_score = 1.0 - (len(ordered_missing) / len(rules.ordered) if rules.ordered else 0.0)
    prohibited_penalty = min(1.0, len(prohibited_found) * 0.15)
    score = max(0.0, round((required_score * 0.5) + (order_score * 0.3) + (entity_score * 0.2) - prohibited_penalty, 3))
    warnings = []
    derived_missing = [item for item in derived_required if item.lower() not in output]
    if derived_missing:
        warnings.append(f"source entities absent from screenplay: {derived_missing[:12]}")
    if source_norm and screenplay_path.exists() and not source_norm[:120] in output:
        warnings.append("screenplay does not preserve the source opening context")
    # Generic mode hard-fails only on likely wholesale substitution: several
    # named source entities exist, almost none survive, and the output contains
    # unrelated named entities. Explicit rules can require stricter behavior.
    output_only_entities = [e for e in _source_entities(_text(screenplay)) if e not in entities]
    wholesale_substitution = bool(entities) and len(entities) >= 2 and entity_score < 0.35 and len(output_only_entities) >= 2
    required_missing.extend(beat_missing)
    prohibited_found.extend(beat_contradictions)
    passed = score >= rules.min_score and not prohibited_found and not (rules.hard_fail and required_missing) and not wholesale_substitution
    report = FidelityReport(
        score=score, passed=passed, required_missing=required_missing,
        ordered_missing=ordered_missing, prohibited_found=prohibited_found,
        source_entities=entities, output_entities=output_entities, warnings=warnings,
        repair_actions=[
            f"Add a dedicated screenplay shot for required beat: {label}"
            for label in beat_missing
        ],
    )
    (project_dir / "fidelity_report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report


def run_gate(project_dir: str | Path, scores: Scores) -> FidelityReport:
    report = analyze(project_dir)
    scores.record("stage2", "global", "source_fidelity_score", report.score)
    scores.record("stage2", "global", "source_fidelity_pass", 1.0 if report.passed else 0.0)
    if not report.passed:
        raise RuntimeError(
            "source fidelity gate failed; see fidelity_report.json: "
            f"missing={report.required_missing}, ordered={report.ordered_missing}, "
            f"prohibited={report.prohibited_found}"
        )
    return report


def repair_screenplay_from_rules(screenplay: dict[str, Any], rules: FidelityRule) -> int:
    """Insert explicit project-owned repair beats that are absent from a draft.

    This is deliberately opt-in. Generic stories without ``repair`` entries are
    never modified by the fidelity layer.
    """
    scenes = screenplay.get("scenes", [])
    flat = _normalize(_text(screenplay))
    inserted = 0
    for beat in sorted(rules.beats, key=lambda item: int(item.get("order", 0))):
        repair = beat.get("repair") or {}
        terms = [str(term).lower() for term in beat.get("terms", [])]
        # A beat is covered only when all of its required terms are present;
        # matching one word must not suppress repair of a partially covered beat.
        if not repair or (terms and all(term in flat for term in terms)):
            continue
        scene_index = max(0, min(len(scenes) - 1, int(repair.get("scene", 1)) - 1))
        if not scenes:
            continue
        scene = scenes[scene_index]
        shots = scene.setdefault("shots", [])
        shot_number = len(shots) + 1
        shot_id = f"sh-{scene_index + 1:03d}-{shot_number:02d}"
        shot = {
            "id": shot_id,
            "shot_type": repair.get("shot_type", "medium"),
            "composition": repair.get("composition", "medium shot, clear story beat"),
            "characters_in_frame": repair.get("characters", []),
            "positioning": repair.get("positioning", "clear readable staging"),
            "movement": repair.get("movement", "static"),
            "facial": repair.get("facial", "focused expression"),
            "posture": repair.get("posture", "natural posture"),
            "beat": repair.get("beat", beat.get("label", "required source beat")),
            "camera_angle": repair.get("camera_angle", "medium_shot"),
            "sd_prompt": "",
            "narration": None,
            "dialogue": repair.get("dialogue", []),
            "lipsync": False,
            "source_required": True,
            "fidelity_rule": beat.get("label", ""),
        }
        insert_at = max(0, min(len(shots), int(repair.get("position", len(shots)))))
        shots.insert(insert_at, shot)
        flat += " " + _text(shot)
        inserted += 1
    return inserted


def remove_prohibited_terms(screenplay: dict[str, Any], rules: FidelityRule) -> int:
    """Remove explicitly prohibited generated terms from repairable prose.

    This only applies to project-owned rules. It never changes source text and
    never silently rewrites arbitrary stories.
    """
    replacements = {
        "knife": "empty hand",
        "blade": "open palm",
        "sword": "open palm",
        "clawed fingers": "bare fingers",
        "ripped mask": "green half-mask remains in place",
    }
    changed = 0

    def scrub(value: Any) -> Any:
        nonlocal changed
        if isinstance(value, str):
            new_value = value
            for term in rules.prohibited:
                new_value = re.sub(
                    re.escape(term), replacements.get(term.lower(), ""), new_value, flags=re.IGNORECASE,
                )
            if new_value != value:
                changed += 1
            return new_value
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: scrub(item) for key, item in value.items()}
        return value

    cleaned = scrub(screenplay)
    screenplay.clear()
    screenplay.update(cleaned)
    return changed
