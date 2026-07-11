"""ComfyClient: template patching by manifest titles + ban enforcement."""

import pytest

from pipeline.comfy_client import ComfyError, WorkflowTemplate, _banned_models_in


def test_flux_template_loads_and_patches():
    t = WorkflowTemplate.load("image_flux_fallback.json")
    g = t.patched({"PROMPT_POS": "a red fox", "SEED": 42, "WIDTH": 512, "HEIGHT": 512})
    assert g["11"]["inputs"]["text"] == "a red fox"
    assert g["14"]["inputs"]["seed"] == 42
    assert g["13"]["inputs"]["width"] == 512
    # original template untouched (deep copy)
    assert t.graph["14"]["inputs"]["seed"] == 0


def test_unknown_patch_title_rejected():
    t = WorkflowTemplate.load("image_flux_fallback.json")
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
