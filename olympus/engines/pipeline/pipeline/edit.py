"""Dynamic (manhwa-recap) editing for stage5 panels mode: [edit] dynamic = true.

Per key frame the director picked a camera move (director.MOVES). This module turns that into
ffmpeg filters (zoompan expression, flash / whip-blur transition, overlays) and collects the
sound effects that land on the cuts:

  punch / shake  -> white flash in, speed lines, impact SFX
  pan_* / tilt_* -> whip-blur in, whoosh SFX
  ui (shot)      -> SYSTEM window on the shot's first two frames, chime SFX
  caption (shot) -> caption on the shot's peak frame, riser into it
"""
from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MOVES = ("push", "pan_right", "pull", "pan_left", "drift")
PEAK = ("punch", "shake")
WHIP = ("pan_left", "pan_right", "tilt_up", "tilt_down")


def zoompan(move: str, n: int) -> str:
    """zoompan z/x/y for `move` over n output frames (input pre-scaled to 1.5x the frame)."""
    n = max(1, n)
    cx, cy = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    exprs = {
        "push": (f"1+0.10*on/{n}", cx, cy),
        "pull": (f"1.10-0.10*on/{n}", cx, cy),
        "pan_right": ("1.08", f"(iw-iw/zoom)*on/{n}", cy),
        "pan_left": ("1.08", f"(iw-iw/zoom)*(1-on/{n})", cy),
        "tilt_up": ("1.08", cx, f"(ih-ih/zoom)*(1-on/{n})"),
        "tilt_down": ("1.08", cx, f"(ih-ih/zoom)*on/{n}"),
        "drift": (f"1.03+0.04*on/{n}", f"{cx}+iw*0.02*(on/{n}-0.5)", cy),
        # fast ease-out zoom to 1.25 in 6 frames, then a slow creep
        "punch": (f"if(lt(on,6),1+0.25*(1-pow(1-on/6,3)),1.25+0.05*(on-6)/{n})", cx, cy),
        # decaying camera shake for the first 16 frames
        "shake": ("1.12", f"{cx}+if(lt(on,16),40*sin(on*2.9)*(1-on/16),0)",
                  f"{cy}+if(lt(on,16),28*cos(on*3.7)*(1-on/16),0)"),
    }
    z, x, y = exprs.get(move, exprs["push"])
    return f"z='{z}':x='{x}':y='{y}'"


def transition(move: str, fps: int) -> str:
    """Post-zoompan filter that makes the cut INTO this frame: flash for peaks, whip blur for
    moves, nothing (hard cut) otherwise."""
    if move in PEAK:
        return ",fade=t=in:st=0:d=0.18:color=white"
    if move in WHIP:
        return ",gblur=sigma=28:sigmaV=0.01:enable='lt(n,5)'"
    return ""


@dataclass
class Frame:
    png: Path
    frames: int
    move: str
    overlays: list[tuple[Path, bool, float]] = field(default_factory=list)  # (png, fade_in, show_for_s|0=all)


@dataclass
class Plan:
    frames: list[Frame]
    sfx: list[tuple[float, str]]  # (seconds from shot start, sfx name)


def plan_shot(stills: list[Path], total_frames: int, fps: int, directed: dict, fx_dir: Path,
              overlays: bool = True, size: tuple[int, int] = (1920, 1080), seed: int = 0) -> Plan:
    """Split a shot's frames across its stills and attach moves, overlays and SFX cues."""
    from . import fx

    n = len(stills)
    moves = [m for m in (directed.get("moves") or []) if m]
    moves = [moves[j] if j < len(moves) else DEFAULT_MOVES[(seed + j) % len(DEFAULT_MOVES)] for j in range(n)]
    per = [total_frames // n] * n
    per[-1] += total_frames - sum(per)
    W, H = size
    out: list[Frame] = []
    sfx: list[tuple[float, str]] = []
    t = 0.0
    ui = (directed.get("ui") or "").strip() if overlays else ""
    caption = (directed.get("caption") or "").strip() if overlays else ""
    cap_at = next((j for j, m in enumerate(moves) if m in PEAK), 0)
    stem = re.sub(r"[^a-z0-9_]+", "_", stills[0].stem.lower())
    fx_dir.mkdir(parents=True, exist_ok=True)
    for j, (png, k, move) in enumerate(zip(stills, per, moves)):
        f = Frame(png, max(1, k), move)
        if overlays and move in PEAK:
            sl = fx_dir / f"speed_{(seed + j) % 4}.png"
            if not sl.exists():
                fx.speed_lines(sl, W, H, seed=(seed + j) % 4)
            f.overlays.append((sl, False, 0.6))
            sfx.append((t, "impact"))
        elif move in WHIP and j + (seed % 2) > 0:     # not every opening pan whooshes
            sfx.append((max(0.0, t - 0.12), "whoosh"))
        if ui and j < 2:
            win = fx_dir / f"ui_{stem}.png"
            if not win.exists():
                fx.system_window(ui, win, W, H)
            f.overlays.append((win, j == 0, 0))
            if j == 0:
                sfx.append((t + 0.25, "chime"))
        if caption and j == cap_at:
            cap = fx_dir / f"cap_{stem}.png"
            if not cap.exists():
                fx.caption(caption, cap, W, H)
            f.overlays.append((cap, True, 0))
            sfx.append((max(0.0, t - 1.2), "riser"))
        out.append(f)
        t += f.frames / fps
    return Plan(out, sfx)


def sfx_track(events: list[tuple[float, str]], library: dict[str, Path], total: float, dest: Path,
              volume: float = 0.45) -> Path | None:
    """All SFX on the episode clock as one wav (exactly `total` s), or None without events."""
    events = [(t, n) for t, n in sorted(events) if n in library and t < total]
    if not events:
        return None
    inputs, chains = [], []
    for i, (t, name) in enumerate(events):
        ms = int(t * 1000)
        inputs += ["-i", str(library[name])]
        chains.append(f"[{i}:a]aresample=44100,aformat=channel_layouts=stereo,adelay={ms}|{ms}[s{i}]")
    graph = ";".join(chains) + ";" + "".join(f"[s{i}]" for i in range(len(events))) + \
        f"amix=inputs={len(events)}:duration=longest:normalize=0,volume={volume},apad[out]"
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[out]",
                    "-t", f"{total:.3f}", str(dest)], check=True, timeout=600)
    return dest


def episode_title(brief: str, slug: str) -> str:
    m = re.search(r'(?im)EPISODE\s*\d+\s*[—–:-]\s*["“]?([^"”\n]+)', brief or "")
    return m.group(1).strip() if m else slug.replace("_", " ")


def thumbnail_frame(shots: list[tuple[dict, Path, float]]) -> Path | None:
    """Thumbnail art: the first shot with a caption, else a punch/shake shot, else the longest.
    shots: (director entry, main panel, seconds)."""
    if not shots:
        return None
    for d, p, _ in shots:
        if d.get("caption"):
            return p
    for d, p, _ in shots:
        if any(m in PEAK for m in d.get("moves") or []):
            return p
    return max(shots, key=lambda s: s[2])[1]
