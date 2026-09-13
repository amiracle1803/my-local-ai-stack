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
