# Voice Studio

Merged from `real-natural-voices` and `second-speech-filter-workflow` (both
archived under `_archive/` in the repo root, not deleted). Same frontend,
same HTTP API as `real-natural-voices` — the only real change is how
F5-TTS runs.

## Why a merge instead of picking one

The two source apps made opposite tradeoffs for F5-TTS, which has a history
of native crashes on Windows (see `patch_f5tts.py`):

- `real-natural-voices` loaded F5-TTS **in the Flask process**, alongside
  Chatterbox. Fast, but a crash took the whole server down (losing both
  loaded models — same VRAM-fragmentation risk already documented for
  ComfyUI on this machine in the repo's root `CLAUDE.md`).
- `second-speech-filter-workflow` ran F5-TTS in a **fresh subprocess per
  request**. Crash-safe, but reloads the ~1.5GB model every single call —
  too slow for chunked streaming.

Voice Studio runs F5-TTS in a **persistent, isolated worker subprocess**
(`f5_worker.py`, managed by `f5_client.py`'s `F5Worker` class): loads once,
stays warm, and if it crashes, only that subprocess dies — `app.py`
detects it and respawns automatically on the next request. Chatterbox
stays in-process (it's been stable, and this keeps its watermark-pipelining
optimization).

## What else changed from real-natural-voices

- `/api/humanize` (Kokoro -> XTTS-v2) was **already broken** in the source
  app — it imported `pipeline.stage1_kokoro` and `pipeline.stage2_xtts`,
  but no `pipeline/` package shipped with it and `stage2_xtts.py` didn't
  exist anywhere in the stack. `pipeline/stage1_kokoro.py` is ported from
  `second-speech-filter-workflow` (the one place it did exist);
  `pipeline/stage2_xtts.py` is new — a small wrapper around Coqui TTS's
  documented XTTS-v2 API, since `TTS.api.TTS(...).tts_to_file(...)` was
  never written despite the app already gating the feature behind
  `HAS_XTTS`.
- Dropped the vestigial `INWORLD_API_KEY` from `.env.example` (a cloud TTS
  key that nothing in the app code ever referenced).
- `patch_f5tts.py` dropped the Fish Speech patch set — neither source app
  used Fish Speech, it was dead code.

## Known issue: Chatterbox fails on the 2nd+ generation

Verified end-to-end 2026-07-02: F5-TTS (via the isolated worker) generates
correctly every time. Chatterbox works for exactly one call per process
(the startup warmup call succeeds) — every generation after that fails
inside the `chatterbox-tts` library itself:

```
File ".../chatterbox/models/t3/t3.py", line 327, in inference
    inputs_embeds = torch.cat([embeds, bos_embed], dim=1)
RuntimeError: Sizes of tensors must match except in dimension 1.
Expected size 1 but got size 2 for tensor number 1 in the list.
```

This is **not** something the merge introduced — it's the exact unmodified
`cb_model.generate(...)` call from the original `real-natural-voices`
code, reproduces identically with bf16 casting on or off, and is a bug
inside the installed `chatterbox-tts` package (looks like internal
KV-cache/conditioning state not resetting cleanly between calls). Whoever
picks this up next: try pinning a different `chatterbox-tts` version, or
look at whether `cb_model.t3` needs an explicit cache-reset call between
generations that this library version doesn't do on its own.

Until fixed, treat F5-TTS as the reliable default engine and Chatterbox
as experimental/needs-restart-between-uses.

## Run it

```
setup.bat   (first time only)
start.bat
```

Then open http://localhost:5050.
