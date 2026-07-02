"""
Speech Filter — F5-TTS Audio Cleaner
Upload audio → F5-TTS re-synthesizes it cleanly in the same voice

Run: python app.py
Open: http://localhost:5001
"""
import os, sys, base64, io, time, tempfile, logging, traceback, json, subprocess
from flask import Flask, request, jsonify, render_template

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

# Log crashes to a file so they're visible even after the server dies
logging.basicConfig(
    filename=os.path.join(BASE, "app.log"),
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB upload limit

AUDIO_DIR = os.path.join(BASE, "audio_output")
os.makedirs(AUDIO_DIR, exist_ok=True)

HAS_F5 = False
_f5_load_error = ""
try:
    import importlib.util
    HAS_F5 = importlib.util.find_spec("f5_tts") is not None
except Exception as _e:
    _f5_load_error = str(_e)

WORKER = os.path.join(BASE, "pipeline", "worker.py")

def _run_worker(text, reference_audio, reference_text, output_path, timeout=600):
    """Run F5-TTS inference in an isolated subprocess so a native crash can't kill Flask."""
    args = json.dumps({
        "text": text,
        "reference_audio": reference_audio,
        "reference_text": reference_text,
    })
    result = subprocess.run(
        [sys.executable, WORKER, args, output_path],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    # Always relay worker stderr → app.log so we see Whisper/F5 progress
    if result.stderr.strip():
        for line in result.stderr.strip().splitlines():
            log.info("[worker] %s", line)

    if result.returncode != 0:
        # Try to pull a structured error from stdout
        try:
            payload = json.loads(result.stdout.strip().splitlines()[-1])
            raise RuntimeError(payload.get("error", "Worker exited with no message"))
        except (json.JSONDecodeError, IndexError):
            raise RuntimeError(
                f"Worker process crashed (exit {result.returncode}). "
                "Check app.log for details."
            )

    payload = json.loads(result.stdout.strip().splitlines()[-1])
    if not payload.get("ok"):
        raise RuntimeError(payload.get("error", "Worker reported failure"))
    return payload["sr"]

# ── routes ────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def status():
    return jsonify({"f5": HAS_F5, "ready": HAS_F5, "error": _f5_load_error})

@app.route("/api/generate", methods=["POST"])
def generate():
    if not HAS_F5:
        return jsonify({"error": "F5-TTS not installed — run setup.bat"}), 503

    if "audio" not in request.files:
        return jsonify({"error": "No audio file uploaded"}), 400

    audio_file = request.files["audio"]
    transcript = (request.form.get("text") or "").strip()

    ext = os.path.splitext(audio_file.filename or "")[1] or ".wav"
    tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
    try:
        audio_file.save(tmp.name)
        tmp.close()
        log.info("Received: %s  transcript=%r", audio_file.filename, transcript[:60] if transcript else "")

        out = os.path.join(AUDIO_DIR, f"out_{int(time.time()*1000)}.wav")
        t0  = time.time()

        log.info("Spawning F5-TTS worker subprocess...")
        try:
            sr = _run_worker(
                text=transcript,
                reference_audio=tmp.name,
                reference_text=transcript,
                output_path=out,
            )
        except subprocess.TimeoutExpired:
            return jsonify({"error": "Processing timed out (>10 min) — try a shorter clip"}), 500

        elapsed = round(time.time() - t0, 2)
        log.info("Worker done in %.1fs", elapsed)

    except Exception as e:
        log.error("generate() failed:\n%s", traceback.format_exc())
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    import soundfile as sf
    buf = io.BytesIO()
    audio_data, sr_read = sf.read(out, dtype="float32")
    sf.write(buf, audio_data, sr_read, format="WAV")
    b64 = base64.b64encode(buf.getvalue()).decode()

    try:
        os.unlink(out)
    except OSError:
        pass

    return jsonify({"audio": b64, "elapsed": elapsed})


@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": "File too large — maximum is 500 MB"}), 413


if __name__ == "__main__":
    log.info("Starting Speech Filter")
    print("\n  Speech Filter - F5-TTS Audio Cleaner")
    print(f"  F5-TTS: {'ready' if HAS_F5 else 'NOT INSTALLED  (run setup.bat)'}")
    print(f"\n  Open http://localhost:5001")
    print(  "  Errors logged to app.log\n")
    app.run(host="127.0.0.1", port=5001, debug=False, threaded=True)
