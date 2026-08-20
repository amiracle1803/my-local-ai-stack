# ADR-002: Tiered LTX Video Router — 2B Default, 2.3 Tiled for Director/Long Clips

## Status
Accepted

## Date
2026-08-17

## Context
The pipeline's `video_router.py` previously had a two-tier design:
1. LTX-2B FP8 (`video_i2v_ltx_2b.json`) — default primary, validated substitute for Wan2.2
2. Wan2.2-TI2V-5B Q4_K_M (`wan_ti2v.json`) — optional higher-quality tier, gated by honest smoke render

On the RTX 4070 8GB VRAM, Wan2.2 full-res VAE decode OOMs (block-swapped stack stays resident), so Wan would not be selected until fixed. The LTX-2.3 22B tiled workflow (`video_i2v_ltx_23b_tiled.json`) existed on disk but was not in the manifest and had no router logic to select it.

The tiered routing design (M-AP-2 + M-AP-3) required:
- Tier 0/1 (ambient, static) → LTX-2B (768×448, 81 frames, fits 8GB)
- Tier 2 (director, dynamic camera) → LTX-2.3 tiled (tiled VAE decode avoids OOM at full res)
- Frames > 81 → LTX-2.3 tiled (long clips need the larger model)
- Wan2.2 NOT returned by `pick_ltx_template` — `stage3c_animation.py:357` still checks `ltx_template == "wan_ti2v.json"` for its own Wan path

## Decision
Rewrite `pipeline/video_router.py` with three-tier priority:

### Constants (module level, test-patchable names)
- `_DEFAULT_TEMPLATE = "video_i2v_ltx_2b.json"` — LTX-2B default primary (in manifest ✓)
- `_TIER2 = 2`
- `_TILED_TEMPLATE = "video_i2v_ltx_23b_tiled.json"` — on disk, NOT in manifest
- `_ltx2b_weights_ready(config)` / `_ltx2b_lab_passed()` — existing
- `_ltx23_weights_ready(config)` / `_ltx23_lab_passed()` — NEW (checks unet + 2×clip + vae for 2.3)
- `_wan_weights_ready(config)` / `_wan_lab_passed()` — existing (not returned by router)

### Routing Logic (`pick_ltx_template(config, tier, frames)`)
```
1. If ltx23 weights ready AND lab passed AND (tier >= 2 OR frames > 81):
       return _TILED_TEMPLATE
2. Elif ltx2b weights ready AND lab passed:
       return _DEFAULT_TEMPLATE
3. Else:
       log warning/error, return None
```
Wan2.2 is explicitly NOT returned — `stage3c_animation.py` handles its own Wan check.

### LTX-2.3 Weights Check
Checks all four required files (on-disk paths verified):
- `models/unet/ltx-2.3-22b-distilled-1.1-Q4_K_M.gguf` (≥2GB)
- `models/text_encoders/gemma-3-12b-it-qat-UD-Q3_K_XL.gguf` (≥100MB)
- `models/text_encoders/ltx-2.3_text_projection_bf16.safetensors` (≥100MB)
- `models/vae/ltx/LTX23_video_vae_bf16.safetensors` (≥100MB)
Lab gate: `ENGINE_ROOT / "workflows" / ".ltx23_smoke_passed"`

### Stale Test Updates
- `test_comfy_client.py`: manifest names fixed (`image_flux_fallback.json`, `wan_ti2v.json`)
- `test_config.py`: fallback/floor = `flux1-schnell-Q4_K_S.gguf` (per stack.toml)
- `test_stage1.py`: voice candidates updated to Kokoro catalog (`am_adam`, `bm_lewis`, `af_heart`, etc.)
- `test_studio_api.py`: CSRF-aware TestClient (GET / to prime cookie, then `x-csrf-token` header)
- `test_video_router.py`: mock `_wan_weights_ready` in degradation test
- `conftest.py`: `tmp_comfyui_dir` + `test_config` fixtures to isolate ComfyUI writes

## Alternatives Considered
| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| Keep Wan as tier-2 | Simpler (two tiers) | Wan OOMs on 8GB; tier-2 needs higher quality than 2B | Rejected |
| Return Wan from router | Unified API | stage3c already has Wan check; would duplicate logic | Rejected |
| LTX-2.3 for all tiers | One model | 2.3 is heavier; 2B sufficient for ambient/short | Rejected |
| Put tiled template in manifest | Consistent loading | Tiled is experimental; not meant for general use | Rejected (kept on-disk only) |

## Consequences
- **Positive**: Tier-2 director shots and long clips (>81 frames) now route to LTX-2.3 tiled when weights + smoke gate are ready, avoiding OOM. LTX-2B remains default for Tier-0/1. All 191 pipeline tests pass.
- **Negative**: New weight-check functions add ~50 lines. `_TILED_TEMPLATE` not in manifest means `WorkflowTemplate.load()` will fail if called directly — only `pick_ltx_template` returns it.
- **Neutral**: Wan2.2 path unchanged in `stage3c_animation.py`.

## Verification
- `pytest olympus/engines/pipeline/tests/ -q` → 191 passed
- Key tests passing: `test_tier1_ambient_uses_default_when_ltx2b_ready`, `test_tier2_director_uses_tiled_when_ltx23_ready`, `test_frames_above_ceiling_uses_tiled_when_ltx23_ready`, `test_degrades_to_tier0_when_no_ltx_available`, `test_falls_back_to_ltx2b_when_ltx23_not_ready`