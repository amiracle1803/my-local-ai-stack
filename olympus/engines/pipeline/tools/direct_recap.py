"""Direct recap v2: script -> ~5s scenes -> krea2 images -> narration -> video.

The SCRIPT TEXT IS THE NARRATION. The script is split into short narration
chunks (~5s each); one krea2 image is generated per chunk and shown for that
chunk's narration duration, so the story gets a NEW IMAGE roughly every 5s.

  generator : ComfyUI krea2_turbo-Q4_K_M (image_txt2img_krea2.json)
  narration : Kokoro TTS of the script text (narrator voice)
  assembly  : per-chunk Ken Burns segment (image + narration) then concat

Usage:
  python tools/direct_recap.py input/source.txt --out OUT --chunk-chars 85
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from pipeline.comfy_client import ComfyClient  # noqa: E402
from pipeline.voice_client import VoiceClient, VoiceSpec  # noqa: E402
from pipeline.config import PipelineConfig  # noqa: E402
from stack.config import cfg as _scfg  # noqa: E402

STYLE = ("Classroom of the Elite anime style, semi-realistic proportions, "
         "sharp clean lineart, subdued muted color palette, detailed expressive "
         "eyes, tense atmosphere, high detail, no text, no watermark")
NEG = ("lowres, bad anatomy, bad hands, extra fingers, cropped, worst quality, "
       "low quality, jpeg artifacts, signature, watermark, blurry, text, letters")

# Varied shot framing per chunk (the all-close-up fix).
FRAMINGS = [
    "wide establishing shot", "medium shot", "close-up",
    "over-the-shoulder shot", "extreme wide shot", "dutch-angle shot",
    "two-shot", "low-angle shot", "aerial shot", "insert shot",
]
_NARRATOR_VOICE = "af_bella"
_KREA2_WF = "image_txt2img_krea2.json"


def split_chunks(text: str, chunk_chars: int) -> list[str]:
    """Split script into ~chunk_chars narration chunks (one image per chunk).
    Splits on sentence boundaries so narration isn't cut mid-sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", text.replace("\n", " "))
    chunks: list[str] = []
    cur = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(cur) + len(s) + 1 <= chunk_chars or not cur:
            cur = cur + " " + s if cur else s
        else:
            if cur:
                chunks.append(cur)
            cur = s
    if cur:
        chunks.append(cur)
    # Drop panel / too-short noise.
    return [c for c in chunks if len(c) > 25]


def scene_prompt(chunk: str, index: int) -> str:
    """Image prompt = a leading visual cue from the chunk + varied framing."""
    cue = re.sub(r"\[.*?\]", "", chunk)
    cue = re.sub(r"[»\-]", "", cue)
    cue = cue.strip()[:200]
    framing = FRAMINGS[index % len(FRAMINGS)]
    return f"{framing}, {cue}, {STYLE}"


def tts(text: str, out: Path, vc: VoiceClient) -> Path:
    out.write_bytes(vc.tts(text=text[:900], voice=VoiceSpec(base=_NARRATOR_VOICE)))
    return out


def probe_duration(media: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(media)],
        capture_output=True, text=True)
    return float(r.stdout.strip() or 0)


def kb_segment(img: Path, wav: Path, out: Path, dur: float, index: int) -> Path:
    zf = 1.05 + (index % 4) * 0.02
    vf = (f"scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080,"
          f"zoompan=z='min(zoom+0.0012,{zf})':d=1:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=24")
    subprocess.run([
        "ffmpeg", "-y", "-loop", "1", "-i", str(img), "-i", str(wav),
        "-filter_complex", vf, "-t", f"{dur:.3f}", "-r", "24",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-shortest", str(out),
    ], check=True, capture_output=True)
    return out


def assemble(segments: list[Path], out: Path) -> Path:
    listf = out.parent / "segments.txt"
    listf.write_text("".join(f"file '{p.resolve()}'\n" for p in segments), encoding="utf-8")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listf),
        "-c", "copy", str(out),
    ], check=True, capture_output=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("script")
    ap.add_argument("--out", default="/home/amire/Documents/olympus-output/direct_recap_krea")
    ap.add_argument("--chunk-chars", type=int, default=85, help="~narration chars per image (~5s)")
    ap.add_argument("--max-chunks", type=int, default=0, help="0 = all")
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()

    cfg = _scfg
    pcfg = PipelineConfig.load()  # ComfyClient needs PipelineConfig (comfyui_dir, models)
    comfy = ComfyClient(pcfg)
    if not comfy.healthy():
        print("ComfyUI not reachable"); sys.exit(1)
    vc = VoiceClient(base_url=cfg.voice.url)
    try:
        vc.list_voices()
    except Exception as e:
        print(f"Voice unreachable: {e}"); sys.exit(1)

    text = Path(args.script).read_text(encoding="utf-8")
    chunks = split_chunks(text, args.chunk_chars)
    if args.max_chunks:
        chunks = chunks[args.start:args.start + args.max_chunks]
    print(f"chunks (~{args.chunk_chars}ch ~5s each): {len(chunks)}")

    out_dir = Path(args.out)
    img_dir = out_dir / "images"; img_dir.mkdir(parents=True, exist_ok=True)
    wav_dir = out_dir / "audio"; wav_dir.mkdir(parents=True, exist_ok=True)
    seg_dir = out_dir / "segments"; seg_dir.mkdir(parents=True, exist_ok=True)

    segments: list[Path] = []
    manifest = []
    for i, chunk in enumerate(chunks):
        tag = f"{i+1:03d}"
        print(f"--- chunk {tag} ---")
        prompt = scene_prompt(chunk, i)
        try:
            imgs = comfy.generate(_KREA2_WF,
                {"PROMPT_POS": prompt, "WIDTH": 1280, "HEIGHT": 720,
                 "SEED": int(time.time()) % 2**31, "STEPS": 8, "CFG": 1.0,
                 "SAVE_PREFIX": f"chunk_{tag}"}, dest=img_dir)
        except Exception as e:
            print(f"  !! krea2 render failed for chunk {tag}: {e}; continuing")
            continue
        if not imgs:
            print(f"  !! no image for chunk {tag}; continuing"); continue
        img = imgs[0]
        wav = tts(chunk, wav_dir / f"chunk_{tag}.wav", vc)
        dur = max(probe_duration(wav), 2.5)
        print(f"  image={img.name} narration={dur:.1f}s")
        seg = kb_segment(img, wav, seg_dir / f"chunk_{tag}.mp4", dur, i)
        segments.append(seg)
        manifest.append({"chunk": tag, "prompt": prompt, "image": str(img),
                         "audio": str(wav), "duration_s": dur, "narration": chunk[:150]})

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if segments:
        final = assemble(segments, out_dir / "direct_recap_krea_master_v001.mp4")
        print(f"DONE -> {final} ({probe_duration(final):.1f}s, {len(segments)} images)")
    else:
        print("no chunks produced")


if __name__ == "__main__":
    main()