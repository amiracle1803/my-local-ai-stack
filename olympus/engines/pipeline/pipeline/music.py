"""Scene score: one ACE-Step 1.5 (turbo, ComfyUI) instrumental cue per scene, picked by mood.

The director tags every shot with a mood; a scene's cue uses its most common mood and runs the
scene's length (+2 s tail for the crossfade). Cues are cached by (tags, length, seed) in
audio/music/scene_NN.mp3 + .json, then laid on the episode clock as audio/music/score.wav.
Settings follow ComfyUI's official audio_ace_step_1_5_checkpoint template (shift 3, 8 steps,
cfg 1, euler/simple). Apache-2.0 model, fine for published videos.
"""
from __future__ import annotations

import json
import math
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

from .comfy_client import _request, _with_oom_retry
from .gpu_lock import gpu_batch

# (tags, bpm, key) per mood — descriptive prose works best for ACE-Step 1.5.
MOOD_CUES = {
    "calm": ("Gentle anime film score: soft felt piano, warm sustained strings, light harp, "
             "slow and peaceful, instrumental", 72, "D major"),
    "mystery": ("Mysterious anime film score: music box melody, low bowed strings, distant choir pads, "
                "sparse and curious, instrumental", 80, "D minor"),
    "tension": ("Tense cinematic anime score: pulsing low string ostinato, ticking percussion, "
                "dark brass swells, building suspense, instrumental", 110, "C minor"),
    "action": ("Epic orchestral anime battle score: driving taiko drums, fast staccato strings, "
               "heroic brass hits, intense and powerful, instrumental", 150, "E minor"),
    "sad": ("Melancholic anime piano ballad: slow solo piano, soft cello, gentle strings, "
            "emotional and bittersweet, instrumental", 66, "A minor"),
    "triumph": ("Triumphant epic anime finale score: soaring strings, full choir, bold brass fanfare, "
                "big drums, uplifting, instrumental", 120, "D major"),
    "wonder": ("Magical whimsical anime score: celesta, harp arpeggios, airy flute, light strings, "
               "sense of wonder, instrumental", 96, "G major"),
}
TAIL_S = 2.0
MIN_RENDER_S = 45.0   # ACE-Step writes a whole "song": a 20 s ask ended after ~9 s and went silent
SECTIONS = "[Intro]\n\n[Verse]\n\n[Chorus]\n\n[Verse]\n\n[Chorus]\n\n[Bridge]\n\n[Outro]"


def scene_mood(moods: list[str]) -> str:
    """The scene's cue: its most common shot mood (first one wins a tie), default mystery."""
    known = [m for m in moods if m in MOOD_CUES]
    return Counter(known).most_common(1)[0][0] if known else "mystery"


def graph(tags: str, seconds: float, seed: int, ckpt: str, bpm: int = 120, keyscale: str = "C major") -> dict:
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "TextEncodeAceStepAudio1.5", "inputs": {
            "clip": ["1", 1], "tags": tags, "lyrics": SECTIONS, "seed": seed, "bpm": bpm,
            "duration": round(seconds, 2), "timesignature": "4", "language": "en", "keyscale": keyscale,
            "generate_audio_codes": True, "cfg_scale": 2.0, "temperature": 0.85, "top_p": 0.9,
            "top_k": 0, "min_p": 0.0}},
        "3": {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["2", 0]}},
        "4": {"class_type": "EmptyAceStep1.5LatentAudio", "inputs": {"seconds": round(seconds, 2), "batch_size": 1}},
        "5": {"class_type": "ModelSamplingAuraFlow", "inputs": {"model": ["1", 0], "shift": 3.0}},
        "6": {"class_type": "KSampler", "inputs": {
            "model": ["5", 0], "seed": seed, "steps": 8, "cfg": 1.0, "sampler_name": "euler",
            "scheduler": "simple", "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
            "denoise": 1.0}},
        "7": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["6", 0], "vae": ["1", 2]}},
        "8": {"class_type": "SaveAudioMP3", "inputs": {"audio": ["7", 0], "filename_prefix": "olympus/music",
                                                        "quality": "V0"}},
    }


def _render(g: dict, dest: Path, base_url: str, timeout: int) -> Path:
    pid = _request(f"{base_url}/prompt", {"prompt": g, "client_id": str(uuid.uuid4())})["prompt_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        h = _request(f"{base_url}/history/{pid}").get(pid)
        if h:
            if h.get("status", {}).get("status_str") == "error":
                raise RuntimeError(json.dumps(h)[:2000])
            item = next((a for o in h.get("outputs", {}).values() for a in o.get("audio", [])), None)
            if item:
                q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                            "type": item.get("type", "output")})
                with urllib.request.urlopen(f"{base_url}/view?{q}", timeout=60) as r:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(r.read())
                return dest
        time.sleep(2)
    raise TimeoutError(f"ACE-Step prompt {pid} timed out")


def render_cue(mood: str, seconds: float, dest: Path, seed: int, ckpt: str,
               base_url: str = "http://127.0.0.1:8188", timeout: int = 900) -> Path:
    """One cue, cached: an existing dest whose sidecar matches (mood, length, seed, ckpt) is kept."""
    tags, bpm, key = MOOD_CUES.get(mood, MOOD_CUES["mystery"])
    want = {"mood": mood, "tags": tags, "seconds": round(seconds, 2), "seed": seed, "ckpt": ckpt}
    side = dest.with_suffix(".json")
    if dest.exists() and side.exists() and json.loads(side.read_text()) == want:
        return dest
    base_url = base_url.rstrip("/")
    raw = dest.with_name(dest.stem + ".raw.mp3")
    ask = max(MIN_RENDER_S, seconds + 15)
    with gpu_batch("comfyui:music"):
        _with_oom_retry(lambda: _render(graph(tags, ask, seed, ckpt, bpm, key), raw, base_url, timeout), base_url)
    trim_silence(raw, dest)
    raw.unlink(missing_ok=True)
    side.write_text(json.dumps(want))
    return dest


def trim_silence(src: Path, dest: Path, threshold_db: int = -50) -> Path:
    """Cut leading and trailing near-silence (quiet intros/outros the model leaves)."""
    cut = f"silenceremove=start_periods=1:start_threshold={threshold_db}dB:start_silence=0.1"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-af", f"{cut},areverse,{cut},areverse",
                    "-c:a", "libmp3lame", "-q:a", "2", str(dest)], check=True, timeout=300)
    return dest


def _seconds(f: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(f)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.5


def build_score(cues: list[tuple[float, Path]], total: float, dest: Path, fade: float = 1.5) -> Path:
    """Lay cues on the episode clock (start seconds, file): each fades in/out over `fade` s so
    neighbouring scenes crossfade; the result is exactly `total` seconds long."""
    inputs, chains, labels = [], [], []
    for i, (start, f) in enumerate(cues):
        nxt = cues[i + 1][0] if i + 1 < len(cues) else total
        length = max(0.5, nxt - start + (fade if i + 1 < len(cues) else 0))
        ms = int(start * 1000)
        # a cue shorter than its scene loops a fixed number of times (an endless -stream_loop -1
        # input never let amix finish: stage5 hung 2026-11-20)
        inputs += ["-stream_loop", str(max(0, math.ceil(length / max(0.5, _seconds(f))) - 1)), "-i", str(f)]
        chains.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,atrim=0:{length:.3f},"
                      f"afade=t=in:d={fade if i else 0.01}:st=0,afade=t=out:d={fade}:st={max(0.0, length - fade):.3f},"
                      f"adelay={ms}|{ms}[m{i}]")
        labels.append(f"[m{i}]")
    graph_ = ";".join(chains) + ";" + "".join(labels) + \
        f"amix=inputs={len(labels)}:duration=longest:normalize=0,apad[out]"
    dest.parent.mkdir(parents=True, exist_ok=True)
    # output -t ends the file at the episode length (apad,atrim in the graph never closed: hung)
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph_, "-map", "[out]",
                    "-t", f"{total:.3f}", str(dest)], check=True, timeout=600)
    return dest


def score_episode(project_dir: Path, scenes: list[dict], total: float, ckpt: str,
                  base_url: str = "http://127.0.0.1:8188") -> Path | None:
    """scenes: [{"start": s, "seconds": d, "moods": [...]}]. Writes audio/music/score.wav.
    Any render failure leaves the episode without a score rather than failing stage5."""
    music = Path(project_dir) / "audio" / "music"
    cues = []
    try:
        for i, sc in enumerate(scenes):
            mood = scene_mood(sc.get("moods", []))
            f = render_cue(mood, sc["seconds"] + TAIL_S, music / f"scene_{i + 1:02d}.mp3", 31 + i, ckpt, base_url)
            cues.append((sc["start"], f))
        return build_score(cues, total, music / "score.wav") if cues else None
    except Exception as e:  # noqa: BLE001
        print(f"  music: score skipped ({type(e).__name__}: {str(e)[:200]})", flush=True)
        return None
