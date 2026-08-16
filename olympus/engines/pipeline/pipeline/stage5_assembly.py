"""Stage 5 -- ASSEMBLY (design section 4 / Stage 5).

1. Per shot: a video segment (panel PNG + Tier-0 oscillating drift, design
   3C.1 -- scale up then crop with the crop offset moving linearly over the
   shot duration; never zoom) muxed with its narration + dialogue audio
   (concat filter, padded to the shot duration); a missing panel falls back
   to a black frame and is counted in ``missing_panels``. Segment files are
   resume-safe (existing ones are never re-encoded).
2. Per block: its segments are concatenated (stream copy, concat demuxer) in
   story order.
3. Final: all blocks concatenated, then MP4 chapter markers written at scene
   boundaries via an FFMETADATA sidecar (``-map_metadata``).
4. Music (design Stage 5.3/5.7): ``audio/music/bg.wav`` is mixed in at -18dB
   ONLY if its sidecar manifest proves ``generated`` or ``license_approved``;
   otherwise assembly refuses (copyright gate). No music file -> skipped.
5. Subtitles: ``video/final.srt`` from narration + dialogue, evenly spaced
   across each shot's cumulative time window.
6. ``timeline.json`` (project root): per-shot timing/audio/panel ledger,
   music info, sfx list, and predicted duration/size for Stage 5.11.
7. Predictions vs actual + the mandatory ``av_sync_error_ms`` metric (video
   vs audio stream duration on the probed final file) close out the stage.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .blueprint import Blueprint
from .config import PipelineConfig
from .scores import Scores
from ._util import now_iso
from .video_metrics import (
    _probe_duration,
    _probe_video_frames,
    repeat_detect,
    segment_align_ratio,
)

import shutil

logger = logging.getLogger(__name__)

_FFMPEG_BIN = shutil.which("ffmpeg") or "/home/amire/Downloads/my-local-ai-stack/ComfyUI/.venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2"
_FFPROBE_BIN = shutil.which("ffprobe") or "/home/amire/Downloads/my-local-ai-stack/ComfyUI/.venv/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffprobe-linux-x86_64-v7.0.2"

_PANEL_SIZE = (1024, 576)  # design 3B generation resolution (reduced from 1216x704, see stage3b OOM note)
_DEFAULT_DURATION_S = 3.0  # fallback when real_duration_s is missing
_DEFAULT_DRIFT_PIXELS = 200  # Tier-0 drift fallback when stage3c has no detail yet
_MUSIC_DB = "-18dB"  # design Stage 5.3
_BITRATE_MBPS = 4.0  # size_gb prediction basis
_AV_SYNC_CAP_MS = 10000.0  # design Stage 5.11 reporting cap


class Stage5Error(RuntimeError):
    """Stage5-specific failures: ffmpeg/ffprobe errors and the copyright gate."""


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------


def _shot_duration(shot: dict[str, Any]) -> float:
    try:
        dur = float(shot.get("real_duration_s") or 0.0)
    except (TypeError, ValueError):
        dur = 0.0
    return dur if dur > 0 else _DEFAULT_DURATION_S


def _run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace")[-2000:]
        raise Stage5Error(f"command failed (exit {proc.returncode}): {cmd[0]} ... {tail}")


def _ffprobe_json(args: list[str]) -> dict[str, Any]:
    proc = subprocess.run([_FFPROBE_BIN, *args], capture_output=True)
    if proc.returncode != 0:
        tail = proc.stderr.decode("utf-8", errors="replace")[-2000:]
        raise Stage5Error(f"ffprobe failed: {tail}")
    raw = proc.stdout.decode("utf-8", errors="replace").strip()
    return json.loads(raw) if raw else {}


def _concat_line(path: Path) -> str:
    escaped = str(path).replace("'", "'\\''")
    return f"file '{escaped}'\n"


def _dialogue_index(path: Path, shot_id: str) -> int:
    suffix = path.stem[len(shot_id) + 1:]
    try:
        return int(suffix)
    except ValueError:
        return 0


def _drift_for(shot_id: str, storyboard: dict[str, Any], config: PipelineConfig) -> dict[str, Any]:
    """Tier-0 drift spec for a shot (design 3C.1); falls back to config +
    a fixed pixel budget when stage3c has not written per-shot detail yet."""
    detail = (storyboard.get("shot_detail") or {}).get(shot_id) or {}
    drift = detail.get("drift") or {}
    axis = drift.get("axis") or config.animation.drift_axis
    direction = int(drift.get("direction") or 1) or 1
    pixels = max(0, int(drift.get("pixels") or _DEFAULT_DRIFT_PIXELS))
    return {"axis": axis, "direction": direction, "pixels": pixels}


# The delivery timeline (design 3B: 1216x704 generation lands "letter-perfect"
# in a 1280x720 timeline == blueprint Target.resolution default). Consistency
# review 2026-07-11 finding 6: segments were shipping at panel size.
_TIMELINE_SIZE = (1280, 720)


def _clip_vf(
    clip_path: Path, dur: float, tw: int, th: int, fps: int,
) -> tuple[str, bool]:
    """Build the filter_graph fragment (with ``[0:v]`` label and ``[v]`` out
    label) for an LTX clip over a shot of ``dur`` seconds.

    Returns ``(vf, needs_loop)``:

    - **Ping-pong loop** (the P0 fix): when the clip is shorter than the shot,
      the clip is played forward then reversed into a seamless ``2*clip_len``
      palindrome and looped, so a 9-12s shot over a ~5s motion clip reads as
      continuous breathing instead of the identical 3x repeat a naive
      ``-stream_loop`` re-showed. The frame one clip-period apart is the
      *reversed* take, defeating :func:`video_metrics.repeat_detect`.
    - **Trim with input loop**: when the clip already covers the full shot (or
      the clip duration/count cannot be probed), fall back to ``-stream_loop```
      + ``trim`` (the validated A/V-sync behavior -- ``needs_loop`` True so the
      caller loops the input). A small clip with an unprobeable length still
      fills the shot rather than silently running short against the audio.
    """
    frames = _probe_video_frames(clip_path)
    clip_dur = _probe_duration(clip_path)
    if frames and frames > 0 and clip_dur and dur > clip_dur * 1.2:
        pal_frames = frames * 2
        vf = (
            "split=2[fw][bk];"
            f"[bk]reverse[rv];"
            f"[fw][rv]concat=n=2:v=1:a=0[pal];"
            f"[pal]loop=loop=-1:size={pal_frames}:start=0,"
            f"trim=0:{dur:.3f},setpts=PTS-STARTPTS,"
            f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
            f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,fps={fps}"
        )
        return f"[0:v]{vf}[v]", False
    # Trim path (clip longer than the shot, or unprobeable -> safe fallback).
    base = (
        f"trim=0:{dur:.3f},setpts=PTS-STARTPTS,"
        f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
        f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2,fps={fps}"
    )
    return f"[0:v]{base}[v]", True


def _drift_filter(axis: str, direction: int, pixels: int, fps: int, dur: float) -> str:
    """scale up + linear crop (never zoom -- design 3C.1), then pad into the
    1280x720 delivery timeline."""
    w, h = _PANEL_SIZE
    tw, th = _TIMELINE_SIZE
    if axis == "horizontal":
        scale = f"{w + pixels}:{h}"
        expr = f"(iw-ow)*t/{dur:.3f}" if direction >= 0 else f"(iw-ow)*(1-t/{dur:.3f})"
        crop = f"crop={w}:{h}:'{expr}':0"
    else:
        scale = f"{w}:{h + pixels}"
        expr = f"(ih-oh)*t/{dur:.3f}" if direction >= 0 else f"(ih-oh)*(1-t/{dur:.3f})"
        crop = f"crop={w}:{h}:0:'{expr}'"
    pad = f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:black"
    return f"scale={scale},{crop},{pad},fps={fps}"


def _segment_stale(seg_path: Path, sources: list[Path | None]) -> bool:
    """True iff the cached segment predates any still-existing source it was
    built from. stage3b/stage3c re-render in place (new panels, new AI-
    upscaled clips) but keep the same filenames, so a plain ``exists()``
    resume check would silently concat stale encodes (review finding: the
    June baseline final kept old 1152x672 segments after an AI re-render)."""
    if not seg_path.exists():
        return True
    try:
        seg_mtime = seg_path.stat().st_mtime
    except OSError:
        return True
    for src in sources:
        if src is None or not src.exists():
            continue
        try:
            if src.stat().st_mtime > seg_mtime:
                return True
        except OSError:
            continue
    return False


def _build_segment_args(
    panel_path: Path | None, seg_path: Path, dur: float, fps: int,
    drift: dict[str, Any], audio_paths: list[Path],
    clip_path: Path | None = None,
) -> list[str]:
    args: list[str] = ["-y"]

    tw, th = _TIMELINE_SIZE
    if clip_path is not None and clip_path.exists():
        # LTX clip: prefer a seamless ping-pong loop so a short (~5s) motion
        # clip fills a 9-12s shot without the "identical 3x repeat" artifact; a
        # small clip that cannot be probed falls back to the -stream_loop + trim
        # behavior (the validated A/V-sync path). Either way the video stream is
        # trimmed to exactly `dur` so it never runs short against the audio.
        vf_full, clip_needs_loop = _clip_vf(clip_path, dur, tw, th, fps)
        if clip_needs_loop:
            args += ["-stream_loop", "-1"]
        args += ["-i", str(clip_path)]
        v_in_label = 0
    elif panel_path is not None:
        args += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(panel_path)]
        vf = _drift_filter(drift["axis"], drift["direction"], drift["pixels"], fps, dur)
        v_in_label = 0
        vf_full = f"[{v_in_label}:v]{vf}[v]"
    else:
        args += ["-f", "lavfi", "-t", f"{dur:.3f}", "-i", f"color=c=black:s={tw}x{th}:r={fps}"]
        vf = f"fps={fps}"
        v_in_label = 0
        vf_full = f"[{v_in_label}:v]{vf}[v]"

    if audio_paths:
        for p in audio_paths:
            args += ["-i", str(p)]
        n_audio = len(audio_paths)
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono"]
        n_audio = 1

    concat_labels = "".join(f"[{v_in_label + 1 + i}:a]" for i in range(n_audio))
    filter_complex = (
        f"{vf_full};"
        f"{concat_labels}concat=n={n_audio}:v=0:a=1[acat];"
        f"[acat]apad[a]"
    )
    args += [
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[a]",
        "-t", f"{dur:.3f}",
        "-r", str(fps),
        "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        str(seg_path),
    ]
    return args


def _ffmeta_escape(text: str) -> str:
    return re.sub(r"([=;#\\\n])", r"\\\1", text)


def _build_chapters(scenes: list[dict[str, Any]], out_path: Path) -> Path:
    """FFMETADATA chapter markers at scene boundaries (design Stage 5.3)."""
    lines = [";FFMETADATA1", ""]
    cum = 0.0
    for scene in scenes:
        shots = scene.get("shots", [])
        if not shots:
            continue
        start = cum
        for shot in shots:
            cum += _shot_duration(shot)
        end = cum
        title = _ffmeta_escape(scene.get("summary", "")[:60] or scene["id"])
        lines += [
            "[CHAPTER]", "TIMEBASE=1/1000",
            f"START={int(round(start * 1000))}",
            f"END={int(round(end * 1000))}",
            f"title={title}", "",
        ]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def _srt_timestamp(seconds: float) -> str:
    ms_total = int(round(max(0.0, seconds) * 1000))
    h, ms_total = divmod(ms_total, 3_600_000)
    m, ms_total = divmod(ms_total, 60_000)
    s, ms = divmod(ms_total, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_subtitles(scenes: list[dict[str, Any]], out_path: Path) -> int:
    """narration then dialogue lines, spaced evenly across each shot's window."""
    entries: list[tuple[int, float, float, str]] = []
    idx = 1
    cum = 0.0
    for scene in scenes:
        for shot in scene.get("shots", []):
            dur = _shot_duration(shot)
            start_shot = cum
            segs: list[str] = []
            if shot.get("narration"):
                segs.append(shot["narration"]["text"])
            for line in shot.get("dialogue", []):
                speaker = line.get("char", "")
                segs.append(f"{speaker}: {line['text']}" if speaker else line["text"])
            if segs:
                seg_dur = dur / len(segs)
                for i, text in enumerate(segs):
                    entries.append((idx, start_shot + i * seg_dur, start_shot + (i + 1) * seg_dur, text))
                    idx += 1
            cum += dur

    lines: list[str] = []
    for i, start, end, text in entries:
        lines += [str(i), f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}", text, ""]
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return len(entries)


def _probe_format(path: Path) -> dict[str, Any]:
    return _ffprobe_json(
        ["-v", "error", "-show_entries", "format=duration,size", "-of", "json", str(path)]
    ).get("format", {})


def _probe_stream_durations(path: Path) -> dict[str, float]:
    out = _ffprobe_json(
        ["-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(path)]
    )
    result: dict[str, float] = {}
    for st in out.get("streams", []):
        ct, dur = st.get("codec_type"), st.get("duration")
        if ct and dur not in (None, "N/A"):
            try:
                result[ct] = float(dur)
            except ValueError:
                pass
    return result


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------
def run(project_dir: str | Path, config: PipelineConfig, scores: Scores) -> dict[str, Any]:
    project_dir = Path(project_dir)
    bp = Blueprint.load(project_dir)
    screenplay = json.loads((project_dir / "screenplay" / "screenplay.json").read_text(encoding="utf-8"))
    storyboard_path = project_dir / "storyboard" / "storyboard.json"
    storyboard = json.loads(storyboard_path.read_text(encoding="utf-8"))

    shots_by_id = {shot["id"]: shot for scene in screenplay["scenes"] for shot in scene["shots"]}
    fps = int(storyboard.get("fps") or bp.fps)

    video_dir = project_dir / "video"
    segments_dir = video_dir / "segments"
    clips_dir = video_dir / "clips"
    segments_dir.mkdir(parents=True, exist_ok=True)
    clips_dir.mkdir(parents=True, exist_ok=True)

    narration_dir = project_dir / "audio" / "narration"
    dialogue_dir = project_dir / "audio" / "dialogue"

    # ---- 1. per-shot segments (+ timeline entries built in the same pass) --
    missing_panels = 0
    total_segments = 0
    predicted_duration_s = 0.0
    cum = 0.0
    timeline_entries: list[dict[str, Any]] = []
    clip_segments: list[tuple[Path, Path]] = []  # (segment, ltx clip) for repeat_detect

    for block in storyboard["blocks"]:
        block_dir = project_dir / "panels" / block["id"]
        for shot_id in block["shots"]:
            shot = shots_by_id.get(shot_id, {})
            dur = _shot_duration(shot)
            panel_path = block_dir / f"{shot_id}.png"
            has_panel = panel_path.exists()
            if not has_panel:
                missing_panels += 1
                logger.warning(
                    "panel missing for shot %s (block %s) - using a black frame", shot_id, block["id"],
                )

            audio_paths: list[Path] = []
            narr_path = narration_dir / f"{shot_id}.wav"
            if narr_path.exists():
                audio_paths.append(narr_path)
            audio_paths.extend(
                sorted(dialogue_dir.glob(f"{shot_id}_*.wav"), key=lambda p: _dialogue_index(p, shot_id))
            )

            seg_path = segments_dir / f"{shot_id}.mp4"
            shot_clip_raw = (storyboard.get("shot_detail") or {}).get(shot_id, {}).get("clip_path")
            shot_clip = (project_dir / shot_clip_raw) if shot_clip_raw else None
            if _segment_stale(seg_path, [panel_path, shot_clip, *audio_paths]):
                drift = _drift_for(shot_id, storyboard, config)
                args = _build_segment_args(
                    panel_path if has_panel else None, seg_path, dur, fps, drift, audio_paths,
                    clip_path=shot_clip,
                )
                _run([_FFMPEG_BIN, *args])
            if shot_clip is not None and shot_clip.exists():
                clip_segments.append((seg_path, shot_clip))
            total_segments += 1

            timeline_entries.append({
                "shot": shot_id,
                "start": round(cum, 3),
                "end": round(cum + dur, 3),
                "panel": str(panel_path.relative_to(project_dir)) if has_panel else None,
                "clip": None,
                "audio": [str(p.relative_to(project_dir)) for p in audio_paths],
            })
            cum += dur
            predicted_duration_s += dur

    # ---- 2. per-block concat (story order) --------------------------------
    for block in storyboard["blocks"]:
        clip_path = clips_dir / f"{block['id']}.mp4"
        if clip_path.exists():
            continue
        list_path = clips_dir / f"{block['id']}.list.txt"
        list_path.write_text(
            "".join(_concat_line(segments_dir / f"{sid}.mp4") for sid in block["shots"]), encoding="utf-8",
        )
        _run([_FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(list_path), "-c", "copy", str(clip_path)])

    # ---- 2b. objective quality gates (no GPU) ------------------------------
    # audio/visual alignment per segment + the P0 repeat-detection regression
    # guard on every LTX clip segment (near-duplicate frames one clip period
    # apart == the "same scene 3x" artifact).
    seg_durations: list[tuple[float, float]] = []
    for seg in sorted(segments_dir.glob("*.mp4")):
        sd = _probe_stream_durations(seg)
        if "video" in sd and "audio" in sd:
            seg_durations.append((sd["video"], sd["audio"]))
    audio_visual_align = segment_align_ratio(seg_durations)

    repeat_events = 0
    repeat_shots: list[str] = []
    repeat_details: dict[str, Any] = {}
    for seg_path, clip in clip_segments:
        clip_dur = _probe_duration(clip)
        if not clip_dur:
            continue
        res = repeat_detect(seg_path, clip_dur)
        repeat_details[seg_path.stem] = res
        if res.get("verdict") == "repeat":
            repeat_events += res["repeat_events"]
            repeat_shots.append(seg_path.stem)
    if repeat_shots:
        logger.warning(
            "repeat-detection flagged %d shots for identical-loop artifacts: %s",
            len(repeat_shots), ", ".join(repeat_shots),
        )
    (video_dir / "quality_metrics.json").write_text(
        json.dumps({
            "audio_visual_align": round(audio_visual_align, 3),
            "repeat_detect": {"events": repeat_events, "shots": repeat_shots,
                              "details": repeat_details},
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---- 3. final concat ----------------------------------------------------
    final_list_path = video_dir / "final.list.txt"
    final_list_path.write_text(
        "".join(_concat_line(clips_dir / f"{b['id']}.mp4") for b in storyboard["blocks"]), encoding="utf-8",
    )
    final_concat_path = video_dir / "final_concat.mp4"
    _run([
        _FFMPEG_BIN, "-y", "-f", "concat", "-safe", "0", "-i", str(final_list_path),
        "-c", "copy", str(final_concat_path),
    ])
    working_path = final_concat_path

    # ---- 4. music (design Stage 5.3 / 5.7 copyright gate) ------------------
    music_dir = project_dir / "audio" / "music"
    bg_path = music_dir / "bg.wav"
    manifest_path = music_dir / "manifest.json"
    music_present = 0
    music_info: dict[str, Any] | None = None
    if bg_path.exists():
        if not manifest_path.exists():
            raise Stage5Error(
                f"music file {bg_path} present without a license manifest at {manifest_path} - "
                "refusing to mix unlicensed audio (design Stage 5.7 copyright gate)."
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not (manifest.get("generated") or manifest.get("license_approved")):
            raise Stage5Error(
                f"music file {bg_path} has no generated/license_approved flag in {manifest_path} - "
                "refusing to mix unlicensed audio (design Stage 5.7 copyright gate)."
            )
        final_music_path = video_dir / "final_music.mp4"
        _run([
            _FFMPEG_BIN, "-y",
            "-i", str(working_path), "-i", str(bg_path),
            "-filter_complex",
            f"[1:a]volume={_MUSIC_DB}[bg];[0:a][bg]amix=inputs=2:duration=first:"
            "dropout_transition=0:normalize=0[a]",
            "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac",
            str(final_music_path),
        ])
        working_path = final_music_path
        music_present = 1
        music_info = {"path": str(bg_path.relative_to(project_dir)), **manifest}

    # ---- 5. chapters (scene boundaries) + final mux ------------------------
    chapters_path = _build_chapters(screenplay["scenes"], video_dir / "chapters.ffmetadata")
    final_path = video_dir / "final.mp4"
    _run([
        _FFMPEG_BIN, "-y", "-i", str(working_path), "-i", str(chapters_path),
        "-map_metadata", "1", "-codec", "copy", "-movflags", "+faststart", str(final_path),
    ])

    # ---- 6. subtitles --------------------------------------------------------
    _build_subtitles(screenplay["scenes"], video_dir / "final.srt")

    # ---- 7. predictions vs actual + mandatory av_sync_error_ms --------------
    fmt = _probe_format(final_path)
    actual_duration_s = float(fmt.get("duration", 0.0) or 0.0)
    actual_size_bytes = int(fmt.get("size", 0) or 0)
    size_mb = actual_size_bytes / 1e6

    predicted_size_gb = predicted_duration_s * _BITRATE_MBPS * 1_000_000 / 8 / 1_000_000_000
    predicted_vs_actual_pct = (
        (actual_duration_s - predicted_duration_s) / predicted_duration_s * 100.0
        if predicted_duration_s > 0 else 0.0
    )

    stream_durs = _probe_stream_durations(final_path)
    video_dur = stream_durs.get("video", actual_duration_s)
    audio_dur = stream_durs.get("audio", actual_duration_s)
    av_sync_error_ms = min(abs(video_dur - audio_dur) * 1000.0, _AV_SYNC_CAP_MS)

    timeline = {
        "story_id": bp.story_id,
        "entries": timeline_entries,
        "music": music_info,
        "sfx": storyboard.get("sfx", []),
        "predicted": {
            "duration_s": round(predicted_duration_s, 2),
            "size_gb": round(predicted_size_gb, 4),
        },
        "next_episode": {"carry": False},
    }
    (project_dir / "timeline.json").write_text(
        json.dumps(timeline, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    scores.record("stage5", "global", "render_segments", float(total_segments))
    scores.record("stage5", "global", "missing_panels", float(missing_panels))
    scores.record("stage5", "global", "music_present", float(music_present))
    scores.record("stage5", "global", "predicted_vs_actual_duration_pct", predicted_vs_actual_pct)
    scores.record("stage5", "global", "av_sync_error_ms", av_sync_error_ms)
    scores.record("stage5", "global", "audio_visual_align", audio_visual_align)
    scores.record("stage5", "global", "repeat_detect_events", float(repeat_events))
    scores.record("stage5", "global", "repeat_detect_shots", float(len(repeat_shots)))
    scores.stage_done("stage5")

    bp.stages["stage5"].status = "done"
    bp.stages["stage5"].ts = now_iso()
    bp.write(project_dir)

    result = {
        "stage": "stage5", "status": "done",
        "final": str(final_path),
        "duration_s": round(actual_duration_s, 3),
        "size_mb": round(size_mb, 2),
        "av_sync_error_ms": round(av_sync_error_ms, 1),
        "audio_visual_align": round(audio_visual_align, 3),
        "repeat_detect_events": repeat_events,
        "segments": total_segments,
        "missing_panels": missing_panels,
    }

    # P0 hard gate (design 5.x): the identical-loop artifact is a reject, not a
    # warning. The final file is already on disk for inspection; the stage is
    # left marked "done" so the artifact stays reviewable, but the run reports
    # FAILURE so automation (and the human) knows to re-render before shipping.
    if repeat_events and config.animation.fail_on_repeat:
        logger.error(
            "repeat-detection found %d identical-loop events across %d shot(s) "
            "(%s) - re-render with the ping-pong loop before shipping.",
            repeat_events, len(repeat_shots), ", ".join(repeat_shots),
        )
        result["status"] = "blocked"
        result["repeat_verdict"] = "repeat"
    else:
        result["repeat_verdict"] = "ok"
    return result
