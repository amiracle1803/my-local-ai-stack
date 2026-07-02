#!/usr/bin/env python3
"""
download_models.py — Pre-download all TTS models before first use.

Run once after setup so models don't download mid-generation:
  python download_models.py

Models:
  Kokoro   ~82 MB   Apache 2.0   hexgrad/Kokoro-82M
  F5-TTS  ~1.5 GB  MIT          SWivid/F5-TTS
"""
import sys
import os

BASE = os.path.dirname(os.path.abspath(__file__))


def step(label):
    print(f"\n{'-'*55}")
    print(f"  {label}")
    print(f"{'-'*55}")


def check_import(pkg, install_hint=""):
    try:
        __import__(pkg)
        return True
    except Exception:
        print(f"  [SKIP] {pkg} not importable.{' ' + install_hint if install_hint else ''}")
        return False


# ── GPU info ──────────────────────────────────────────────────
try:
    import torch
    if torch.cuda.is_available():
        print(f"\n  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  VRAM: {torch.cuda.get_device_properties(0).total_memory // 1024**2} MB")
    else:
        print("\n  GPU: not available — will use CPU (slower)")
except Exception as e:
    print(f"\n  [WARN] torch check failed: {e}")


# ── Kokoro ────────────────────────────────────────────────────
step("Kokoro (~82 MB)  Apache 2.0  hexgrad/Kokoro-82M")
if check_import("kokoro", "Run: pip install kokoro"):
    try:
        from kokoro import KPipeline
        print("  Initialising Kokoro (triggers model download)...")
        pipe = KPipeline(lang_code="a")
        gen  = pipe("Hi.", voice="af_heart", speed=1.0)
        for _ in gen:
            pass
        print("  Kokoro ready.")
    except Exception as e:
        print(f"  [WARN] Kokoro warmup error: {e}")


# ── F5-TTS ────────────────────────────────────────────────────
step("F5-TTS (~1.5 GB)  MIT  SWivid/F5-TTS")
if check_import("f5_tts", "Run: pip install f5-tts cached-path matplotlib pydub vocos"):
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
        from f5_tts.api import F5TTS
        print(f"  Loading F5-TTS on {device} (downloads ~1.5 GB if not cached)...")
        m = F5TTS(device=device)
        print("  F5-TTS ready.")
        del m
        if device == "cuda":
            torch.cuda.empty_cache()
    except Exception as e:
        print(f"  [WARN] F5-TTS error: {e}")


print(f"\n{'='*55}")
print("  All available models pre-downloaded.")
print("  Run setup.bat (or python app.py) to start the app.")
print(f"{'='*55}\n")
