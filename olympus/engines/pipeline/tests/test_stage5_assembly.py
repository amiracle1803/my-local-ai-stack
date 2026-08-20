"""Stage 5 assembly: ping-pong loop fix (P0) + audio-driven shot duration."""
from pathlib import Path
from unittest.mock import patch

from pipeline.stage5_assembly import _build_segment_args, _clip_vf, _shot_duration

_TW, _TH = 1280, 720


def test_shot_duration_uses_real_duration_s():
    """P1: shot length comes from Stage 4's measured TTS duration, not a word
    count estimate. ``real_duration_s`` is authoritative; missing/zero falls
    back to the default."""
    assert _shot_duration({"real_duration_s": 9.5}) == 9.5
    assert _shot_duration({"real_duration_s": 0.0}) == 5.0  # default
    assert _shot_duration({}) == 5.0
    assert _shot_duration({"real_duration_s": "bad"}) == 5.0


def test_clip_vf_pingpong_when_clip_shorter_than_shot(tmp_path):
    """A short clip over a long shot builds the forward+reverse palindrome
    (ping-pong) so the identical 3x repeat is gone."""
    clip = tmp_path / "short.mp4"
    clip.write_bytes(b"fake")
    with patch("pipeline.stage5_assembly._probe_video_frames", return_value=81), \
         patch("pipeline.stage5_assembly._probe_duration", return_value=5.06):
        vf, needs_loop = _clip_vf(clip, dur=11.0, tw=_TW, th=_TH, fps=24)
    assert needs_loop is False
    assert "reverse" in vf and "concat=n=2" in vf
    assert "loop=loop=-1" in vf
    assert "trim=0:11.000" in vf


def test_clip_vf_trim_fallback_when_clip_longer_than_shot(tmp_path):
    """A clip already long enough trims (no reverse overhead) and loops the
    input so an unprobeable short clip still fills the shot (A/V-sync safe)."""
    clip = tmp_path / "long.mp4"
    clip.write_bytes(b"fake")
    with patch("pipeline.stage5_assembly._probe_video_frames", return_value=200), \
         patch("pipeline.stage5_assembly._probe_duration", return_value=15.0):
        vf, needs_loop = _clip_vf(clip, dur=5.0, tw=_TW, th=_TH, fps=24)
    assert needs_loop is True
    assert "reverse" not in vf
    assert "trim=0:5.000" in vf


def test_clip_vf_unprobeable_falls_back_with_loop(tmp_path):
    """A clip ffprobe cannot read (corrupt/empty) must still loop the input
    so the video stream never runs short against the audio (the av_sync
    regression we fixed on clockguard)."""
    clip = tmp_path / "broken.mp4"
    clip.write_bytes(b"")
    with patch("pipeline.stage5_assembly._probe_video_frames", return_value=None), \
         patch("pipeline.stage5_assembly._probe_duration", return_value=None):
        vf, needs_loop = _clip_vf(clip, dur=10.0, tw=_TW, th=_TH, fps=24)
    assert needs_loop is True
    assert "trim=0:10.000" in vf


def test_build_segment_args_pingpong_no_stream_loop(tmp_path):
    """Ping-pong path: the input is NOT -stream_loop'd (the loop filter does
    it inside the graph); output is trimmed to dur."""
    clip = tmp_path / "short.mp4"
    clip.write_bytes(b"fake")
    seg = tmp_path / "seg.mp4"
    audio = tmp_path / "n.wav"
    audio.write_bytes(b"\x00")
    with patch("pipeline.stage5_assembly._probe_video_frames", return_value=81), \
         patch("pipeline.stage5_assembly._probe_duration", return_value=5.06):
        args = _build_segment_args(
            panel_path=None, seg_path=seg, dur=10.0, fps=24,
            drift={"axis": "vertical", "direction": 1, "pixels": 80},
            audio_paths=[audio], clip_path=clip,
        )
    assert "-stream_loop" not in args  # loop is inside the filter graph
    fc = args[args.index("-filter_complex") + 1]
    assert "reverse" in fc and "concat=n=2" in fc and "loop=loop=-1" in fc
    assert "trim=0:10.000" in fc


def test_build_segment_args_fallback_keeps_stream_loop(tmp_path):
    """Fallback path keeps -stream_loop -1 (the A/V-sync-safe behavior) for an
    unprobeable clip -- regression guard for the original av desync fix."""
    clip = tmp_path / "broken.mp4"
    clip.touch()
    seg = tmp_path / "seg.mp4"
    audio = tmp_path / "n.wav"
    audio.write_bytes(b"\x00")
    with patch("pipeline.stage5_assembly._probe_video_frames", return_value=None), \
         patch("pipeline.stage5_assembly._probe_duration", return_value=None):
        args = _build_segment_args(
            panel_path=None, seg_path=seg, dur=10.0, fps=24,
            drift={"axis": "vertical", "direction": 1, "pixels": 80},
            audio_paths=[audio], clip_path=clip,
        )
    assert "-stream_loop" in args and "-1" in args
    fc = args[args.index("-filter_complex") + 1]
    assert "trim=0:10.000" in fc
