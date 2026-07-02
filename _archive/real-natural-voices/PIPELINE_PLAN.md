# Two-Stage TTS Humanization Pipeline
## Build Spec for Claude

---

## What This Is

A two-stage audio pipeline that produces human-sounding speech from a text source.

- **Stage 1 — Kokoro TTS:** Generates fast, clean base audio from text using built-in voices
- **Stage 2 — Fish Speech 1.5:** Takes the Kokoro audio + original text script and re-synthesizes a new WAV that is more natural, expressive, and human-sounding

The user drops:
1. A text source (`.txt` file or raw string)
2. Optionally a reference WAV (target voice to clone)

The pipeline outputs a single final `.wav` file.

---

## Why Two Stages

Kokoro is fast but has a limited expressiveness ceiling — it reads text mechanically. Fish Speech 1.5 was trained on in-the-wild conversational speech. By passing the Kokoro output as a voice reference into Fish Speech alongside the original text:

- The **Kokoro audio** gives Fish Speech the voice identity (timbre, tone, accent)
- The **original text** gives Fish Speech the full linguistic map (stress, emotion, pauses)
- Fish Speech **re-synthesizes from scratch** using both — it does not modify the Kokoro audio
- Result: Kokoro's voice, Fish Speech's naturalness

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

### 4. Update `patch_f5tts.py` (if Fish Speech needs Windows patches)

Check if Fish Speech has any Windows import issues at install time and add patches to `patch_f5tts.py` following the same pattern as the existing F5-TTS patches.

---

## Fish Speech 1.5 Integration Details

**Repo:** `https://github.com/fishaudio/fish-speech`  
**HuggingFace:** `fishaudio/fish-speech-1.5`  
**License:** BSD-3-Clause  
**Model size:** ~500MB  
**Install:** `pip install fish-speech` or clone repo  

**Basic inference pattern:**
```python
from fish_speech.inference import TTSInference

model = TTSInference(
    model_path="checkpoints/fish-speech-1.5",
    device="cuda"
)

wav = model.generate(
    text=original_script,
    reference_audio="kokoro_stage1.wav",
    reference_text=original_script,   # same text = perfect alignment
    chunk_length=200,
    max_new_tokens=2048,
)
```

**Key parameters:**
- `reference_audio` — the Kokoro output WAV (voice identity source)
- `reference_text` — the original script (linguistic alignment, not transcription)
- `chunk_length` — process in chunks for long texts (200 chars recommended)

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

## File Structure To Create

```
real natural voices/
├── humanize.py              ← NEW: standalone CLI pipeline script
├── pipeline/
│   ├── __init__.py          ← NEW
│   ├── stage1_kokoro.py     ← NEW: Kokoro wrapper
│   └── stage2_fish.py       ← NEW: Fish Speech wrapper
├── app.py                   ← MODIFY: add /api/humanize endpoint
├── setup.bat                ← MODIFY: add Fish Speech install step
├── patch_f5tts.py           ← MODIFY IF NEEDED: add Fish Speech patches
└── PIPELINE_PLAN.md         ← THIS FILE
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
