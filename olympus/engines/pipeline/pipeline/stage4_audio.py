"""Stage 4 -- VOICE SYSTEM (design section 4.4).

All rendering goes through the Voice Studio HTTP API (``/api/tts``); nothing
here talks to a TTS model directly.

Order of operations:

1. **Render**: every shot narration and every dialogue line is rendered to a
   WAV via Voice Studio -- narration uses ``voices["_narrator"]``, dialogue
   uses ``voices[char_id]`` (falling back to ``_narrator`` with a logged
   warning when a character has no voice spec). Resume-safe: an existing wav
   is never re-rendered.
2. **Pacing bake-in**: ``pause_before_ms`` becomes leading silence spliced
   onto the front of the wav; ``audio_thought`` lines get a flat -3 dB gain
   cut. Both done in-process via ``soundfile``/``numpy`` at the file's native
   sample rate (Voice Studio/Kokoro emits 24 kHz).
3. **Per-line QC** (design 4.4.3): rendered duration (excluding the
   prepended pause) must be within +-50% of ``word_count * 0.35s``. A first
   failure triggers exactly one re-render; a line that still fails is
   flagged (never dropped) and counted in the ``qc_flags`` metric.
4. **Loudness**: full LUFS normalization is NOT implemented here (future
   work) -- the ``loudness_normalized`` metric is recorded as 0.0 so this
   gap stays visible in the scorecard rather than being silently assumed.
5. **Real durations**: each shot's ``real_duration_s`` (sum of its
   narration + dialogue wav durations, pauses included, floor 2.5s) is
   written back into ``screenplay.json``.
6. **Forced alignment** (design 4.4.4): each wav is transcribed once via
   ``faster_whisper`` (``tiny``, CPU, int8, word timestamps) into a sidecar
   ``<name>.align.json`` holding word timings, a crude viseme timeline
   (first-letter heuristic -> A/E/I/O/U/M/F/L), and a coverage ratio
   (transcribed words / known transcript words, capped at 1.0). If
   ``faster_whisper`` is unavailable the import is caught and every line
   gets coverage 0.0 -- the stage still completes, it just proves nothing.
"""

from __future__ import annotations

import io
import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import requests
import soundfile as sf

from .blueprint import Blueprint
from . import identity
from .config import PipelineConfig
from .scores import Scores
from ._util import now_iso

logger = logging.getLogger(__name__)

_VOICE_STUDIO_URL = "http://127.0.0.1:5050"

_WORDS_TO_SECONDS = 0.35  # design 4.4.3 duration-sanity baseline
_QC_TOLERANCE = 0.5       # +-50% band
_THOUGHT_GAIN = 10 ** (-3 / 20)  # -3 dB for audio_thought lines
_MIN_SHOT_DURATION_S = 2.5

_VOWEL_VISEME = {"a": "A", "e": "E", "i": "I", "o": "O", "u": "U"}
_CONSONANT_VISEME = {
    "m": "M", "b": "M", "p": "M",
    "f": "F", "v": "F",
    "l": "L", "n": "L", "t": "L", "d": "L", "r": "L",
}


class Stage4Error(ValueError):
    """Stage4-specific data problems."""


# --------------------------------------------------------------------------
# Voice Studio client
# --------------------------------------------------------------------------
def _voice_studio_healthy(base_url: str) -> bool:
    try:
        r = requests.get(f"{base_url}/api/health", timeout=5)
        return r.ok
    except requests.RequestException:
        return False


def _render_tts(text: str, voice: dict[str, Any], base_url: str) -> bytes:
    r = requests.post(
        f"{base_url}/api/tts",
        json={"text": text, "voice": voice["base"], "speed": voice.get("speed", 1.0)},
        timeout=120,
    )
    r.raise_for_status()
    ct = r.headers.get("content-type", "")
    if "audio" not in ct and "wav" not in ct:
        raise RuntimeError(f"Voice Studio returned non-audio response: {ct}")
    return r.content


# --------------------------------------------------------------------------
# per-line QC (design 4.4.3)
# --------------------------------------------------------------------------
def _qc_pass(duration_s: float, word_count: int) -> bool:
    if word_count == 0:
        return True
    expected = word_count * _WORDS_TO_SECONDS
    return expected * (1 - _QC_TOLERANCE) <= duration_s <= expected * (1 + _QC_TOLERANCE)


def _apply_emotional_delivery(data: np.ndarray, sr: int, delivery: str | None, emotion: str | None) -> np.ndarray:
    """Apply emotional delivery transforms (design 4.4.2)."""
    if delivery == "whispered":
        data = data * 0.5  # -6 dB
        data = data * 0.92  # speed adjustment via resample would need scipy; approximate with gain
        # Lowpass 6 kHz - simplified
        from scipy.signal import butter, filtfilt
        b, a = butter(4, 6000 / (sr / 2), btype='low')
        data = filtfilt(b, a, data, axis=0)
    elif delivery == "shouted":
        data = data * 1.41  # +3 dB
        data = np.clip(data, -1.0, 1.0)
        # Mild compression
        data = np.sign(data) * (1 - np.exp(-2 * np.abs(data)))
    elif delivery == "trailing_off":
        fade_len = int(sr * 0.4)  # 400 ms
        if len(data) > fade_len:
            fade = np.linspace(1.0, 0.0, fade_len)
            if data.ndim > 1:
                fade = fade[:, np.newaxis]
            data[-fade_len:] *= fade
    elif delivery == "cutting_in":
        # Trim leading silence
        if data.ndim == 1:
            nonzero = np.where(np.abs(data) > 0.01)[0]
        else:
            nonzero = np.where(np.abs(data).max(axis=1) > 0.01)[0]
        if len(nonzero) > 0:
            data = data[nonzero[0]:]
    elif delivery == "inner_thought" or emotion == "thought":
        data = data * 0.707  # -3 dB
        # Simple reverb approximation
        delay = int(sr * 0.03)  # 30ms
        if len(data) > delay:
            wet = np.zeros_like(data)
            wet[delay:] = data[:-delay] * 0.12
            data = data + wet
    return data


def _process_and_save(
    wav_bytes: bytes, out_path: Path, pause_before_ms: int, audio_thought: bool,
    delivery: str | None = None, emotion: str | None = None,
) -> float:
    """Prepend leading silence for ``pause_before_ms``, apply emotional
    delivery transforms, then write the wav. Returns total duration (pause included)."""
    data, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    data = _apply_emotional_delivery(data, sr, delivery, emotion)
    if pause_before_ms > 0:
        pad_len = int(sr * pause_before_ms / 1000)
        pad = np.zeros((pad_len,) + data.shape[1:], dtype=data.dtype)
        data = np.concatenate([pad, data], axis=0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(out_path, data, sr)
    return len(data) / sr


def _render_and_qc(
    text: str, voice: dict[str, Any], out_path: Path, pause_before_ms: int,
    audio_thought: bool, base_url: str, label: str,
) -> tuple[float, bool]:
    """Render one line, then bake in pause/gain. Duration QC re-renders once
    on failure and flags (never drops) a line that still fails. Resume-safe:
    an existing wav is trusted as-is and never re-rendered or re-QC'd."""
    if out_path.exists():
        data, sr = sf.read(out_path, dtype="float32")
        return len(data) / sr, False

    word_count = len(text.split())
    wav_bytes = _render_tts(text, voice, base_url)
    raw, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    flagged = False
    if not _qc_pass(len(raw) / sr, word_count):
        logger.warning(
            "%s: duration QC failed (%.2fs for %d words) - re-rendering once",
            label, len(raw) / sr, word_count,
        )
        wav_bytes = _render_tts(text, voice, base_url)
        raw, sr = sf.read(io.BytesIO(wav_bytes), dtype="float32")
        if not _qc_pass(len(raw) / sr, word_count):
            logger.warning("%s: duration QC still failing after re-render - flagging", label)
            flagged = True

    # Map emotion to delivery type
    emotion = "neutral"  # default; override if shot narration has emotion field
    delivery = None
    if audio_thought:
        delivery = "inner_thought"
    elif emotion in ("whispered", "whisper"):
        delivery = "whispered"
    elif emotion in ("shouted", "shout", "yell", "scream"):
        delivery = "shouted"
    elif emotion in ("trailing_off", "trail_off", "fade"):
        delivery = "trailing_off"
    elif emotion in ("cutting_in", "cut_in", "interrupt"):
        delivery = "cutting_in"

    total = _process_and_save(wav_bytes, out_path, pause_before_ms, audio_thought, delivery, emotion)
    return total, flagged


# --------------------------------------------------------------------------
# forced alignment + crude visemes (design 4.4.4)
# --------------------------------------------------------------------------
def _viseme_for_word(word: str) -> str:
    """First-letter heuristic -> one of A/E/I/O/U/M/F/L."""
    letters = re.sub(r"[^a-zA-Z]", "", word).lower()
    if not letters:
        return "M"
    first = letters[0]
    return _VOWEL_VISEME.get(first) or _CONSONANT_VISEME.get(first, "M")


class _Aligner:
    """Lazy Whisper (tiny/CPU) wrapper with faster-whisper fallback.
    Never raises -- any load or transcription failure degrades to coverage 0.0."""

    def __init__(self) -> None:
        self._model = None
        self._fallback_model = None
        try:
            from faster_whisper import WhisperModel
            self._model = WhisperModel("tiny", device="cpu", compute_type="int8")
        except ImportError as exc:
            logger.warning("faster_whisper not installed (%s) - trying whisper fallback", exc)
            try:
                import whisper
                self._fallback_model = whisper.load_model("tiny")
                logger.info("whisper fallback loaded successfully")
            except ImportError:
                logger.warning("whisper not installed either - alignment coverage forced to 0.0")
        except Exception as exc:  # model files missing, etc. -- never crash the stage
            logger.warning("faster_whisper model load failed (%s) - trying whisper fallback", exc)
            try:
                import whisper
                self._fallback_model = whisper.load_model("tiny")
                logger.info("whisper fallback loaded successfully after faster-whisper failure")
            except ImportError:
                logger.warning("whisper not installed either - alignment coverage forced to 0.0")

    def align(self, wav_path: Path, transcript: str) -> tuple[list[dict[str, Any]], float]:
        known_words = transcript.split()
        words: list[dict[str, Any]] = []
        coverage = 0.0
        model_used = "none"

        # Try faster-whisper first
        if self._model is not None:
            try:
                segments, _info = self._model.transcribe(str(wav_path), word_timestamps=True)
                words = [
                    {"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
                    for seg in segments for w in (seg.words or [])
                ]
                model_used = "faster-whisper"
            except Exception as exc:
                logger.warning("faster-whisper alignment failed for %s: %s", wav_path, exc)
                self._model = None  # reset on failure

        # Fallback to whisper if faster-whisper failed or unavailable
        if not words and self._fallback_model is not None:
            try:
                result = self._fallback_model.transcribe(str(wav_path))
                words = [
                    {"word": w.word.strip(), "start": float(w.start), "end": float(w.end)}
                    for w in result.get("words", [])
                ]
                model_used = "whisper-fallback"
            except Exception as exc:
                logger.warning("whisper fallback alignment failed for %s: %s", wav_path, exc)

        if known_words:
            coverage = min(1.0, len(words) / len(known_words))
        else:
            coverage = 1.0 if words else 0.0

        return words, coverage


def _write_alignment(aligner: _Aligner, wav_path: Path, transcript: str, align_path: Path) -> float:
    """Resume-safe: an existing align.json's coverage is reused as-is."""
    if align_path.exists():
        try:
            return float(json.loads(align_path.read_text(encoding="utf-8")).get("coverage", 0.0))
        except (json.JSONDecodeError, OSError):
            pass
    words, coverage = aligner.align(wav_path, transcript)
    visemes = [{"viseme": _viseme_for_word(w["word"]), "start": w["start"], "end": w["end"]} for w in words]
    align_path.write_text(
        json.dumps({"words": words, "coverage": coverage, "visemes": visemes}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return coverage


# --------------------------------------------------------------------------
# main entry point
# --------------------------------------------------------------------------


def run(project_dir: str | Path, config: PipelineConfig, scores: Scores, force: bool = False) -> dict[str, Any]:
    project_dir = Path(project_dir)
    base_url = _VOICE_STUDIO_URL
    if not _voice_studio_healthy(base_url):
        raise RuntimeError(
            f"Voice Studio is not reachable at {base_url} - "
            "systemctl --user start voice-studio.service"
        )

    screenplay_path = project_dir / "screenplay" / "screenplay.json"
    screenplay = json.loads(screenplay_path.read_text(encoding="utf-8"))
    voices = json.loads((project_dir / "voices.json").read_text(encoding="utf-8"))
    narrator_voice = voices.get("_narrator")
    if narrator_voice is None:
        raise Stage4Error("voices.json is missing the required '_narrator' entry")

    narration_dir = project_dir / "audio" / "narration"
    dialogue_dir = project_dir / "audio" / "dialogue"
    narration_dir.mkdir(parents=True, exist_ok=True)
    dialogue_dir.mkdir(parents=True, exist_ok=True)
    project = identity.project_code(project_dir)

    aligner = _Aligner()
    lines_rendered = 0
    qc_flags = 0
    coverages: list[float] = []

    for scene in screenplay["scenes"]:
        for shot in scene["shots"]:
            shot_id = shot["id"]
            durations: list[float] = []

            narration = shot.get("narration")
            if narration:
                text = narration["text"]
                wav_path = identity.audio_path(narration_dir, shot_id, project, "audio_narration")
                if force or not wav_path.exists():
                    duration, flagged = _render_and_qc(
                        text, narrator_voice, wav_path, 0, False, base_url, f"narration {shot_id}",
                    )
                else:
                    # reuse existing wav length (resume-safe)
                    data, sr = sf.read(wav_path)
                    duration = len(data) / sr
                    flagged = False
                durations.append(duration)
                lines_rendered += 1
                qc_flags += int(flagged)
                align_path = identity.audio_path(
                    narration_dir, shot_id, project, "audio_narration", ext="align.json")
                coverages.append(_write_alignment(aligner, wav_path, text, align_path))

            for n, line in enumerate(shot.get("dialogue", [])):
                char_id = line["char"]
                voice = voices.get(char_id)
                if voice is None:
                    logger.warning(
                        "no voice spec for character %r (shot %s) - falling back to _narrator",
                        char_id, shot_id,
                    )
                    voice = narrator_voice
                text = line["text"]
                wav_path = identity.dialogue_path(dialogue_dir, shot_id, project, n)
                if force or not wav_path.exists():
                    duration, flagged = _render_and_qc(
                        text, voice, wav_path, line.get("pause_before_ms", 0),
                        line.get("audio_thought", False), base_url, f"dialogue {shot_id}_{n}",
                    )
                else:
                    data, sr = sf.read(wav_path)
                    duration = len(data) / sr
                    flagged = False
                durations.append(duration)
                lines_rendered += 1
                qc_flags += int(flagged)
                align_path = identity.audio_path(
                    dialogue_dir, shot_id, project, "dialogue", ext="align.json")
                coverages.append(_write_alignment(aligner, wav_path, text, align_path))

            shot["real_duration_s"] = max(_MIN_SHOT_DURATION_S, sum(durations))

    screenplay_path.write_text(
        json.dumps(screenplay, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    alignment_coverage = sum(coverages) / len(coverages) if coverages else 0.0

    scores.record("stage4", "global", "lines_rendered", float(lines_rendered))
    scores.record("stage4", "global", "qc_flags", float(qc_flags))
    scores.record("stage4", "global", "alignment_coverage", alignment_coverage)
    scores.record("stage4", "global", "loudness_normalized", 0.0)  # future work -- no LUFS pass yet
    scores.stage_done("stage4")

    bp = Blueprint.load(project_dir)
    bp.stages["stage4"].status = "done"
    bp.stages["stage4"].ts = now_iso()
    bp.write(project_dir)

    return {
        "stage": "stage4", "status": "done",
        "lines_rendered": lines_rendered,
        "alignment_coverage": round(alignment_coverage, 3),
        "qc_flags": qc_flags,
    }
