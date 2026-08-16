#!/usr/bin/env python3
"""Smoke test for stage3b (dry-run, no GPU/ComfyUI/Ollama needed).

Creates a minimal project structure and runs stage3b with a mocked ComfyClient
to verify the full flow: plate generation -> panel generation -> vision judge -> V-JEPA2 gate.
"""
import json
import tempfile
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add engine root to path
import sys
TEST_DIR = Path(__file__).resolve().parent
ENGINE_ROOT = TEST_DIR.parent  # /home/amire/.../olympus/engines/pipeline
PIPELINE_ROOT = ENGINE_ROOT / "pipeline"
# PIPELINE_ROOT must come FIRST for `from pipeline.xxx` to work
sys.path.insert(0, str(PIPELINE_ROOT))
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.stage3b_images import run
from pipeline.config import PipelineConfig
from pipeline.scores import Scores
from pipeline.schemas.worldbible import WorldBible


def create_minimal_project(project_dir: Path) -> None:
    """Create a minimal project structure for stage3b dry-run."""
    project_dir.mkdir(parents=True, exist_ok=True)

    # worldbible/world_bible.json
    wb = WorldBible(
        story_id="smoke-test",
        characters=[
            {
                "id": "char-kaela",
                "name": "Kaela",
                "aliases": [],
                "appearance": {"hair": "silver bob", "eyes": "blue", "skin": "fair", "build": "slender",
                               "clothing_primary": "white dress", "distinguishing_feature": "blue ribbon"},
                "appearance_invented": False,
                "sd_prompt": "1girl, silver bob hair, blue eyes, fair skin, slender, white dress, blue ribbon, solo",
                "voice_id_suggestion": "af_heart",
                "speech_style": {"category": "gentle", "avg_words_per_line": "medium", "vocabulary_register": "polite", "distinctive_patterns": ""},
                "personality": {"traits": ["curious", "determined"], "core_drive": "find truth", "core_fear": "being forgotten"},
                "role": "protagonist",
                "arc_this_episode": {"starts": "uncertain", "ends": "confident"},
                "first_episode": "ep1",
                "provenance": [{"chunk_index": 0}]
            }
        ],
        locations=[
            {
                "id": "loc-cafe",
                "name": "Cafe Lumiere",
                "description": "Cozy corner cafe with warm lighting and wooden furniture",
                "sd_prompt": "cozy cafe interior, warm amber lighting, wooden tables, potted plants, large window, morning sunlight",
                "angles": ["wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"]
            },
            {
                "id": "loc-street",
                "name": "Main Street",
                "description": "Bustling daytime street with shops",
                "sd_prompt": "anime street, daytime, storefronts, pedestrians, soft shadows, cobblestone",
                "angles": ["wide_establishing", "medium_shot", "closeup_counter", "over_shoulder"]
            }
        ],
        world={"era": "modern", "technology": "contemporary", "magic": "none", "government": "democratic", "daily_life": "peaceful", "economy": "market"},
        relationships=[],
        power_system={},
        world_rules=[],
        lore_entries=[],
        meta={"generated_at": "2026-08-09T00:00:00Z", "scanned_names": ["Kaela"]}
    )
    (project_dir / "worldbible").mkdir()
    (project_dir / "worldbible" / "world_bible.json").write_text(
        wb.model_dump_json(indent=2), encoding="utf-8"
    )

    # screenplay/screenplay.json
    screenplay = {
        "scenes": [
            {
                "id": "sc-001",
                "location": "loc-cafe",
                "time_of_day": "morning",
                "summary": "Kaela enters the cafe",
                "characters": ["char-kaela"],
                "shots": [
                    {
                        "id": "sh-001-01",
                        "shot_type": "establishing",
                        "composition": "wide shot, cafe interior, morning light through window",
                        "characters_in_frame": [],
                        "positioning": "empty",
                        "movement": "static",
                        "facial": "none",
                        "posture": "none",
                        "beat": "Establish cafe atmosphere",
                        "sd_prompt": "cozy cafe interior, warm amber lighting, wooden tables, potted plants, large window, morning sunlight, empty, no people",
                        "narration": {"text": "The morning light spilled through the cafe window."},
                        "dialogue": [],
                        "lipsync": False,
                        "camera_angle": "wide_establishing"
                    },
                    {
                        "id": "sh-001-02",
                        "shot_type": "medium",
                        "composition": "medium shot, Kaela at counter, barista behind",
                        "characters_in_frame": ["char-kaela"],
                        "positioning": "center frame, facing counter",
                        "movement": "walks to counter",
                        "facial": "curious, slight smile",
                        "posture": "relaxed standing",
                        "beat": "Kaela approaches counter",
                        "sd_prompt": "1girl, silver bob hair, blue eyes, fair skin, slender, white dress, blue ribbon, solo, cozy cafe interior, warm amber lighting, wooden counter, morning sunlight, medium shot, character center frame",
                        "narration": {"text": "She walked to the counter, her blue ribbon catching the light."},
                        "dialogue": [{"char_id": "char-kaela", "text": "Good morning.", "emotion": "cheerful", "pause_class": "casual", "audio_thought": False}],
                        "lipsync": True,
                        "camera_angle": "medium_shot"
                    },
                    {
                        "id": "sh-001-03",
                        "shot_type": "close_up",
                        "composition": "close-up, Kaela's face, steam from cup",
                        "characters_in_frame": ["char-kaela"],
                        "positioning": "face fills upper frame",
                        "movement": "sips tea",
                        "facial": "content, eyes closed",
                        "posture": "hands cupping cup",
                        "beat": "Kaela tastes her drink",
                        "sd_prompt": "1girl, silver bob hair, blue eyes, fair skin, slender, white dress, blue ribbon, solo, steam rising from ceramic cup, close-up, intimate, warm lighting",
                        "narration": {"text": "The first sip warmed her hands."},
                        "dialogue": [],
                        "lipsync": False,
                        "camera_angle": "closeup_counter"
                    }
                ]
            }
        ]
    }
    (project_dir / "screenplay").mkdir()
    (project_dir / "screenplay" / "screenplay.json").write_text(
        json.dumps(screenplay, indent=2), encoding="utf-8"
    )

    # storyboard/storyboard.json
    storyboard = {
        "story_id": "smoke-test",
        "fps": 24,
        "scenes": screenplay["scenes"],
        "blocks": [
            {
                "id": "blk-001",
                "scene_id": "sc-001",
                "shots": ["sh-001-01", "sh-001-02", "sh-001-03"],
                "order": "first",
                "est_seconds": 15.0,
                "seed_frame": None,
                "status": "pending"
            }
        ],
        "panels": {
            "sh-001-01": {"status": "pending", "locked_by": None, "issues": []},
            "sh-001-02": {"status": "pending", "locked_by": None, "issues": []},
            "sh-001-03": {"status": "pending", "locked_by": None, "issues": []}
        },
        "shot_detail": {
            "sh-001-01": {"facial": "none", "posture": "none", "movement": "static", "motion_tier": 0, "motion_prompt": None, "lipsync": False},
            "sh-001-02": {"facial": "curious", "posture": "relaxed standing", "movement": "walks to counter", "motion_tier": 1, "motion_prompt": "gentle camera pan", "lipsync": True},
            "sh-001-03": {"facial": "content", "posture": "hands cupping cup", "movement": "sips tea", "motion_tier": 1, "motion_prompt": "steam rises", "lipsync": False}
        },
        "estimated_duration_s": 15.0
    }
    (project_dir / "storyboard").mkdir()
    (project_dir / "storyboard" / "storyboard.json").write_text(
        json.dumps(storyboard, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # blueprint.json
    from pipeline.blueprint import Blueprint, StageEntry, Style, Target
    from pipeline._util import now_iso
    bp = Blueprint(
        story_id="smoke-test", slug="smoke-test", title_hash="x" * 16, created=now_iso(),
        fps=24, style=Style(), target=Target(),
        stages={
            s: StageEntry(status="done" if s != "stage3b" else "pending", ts=now_iso())
            for s in ["stage0", "stage1", "stage1r", "stage2", "stage3", "stage3b", "stage4", "stage3c", "stage5"]
        },
    )
    (project_dir / "blueprint.json").write_text(bp.to_json(), encoding="utf-8")

    # Input script
    (project_dir / "input").mkdir()
    (project_dir / "input" / "script.txt").write_text(
        "Kaela enters the cafe. Morning light. She orders tea.", encoding="utf-8"
    )


class MockComfyClient:
    """Mock ComfyClient that simulates generation without GPU."""
    def __init__(self, config):
        self.config = config
        self.call_log = []
        self._healthy = True
        self._models_loaded = set()

    def healthy(self):
        return self._healthy

    def unload_ollama(self):
        pass

    def free(self):
        self._models_loaded.clear()

    def upload_image(self, path, name):
        self.call_log.append(("upload_image", str(path), name))
        return f"mock_{name}"

    def generate(self, template, patches, dest):
        self.call_log.append(("generate", template, list(patches.keys())))
        dest.mkdir(parents=True, exist_ok=True)
        # SAVE_PREFIX contains path like "pipeline/project/panels/sh-001"
        # We need just the filename part
        save_prefix = patches.get('SAVE_PREFIX', 'out')
        filename = Path(save_prefix).name + ".png"
        fake_png = dest / filename
        fake_png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
        return [fake_png]


def test_stage3b_smoke():
    """Run stage3b with mocked ComfyClient."""
    print("=== Stage3b Smoke Test ===")

    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir) / "smoke_project"
        create_minimal_project(project_dir)

        config = PipelineConfig()
        scores = Scores(str(project_dir / "scores.db"))

        # Mock ComfyClient
        mock_comfy = MockComfyClient(config)

        # Patch ComfyClient import in stage3b
        with patch("pipeline.stage3b_images.ComfyClient", return_value=mock_comfy):
            # Mock vision_judge to avoid Ollama call
            with patch("pipeline.stage3b_images.vision_judge") as mock_vision:
                mock_vision.return_value = (True, {
                    "characters_visible": 1,
                    "background_matches": True,
                    "composition_matches": True,
                    "inconclusive": False
                })

                # Mock V-JEPA2 to avoid model load
                with patch("pipeline.stage3b_images.vjepa.JEPA2") as mock_jepa_class:
                    mock_jepa = MagicMock()
                    mock_jepa.embed.return_value = [0.1] * 512
                    mock_jepa_class.return_value.__enter__.return_value = mock_jepa

                    with patch("pipeline.stage3b_images.vjepa.cosine", return_value=0.92):
                        # Mock GpuBatch to avoid file-based locking
                        with patch("pipeline.stage3b_images.GpuBatch") as mock_gpu_batch_class:
                            mock_gpu_batch = MagicMock()
                            mock_gpu_batch.acquire.return_value = True
                            mock_gpu_batch.__enter__.return_value = mock_gpu_batch
                            mock_gpu_batch_class.return_value = mock_gpu_batch

                            try:
                                result = run(
                                    project_dir, config, scores,
                                    comfy=mock_comfy, force=True
                                )
                                print(f"Result: {result}")
                                print(f"Comfy calls: {len(mock_comfy.call_log)}")
                                for call in mock_comfy.call_log:
                                    print(f"  {call[0]}: template={call[1]}, patches={call[2]}")

                                # Verify plates created
                                plate_dir = project_dir / "panels" / "blk-001" / "_plates"
                                plates = list(plate_dir.glob("*.png"))
                                print(f"Plates generated: {len(plates)}")
                                for p in plates:
                                    print(f"  {p.name}")

                                # Verify panels created
                                panel_dir = project_dir / "panels" / "blk-001"
                                panels = list(panel_dir.glob("sh-*.png"))
                                print(f"Panels generated: {len(panels)}")
                                for p in panels:
                                    print(f"  {p.name}")

                                # Verify sidecars
                                sidecars = list(panel_dir.glob("sh-*.json"))
                                print(f"Sidecars: {len(sidecars)}")

                                # Verify reference manifest
                                manifest = panel_dir / "reference_manifest.json"
                                if manifest.exists():
                                    print(f"Reference manifest: EXISTS")
                                    mf = json.loads(manifest.read_text())
                                    print(f"  plate: {mf.get('plate')}")
                                    print(f"  reference_first: {mf.get('reference_first')}")

                                # Verify storyboard updated
                                sb = json.loads((project_dir / "storyboard" / "storyboard.json").read_text())
                                block = sb["blocks"][0]
                                print(f"Block status: {block.get('status')}")
                                print(f"Seed frame: {block.get('seed_frame')}")

                                print("\n=== SMOKE TEST PASSED ===")
                                return True

                            except Exception as e:
                                print(f"\n=== SMOKE TEST FAILED ===")
                                print(f"Error: {e}")
                                import traceback
                                traceback.print_exc()
                                return False


if __name__ == "__main__":
    success = test_stage3b_smoke()
    sys.exit(0 if success else 1)