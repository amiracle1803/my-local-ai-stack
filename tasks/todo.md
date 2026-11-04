# Pipeline Redesign Tasks

- [x] Reorder stage execution to script -> audio -> visuals -> assembly.
- [x] Add faithful source intake mode.
- [x] Make stage2 independent of storyboard.
- [x] Make stage4 independent of references.
- [x] Make stage3 enrich screenplay instead of regenerating story beats.
- [x] Add prompt/beat/source provenance and immutable intake guards.
- [x] Add local TTS engine selector and fallback verification.
- [x] Add capability preflight and bounded smoke/production profiles.
- [x] Add generic source-fidelity gate and project-local repair rules.
- [x] Grade a full faithful Bloodline run with NIM.
- [ ] Build and validate audio-conditioned LTX2 API workflow using stage4 WAVs.
- [ ] Repair Bloodline visual continuity after strict beat gate passes.
- [ ] Add a verified Hugging Face T2I/I2I adapter after `HF_TOKEN` is configured.
- [ ] Revisit hosted I2V/TTS only after a provider has a verified quota and adapter.

## Prototype checkpoint (2026-09-14)

- [x] Rebuilt ComfyUI runtime at `~/Downloads/ComfyUI` with Python 3.12 and
  Torch 2.6.0+cu124; corrected the stale systemd path.
- [x] Added the hardware-aware optimizer profile manifest and GPU smoke marker.
- [x] Downloaded and validated Anima Base dependencies for the 8 GB profile.
- [x] Added native ComfyUI API panel rendering behind `OLYMPUS_REAL_COMFY=1`.
- [x] Ran `bloodline_real_smoke` through all 12 stages and produced a valid
  1280x720 H.264/AAC MP4, SRT, panels, audio timeline, and scorecard.
- [ ] Compare F5-TTS, IndexTTS2, ChatterBox, and XTTS-v2 against Kokoro.
- [x] Add TTS benchmark harness and normalize streamed WAV headers.
- [ ] Keep expressive TTS experiments in a dedicated venv; do not alter the
  shared stack venv or ComfyUI venv for model-specific Transformers pins.
- [x] Install F5-TTS in `/home/amire/Downloads/tts-f5-venv` and validate CUDA
  inference with a 24 kHz reference-free smoke output.
- [x] Install Spark-TTS 0.5B in `/home/amire/Downloads/tts-spark-venv` and
  validate CUDA voice-clone inference with the official reference audio.
- [x] Install Chatterbox Turbo in `/home/amire/Downloads/tts-chatterbox-venv`
  and validate CUDA voice-clone inference; normalize its float WAV output to
  PCM16 for pipeline compatibility.
