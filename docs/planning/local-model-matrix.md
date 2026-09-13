# Local Generation Model Matrix

Hardware baseline: RTX 4070 Laptop, 8 GB VRAM, 32 GB RAM.

## Decision

Flux.2 Klein 4B is the safe local default for T2I/I2I on this machine. Krea2
remains the preferred quality target, but its native local workflow is not
safe on the current 8 GB card and is therefore an opt-in experimental profile.

## T2I / I2I

| Model | Installed | Quality preference | 8 GB result | Decision |
|---|---:|---:|---|---|
| Krea2 Turbo Q4_K_S/M | yes | highest for the user's target look | direct 512x288 smoke OOM | experimental only |
| Krea2 NVFP4 | yes | potentially better memory behavior | not yet validated with the native workflow | test separately, do not route automatically |
| Flux.2 Klein 4B Q4_K_M | yes | good, less preferred style | completed direct smoke successfully | default |
| Anima 1.0 | yes | anime-tuned | separate encoder/checkpoint path; not current default | optional profile |

The current native Krea2 workflow requires the Qwen3-VL encoder and Qwen Image
VAE in addition to the roughly 7 GB Krea2 weights. This exceeds safe VRAM
headroom even with `--novram`. Krea2 should not be selected automatically until
an explicit low-resolution/quantized profile passes a real smoke test.

## I2I

Krea2 has the best intended identity/edit workflow, but the current Krea2 I2I
templates are not registered in the canonical runtime manifest and the native
Krea2 path is subject to the same VRAM constraint. Flux2 Klein reference-first
I2I is the current reliable local choice:

```text
panel_ref_flux_klein.json
panel_i2i_flux_klein.json
```

## I2V

| Model | Installed | Practical status |
|---|---:|---|
| LTX-2B | yes | best local candidate, but router path/workflow model locations need reconciliation |
| LTX-2.3 22B | yes | experimental/offload-heavy; too slow for routine 8 GB runs |
| Wan 2.2 TI2V 5B | yes | optional; requires a validated smoke marker and high RAM/VRAM pressure |
| SVD-XT | yes | fallback candidate for short motion, lower story-specific control |
| MiniMax H3 | yes | too large for default local 8 GB execution |

The I2V default should remain disabled for smoke and panel-mode assembly. When
enabled, LTX-2B should be the first validation target after its workflow paths
are corrected to the installed `diffusion_models/` and encoder locations.

## Current Routing

```toml
[comfyui.models]
panel = "flux-2-klein-4b-Q4_K_M.gguf"
character = "flux-2-klein-4b-Q4_K_M.gguf"
fallback = "flux-2-klein-4b-Q4_K_M.gguf"
```

This is intentional. It is not a claim that Flux2 is visually superior to
Krea2; it is a stability decision for the current hardware.

## Next Model Work

1. Build an isolated Krea2 NVFP4 smoke profile at 384x216 and 512x288.
2. Measure peak VRAM, render time, face quality, and prompt adherence.
3. Add Krea2 as a UI-selectable experimental profile only if both resolutions
   pass without OOM.
4. Reconcile LTX-2B workflow paths and run a single 24-frame smoke render.
5. Do not delete existing models until provider references and project contracts
   prove they are unused.
