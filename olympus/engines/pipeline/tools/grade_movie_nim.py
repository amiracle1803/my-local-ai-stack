#!/usr/bin/env python3
"""Movie-grade evaluation of a completed pipeline project via NVIDIA NIM."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ENGINE = ROOT / "olympus" / "engines" / "pipeline"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from pipeline.nvidia_gen import NvidiaClient, resolve_api_key  # noqa: E402
from stack.config import cfg  # noqa: E402


SYSTEM = """You are a ruthless senior film editor, anime recap producer, and story doctor. Grade the completed local anime recap as a movie, not as isolated prose. Return JSON only with this schema: {\"scores\": {\"story_fidelity\": number, \"narrative_structure\": number, \"character_arcs\": number, \"pacing\": number, \"dialogue_narration\": number, \"visual_prompt_adherence\": number, \"visual_continuity\": number, \"audio_editing\": number, \"technical_finish\": number, \"overall\": number}, \"verdict\": \"PASS|REVIEW|FAIL\", \"strengths\": [string], \"critical_failures\": [string], \"scene_notes\": [string], \"rerun_priorities\": [string]}. Use 0-10. A polished-looking artifact with story contradictions must fail."""


def extract_json(raw: str) -> dict:
    decoder = json.JSONDecoder()
    for i, char in enumerate(raw):
        if char not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[i:])
            return value
        except json.JSONDecodeError:
            continue
    return {"raw": raw[:6000], "verdict": "REVIEW"}


def compact_story(project: Path) -> str:
    source = (project / "input" / "source.txt")
    if not source.exists():
        source = project / "input" / "script.txt"
    script = source.read_text(encoding="utf-8", errors="replace")
    scenes = json.loads((project / "screenplay" / "screenplay.json").read_text())
    beats = []
    for scene in scenes.get("scenes", []):
        beats.append(f"SCENE {scene.get('id')}: {scene.get('summary', '')}")
        for shot in scene.get("shots", []):
            narration = (shot.get("narration") or {}).get("text", "")
            beats.append(f"{shot.get('id')}: beat={shot.get('beat','')}; narration={narration}")
    return "SOURCE SCRIPT:\n" + script[:26000] + "\n\nGENERATED STORYBOARD/SCREENPLAY:\n" + "\n".join(beats)[:30000]


def visual_sample(project: Path, count: int) -> list[dict]:
    sidecars = sorted(project.glob("panels/**/*.json"))
    if not sidecars:
        return []
    selected = sidecars[:: max(1, len(sidecars) // count)][:count]
    out = []
    for sidecar in selected:
        data = json.loads(sidecar.read_text())
        shot_id = sidecar.stem
        parts = shot_id.split("-")
        image = None
        if len(parts) == 3 and parts[1].isdigit() and parts[2].isdigit():
            fragment = f"_sc{int(parts[1]):03d}_sh{int(parts[2]):03d}_"
            image = next((p for p in project.glob("panels/**/*.png") if fragment in p.name and "_manga_" not in p.name), None)
        if image:
            out.append({"shot_id": shot_id, "prompt": data.get("prompt", ""), "image": image})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--visual-samples", type=int, default=6)
    args = parser.parse_args()
    project = ENGINE / "projects" / args.slug
    if not project.is_dir():
        raise SystemExit(f"missing project: {project}")
    key = resolve_api_key(cfg.nim)
    if not key:
        raise SystemExit("NVIDIA API key is not configured")
    client = NvidiaClient(cfg.nim)
    story = compact_story(project)
    raw = client.chat(
        "Grade this entire completed movie from the source and generated artifacts below.\n\n" + story,
        system=SYSTEM, model=cfg.nim.text_model, temperature=0.0, max_tokens=3000,
    )
    report = {"project": args.slug, "models": {"text": cfg.nim.text_model, "vision": cfg.nim.vision_model}, "movie_grade": extract_json(raw or "NIM unavailable"), "visual_samples": []}
    for item in visual_sample(project, args.visual_samples):
        prompt = f"Grade this frame against its exact positive prompt. Return JSON only: {{\"prompt_adherence\": number, \"character_consistency\": number, \"composition\": number, \"issues\": [string], \"verdict\": \"PASS|REVIEW|FAIL\"}}\n\nPROMPT:\n{item['prompt']}"
        raw = client.judge_vision(prompt, [item["image"]], system=SYSTEM, model=cfg.nim.vision_model, temperature=0.0, max_tokens=1000)
        report["visual_samples"].append({"shot_id": item["shot_id"], "image": str(item["image"].relative_to(project)), "result": extract_json(raw or "NIM vision unavailable")})
    out = project / "comparisons" / "movie_grade_nim.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
