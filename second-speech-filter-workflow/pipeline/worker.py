"""
Standalone worker — called by app.py in a subprocess.
If F5-TTS causes a native crash, only this process dies; Flask keeps running.

Usage:
    python pipeline/worker.py <json-args> <output-wav-path>
"""
import sys
import os
import json
import logging
import traceback

logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BASE)


def main():
    if len(sys.argv) < 3:
        sys.stderr.write("Usage: worker.py <json-args> <output-wav-path>\n")
        sys.exit(2)

    args = json.loads(sys.argv[1])
    output_path = sys.argv[2]

    try:
        from pipeline.stage2_f5 import generate
        audio, sr = generate(
            text=args.get("text", ""),
            reference_audio=args["reference_audio"],
            reference_text=args.get("reference_text", ""),
            output_path=output_path,
        )
        # Signal success with sample rate on stdout
        print(json.dumps({"ok": True, "sr": int(sr)}))
        sys.exit(0)

    except Exception as e:
        msg = traceback.format_exc()
        log.error("Worker generate() failed:\n%s", msg)
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(1)


if __name__ == "__main__":
    main()
