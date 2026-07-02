# Two-Stage TTS Humanization Pipeline
## Build Spec

---

## What This Is

A two-stage audio pipeline that produces human-sounding speech from a text source.

- **Stage 1 — Kokoro TTS:** Generates fast, clean base audio from text using built-in voices
- **Stage 2 — F5-TTS:** Takes the Kokoro audio as a voice reference and re-synthesizes a new WAV that is more natural, expressive, and human-sounding

The user drops:
1. A text source (`.txt` file or raw string)
2. Optionally a reference WAV (target voice to clone)

The pipeline outputs a single final `.wav` file.

---

## Why Two Stages

Kokoro is fast but has a limited expressiveness ceiling — it reads text mechanically. XTTS-v2 (Coqui) has superior prosody and naturalness. By passing the Kokoro output as a voice reference into XTTS-v2:

- The **Kokoro audio** gives F5-TTS the voice identity (timbre, tone, accent)
- F5-TTS **re-synthesizes from scratch** using the reference — it does not modify the Kokoro audio
- Result: Kokoro's voice character, F5-TTS's naturalness and expressiveness

Stage 2 engine: **F5-TTS** (`SWivid/F5-TTS`, MIT, ~1.5 GB, no API key required)

---

## Existing Project Context

This is a Flask-based local TTS web app located at:
```
c:\Users\amire\Desktop\real natural voices\
```

Existing engines already integrated:
- **F5-TTS** — fast, voice cloning from WAV reference
- **Chatterbox** — expressive, voice cloning from WAV reference
- **Kokoro** — fast, 50 built-in voices, no voice cloning (being added)

The app uses:
- Flask backend (`app.py`)
- SSE streaming (`/api/generate_stream`)
- Web Audio API on the frontend for progressive playback
- Virtual environment at `venv/`
- Setup script: `setup.bat`
- Package patch script: `patch_f5tts.py`

---

## What To Build

### 1. Standalone Pipeline Script: `humanize.py`

A command-line script the user can run directly:

```
python humanize.py --text "path/to/script.txt" --output "output.wav"
python humanize.py --text "path/to/script.txt" --ref "reference_voice.wav" --output "output.wav"
```

**Arguments:**
- `--text` — path to `.txt` file OR raw text string
- `--ref` — optional WAV file to use as target voice (if omitted, Kokoro picks best default voice)
- `--output` — output WAV file path (default: `output_humanized.wav`)
- `--kokoro-voice` — Kokoro voice name to use in Stage 1 (default: `af_heart`)
- `--stage1-only` — skip Stage 2, just return Kokoro output
- `--stage2-only` — skip Stage 1, pass `--ref` WAV directly into Fish Speech

**Internal flow:**
```
text_input
    │
    ▼
[Stage 1: Kokoro]
    ├── voice = af_heart (or --kokoro-voice)
    ├── speed = 0.88  (slightly slower = more natural base)
    ├── split text at sentence boundaries
    ├── generate each sentence
    └── concatenate → stage1_output.wav (temp file)
    │
    ▼
stage1_output.wav  +  original_text
    │
    ▼
[Stage 2: Fish Speech 1.5]
    ├── reference_audio = stage1_output.wav
    ├── reference_text  = original_text  (critical — gives linguistic map)
    ├── generate_text   = original_text
    └── output → final humanized WAV
    │
    ▼
Save to --output path
Print: "Done. Saved to output.wav (Xsec)"
```

### 2. Flask API Endpoint: `/api/humanize` (optional, wire into existing app)

```
POST /api/humanize
Content-Type: multipart/form-data

Fields:
  text        — string, required
  ref_wav     — file upload, optional (WAV/MP3)
  kokoro_voice — string, optional (default: af_heart)
  stage1_only — bool, optional

Response: WAV file (audio/wav)
```

Integrates into the existing `app.py` alongside the other engines.

### 3. Update `setup.bat`

Add Fish Speech installation step after the F5-TTS installation block:

```bat
echo         Installing Fish Speech...
python -m pip install fish-speech --no-deps -q
:: or via git clone if pip not available:
:: git clone https://github.com/fishaudio/fish-speech
:: pip install -e fish-speech
```

---

## F5-TTS Stage 2 Integration Details

**HuggingFace:** `SWivid/F5-TTS`  
**License:** MIT (commercially usable)  
**Model size:** ~1.5 GB (downloads automatically on first use)  
**Install:** `pip install f5-tts cached-path matplotlib pydub vocos`  

**Key parameters:**
- `ref_file` — the Kokoro output WAV (voice identity source, trimmed to 3-12 s)
- `ref_text` — transcript of the reference audio (equals `gen_text` when using Kokoro output)
- `gen_text` — the text to synthesize
- GPU: fully CUDA accelerated, RTX 4070 supported

**Why F5-TTS over XTTS-v2:**
- No C++ Build Tools required on Windows (XTTS-v2 requires MSVC to compile Cython extension)
- MIT license (XTTS-v2 is CC-BY 4.0)
- Comparable voice cloning quality, faster on modern GPUs

---

## Kokoro Stage 1 Integration Details

**Install:** `pip install kokoro soundfile`  
**Model size:** ~82MB  
**License:** MIT  

```python
from kokoro import KPipeline
import soundfile as sf
import numpy as np

pipeline = KPipeline(lang_code='a')  # 'a' = American English

def kokoro_generate(text, voice='af_heart', speed=0.88):
    sentences = split_sentences(text)
    chunks = []
    for sentence in sentences:
        generator = pipeline(sentence, voice=voice, speed=speed)
        for _, _, audio in generator:
            chunks.append(audio)
    return np.concatenate(chunks)
```

**Voice recommendations for Stage 1 (best base for humanization):**
- `af_heart` — warm American female, best prosody base
- `af_bella` — clear, neutral
- `bm_george` — British male, formal
- `am_adam` — American male

Speed `0.88` recommended — slightly slower base gives Stage 2 more prosody information to work with.

---

## Sentence Splitting Logic

Text should be split at sentence boundaries before Kokoro Stage 1. This gives cleaner prosody per chunk and better alignment for Stage 2.

```python
import re

def split_sentences(text):
    # Split on . ! ? followed by space or end
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())
    # Merge very short sentences (under 20 chars) with the next
    merged = []
    buffer = ""
    for s in sentences:
        buffer = (buffer + " " + s).strip()
        if len(buffer) >= 20:
            merged.append(buffer)
            buffer = ""
    if buffer:
        merged.append(buffer)
    return merged
```

---

## File Structure

```
second speech filter workflow/
├── humanize.py              — standalone CLI pipeline script
├── pipeline/
│   ├── __init__.py
│   ├── stage1_kokoro.py     — Kokoro TTS wrapper
│   └── stage2_f5.py         — F5-TTS voice cloning wrapper
├── app.py                   — Flask web app (port 5001)
├── setup.bat                — installs deps and starts app
├── download_models.py       — pre-warms model downloads
├── templates/index.html     — web UI
├── static/script.js
├── static/style.css
└── PIPELINE_PLAN.md
```

---

## Key Constraints

- Windows 11, PowerShell environment
- NVIDIA GPU (CUDA), existing PyTorch already installed in venv
- Virtual environment at `venv/` — all installs go there
- Do NOT use `torch.compile` — crashes on Windows PyTorch 2.6 (inductor/triton issue)
- All pip installs should use `-q` flag and have `--no-deps` fallback if build fails
- Follow the same pattern as `patch_f5tts.py` for any venv file patches needed
- Flask app streams via SSE — any new endpoint should also support streaming if text is long

---

## Definition of Done

1. `python humanize.py --text "Hello world." --output test.wav` runs end to end
2. Output WAV sounds noticeably more natural than Kokoro alone
3. Long text (500+ words) processes without memory error
4. Works on GPU with existing venv, no new venv required
5. `setup.bat` installs Fish Speech automatically on fresh machine
6. Optional: `/api/humanize` endpoint accessible in the running Flask app
