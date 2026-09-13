#!/usr/bin/env python3
"""Compare a completed local pipeline run against NVIDIA NIM.

This is an evaluation tool, not a runtime dependency. It sends a bounded sample
of local screenplay/prompt text and panel images to the configured NIM models,
then writes a reproducible report under the project directory.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
ENGINE = ROOT / "olympus" / "engines" / "pipeline"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.nvidia_gen import NvidiaClient, resolve_api_key  # noqa: E402
from stack.config import cfg  # noqa: E402


TEXT_SYSTEM = """You are a demanding anime recap pipeline evaluator. Compare the local artifact against the source requirements. Score each dimension from 0 to 10 and return JSON only with this shape: {\"fidelity\": number, \"prompt_adherence\": number, \"continuity\": number, \"specific_issues\": [string], \"verdict\": \"PASS|REVIEW|FAIL\"}. Do not reward attractive prose that contradicts the source."""
TEXT_PROMPT = """Evaluate this local pipeline output.

SOURCE REQUIREMENTS:
{source}

LOCAL OUTPUT:
{output}

Focus on story beat fidelity, concrete prompt constraints, character/location continuity, and omissions."""

VISION_SYSTEM = """You are a strict anime production QC evaluator. Return JSON only: {\"prompt_adherence\": number, \"character_consistency\": number, \"composition\": number, \"text_artifacts\": number, \"issues\": [string], \"verdict\": \"PASS|REVIEW|FAIL\"}. Score 0-10. Compare the image to the supplied prompt; do not infer quality from aesthetics alone."""
VISION_PROMPT = """Evaluate this local generated panel against its exact positive prompt.

POSITIVE PROMPT:
{prompt}

Check composition/camera, number and identity of characters, location, action beat, style constraints, and unwanted text."""


def _json_response(raw: str) -> dict:
    decoder = json.JSONDecoder()
    for i, c in enumerate(raw):
        if c not in "[{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[i:])
            return value
        except json.JSONDecodeError:
            continue
    return {"raw": raw[:4000], "verdict": "REVIEW"}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("slug")
    parser.add_argument("--sample-shots", type=int, default=3)
    args = parser.parse_args()
    project = ENGINE / "projects" / args.slug
    screenplay_path = project / "screenplay" / "screenplay.json"
    if not screenplay_path.exists():
        raise SystemExit(f"missing screenplay: {screenplay_path}")
    screenplay = json.loads(screenplay_path.read_text(encoding="utf-8"))
    shots = [shot for scene in screenplay.get("scenes", []) for shot in scene.get("shots", [])]
    sidecars = sorted(project.glob("panels/**/*.json"))
    sidecar_by_id = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sidecars}
    sampled = [s for s in shots if s.get("id") in sidecar_by_id][: max(1, args.sample_shots)]

    key = resolve_api_key(cfg.nim)
    if not key:
        raise SystemExit("NVIDIA API key is not configured")
    client = NvidiaClient(cfg.nim)
    report = {
        "project": args.slug,
        "models": {"text": cfg.nim.text_model, "vision": cfg.nim.vision_model},
        "sample_count": len(sampled),
        "text": [],
        "vision": [],
    }

    source = "\n".join(f"{s['id']}: {s.get('beat', '')}" for s in sampled)
    output = "\n".join(f"{s['id']}: {s.get('narration', {}).get('text', '')}" for s in sampled)
    raw = client.chat(TEXT_PROMPT.format(source=source, output=output), system=TEXT_SYSTEM, model=cfg.nim.text_model, temperature=0.0, max_tokens=1200)
    report["text"] = _json_response(raw or "NIM text comparison failed")

    for shot in sampled:
        sidecar = sidecar_by_id[shot["id"]]
        parts = shot["id"].split("-")
        canonical_fragment = f"_sc{int(parts[1]):03d}_sh{int(parts[2]):03d}_"
        panel = next(
            (p for p in project.glob("panels/**/*.png") if canonical_fragment in p.name and "_manga_" not in p.name),
            None,
        )
        if panel is None:
            continue
        raw = client.judge_vision(
            VISION_PROMPT.format(prompt=sidecar.get("prompt", shot.get("sd_prompt", ""))),
            [panel], system=VISION_SYSTEM, model=cfg.nim.vision_model, temperature=0.0, max_tokens=800,
        )
        report["vision"].append({"shot_id": shot["id"], "panel": str(panel.relative_to(project)), "result": _json_response(raw or "NIM vision comparison failed")})

    out = project / "comparisons" / "local_vs_nim.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(out)
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
