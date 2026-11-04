# ComfyUI Rebuild and OOM Log

## Current Host

- GPU: RTX 4070 Laptop, 8 GB VRAM
- ComfyUI: 0.33.0
- PyTorch: 2.7.1+cu126
- Launch flags: `--novram --disable-cuda-malloc --cache-lru 4 --preview-method none`

## Findings

### Krea2

Installed native Krea2 assets:

- `models/unet/krea2_turbo-Q4_K_S.gguf` (about 7 GB)
- `models/unet/krea2_turbo-Q4_K_M.gguf` (about 7 GB)
- Qwen3-VL encoder
- Qwen Image VAE

Direct native Krea2 smoke at 512x288 failed with CUDA OOM. The model plus
encoder/VAE leaves insufficient VRAM headroom on this host. Krea2 remains the
preferred quality target but is not a safe default.

### Flux2 Klein

Installed and validated:

- `flux-2-klein-4b-Q4_K_M.gguf`
- `qwen_3_4b.safetensors`
- `flux2-vae.safetensors`

The native API workflow completed direct T2I smoke renders. Flux2 remains the
stable default T2I/I2I path.

### LTX2B

Installed assets:

- `models/diffusion_models/ltxv-2b-0.9.8-distilled-fp8-i2v.safetensors`
- `models/text_encoders/t5xxl_fp8_e4m3fn.safetensors`

The previous router checked obsolete `models/checkpoints` and `models/clip`
locations; those paths are corrected.

Three short I2V smokes passed:

| Seed | Time | Result |
|---:|---:|---|
| 42 | 16.1s | PASS |
| 1337 | 17.1s | PASS |
| 424242 | 17.1s | PASS |

The current canonical workflow is video-only. ComfyUI logs show audio connector
keys in the model checkpoint as unexpected, which means the installed runtime
workflow is not yet using LTX2 audio conditioning. The Aitrepreneur video's
custom-audio workflow must be rebuilt and validated separately before claiming
audio-driven I2V support.

### Wan / LTX2.3 / MiniMax

Weights are installed, but these are not safe defaults for the 8 GB card:

- Wan2.2 requires a validated smoke marker and remains opt-in.
- LTX2.3 22B is offload-heavy and too slow for routine production.
- MiniMax H3 is too large for the default local profile.

## Runtime Policy

```text
T2I/I2I: Flux2 Klein default
Krea2: experimental, host-specific OOM gate required
I2V: LTX2B, smoke-gated
Wan/LTX2.3/MiniMax: experimental only
```

No models were deleted. The evidence supports capability gates and profile
selection, not destructive cleanup.
