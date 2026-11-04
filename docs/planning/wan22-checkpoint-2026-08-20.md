# Wan 2.2 I2V Progress Checkpoint (2026-08-20)

Status: **Paused** — switched to LTX-2.3 for the primary stage3c engine.
This file records everything needed to resume Wan 2.2 work later.

## Objective (still open)
Wan 2.2 was being tested as the final-pass animation model (per user's
recommendation: 5B TI2V, Q4_K_M GGUF, Flux-2-Klein keyframes as I2V input).
Problem being solved: single-frame clips were grainy/shaky/static; we moved
to FIRST+LAST-frame conditioning with consistent i2i-generated panels.

## Engine config knob
`stack.toml` `[animation] engine` selects the stage3c I2V engine:
  "ltx2b" | "svd_xt" | "wan22" (single-frame) | "wan22_2f" (first+last-frame)
Router: `olympus/engines/pipeline/pipeline/video_router.py`
  - `wan22`    -> `wan_ti2v.json`      (single-frame, prefix latent)
  - `wan22_2f` -> `wan_ti2v_2f.json`   (first+last-frame, prefix + end latent)
  - `svd_xt`   -> `video_svd.json`     (ComfyUI-native SVD)
Constants live in `stage3c_animation.py` (_WAN_* family).

## Templates built + validated (0 errors vs live /object_info)
1. `workflows/wan_ti2v.json`        — Wan 2.2 TI2V-5B, single-frame prefix
   latent (WanVideoEmptyEmbeds extra_latents), T5 bf16, block-swap 20.
   Defaults tuned to 672x384, 33f, 14 steps, cfg 2.5, identity-preserving neg.
2. `workflows/wan_ti2v_2f.json`     — FIRST+LAST frame. Start encoded + injected
   at latent index 0 (WanVideoEmptyEmbeds), end encoded + injected at
   latent index -1 (WanVideoAddExtraLatent). Two-keyframe interpolation.
3. `workflows/panel_i2i_flux_klein.json` — Flux-2-Klein img2img END-frame
   generator using core `ReferenceLatent` + `KSampler` denoise 0.55. Source
   panel is both img2img latent AND reference conditioning => characters +
   background stay consistent while the moment advances. NEG blocks
   character/background/character-count drift. This is the piece that fixed
   the "dead clip" problem.

## Verified results (single prismrebel sh-001-01 test)
- Consistent end frame via i2i: 39s, character/background held, moment advanced
  (start/end pixel diff 45.5).
- Wan 2.2 2-frame (672x384, 33f, 14 steps, cfg 2.5): 183s,
  **motion_verified=True, axis=scene, scene_speed=0.411px**.
  => FIRST Wan 2.2 clip to pass the motion gate. i2i consistency was the key.
- Clips in /tmp/i2v-shootout/:
    wan22_512x288_33f_8s.mp4                 (early sanity, scene)
    wan22_832x480_81f_20s.mp4                (post-VRAM-fix full res, scene)
    wan22_2frame_same_672x384_33f_14s.mp4    (both frames same => dead, expected)
    wan22_2frame_672x384_33f_14s.mp4         (naive end frame => dead)
    wan22_2frame_consistent_672x384_33f_14s.mp4 (i2i consistent => PASS scene)

## Remaining knobs to improve Wan motion (scene-only, 0.41px is modest)
- More frames (49-65), higher FPS (24), slightly higher CFG (2.5-3.5).
- Generate 4 seeds per shot, keep best (user recommendation).
- Full cross-shot chaining NOT yet implemented: currently _render_end_frame
  chains within one shot (start panel -> final panel). The user's desired
  cross-shot chain is: panel1 = first_shot1 -> final_shot1;
  panel2 = final_shot1 -> final_shot2 (or first_shot2 -> final_shot2).
  That logic still needs wiring in stage3c if we return to Wan.

## Model weights on disk
- diffusion_models/Wan2.2-TI2V-5B-Q4_K_M.gguf (11.34GB, primary)
- diffusion_models/Wan2_2-TI2V-5B_fp8_e4m3fn_scaled_KJ.safetensors
- text_encoders/umt5-xxl-enc-bf16.safetensors (11.4GB, T5)
- vae/Wan2_2_VAE_bf16.safetensors
- unet/flux-2-klein-4b-Q4_K_M.gguf + text_encoders/qwen_3_4b.safetensors
  + vae/flux2-vae.safetensors (for the i2i end-frame generator)

## VRAM fixes that made Wan feasible (do NOT revert)
- voice-studio.service: `Environment=CUDA_VISIBLE_DEVICES=""` (was squatting
  1.2GB VRAM as a torch CUDA context despite being CPU-only).
- comfyui-server.service: `--cache-lru 10` -> `--cache-lru 4`.
- Net effect: free VRAM 1.9GB -> 6.5GB.

## Wan 2.2 first+last-frame workflow files (user-provided reference)
- "/home/amire/Downloads/imported comfly workflows/wan2-2_flf2v-first-last-frame-video-generation.json"
  Official ComfyUI core Wan 2.2 FLF2V workflow. REQUIRES 14B high+low-noise
  model pair (14.29GB each) — too heavy for 8GB (~20GB VRAM per its own note
  on a 24GB RTX 4090). Its custom node (ed29e010...) is NOT installed; we
  replicated the technique with the installed core ReferenceLatent instead.

## How to resume
1. `stack.toml` [animation] engine = "wan22_2f"
2. Re-run stage3c on the target project; i2i end frames + 2-frame Wan render.
3. Optionally implement cross-shot chaining (see Remaining knobs) and bump
   frames/fps/seeds to strengthen motion.
