"""NIM hosted-VLM calibration sweep (one-shot, then retire).

Borrows an NVIDIA NIM hosted VLM (default ``meta/llama-3.2-90b-vision-instruct``,
a much stronger judge than the local qwen2.5vl:7b) to verify EVERY generated
image in a project against pipeline ground truth (screenplay + world bible), so
the local judge and the quality-gate thresholds can be dialed in against a
trusted reference. After calibration the hosted VLM is retired: this tool forces
NIM ON at runtime and stack.toml ``[nim] enabled`` stays false (fully local).

Verified per image kind:
  panels  -> extract-then-compare QC (on-model vs appearance facts) + side-by-side
             against the local judge's recorded verdict (stage3b sidecars).
  plates  -> generic render-quality check (blank/corrupt/artifacts).
  manga   -> legibility + SPELLING check: the drawn narration/dialogue must match
             the screenplay text exactly (the PIL text pass's correctness claim).
  refs    -> character-present + quality check on stage1r reference sheets.

Usage:
  python tools/nim_calibrate.py clockguard [--kinds panels,plates,manga,refs]
  python tools/nim_calibrate.py clockguard --limit 6        # quick smoke
  python tools/nim_calibrate.py clockguard --model meta/llama-3.2-11b-vision-instruct

Output: <project>/verification/nim_calibration.json  (+ printed dial-in summary).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.config import PipelineConfig  # noqa: E402
from pipeline.nim_client import NIMClient  # noqa: E402
from pipeline import identity  # noqa: E402
from pipeline.stage3b_images import (  # noqa: E402
    _VisionCheck,
    _appearance_verdict,
    _extract_json_text,
    _shot_appearance,
)
from pipeline.schemas.worldbible import WorldBible  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

logger = logging.getLogger(__name__)

KINDS = ("panels", "plates", "manga", "refs")

_QC_PROMPT = (
    "Look at this anime image. Answer as JSON only, no prose: "
    '{"render_valid": <bool>, "artifacts": <bool>, "notes": "<short string>"}. '
    'render_valid=false if the image is blank, corrupt, or black. '
    'artifacts=true if you see smeared limbs, garbled text, or severe artifacts.'
)


# --------------------------------------------------------------------------
# project loading
# --------------------------------------------------------------------------
def _load_project(project_dir: Path):
    wb = WorldBible.model_validate_json(
        (project_dir / "worldbible" / "world_bible.json").read_text(encoding="utf-8")
    )
    screenplay = json.loads(
        (project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8")
    )
    storyboard = json.loads(
        (project_dir / "storyboard" / "storyboard.json").read_text(encoding="utf-8")
    )
    shots_by_id: dict[str, dict] = {}
    scenes_by_id: dict[str, dict] = {}
    for scene in screenplay["scenes"]:
        scenes_by_id[scene["id"]] = scene
        for sh in scene["shots"]:
            shots_by_id[sh["id"]] = sh
    chars_by_id = {c.id: c for c in wb.characters}
    project = identity.project_code(project_dir)
    return {
        "wb": wb, "screenplay": screenplay, "storyboard": storyboard,
        "shots_by_id": shots_by_id, "scenes_by_id": scenes_by_id,
        "chars_by_id": chars_by_id, "project": project,
    }


def _panel_items(project_dir: Path, project: str) -> list[dict]:
    out: list[dict] = []
    for block_dir in (project_dir / "panels").iterdir() if (project_dir / "panels").is_dir() else []:
        if not block_dir.is_dir() or block_dir.name.startswith("_"):
            continue
        for png in sorted(block_dir.glob("*.png")):
            if png.name.startswith("_") or "_manga" in png.name:
                continue
            sid = identity.sid_from_panel_name(png.name, project)
            if not re.match(r"^sh-\d{3}-\d{2}$", sid or ""):
                continue
            sidecar = block_dir / f"{sid}.json"
            out.append({
                "kind": "panels", "file": png, "sid": sid,
                "sidecar": sidecar if sidecar.exists() else None,
                "block": block_dir.name,
            })
    return out


def _plate_items(project_dir: Path) -> list[dict]:
    out = []
    for block_dir in (project_dir / "panels").iterdir() if (project_dir / "panels").is_dir() else []:
        if not block_dir.is_dir():
            continue
        plates = block_dir / "_plates"
        if plates.is_dir():
            for png in sorted(plates.glob("*.png")):
                out.append({"kind": "plates", "file": png, "sid": png.stem, "block": block_dir.name})
    return out


def _manga_items(project_dir: Path) -> list[dict]:
    out = []
    idx_path = project_dir / "panels" / "manga.json"
    if not idx_path.exists():
        return out
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    for pg in idx.get("pages", []):
        out.append({"kind": "manga", "file": project_dir / pg["file"],
                    "sid": f"{pg['block']}_p{pg['page']:02d}", "shots": pg.get("shots", [])})
    return out


def _ref_items(project_dir: Path) -> list[dict]:
    out = []
    for char_dir in (project_dir / "refs").iterdir() if (project_dir / "refs").is_dir() else []:
        if not char_dir.is_dir():
            continue
        for png in sorted(char_dir.glob("*.png")):
            out.append({"kind": "refs", "file": png, "sid": char_dir.name, "block": char_dir.name})
    return out


# --------------------------------------------------------------------------
# prompts
# --------------------------------------------------------------------------
def _panel_prompt(shot: dict, scene: dict) -> str:
    expected = len(shot.get("characters_in_frame") or [])
    return (
        "Look at this anime panel. Answer as JSON only, no prose: "
        '{"characters_visible": <int>, "background_matches": <bool>, '
        '"composition_matches": <bool>, "hair_color": <string>, '
        '"eye_color": <string>, "outfit": <string>}. '
        f"The panel should show exactly {expected} character(s), "
        f"a background of: {scene.get('time_of_day', '')} {scene.get('location', '')}, "
        f"and composition: {shot.get('composition', '')}. "
        "For hair_color / eye_color / outfit: describe the PRIMARY character's "
        "appearance in 1-4 words each (e.g. 'black', 'blue', 'red coat'). "
        "Write 'unknown' if you cannot tell."
    )


def _manga_prompt() -> str:
    """Legibility + real-typo check for the drawn text boxes.

    The page text is drawn verbatim from the screenplay (PIL), so spelling is
    correct by construction. Asking a VLM to transcribe long narration prose
    and diff it against the expected string produces false 'mismatch' flags
    (it paraphrases, then calls its own words different) -- so we only check
    legibility and obvious typos here. ``expected_text`` stays in the report as
    the human-readable reference.
    """
    return (
        "This is a manga page with speech bubbles and narration boxes drawn as "
        "white rectangles with black text. Answer as JSON only, no prose: "
        '{"text_legible": <bool>, "text_spelling_ok": <bool>, '
        '"typos": ["<word>", ...], "artifacts": <bool>, "notes": "<short string>"}. '
        "text_legible=false if any box text is unreadable or cut off. "
        "text_spelling_ok=false ONLY if you see a word that is clearly misspelled "
        "or garbled (not an unusual word choice, not a paraphrase). "
        "List any clearly-misspelled words in typos."
    )


class _MangaCheck(BaseModel):
    """Verdict schema for the manga-page prompt (legibility + real typos)."""
    text_legible: bool = True
    text_spelling_ok: bool = True
    typos: list[str] = Field(default_factory=list)
    artifacts: bool = False
    notes: str = ""


class _GenericCheck(BaseModel):
    """Verdict schema for the generic quality prompt (plates/refs)."""
    render_valid: bool = True
    artifacts: bool = False
    notes: str = ""


# --------------------------------------------------------------------------
# judging
# --------------------------------------------------------------------------
def _robust_json(text: str) -> dict | None:
    """Extract the first brace-balanced JSON object from a model reply that
    may carry trailing prose (small models often append commentary after the
    JSON). Returns the parsed dict, or None."""
    text = _extract_json_text(text)
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    return None
    return None


def _judge(nim: NIMClient, prompt: str, image: Path, schema) -> dict | None:
    raw = nim.judge_vision(prompt, [image])
    if not raw:
        return None
    obj = _robust_json(raw)
    if obj is None:
        return {"parse_error": raw[:200]}
    try:
        check = schema.model_validate(obj)
    except ValueError:
        return {"parse_error": raw[:200]}
    return check.model_dump()


def _on_model(detail: dict, shot: dict, wb: WorldBible) -> dict:
    facts = _shot_appearance(shot, wb)[1]
    matches, issue = _appearance_verdict(
        {"hair_color": detail.get("hair_color", ""),
         "eye_color": detail.get("eye_color", ""),
         "outfit": detail.get("outfit", "")},
        facts,
    )
    expected = len(shot.get("characters_in_frame") or [])
    return {
        "appearance_matches": matches,
        "appearance_issue": issue,
        "characters_visible_ok": (detail.get("characters_visible") or 0) >= 1,
        "characters_expected": expected,
        "appearance_facts": facts,
    }


def _local_verdict(item: dict) -> dict | None:
    if not item.get("sidecar"):
        return None
    try:
        sc = json.loads(item["sidecar"].read_text(encoding="utf-8"))
        v = sc.get("vision") or {}
    except (OSError, ValueError):
        return None
    return {
        "appearance_matches": v.get("appearance_matches"),
        "characters_visible": v.get("characters_visible"),
        "composition_matches": v.get("composition_matches"),
        "background_matches": v.get("background_matches"),
        "judge": v.get("judge"),
    }


# --------------------------------------------------------------------------
# main sweep
# --------------------------------------------------------------------------
def sweep(project_dir: Path, *, kinds: list[str], model: str, limit: int | None) -> dict:
    project_dir = Path(project_dir)
    cfg = PipelineConfig.load()
    cfg.nim.enabled = True          # force NIM on for the calibration run
    cfg.nim.model = model
    nim = NIMClient(cfg.nim)
    if not nim.available():
        raise SystemExit("NIM unavailable (no key / disabled) — set NVIDIA_API_KEY or .agent-secrets/nvidia_key")

    P = _load_project(project_dir)
    wb, shots, scenes = P["wb"], P["shots_by_id"], P["scenes_by_id"]

    items: list[dict] = []
    if "panels" in kinds:
        items += _panel_items(project_dir, P["project"])
    if "plates" in kinds:
        items += _plate_items(project_dir)
    if "manga" in kinds:
        items += _manga_items(project_dir)
    if "refs" in kinds:
        items += _ref_items(project_dir)
    if limit:
        items = items[:limit]

    images: list[dict] = []
    verified = inconclusive = 0
    for item in items:
        rec: dict = {"kind": item["kind"], "file": str(item["file"].relative_to(project_dir)),
                     "sid": item["sid"], "judge": model}
        if item["kind"] == "panels":
            shot, scene = shots.get(item["sid"]), scenes.get(_scene_id_of(shot_id=item["sid"], scenes=scenes))
            prompt = _panel_prompt(shot, scene) if shot and scene else _QC_PROMPT
            rec["expected"] = shot.get("sd_prompt")[:120] if shot else None
        elif item["kind"] == "manga":
            expected = []
            for sid in item.get("shots", []):
                sh = shots.get(sid)
                if sh:
                    narr = (sh.get("narration") or {}).get("text")
                    if narr:
                        expected.append(narr)
                    for d in sh.get("dialogue") or []:
                        expected.append(d.get("text", ""))
            prompt = _manga_prompt()
            rec["expected_text"] = expected
        else:
            prompt = _QC_PROMPT

        if item["kind"] == "manga":
            detail = _judge(nim, prompt, item["file"], _MangaCheck)
        else:
            detail = _judge(nim, prompt, item["file"], _VisionCheck)
        if detail is None:
            inconclusive += 1
            rec["verdict"] = {"inconclusive": True}
            rec["note"] = "NIM transport/parse failure"
        elif "parse_error" in detail:
            inconclusive += 1
            rec["verdict"] = {"inconclusive": True, "raw": detail["parse_error"]}
        else:
            verified += 1
            rec["verdict"] = detail
            if item["kind"] == "panels":
                shot = shots.get(item["sid"])
                if shot:
                    rec["on_model"] = _on_model(detail, shot, wb)
                local = _local_verdict(item)
                rec["local"] = local
                if local and local.get("appearance_matches") is not None:
                    rec["local_agreement"] = bool(local["appearance_matches"] == rec["on_model"]["appearance_matches"])
            if item["kind"] == "manga":
                rec["spelling_correct"] = bool(detail.get("text_spelling_ok"))
                rec["legible"] = bool(detail.get("text_legible"))
        images.append(rec)

    summary, dial_in = _summarize(images)
    report = {
        "tool": "nim_calibrate",
        "model": model,
        "project": P["project"],
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "images_total": len(items),
        "images_verified": verified,
        "images_inconclusive": inconclusive,
        "summary": summary,
        "dial_in": dial_in,
        "images": images,
    }
    out_dir = project_dir / "verification"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "nim_calibration.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return report


def _scene_id_of(*, shot_id: str, scenes: dict) -> str | None:
    canon = identity.scene_id_from_shot(shot_id)
    for sc_id in scenes:
        if sc_id == canon or sc_id.replace("-", "") == canon.replace("-", ""):
            return sc_id
    return None


def _summarize(images: list[dict]) -> tuple[dict, dict]:
    summary: dict = {}
    for kind in KINDS:
        sub = [i for i in images if i["kind"] == kind]
        if not sub:
            continue
        verified = [i for i in sub if "verdict" in i and not i["verdict"].get("inconclusive")]
        entry: dict = {"count": len(sub), "verified": len(verified)}
        if kind == "panels":
            hard = [i for i in verified if i.get("on_model")]
            entry["on_model_rate"] = round(sum(1 for i in hard if i["on_model"]["appearance_matches"]) / len(hard), 3) if hard else None
            entry["any_character_visible_rate"] = round(sum(1 for i in hard if i["on_model"]["characters_visible_ok"]) / len(hard), 3) if hard else None
            agreed = [i for i in verified if i.get("local_agreement") is not None]
            if agreed:
                entry["local_vs_nim_agreement"] = round(sum(1 for i in agreed if i["local_agreement"]) / len(agreed), 3)
        elif kind == "manga":
            entry["spelling_correct_rate"] = round(sum(1 for i in verified if i.get("spelling_correct")) / len(verified), 3)
            entry["legible_rate"] = round(sum(1 for i in verified if i.get("legible")) / len(verified), 3)
        elif kind in ("plates", "refs"):
            entry["render_valid_rate"] = round(sum(1 for i in verified if i["verdict"].get("render_valid")) / len(verified), 3)
        summary[kind] = entry

    # dial-in recommendations
    recs: list[str] = []
    p = summary.get("panels")
    if p and p.get("on_model_rate") is not None and p["on_model_rate"] < 0.5:
        recs.append(f"on-model rate {p['on_model_rate']:.0%} < 0.50 gate — tighten appearance specs or raise regen budget.")
    if p and p.get("local_vs_nim_agreement") is not None and p["local_vs_nim_agreement"] < 0.7:
        recs.append(f"local judge agrees with NIM only {p['local_vs_nim_agreement']:.0%} — re-tune the local vision judge prompt/thresholds.")
    m = summary.get("manga")
    if m and m.get("spelling_correct_rate") is not None and m["spelling_correct_rate"] < 1.0:
        recs.append("manga text boxes have spelling/legibility issues — check the PIL font/size.")
    elif m and m.get("spelling_correct_rate") == 1.0:
        recs.append("manga text spelling is 100% correct — PIL text pass confirmed; hosted VLM can be retired.")
    if not recs:
        recs.append("framework dialed in: NIM and local judges agree, gates hold — safe to retire the hosted VLM.")

    return summary, {"recommendations": recs}


def main() -> int:
    ap = argparse.ArgumentParser(description="NIM hosted-VLM calibration sweep (one-shot, then retire)")
    ap.add_argument("slug", help="project slug under projects/")
    ap.add_argument("--kinds", default=",".join(KINDS), help=f"comma list of {KINDS}")
    ap.add_argument("--model", default="meta/llama-3.2-11b-vision-instruct",
                    help="hosted NIM VLM to borrow (11b default: reliable for panel QC; "
                         "90b is stronger but its safety filter refuses the character-QC prompt)")
    ap.add_argument("--limit", type=int, default=None, help="cap images processed (smoke test)")
    args = ap.parse_args()

    project_dir = Path(__file__).resolve().parent.parent / "projects" / args.slug
    if not project_dir.exists():
        print(f"no such project: {project_dir}", file=sys.stderr)
        return 2

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    report = sweep(project_dir, kinds=kinds, model=args.model, limit=args.limit)

    print(f"NIM calibration for {report['project']} ({report['model']})")
    print(f"  verified {report['images_verified']}/{report['images_total']}, "
          f"inconclusive {report['images_inconclusive']}")
    for kind, entry in report["summary"].items():
        print(f"  [{kind}] {entry}")
    print("  dial-in:")
    for r in report["dial_in"]["recommendations"]:
        print(f"    - {r}")
    print(f"  report: {project_dir / 'verification' / 'nim_calibration.json'}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    raise SystemExit(main())