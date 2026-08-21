# LTX Director (V2V) — stage3c engine research & usage (2026-08-20)

Status: **Active** — LTXDirector is the primary stage3c engine (`[animation]
engine = "ltx_director"`). It produced the best animation result so far. This
file records how the node actually works (read from its backend source) and how
we use it, plus what is deliberately deferred.

## Engine config knob
`stack.toml` `[animation] engine` selects the stage3c animation engine:
  "ltx_director" (primary) | "ltx2b" | "svd_xt" | "wan22" | "wan22_2f" | "ltx23"
Template: `olympus/engines/pipeline/workflows/ltx_director_23.json`
Router/dispatch: `stage3c_animation.py` `_render_director_phase()`
Config mirrors: `stack/config.py` + `olympus/.../pipeline/config.py` +
`stack.toml`.

## What the node is
`LTXDirector` (`ComfyUI/custom_nodes/ComfyUI-LTXDirector/ltx_director.py`) is the
WYSIWYG-timeline variant of "Prompt Relay Encode" (LTX-2.3). It composes a
directed clip from a **timeline** of segments, not a single start frame. It is
NOT a LoRA node — it consumes `clip` + `model` and produces conditioning, a
latent, guide data, and a patched model. LoRAs enter through the downstream
`LTXDirectorGuide` node's `ic_lora_name`/`ic_lora_strength` inputs (IC-LoRA
video), and are **deferred** (see below).

## Timeline format (the critical part)
The `timeline_data` JSON drives everything:
- `segments[]` each with `{start, length, type, prompt|imageFile, isEndFrame}`.
  - `type:"text"`  → a local beat prompt.
  - `type:"image"` → a keyframe (start frame); loaded via `_load_image_tensor`,
    resized to `custom_width/height` (0 = keep AR, snapped to `divisible_by`).
  - `type:"video"` → a source clip (true V2V); loaded via `_load_video_tensor`
    using `imageFile`/`trimStart`/`length` frames.
- `motionSegments[]` → IC-LoRA motion video guidance (only read when
  `use_custom_motion` is true).
- `global_prompt` anchors identity/style across the whole clip.

Prompt encoding (`_encode_relay`, ltx_director.py:773):
- `local_prompts` is split on `"|"` → `locals_list`. Empty entries fall back to
  `global_prompt`. Each non-empty entry becomes a token-range segment.
- `segment_lengths` is a comma list of **pixel-frame** counts, one per
  `locals_list` entry, converted to latent lengths and distributed to exactly
  fit the latent (must have `len == len(locals_list)`).
- `guide_strength` is a comma list, one per image segment (default 1.0).

### Our per-shot construction (proven)
For one shot we emit 4 segments (empty head, image start keyframe, text beat,
empty tail) and the matching 3-entry relay strings:
```
segments = [
  {start:0, length:0,  type:text,   prompt:""},
  {start:0, length:F,  type:image,  imageFile:<panel>},
  {start:0, length:F,  type:text,   prompt:<motion beat>},
  {start:F, length:0,  type:text,   prompt:""},
]
local_prompts   = " | <motion beat>\n | "
segment_lengths = "0,<F>,0"
guide_strength  = "1.0"
```
This matches the aether-pipeline-v2 STAGE 3 (V2V Director) format exactly.
`F = _DIRECTOR_FRAMES = 97`; `duration_frames`/`end_frame` patched together via
the `FRAMES` patchable so the auto-generated latent is `97` pixel frames
(`97f @24fps = 4s`, LTX `8n+1` latent rule).

End-of-clip blur is handled **natively** by the tiled decode node's
`last_frame_fix` (set `true` in `ltx_director_23.json`), which repeats the last
latent frame through the VAE — zero extra GPU render. A separate img2img END
keyframe was trialed but reverted (doubles GPU cost per shot on 8GB and breaks
the one-render-per-shot stage3c contract).

## Template graph (ltx_director_23.json) — grounded in live /object_info
Reuses the proven 8GB LTX-2.3 22B stack from `video_i2v_ltx_23b_8gb.json`:
```
UnetLoaderGGUF(1) -> LTXVChunkFeedForward(90, chunks=2)      # 8GB FFN chunking
DualCLIPLoaderGGUF(2, gemma-3 Q3_K_XL) ; VAELoaderKJ(3, LTX23 video vae)
CLIPTextEncode(4 global) ; CLIPTextEncode(5 neg)
LTXDirector(100)  : model=[90,0], clip=[2,0], timeline/local/segments/guide,
                    custom_width/height, use_custom_motion=false
ConditioningZeroOut(102) -> LTXVConditioning(103)
LTXDirectorGuide(104): positive/negative=[103], vae=[3], latent=[100,2 video],
                    guide_data=[100,4], motion_guide_data=[100,5], model=[100,0],
                    ic_lora_name="None"
LTXVScheduler(6, latent=[104,2]) ; RandomNoise(7) ; KSamplerSelect(8)
CFGGuider(9, model=[90,0]) -> SamplerCustomAdvanced(10, latent=[104,2])
LTXVSpatioTemporalTiledVAEDecode(11) -> VHS_VideoCombine(12)
```
Outputs are collected via the standard `ComfyClient._collect` (VHS `gifs`).

## Verified result
Re-validated 2026-08-21 with the 97-frame (4s) + `last_frame_fix` config:
**576x320, 97 frames @24fps, 4.0s, ~168s wall, `motion_verified=True`
(axis=scene, scene_speed 1.79px)**, re-render of `sh-001-02` seed 12345. The
original 33-frame run (41 frames, 1.7s, ~44s wall) also passed the optical-flow
gate — the 97f config keeps motion while eliminating end-of-clip blur via
`last_frame_fix`. Gate marker `.ltx_director_smoke_passed` refreshed.

## Deferred / not wired (by decision)
- **IC-LoRA (LoRA) step skipped for now.** The `LTXDirectorGuide` `ic_lora_name`
  stays `"None"`; `IC_LORA`/`IC_LORA_STRENGTH` patchable keys exist but are
  unused. When enabled later, IC-LoRA applies video-conditioned identity/motion
  via `motionSegments` (needs `use_custom_motion=true`). The installed LTX-2.3
  LoRAs (`LTX-2_3-ID-LoRA-CelebVHQ-3K.safetensors`, etc.) are IC-LoRA files.
- **True V2V re-render of an existing clip** (a `type:"video"` segment as the
  source) is supported by the node but not yet exercised — current path is
  image-keyframe + text beat (directed I2V), which is what produced the best
  result.
- `use_custom_audio` / `audio_vae` (generated audio track) is off.

## Re-run
`PYTHONPATH=olympus/engines/pipeline .venv/bin/python \
  olympus/engines/pipeline/tools/ltx_director_smoke.py \
  --template ltx_director_23.json --panel <panel.png>`
Writes the lab gate marker `workflows/.ltx_director_smoke_passed`.
