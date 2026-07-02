#!/usr/bin/env python3
"""
humanize.py — Two-stage TTS humanization pipeline

Stage 1 — Kokoro TTS:     fast, clean base audio from text
Stage 2 — Fish Speech 1.5: re-synthesizes using Stage 1 as voice reference

Usage:
  python humanize.py --text "path/to/script.txt" --output output.wav
  python humanize.py --text "Hello world." --output output.wav
  python humanize.py --text script.txt --ref voice.wav --output output.wav
  python humanize.py --text script.txt --stage1-only --output kokoro_only.wav
  python humanize.py --text script.txt --ref myvoice.wav --stage2-only --output fish_only.wav
"""
import argparse
import os
import sys
import time
import tempfile


def load_text(arg):
    if os.path.isfile(arg):
        with open(arg, 'r', encoding='utf-8') as f:
            return f.read().strip()
    return arg.strip()


def main():
    parser = argparse.ArgumentParser(
        description="Kokoro -> Fish Speech 1.5 TTS humanization pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--text",         required=True,
                        help="Path to .txt file OR raw text string")
    parser.add_argument("--output",       default="output_humanized.wav",
                        help="Output WAV path (default: output_humanized.wav)")
    parser.add_argument("--ref",          default=None,
                        help="Optional WAV for voice identity (replaces Kokoro output as Stage 2 reference)")
    parser.add_argument("--kokoro-voice", default="af_heart",
                        help="Kokoro voice for Stage 1 (default: af_heart)")
    parser.add_argument("--kokoro-speed", type=float, default=0.88,
                        help="Kokoro speaking speed (default: 0.88)")
    parser.add_argument("--model-path",   default=None,
                        help="Path to fish-speech-1.5 checkpoints directory")
    parser.add_argument("--device",       default=None,
                        help="'cuda' or 'cpu' (default: auto-detect)")
    parser.add_argument("--stage1-only",  action="store_true",
                        help="Skip Stage 2; output Kokoro audio directly")
    parser.add_argument("--stage2-only",  action="store_true",
                        help="Skip Stage 1; use --ref WAV as voice source")
    args = parser.parse_args()

    if args.stage1_only and args.stage2_only:
        sys.exit("Error: --stage1-only and --stage2-only are mutually exclusive.")
    if args.stage2_only and not args.ref:
        sys.exit("Error: --stage2-only requires --ref <voice.wav>")

    text = load_text(args.text)
    if not text:
        sys.exit("Error: no text provided.")

    if args.device:
        device = args.device
    else:
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            device = "cpu"

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    start = time.perf_counter()
    stage1_tmp_path = None

    try:
        # Stage 1: Kokoro TTS
        if not args.stage2_only:
            from pipeline.stage1_kokoro import generate as kokoro_generate
            try:
                import soundfile as sf
            except ImportError:
                sys.exit("soundfile is not installed. Run: pip install soundfile")

            print(f"[Stage 1] Kokoro TTS  voice={args.kokoro_voice}  speed={args.kokoro_speed}")
            t1 = time.perf_counter()
            audio_np, sr = kokoro_generate(text, voice=args.kokoro_voice, speed=args.kokoro_speed)
            dur = len(audio_np) / sr
            elapsed1 = round(time.perf_counter() - t1, 2)
            print(f"          Done in {elapsed1}s -> {dur:.1f}s of audio")

            if args.stage1_only:
                sf.write(args.output, audio_np, sr)
                total = round(time.perf_counter() - start, 2)
                print(f"\nDone. Saved to {args.output} ({total}s)")
                return

            tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            stage1_tmp_path = tmp.name
            tmp.close()
            sf.write(stage1_tmp_path, audio_np, sr)

        # Stage 2: F5-TTS
        ref_audio = args.ref if args.stage2_only else (args.ref or stage1_tmp_path)

        from pipeline.stage2_f5 import generate as f5_generate

        print(f"[Stage 2] F5-TTS  device={device}")
        t2 = time.perf_counter()

        f5_generate(
            text=text,
            reference_audio=ref_audio,
            reference_text=text,
            output_path=args.output,
            model_path=args.model_path,
            device=device,
        )

        elapsed2 = round(time.perf_counter() - t2, 2)
        print(f"          Done in {elapsed2}s")

    finally:
        if stage1_tmp_path and os.path.exists(stage1_tmp_path):
            os.unlink(stage1_tmp_path)

    total = round(time.perf_counter() - start, 2)
    print(f"\nDone. Saved to {args.output} ({total}s)")


if __name__ == "__main__":
    main()
