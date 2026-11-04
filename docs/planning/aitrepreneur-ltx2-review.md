# Aitrepreneur LTX2 Review

Source video: `https://www.youtube.com/watch?v=KKdEgpA3rjw`
Channel: Aitrepreneur

Local transcript:
`docs/research/aitrepreneur/KKdEgpA3rjw.transcript.txt`

## Relevant Findings

- LTX2 supports text-to-video, image-to-video, control inputs, and custom audio.
- The creator recommends the sub-12 GB VRAM quantization/profile for smaller GPUs.
- Image-to-video is preferred over text-to-video for quality.
- Custom audio should be enabled when lip-sync or timed speech matters.
- Video duration should be slightly longer than the supplied audio duration.
- The example uses short clips around 5-8 seconds, not an entire episode in one generation.
- The prompt for custom-audio mode should describe the visual action/lip-sync, not repeat the spoken transcript.

## Application To Olympus

The video supports the audio-first redesign:

```text
script -> TTS/alignment -> panel -> LTX2 I2V + matching audio -> assembly
```

It does not justify enabling 4K/50fps generation on the RTX 4070 8 GB. The
local profile should use short 24fps clips at the tested 8GB workflow size.

## Decision

- Keep Flux2 Klein as the stable local T2I/I2I fallback.
- Keep LTX2B as the first local I2V candidate.
- Add an audio-conditioned LTX2B smoke workflow before enabling stage3C.
- Use one shot/audio segment per I2V request; do not feed the full episode audio
  to one generation.
- Require a clip duration at least 0.5-1.0 seconds longer than the aligned audio
  segment, then trim/mux during stage5.
- Do not replace the current canonical workflow with imported UI subgraphs until
  the exact API node graph and model paths pass ComfyUI validation.

## Local Iteration Results

The canonical `video_i2v_ltx_2b.json` workflow was run three times on the local
ComfyUI service using the short 480x270 / 17-frame smoke profile:

| Seed | Result | Time |
|---:|---|---:|
| 42 | PASS | 16.1s |
| 1337 | PASS | 17.1s |
| 424242 | PASS | 17.1s |

Outputs were written under `/tmp/ltx-smoke/` with distinct seed labels. The
supplied UUID `3711e7a0-9365-4054-bf93-a68d5ff5075d` was checked only against
the local ComfyUI API; `/history/<uuid>` returned `{}` and the queue was empty,
so it is not an active local job or usable local API credential.

The Aitrepreneur Hugging Face account does not expose the current LTX2 Ultra
workflow used in the video. The local canonical API workflow remains the
validated implementation.
