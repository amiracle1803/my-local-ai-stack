"""Voice Studio — local TTS engine on port 5050 (rebuilt 2026-07-09).

Standalone Flask app wrapping Kokoro-82M (fully local; the model weights
(~330 MB) auto-download from Hugging Face on first synthesis and are cached).
GPU is NOT used — Kokoro-82M is fast enough on CPU and this keeps the 8 GB
RTX 4070 free for ComfyUI.

    GET  /api/health          {"status": "ok", ...}
    GET  /api/voices          available voice ids
    POST /api/tts             {"text": "...", "voice": "af_heart", "speed": 1.0}
                              -> audio/wav
    GET  /                    minimal test page

Run:  start.bat  (creates .venv on first run)
"""

from __future__ import annotations

import io
import threading

import numpy as np
import soundfile as sf
from flask import Flask, jsonify, request, send_file

SAMPLE_RATE = 24_000

# Kokoro voice ids: prefix = accent/gender (af = american female, am = male,
# bf/bm = british). The full list lives in the model repo; these are the
# commonly used ones.
VOICES = [
    "af_heart", "af_bella", "af_nicole", "af_sarah", "af_sky",
    "am_adam", "am_michael", "bf_emma", "bf_isabella", "bm_george", "bm_lewis",
]

app = Flask(__name__)

_pipeline = None
_pipeline_lock = threading.Lock()


def get_pipeline():
    """Lazy-load Kokoro so /api/health answers instantly after boot."""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            from kokoro import KPipeline
            _pipeline = KPipeline(lang_code="a")  # American English
        return _pipeline


@app.get("/api/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "voice-studio",
        "engine": "kokoro-82M",
        "model_loaded": _pipeline is not None,
    })


@app.get("/api/voices")
def voices():
    return jsonify(VOICES)


@app.post("/api/tts")
def tts():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    voice = body.get("voice") or "af_heart"
    try:
        speed = float(body.get("speed") or 1.0)
    except (ValueError, TypeError):
        speed = 1.0
    if not text:
        return jsonify({"error": "missing 'text'"}), 422
    if voice not in VOICES:
        return jsonify({"error": f"unknown voice '{voice}'", "voices": VOICES}), 422

    pipeline = get_pipeline()
    chunks = [audio for _, _, audio in pipeline(text, voice=voice, speed=speed)]
    if not chunks:
        return jsonify({"error": "no audio produced"}), 500
    audio = np.concatenate(chunks)

    buf = io.BytesIO()
    sf.write(buf, audio, SAMPLE_RATE, format="WAV")
    buf.seek(0)
    return send_file(buf, mimetype="audio/wav", download_name="tts.wav")


@app.get("/")
def index():
    return """<!DOCTYPE html><html><head><title>Voice Studio</title><style>
    body{font:15px system-ui;background:#0f1115;color:#e6e6e6;max-width:640px;margin:3rem auto;padding:0 1rem}
    textarea,select,button{font:inherit;background:#171a21;color:inherit;border:1px solid #2c3242;border-radius:8px;padding:.5rem}
    textarea{width:100%;min-height:90px}button{cursor:pointer;background:#2f6feb;border-color:#2f6feb;margin-top:.5rem}
    </style></head><body><h2>Voice Studio</h2>
    <textarea id="t">Hello from the rebuilt Voice Studio.</textarea><br>
    <select id="v"></select> <button onclick="go()">Speak</button>
    <p id="s"></p><audio id="a" controls></audio>
    <script>
    fetch('/api/voices').then(r=>r.json()).then(vs=>{v.innerHTML=vs.map(x=>`<option>${x}</option>`).join('')});
    async function go(){s.textContent='generating… (first run downloads the model)';
      const r=await fetch('/api/tts',{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({text:t.value,voice:v.value})});
      if(!r.ok){s.textContent='error: '+(await r.text());return}
      a.src=URL.createObjectURL(await r.blob());a.play();s.textContent='done'}
    </script></body></html>"""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5050)
