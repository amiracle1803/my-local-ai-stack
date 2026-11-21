"""[render] profiles drive the panel + LTX graphs (2026-11-20 DynamicVRAM/quality rebuild)."""
from stack.config import RenderConfig, RenderProfile, StackConfig
from pipeline import comfy_client, ltx2b, stages

HQ = RenderProfile(panel_unet="flux-2-klein-9b-Q5_K_M.gguf", panel_clip="qwen_3_8b_fp8mixed.safetensors",
                   panel_width=1280, panel_height=720, panel_steps=4, panel_cfg=1.0,
                   panel_upscale="2x-AnimeSharpV4_RCAN.safetensors",
                   video_unet="LTXV-13B-0.9.8-distilled-Q4_K_M.gguf",
                   video_vae="LTXV-13B-0.9.8-distilled-VAE.safetensors", video_width=768, video_height=448,
                   video_upscale="ltxv-spatial-upscaler-0.9.8.safetensors", video_img_compression=35,
                   output_width=1920, output_height=1080)


def _by_type(g, t):
    return [k for k, n in g.items() if n["class_type"] == t]


def test_missing_render_table_keeps_the_legacy_recipe():
    p = RenderConfig().active()
    assert (p.panel_unet, p.panel_width, p.panel_steps, p.panel_cfg) == ("flux-2-klein-4b-Q4_K_M.gguf", 832, 20, 5.0)
    assert p.video_ckpt.startswith("ltxv-2b") and not p.video_unet and not p.video_upscale


def test_stack_toml_profiles_and_env_override(monkeypatch):
    cfg = StackConfig.load()
    assert {"fast", "hq"} <= set(cfg.render.profiles)
    monkeypatch.setenv("OLYMPUS_RENDER_PROFILE", "fast")
    fast = cfg.render.active()
    assert fast.panel_steps == 4 and fast.panel_cfg == 1.0      # klein is step-distilled
    monkeypatch.setenv("OLYMPUS_RENDER_PROFILE", "nope")
    assert cfg.render.active().panel_unet == fast.panel_unet    # unknown name -> fast


def test_panel_graph_follows_profile_and_upscales():
    g = comfy_client._graph("p", 1, "x", prof=HQ)
    assert g["1"]["inputs"]["unet_name"] == HQ.panel_unet
    assert g["2"]["inputs"]["clip_name"] == HQ.panel_clip
    assert g["13"]["inputs"]["width"] == 1280 and g["15"]["inputs"]["steps"] == 4
    assert g["18"]["inputs"]["cfg"] == 1.0
    assert g["16"]["inputs"]["images"] == ["22", 0] and g["21"]["class_type"] == "UpscaleModelLoader"
    plain = comfy_client._graph("p", 1, "x", prof=RenderProfile())
    assert plain["16"]["inputs"]["images"] == ["20", 0] and "21" not in plain


def test_ltx13b_i2v_graph_upscales_and_keeps_first_frame():
    g = ltx2b.graph("move", 7, image="panel.png", prof=HQ)
    assert g["1"]["class_type"] == "UnetLoaderGGUF" and g["1v"]["inputs"]["vae_name"] == HQ.video_vae
    assert g["6"]["inputs"]["width"] == 768 and g["6"]["inputs"]["image"] == ["5p", 0]
    assert g["5p"]["inputs"]["img_compression"] == 35
    assert _by_type(g, "LTXVLatentUpsampler") and _by_type(g, "LTXVImgToVideoInplace")
    assert len(_by_type(g, "SamplerCustomAdvanced")) == 2
    assert g["9"]["class_type"] == "VAEDecodeTiled" and g["9"]["inputs"]["samples"] == ["24", 0]
    assert g["12"]["inputs"]["sigmas"] == ltx2b.FIRST_PASS_SIGMAS


def test_ltx13b_t2v_has_no_image_nodes():
    g = ltx2b.graph("move", 7, prof=HQ)
    assert not _by_type(g, "LoadImage") and not _by_type(g, "LTXVImgToVideoInplace")
    assert g["24"]["inputs"]["latent_image"] == ["21", 0]


def test_ltx2b_checkpoint_graph_single_pass():
    g = ltx2b.graph("move", 7, image="panel.png", prof=RenderProfile())
    assert g["1"]["class_type"] == "CheckpointLoaderSimple" and "1v" not in g and "5p" not in g
    assert g["9"]["class_type"] == "VAEDecode" and g["9"]["inputs"]["samples"] == ["8", 0]
    assert g["6"]["inputs"]["height"] == 512


def test_master_size_follows_profile(monkeypatch):
    monkeypatch.setattr(comfy_client, "render_profile", lambda: HQ)
    assert stages._out_size() == (1920, 1080)
    assert "crop=1920:1080" in stages._fit(*stages._out_size())


def test_anima_profile_builds_the_anima_graph():
    """Anima (merged from the old anime-pipeline renderer): UNETLoader + Qwen3 0.6B CLIP + qwen_image
    VAE + real-cfg KSampler, quality tags prefixed, its own negative, no ReferenceLatent."""
    from stack.config import cfg
    from pipeline.comfy_client import _graph
    prof = cfg.render.profiles["anima"]
    g = _graph("Aya on the stairs", 7, "p", "", ["sheet.png"], prof)
    types = {n["class_type"] for n in g.values()}
    assert {"UNETLoader", "CLIPLoader", "KSampler", "EmptySD3LatentImage"} <= types
    assert "ReferenceLatent" not in types and "UnetLoaderGGUF" not in types
    assert g["11"]["inputs"]["text"].startswith("masterpiece, best quality") and "Aya" in g["11"]["inputs"]["text"]
    assert g["19"]["inputs"]["cfg"] == 4.0 and "worst quality" in g["12"]["inputs"]["text"]
