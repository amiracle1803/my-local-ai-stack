"""
Voice Studio -- merged from real-natural-voices + second-speech-filter-workflow.

Chatterbox TTS runs in-process (as it did in real-natural-voices) -- it's
been stable, and keeping it in-process preserves the pipelined watermarking
optimization. F5-TTS runs in an isolated, persistent worker subprocess (see
f5_worker.py / f5_client.py) -- it's the engine with a history of native
crashes on Windows, so isolating it means a crash there can't take down
Chatterbox or the whole Flask app, while staying warm (no per-call model
reload) unlike second-speech-filter-workflow's fresh-subprocess-per-call
approach.

Everything else (voice library, SSE streaming API shape, humanize pipeline,
file browser) is unchanged from real-natural-voices -- same HTTP API, same
frontend, so nothing about the user-facing app changed except F5-TTS no
longer being able to crash the server.
"""

import sys
import os
import re
import io
import json
import time
import base64
import mimetypes
import tempfile
import warnings
import logging
import concurrent.futures
from datetime import datetime
from importlib.resources import files as pkg_files

# Windows' default console codepage (cp1252) can't encode characters like
# "->"/em-dashes that show up in library log output -- an uncaught
# UnicodeEncodeError from a stray print() would otherwise crash whatever SSE
# generator happened to be mid-stream. errors="replace" degrades to "?"
# instead of taking down a live request.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

os.environ["HF_HUB_VERBOSITY"] = "error"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
warnings.filterwarnings("ignore", category=FutureWarning)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

import torch
import torchaudio
import numpy as np
from flask import Flask, render_template, request, jsonify, send_file, Response, stream_with_context

from f5_client import F5Worker

if torch.cuda.is_available():
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cuda.enable_flash_sdp(True)
    torch.backends.cuda.enable_mem_efficient_sdp(True)

torch.set_num_threads(os.cpu_count() or 4)

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio_output")
VOICES_DIR = os.path.join(BASE_DIR, "voices")
TMP_DIR = os.path.join(BASE_DIR, "_tmp")
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(VOICES_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)

device = "cuda" if torch.cuda.is_available() else "cpu"

# ── Load Chatterbox (in-process) ────────────────────────────────
print("  Loading Chatterbox TTS...")
from chatterbox.tts import ChatterboxTTS
cb_model = ChatterboxTTS.from_pretrained(device=device)
CB_SR = cb_model.sr
print("  Chatterbox ready!")

if device == "cuda":
    if torch.cuda.is_bf16_supported():
        print("  Converting Chatterbox to bfloat16...")
        cb_model.t3 = cb_model.t3.to(dtype=torch.bfloat16)
        cb_model.s3gen.flow = cb_model.s3gen.flow.to(dtype=torch.bfloat16)
        cb_model.s3gen.speaker_encoder = cb_model.s3gen.speaker_encoder.to(dtype=torch.bfloat16)
        print("  T3 + S3Gen bfloat16 active!")
    print("  Warming up Chatterbox...")
    _d = cb_model.generate("Hello.", n_cfm_steps=2)
    del _d
    torch.cuda.empty_cache()
    print("  Chatterbox GPU ready!")

# ── Start F5-TTS worker (isolated subprocess) ───────────────────
F5_DEF_REF = str(pkg_files("f5_tts").joinpath("infer/examples/basic/basic_ref_en.wav"))
F5_DEF_TEXT = "Some call me nature, others call me mother nature."

f5_worker = F5Worker(os.path.join(BASE_DIR, "f5_worker.py"))
HAS_F5 = f5_worker.available
F5_SR = f5_worker.sr

# ── Check Kokoro + XTTS-v2 (both needed for /api/humanize) ──────
HAS_KOKORO = False
try:
    import kokoro as _kokoro_check  # noqa: F401
    HAS_KOKORO = True
    print("  Kokoro available.")
except ImportError:
    print("  Kokoro not installed — /api/humanize will be unavailable.")
    print("  To install: pip install kokoro soundfile")

HAS_XTTS = False
try:
    import importlib.util as _ilu
    if _ilu.find_spec("TTS") is not None:
        HAS_XTTS = True
        print("  XTTS-v2 (TTS package) available.")
    else:
        raise ImportError
except ImportError:
    print("  TTS (XTTS-v2) not installed — /api/humanize Stage 2 unavailable.")
    print("  To install: pip install TTS")

HAS_HUMANIZE = HAS_KOKORO and HAS_XTTS


# ── Helpers ───────────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    safe = "".join(c for c in name if c.isalnum() or c in (" ", "-", "_", ".", "(", ")")).strip()
    return safe if safe else f"audio_{int(time.time())}"


def split_text_chunks(text: str, max_chars: int = 400) -> list:
    text = " ".join(text.split())
    if not text:
        return []
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks, current = [], ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            clauses = re.split(r'(?<=,)\s+', sentence)
            for clause in clauses:
                if current and len(current) + 1 + len(clause) > max_chars:
                    chunks.append(current)
                    current = clause
                else:
                    current = (current + " " + clause).strip() if current else clause
        else:
            if current and len(current) + 1 + len(sentence) > max_chars:
                chunks.append(current)
                current = sentence
            else:
                current = (current + " " + sentence).strip() if current else sentence
    if current:
        chunks.append(current)
    return [c for c in chunks if c.strip()]


_cb_cond_cache: dict = {}  # (wav_path, exaggeration) -> Conditionals object

def _prepare_cb_conditionals(wav_path: str, exaggeration: float):
    """Load and cache Chatterbox speaker conditionals — skips re-embedding if unchanged."""
    key = (wav_path, round(exaggeration, 2))
    if key not in _cb_cond_cache:
        cb_model.prepare_conditionals(wav_path, exaggeration=exaggeration)
        _cb_cond_cache.clear()  # evict old entries (keep VRAM tidy)
        _cb_cond_cache[key] = cb_model.conds
    else:
        cb_model.conds = _cb_cond_cache[key]


def _voice_ref(voice_name: str):
    """Return (wav_path, ref_text) for the given saved voice name."""
    if voice_name:
        wav = os.path.join(VOICES_DIR, f"{sanitize_filename(voice_name)}.wav")
        txt = os.path.join(VOICES_DIR, f"{sanitize_filename(voice_name)}.txt")
        if os.path.isfile(wav):
            ref_text = ""
            if os.path.isfile(txt):
                with open(txt, "r", encoding="utf-8") as fh:
                    ref_text = fh.read().strip()
            return wav, ref_text
    return None, None


def _f5_generate_tensor(ref_wav, ref_text, gen_text, nfe_steps, cfg_strength,
                         cross_fade_duration=0.15):
    """Run one F5-TTS call through the isolated worker, return (wav_tensor, sr)."""
    tmp_path = os.path.join(TMP_DIR, f"f5_{os.getpid()}_{time.time_ns()}.wav")
    try:
        sr = f5_worker.generate(
            ref_file=ref_wav, ref_text=ref_text, gen_text=gen_text, out_path=tmp_path,
            nfe_step=nfe_steps, cfg_strength=cfg_strength,
            cross_fade_duration=cross_fade_duration,
        )
        wav_t, loaded_sr = torchaudio.load(tmp_path)
        return wav_t, loaded_sr or sr
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ── Routes ────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/engines")
def list_engines():
    return jsonify({"chatterbox": True, "f5": f5_worker.available, "kokoro": HAS_KOKORO,
                    "xtts": HAS_XTTS, "humanize": HAS_HUMANIZE})


@app.route("/api/generate", methods=["POST"])
def generate():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    filename_raw = (data.get("filename") or f"audio_{int(time.time())}").strip()
    engine = (data.get("engine") or "f5").strip()
    voice_name = (data.get("voiceName") or "").strip()

    if not text:
        return jsonify({"error": "Text is required."}), 400

    chunks = split_text_chunks(text, max_chars=400)
    if not chunks:
        return jsonify({"error": "Text is required."}), 400

    start = time.perf_counter()
    wav = None
    out_sr = CB_SR

    try:
        # ── F5-TTS path (via isolated worker) ──────────────────
        if engine == "f5":
            if not f5_worker.available:
                return jsonify({"error": "F5-TTS worker is not available. Check the console for details."}), 400

            nfe_steps = max(4, min(32, int(data.get("nfeSteps") or 16)))
            cfg_strength = max(0.0, min(2.0, float(data.get("cfgStrength") or 2.0)))
            ref_wav, ref_txt = _voice_ref(voice_name)
            if ref_wav is None:
                ref_wav, ref_txt = F5_DEF_REF, F5_DEF_TEXT

            full_text = " ".join(chunks)  # F5-TTS handles internal chunking with cross-fade
            print(f"  F5-TTS: {len(full_text)} chars, {nfe_steps} NFE steps, cfg={cfg_strength}")
            wav, out_sr = _f5_generate_tensor(ref_wav, ref_txt, full_text, nfe_steps, cfg_strength)

        # ── Chatterbox path (in-process) ───────────────────────
        else:
            exaggeration = max(0.0, min(1.0, float(data.get("exaggeration") or 0.5)))
            cfg_weight = max(0.0, min(1.0, float(data.get("cfgWeight") or 0.0)))
            cfm_steps = data.get("cfmSteps")
            if cfm_steps is not None:
                cfm_steps = max(2, min(30, int(cfm_steps)))

            ref_wav, _ = _voice_ref(voice_name)
            if ref_wav:
                _prepare_cb_conditionals(ref_wav, exaggeration)

            def _watermark(raw_tensor):
                np_wav = raw_tensor.squeeze(0).numpy()
                wm_np = cb_model.watermarker.apply_watermark(np_wav, sample_rate=CB_SR)
                return torch.from_numpy(wm_np).unsqueeze(0)

            multi_chunk = len(chunks) > 1
            if multi_chunk:
                wavs = []
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as wm_pool:
                    pending = None
                    for i, chunk in enumerate(chunks):
                        print(f"  CB chunk {i+1}/{len(chunks)}: {chunk[:60]}{'...' if len(chunk)>60 else ''}")
                        raw = cb_model.generate(
                            text=chunk, audio_prompt_path=None,
                            exaggeration=exaggeration, cfg_weight=cfg_weight,
                            n_cfm_steps=cfm_steps, skip_watermark=True,
                        )
                        if pending is not None:
                            wavs.append(pending.result())
                        pending = wm_pool.submit(_watermark, raw)
                    if pending is not None:
                        wavs.append(pending.result())
                wav = torch.cat(wavs, dim=1)
            else:
                wav = cb_model.generate(
                    text=chunks[0], audio_prompt_path=None,
                    exaggeration=exaggeration, cfg_weight=cfg_weight,
                    n_cfm_steps=cfm_steps, skip_watermark=False,
                )
            out_sr = CB_SR

    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Generation failed: {exc}"}), 500

    elapsed = round(time.perf_counter() - start, 3)
    print(f"  Done in {elapsed}s")

    safe_name = sanitize_filename(filename_raw)
    full_name = f"{safe_name}.wav"
    filepath = os.path.join(AUDIO_DIR, full_name)
    counter = 1
    while os.path.exists(filepath):
        full_name = f"{safe_name}_{counter}.wav"
        filepath = os.path.join(AUDIO_DIR, full_name)
        counter += 1

    torchaudio.save(filepath, wav.cpu(), out_sr)

    with open(filepath, "rb") as fh:
        audio_b64 = base64.b64encode(fh.read()).decode()

    return jsonify({
        "success": True,
        "filename": full_name,
        "fileSize": os.path.getsize(filepath),
        "serverElapsed": elapsed,
        "audioData": audio_b64,
        "audioFormat": "wav",
        "chunks": len(chunks),
        "engine": engine,
    })


@app.route("/api/generate_stream", methods=["POST"])
def generate_stream():
    """SSE streaming endpoint — sends one JSON event per chunk so the UI can show live progress."""
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    filename_raw = (data.get("filename") or f"audio_{int(time.time())}").strip()
    engine = (data.get("engine") or "f5").strip()
    voice_name = (data.get("voiceName") or "").strip()

    def _evt(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    def _run():
        if not text:
            yield _evt({"type": "error", "error": "Text is required."})
            return

        chunks = split_text_chunks(text, max_chars=400)
        if not chunks:
            yield _evt({"type": "error", "error": "Text is required."})
            return

        all_wavs = []
        out_sr = CB_SR
        start = time.perf_counter()

        try:
            # ── F5-TTS streaming (via isolated worker) ─────────────
            if engine == "f5":
                if not f5_worker.available:
                    yield _evt({"type": "error", "error": "F5-TTS worker is not available."})
                    return

                nfe_steps = max(4, min(32, int(data.get("nfeSteps") or 16)))
                cfg_strength = max(0.0, min(2.0, float(data.get("cfgStrength") or 2.0)))
                ref_wav, ref_txt = _voice_ref(voice_name)
                if ref_wav is None:
                    ref_wav, ref_txt = F5_DEF_REF, F5_DEF_TEXT
                out_sr = f5_worker.sr

                for i, chunk in enumerate(chunks):
                    yield _evt({"type": "progress", "chunk": i + 1, "total": len(chunks)})
                    print(f"  F5 stream {i+1}/{len(chunks)}: {chunk[:60]}...")
                    try:
                        wav_t, sr = _f5_generate_tensor(
                            ref_wav, ref_txt, chunk, nfe_steps, cfg_strength,
                            cross_fade_duration=0.0,
                        )
                    except RuntimeError as exc:
                        yield _evt({"type": "error", "error": str(exc)})
                        return
                    all_wavs.append(wav_t)
                    out_sr = int(sr)

                    buf = io.BytesIO()
                    torchaudio.save(buf, wav_t.cpu(), out_sr, format="wav")
                    yield _evt({"type": "chunk", "index": i,
                                "audio": base64.b64encode(buf.getvalue()).decode()})

            # ── Chatterbox streaming (in-process) ──────────────────
            else:
                exaggeration = max(0.0, min(1.0, float(data.get("exaggeration") or 0.5)))
                cfg_weight = max(0.0, min(1.0, float(data.get("cfgWeight") or 0.0)))
                cfm_steps = data.get("cfmSteps")
                if cfm_steps is not None:
                    cfm_steps = max(2, min(30, int(cfm_steps)))
                out_sr = CB_SR

                ref_wav, _ = _voice_ref(voice_name)
                if ref_wav:
                    _prepare_cb_conditionals(ref_wav, exaggeration)

                def _watermark(raw_tensor):
                    np_wav = raw_tensor.squeeze(0).numpy()
                    wm_np = cb_model.watermarker.apply_watermark(np_wav, sample_rate=CB_SR)
                    return torch.from_numpy(wm_np).unsqueeze(0)

                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as wm_pool:
                    pending_fut = None
                    pending_idx = None
                    for i, chunk in enumerate(chunks):
                        yield _evt({"type": "progress", "chunk": i + 1, "total": len(chunks)})
                        print(f"  CB stream {i+1}/{len(chunks)}: {chunk[:60]}...")
                        raw = cb_model.generate(
                            text=chunk, audio_prompt_path=None,
                            exaggeration=exaggeration, cfg_weight=cfg_weight,
                            n_cfm_steps=cfm_steps, skip_watermark=True,
                        )
                        if pending_fut is not None:
                            wm = pending_fut.result()
                            all_wavs.append(wm)
                            buf = io.BytesIO()
                            torchaudio.save(buf, wm.cpu(), CB_SR, format="wav")
                            yield _evt({"type": "chunk", "index": pending_idx,
                                        "audio": base64.b64encode(buf.getvalue()).decode()})
                        pending_fut = wm_pool.submit(_watermark, raw)
                        pending_idx = i
                    if pending_fut is not None:
                        wm = pending_fut.result()
                        all_wavs.append(wm)
                        buf = io.BytesIO()
                        torchaudio.save(buf, wm.cpu(), CB_SR, format="wav")
                        yield _evt({"type": "chunk", "index": pending_idx,
                                    "audio": base64.b64encode(buf.getvalue()).decode()})

        except Exception as exc:
            import traceback; traceback.print_exc()
            yield _evt({"type": "error", "error": str(exc)})
            return

        if not all_wavs:
            yield _evt({"type": "error", "error": "No audio generated."})
            return

        elapsed = round(time.perf_counter() - start, 3)
        full_wav = torch.cat(all_wavs, dim=1)
        safe_name = sanitize_filename(filename_raw)
        full_name = f"{safe_name}.wav"
        filepath = os.path.join(AUDIO_DIR, full_name)
        counter = 1
        while os.path.exists(filepath):
            full_name = f"{safe_name}_{counter}.wav"
            filepath = os.path.join(AUDIO_DIR, full_name)
            counter += 1
        torchaudio.save(filepath, full_wav.cpu(), out_sr)
        print(f"  Stream done in {elapsed}s -> {full_name}")

        yield _evt({
            "type": "done",
            "filename": full_name,
            "fileSize": os.path.getsize(filepath),
            "serverElapsed": elapsed,
            "chunks": len(chunks),
            "engine": engine,
        })

    return Response(
        stream_with_context(_run()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/humanize", methods=["POST"])
def humanize():
    """
    Two-stage TTS humanization: Kokoro -> XTTS-v2.

    POST JSON fields:
      text         (str, required)
      kokoro_voice (str, optional, default: af_heart)
      kokoro_speed (float, optional, default: 0.88)
      stage1_only  (bool, optional) — return Kokoro output, skip XTTS-v2
      filename     (str, optional)

    Returns: JSON with audioData (base64 WAV), filename, serverElapsed.
    """
    if not HAS_KOKORO:
        return jsonify({"error": "Kokoro is not installed. Run: pip install kokoro soundfile"}), 400

    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()
    kokoro_voice = (data.get("kokoro_voice") or "af_heart").strip()
    kokoro_speed = max(0.5, min(2.0, float(data.get("kokoro_speed") or 0.88)))
    stage1_only = bool(data.get("stage1_only"))
    filename_raw = (data.get("filename") or f"humanized_{int(time.time())}").strip()

    if not stage1_only and not HAS_XTTS:
        return jsonify({
            "error": "XTTS-v2 is not installed. Run: pip install TTS  "
                     "(or enable Stage 1 only mode to use Kokoro without re-synthesis)"
        }), 400

    if not text:
        return jsonify({"error": "Text is required."}), 400

    stage1_tmp = None
    try:
        import soundfile as _sf
    except ImportError:
        return jsonify({"error": "soundfile is not installed. Run: pip install soundfile"}), 500

    try:
        start = time.perf_counter()

        from pipeline.stage1_kokoro import generate as _kokoro_gen
        print(f"  [Humanize Stage 1] Kokoro ({kokoro_voice})...")
        audio_np, ksr = _kokoro_gen(text, voice=kokoro_voice, speed=kokoro_speed)

        if stage1_only:
            wav_t = torch.from_numpy(audio_np).unsqueeze(0)
            safe_name = sanitize_filename(filename_raw)
            full_name = f"{safe_name}.wav"
            filepath = os.path.join(AUDIO_DIR, full_name)
            counter = 1
            while os.path.exists(filepath):
                full_name = f"{safe_name}_{counter}.wav"
                filepath = os.path.join(AUDIO_DIR, full_name)
                counter += 1
            torchaudio.save(filepath, wav_t.cpu(), ksr)
            elapsed = round(time.perf_counter() - start, 3)
            with open(filepath, "rb") as fh:
                audio_b64 = base64.b64encode(fh.read()).decode()
            return jsonify({
                "success": True, "filename": full_name,
                "fileSize": os.path.getsize(filepath),
                "serverElapsed": elapsed, "stage": "kokoro",
                "audioData": audio_b64, "audioFormat": "wav",
            })

        stage1_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=TMP_DIR)
        stage1_path = stage1_tmp.name
        stage1_tmp.close()
        _sf.write(stage1_path, audio_np, ksr)
        print(f"  [Humanize Stage 1] Done -> {len(audio_np)/ksr:.1f}s audio")

        safe_name = sanitize_filename(filename_raw)
        full_name = f"{safe_name}.wav"
        filepath = os.path.join(AUDIO_DIR, full_name)
        counter = 1
        while os.path.exists(filepath):
            full_name = f"{safe_name}_{counter}.wav"
            filepath = os.path.join(AUDIO_DIR, full_name)
            counter += 1

        print("  [Humanize Stage 2] XTTS-v2...")
        from pipeline.stage2_xtts import generate as _xtts_gen
        _xtts_gen(
            text=text, reference_audio=stage1_path, reference_text=text,
            output_path=filepath, device=device,
        )

        elapsed = round(time.perf_counter() - start, 3)
        print(f"  [Humanize] Done in {elapsed}s -> {full_name}")

        with open(filepath, "rb") as fh:
            audio_b64 = base64.b64encode(fh.read()).decode()

        return jsonify({
            "success": True, "filename": full_name,
            "fileSize": os.path.getsize(filepath),
            "serverElapsed": elapsed, "stage": "humanized",
            "audioData": audio_b64, "audioFormat": "wav",
        })

    except Exception as exc:
        import traceback; traceback.print_exc()
        return jsonify({"error": f"Humanize failed: {exc}"}), 500

    finally:
        if stage1_tmp and os.path.exists(stage1_tmp.name):
            try:
                os.unlink(stage1_tmp.name)
            except OSError:
                pass


@app.route("/api/voices", methods=["GET"])
def list_voices():
    voices = []
    for f in sorted(os.listdir(VOICES_DIR)):
        if f.lower().endswith(".wav"):
            name = f[:-4]
            fp = os.path.join(VOICES_DIR, f)
            txt_fp = os.path.join(VOICES_DIR, f"{name}.txt")
            has_txt = os.path.isfile(txt_fp)
            voices.append({"name": name, "size": os.path.getsize(fp), "hasRefText": has_txt})
    return jsonify({"voices": voices})


@app.route("/api/voices/upload", methods=["POST"])
def upload_voice():
    if "audio" not in request.files:
        return jsonify({"error": "No audio file provided."}), 400
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Voice name is required."}), 400
    ref_text = (request.form.get("refText") or "").strip()
    safe_name = sanitize_filename(name)
    file = request.files["audio"]
    tmp_path = os.path.join(VOICES_DIR, f"_tmp_{safe_name}_{int(time.time())}")
    file.save(tmp_path)
    try:
        wav, sr = torchaudio.load(tmp_path)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        target_sr = f5_worker.sr or 24000
        if sr != target_sr:
            wav = torchaudio.functional.resample(wav, sr, target_sr)
        out_path = os.path.join(VOICES_DIR, f"{safe_name}.wav")
        torchaudio.save(out_path, wav.cpu(), target_sr)
        if ref_text:
            with open(os.path.join(VOICES_DIR, f"{safe_name}.txt"), "w", encoding="utf-8") as tf:
                tf.write(ref_text)
    except Exception as exc:
        return jsonify({"error": f"Could not process audio: {exc}"}), 400
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
    return jsonify({"success": True, "name": safe_name})


@app.route("/api/voices/<name>", methods=["DELETE"])
def delete_voice(name):
    safe_name = sanitize_filename(name)
    fp = os.path.join(VOICES_DIR, f"{safe_name}.wav")
    if not os.path.isfile(fp):
        return jsonify({"error": "Voice not found."}), 404
    os.remove(fp)
    txt_fp = os.path.join(VOICES_DIR, f"{safe_name}.txt")
    if os.path.isfile(txt_fp):
        os.remove(txt_fp)
    return jsonify({"success": True})


@app.route("/api/files")
def list_files():
    files = []
    for fname in os.listdir(AUDIO_DIR):
        fpath = os.path.join(AUDIO_DIR, fname)
        if os.path.isfile(fpath):
            stat = os.stat(fpath)
            files.append({
                "name": fname,
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "_mtime": stat.st_mtime,
            })
    files.sort(key=lambda f: f["_mtime"], reverse=True)
    for f in files:
        del f["_mtime"]
    return jsonify({"files": files})


@app.route("/download/<path:filename>")
def download(filename):
    fp = os.path.join(AUDIO_DIR, filename)
    if not os.path.abspath(fp).startswith(os.path.abspath(AUDIO_DIR)):
        return jsonify({"error": "Forbidden"}), 403
    if not os.path.isfile(fp):
        return jsonify({"error": "File not found"}), 404
    return send_file(fp, as_attachment=True, download_name=filename)


@app.route("/play/<path:filename>")
def play(filename):
    fp = os.path.join(AUDIO_DIR, filename)
    if not os.path.abspath(fp).startswith(os.path.abspath(AUDIO_DIR)):
        return jsonify({"error": "Forbidden"}), 403
    if not os.path.isfile(fp):
        return jsonify({"error": "File not found"}), 404
    mime, _ = mimetypes.guess_type(fp)
    return send_file(fp, mimetype=mime or "audio/wav")


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "chatterbox": True, "f5": f5_worker.available})


# ── Startup ───────────────────────────────────────────────────

if __name__ == "__main__":
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    print("\n  Voice Studio")
    print("  Chatterbox (in-process) + F5-TTS (isolated worker)  |  Local  |  Free")
    print("\n  Open your browser and go to:")
    print("  >>> http://localhost:5050 <<<\n")
    app.run(host="0.0.0.0", port=5050, debug=False)
