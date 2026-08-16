"""ComfyClient: template patching by manifest titles + ban enforcement."""

import pytest

from pipeline.comfy_client import ComfyError, WorkflowTemplate, _banned_models_in


def test_flux_template_loads_and_patches():
    t = WorkflowTemplate.load("image_flux_fallback_txt2img.json")
    g = t.patched({"PROMPT_POS": "a red fox", "SEED": 42, "WIDTH": 512, "HEIGHT": 512})
    assert g["11"]["inputs"]["text"] == "a red fox"
    assert g["14"]["inputs"]["seed"] == 42
    assert g["13"]["inputs"]["width"] == 512
    # original template untouched (deep copy)
    assert t.graph["14"]["inputs"]["seed"] == 0


def test_unknown_patch_title_rejected():
    t = WorkflowTemplate.load("image_flux_fallback_txt2img.json")
    with pytest.raises(ComfyError):
        t.patched({"NOT_A_TITLE": 1})


def test_ban_check_matches_with_and_without_extension():
    graph = {"1": {"inputs": {"ckpt_name": "NoobAI-XL-v1.1.safetensors"}}}
    assert _banned_models_in(graph, ["NoobAI-XL-v1.1"]) == ["NoobAI-XL-v1.1.safetensors"]
    graph2 = {"1": {"inputs": {"unet_name": "flux1-schnell-Q4_K_S.gguf"}}}
    assert _banned_models_in(graph2, ["NoobAI-XL-v1.1"]) == []


def test_all_manifest_templates_validate():
    import json
    from pipeline.comfy_client import WORKFLOWS_DIR

    manifest = json.loads((WORKFLOWS_DIR / "manifest.json").read_text())
    for name in manifest["templates"]:
        WorkflowTemplate.load(name)  # raises if a patch target is missing


def test_ltx2b_template_patches_and_routes():
    """LTX-2 2B is the primary animation path. 2026-08-07: switched from the
    broken gemma+patched-connector (caption_channels 3840, flat mush) to
    T5-XXL + the original un-patched 2B checkpoint (caption_channels 4096).
    It must load as a patchable workflow and be the default route for Tier-1
    ambient shots (the validated 768x448x81f configuration)."""
    from pipeline.video_router import pick_ltx_template
    from unittest.mock import MagicMock
    import pipeline.video_router as vr

    # Mock the readiness checks
    vr._ltx2b_weights_ready = lambda c: True
    vr._ltx2b_lab_passed = lambda: True
    vr._ltx23_weights_ready = lambda c: False
    config = MagicMock()

    t = WorkflowTemplate.load("video_ltx2b_i2v.json")
    g = t.patched({
        "MOTION_PROMPT": "slow pan, hair drifts",
        "START_FRAME": "anim_sh-001-01.png",
        "WIDTH": 768, "HEIGHT": 448, "FRAMES": 81, "STEPS": 8,
        "SEED": 1234, "FPS": 16, "SAVE_PREFIX": "pipeline/p/clips/s",
    })
    assert g["4"]["inputs"]["text"] == "slow pan, hair drifts"
    assert g["50"]["inputs"]["image"] == "anim_sh-001-01.png"
    assert g["52"]["inputs"]["length"] == 81
    # original untouched (deep copy)
    assert t.graph["52"]["inputs"]["length"] == 81
    # loader must reference the original (un-patched) 2B checkpoint + T5-XXL
    assert g["1"]["inputs"]["ckpt_name"] == "ltxv-2b-0.9.8-distilled-fp8-i2v.safetensors"
    assert g["2"]["inputs"]["clip_name"] == "t5xxl_fp8_e4m3fn.safetensors"
    assert g["2"]["inputs"]["type"] == "ltxv"
    # prompt+negative routes through distinct nodes (was pos==neg, zeroing guidance)
    assert g["4"]["class_type"] == "CLIPTextEncode"
    assert g["5"]["class_type"] == "CLIPTextEncode"
    assert g["53"]["inputs"]["positive"] == ["4", 0]
    assert g["53"]["inputs"]["negative"] == ["5", 0]
    # VAE comes from the checkpoint's bundled VAE (port 2), not the broken LTX23 VAE
    assert g["11"]["inputs"]["vae"] == ["1", 2]
    assert pick_ltx_template(config, 1, 81) == "video_ltx2b_i2v.json"


def test_wan_i2v_template_patches():
    """Wan 2.2 TI2V-5B I2V comparison template must load and patch so the
    same panel start frame drives both the LTX-2 2B and Wan paths."""
    t = WorkflowTemplate.load("video_wan_i2v.json")
    g = t.patched({
        "MOTION_PROMPT": "slow push-in, hair drifts",
        "START_FRAME": "anim_sh-001-01.png",
        "WIDTH": 768, "HEIGHT": 448, "FRAMES": 81,
        "STEPS": 20, "CFG": 4.0, "SEED": 1234,
        "FPS": 16, "SAVE_PREFIX": "pipeline/p/clips/wan",
    })
    assert g["4"]["inputs"]["positive_prompt"] == "slow push-in, hair drifts"
    assert g["6"]["inputs"]["image"] == "anim_sh-001-01.png"
    assert g["9"]["inputs"]["num_frames"] == 81
    assert g["10"]["inputs"]["steps"] == 20
    assert g["10"]["inputs"]["cfg"] == 4.0
    assert g["13"]["inputs"]["filename_prefix"].endswith("wan")
    # original untouched (deep copy)
    assert t.graph["9"]["inputs"]["num_frames"] == 81


def test_collect_handles_vhs_video_output(tmp_path):
    """`VHS_VideoCombine` (used by every LTX animation workflow) writes its
    produced file under the ``gifs`` UI key with a ``type`` field of
    ``output`` or ``temp`` -- not the ``images`` key that SaveImage uses.
    `_collect` must copy the right file from the right root or every
    animation job reports "produced no images" even though the clip was
    written successfully."""
    import shutil
    from pipeline.comfy_client import ComfyClient
    from pipeline.config import PipelineConfig

    cfg = PipelineConfig.load()
    client = ComfyClient(cfg)

    # Fake ComfyUI layout: write the produced clip into ComfyUI/output/.
    out_root = client.config.comfyui_dir() / "output"
    sub = out_root / "anim"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "sh-001-01.mp4").write_bytes(b"FAKE_MP4")

    dest = tmp_path / "clips"
    outputs = {
        "12": {
            # VHS_VideoCombine emits this exact shape (see VideoHelperSuite/nodes.py)
            "gifs": [{"filename": "sh-001-01.mp4", "subfolder": "anim", "type": "output"}],
        }
    }
    paths = client._collect(outputs, dest)
    assert len(paths) == 1
    assert paths[0].name == "sh-001-01.mp4"
    assert paths[0].read_bytes() == b"FAKE_MP4"
    # cleanup the fixture we wrote into ComfyUI/output
    shutil.rmtree(sub, ignore_errors=True)


def test_collect_handles_vhs_temp_output(tmp_path):
    """VHS writes to ``ComfyUI/temp/`` when ``save_output=false`` --
    `_collect` must consult the ``type`` field and pull from ``temp`` not
    ``output`` (or it would raise "missing on disk" and abort the run)."""
    import shutil
    from pipeline.comfy_client import ComfyClient, ComfyError
    from pipeline.config import PipelineConfig

    cfg = PipelineConfig.load()
    client = ComfyClient(cfg)

    temp_root = client.config.comfyui_dir() / "temp"
    sub = temp_root / "preview"
    sub.mkdir(parents=True, exist_ok=True)
    (sub / "clip.webm").write_bytes(b"FAKE_WEBM")

    dest = tmp_path / "clips"
    outputs = {
        "12": {"gifs": [{"filename": "clip.webm", "subfolder": "preview", "type": "temp"}]},
    }
    paths = client._collect(outputs, dest)
    assert paths[0].name == "clip.webm"
    shutil.rmtree(sub, ignore_errors=True)


def test_collect_raises_when_image_missing(tmp_path):
    """Image outputs (SaveImage) still go through the images branch; a
    missing file must raise ComfyError so the upstream contingency can fire."""
    from pipeline.comfy_client import ComfyClient, ComfyError
    from pipeline.config import PipelineConfig

    client = ComfyClient(PipelineConfig.load())
    with pytest.raises(ComfyError):
        client._collect(
            {"9": {"images": [{"filename": "nope.png", "subfolder": "", "type": "output"}]}},
            tmp_path,
        )
