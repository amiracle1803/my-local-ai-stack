"""
f5_worker.py -- runs F5-TTS in its own OS process, talking to app.py over
stdin/stdout JSON-lines.

Why a persistent worker instead of loading F5-TTS in the Flask process
(what real-natural-voices did) or spawning a fresh subprocess per call
(what second-speech-filter-workflow did):
  - In-process: fast, but F5-TTS is the one engine with a history of native
    crashes on Windows (see patch_f5tts.py) -- a crash there used to take
    the whole Flask app down, along with the already-loaded Chatterbox
    model, and risked the same GPU VRAM fragmentation already documented
    for ComfyUI on this machine.
  - Fresh subprocess per call: crash-safe, but reloads the ~1.5GB model on
    every single request -- too slow for the chunked streaming UI.
  - This worker: loads the model once, stays warm, and only this process
    dies if F5-TTS crashes. app.py (via the F5Worker class) detects that
    and respawns it automatically on the next request.

Protocol: one JSON object per line, both directions.
  Startup  -> stdout: {"ready": true, "sr": <int>} or {"ready": false, "error": "..."}
  Request  <- stdin:  {"ref_file","ref_text","gen_text","nfe_step","cfg_strength",
                        "speed","cross_fade_duration","out_path"}
  Response -> stdout: {"ok": true, "sr": <int>} or {"ok": false, "error": "..."}
Anything that isn't the single-line JSON protocol (model load logs, warnings,
tracebacks) goes to stderr, which the parent relays into its own console.
"""

import json
import os
import sys
import warnings

os.environ["HF_HUB_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
warnings.filterwarnings("ignore", category=FutureWarning)

# f5_tts/vocos/huggingface_hub print progress/status lines with plain print()
# during model load (e.g. "Download Vocos from huggingface ..."), which would
# land on stdout and corrupt the JSON-lines protocol below. Keep the real
# stdout handle only for _send(); everything else (including library prints
# and our own progress messages) goes to stderr instead.
_real_stdout = sys.stdout
sys.stdout = sys.stderr


def _send(obj: dict) -> None:
    _real_stdout.write(json.dumps(obj) + "\n")
    _real_stdout.flush()


def main() -> None:
    import numpy as np
    import torch
    import torchaudio

    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.set_num_threads(os.cpu_count() or 4)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from f5_tts.api import F5TTS
        print("Loading F5-TTS...", file=sys.stderr)
        model = F5TTS(device=device)
        sr = model.target_sample_rate
        print("Warming up F5-TTS...", file=sys.stderr)
        _w, _sr, _ = model.infer(
            ref_file=str(_default_ref()), ref_text=_default_ref_text(),
            gen_text="Hello.", nfe_step=4, cfg_strength=0.0,
            show_info=lambda *a: None, progress=None,
        )
        del _w
        if device == "cuda":
            torch.cuda.empty_cache()
        print(f"F5-TTS worker ready (sr={sr}).", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        _send({"ready": False, "error": str(exc)})
        return

    _send({"ready": True, "sr": int(sr)})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as exc:
            _send({"ok": False, "error": f"Malformed request JSON: {exc}"})
            continue

        try:
            wav_np, out_sr, _ = model.infer(
                ref_file=req["ref_file"],
                ref_text=req.get("ref_text", ""),
                gen_text=req["gen_text"],
                nfe_step=int(req.get("nfe_step", 16)),
                cfg_strength=float(req.get("cfg_strength", 2.0)),
                speed=float(req.get("speed", 1.0)),
                cross_fade_duration=float(req.get("cross_fade_duration", 0.15)),
                show_info=lambda *a: None,
                progress=None,
            )
            wav_np = np.array(wav_np, dtype=np.float32)
            if wav_np.ndim == 1:
                wav_np = wav_np[np.newaxis, :]
            wav_t = torch.from_numpy(wav_np)
            torchaudio.save(req["out_path"], wav_t.cpu(), int(out_sr))
            if device == "cuda":
                torch.cuda.empty_cache()
            _send({"ok": True, "sr": int(out_sr)})
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc(file=sys.stderr)
            _send({"ok": False, "error": str(exc)})


def _default_ref():
    from importlib.resources import files as pkg_files
    return pkg_files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav")


def _default_ref_text() -> str:
    return "Some call me nature, others call me mother nature."


if __name__ == "__main__":
    main()
