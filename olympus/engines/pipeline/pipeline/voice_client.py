"""Voice Studio API client (design §4.4).

Thin HTTP client for the Voice Studio on :5050. Used by stage4_audio.py
for TTS synthesis, QC, voice assignment, and delivery transforms. One
instance per stage run.

    POST /api/tts        synthesize WAV from text + VoiceSpec
    GET  /api/health     liveness check
    GET  /api/voices     list available voices
"""

from __future__ import annotations

import io
import json
import logging
import struct
import urllib.error
import urllib.request
import wave
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from .config import PipelineConfig

logger = logging.getLogger(__name__)

VOICE_STUDIO_URL = "http://127.0.0.1:5050"


# ── data models ───────────────────────────────────────────────────────────

class VoiceBlend(BaseModel):
    """Kokoro embedding mixing (design §4.4.1)."""
    with_: str = Field(alias="with")
    ratio: float


class VoiceSpec(BaseModel):
    """Immutable voice identity per character (design §4.4.1)."""
    base: str
    blend: VoiceBlend | None = None
    speed: float = 1.0
    pitch_semitones: float = 0.0
    assigned_by: str = "auto"
    audition: str | None = None


class DeliveryNote(BaseModel):
    """Delivery parameters for one line (design §4.4.2)."""
    emotion: str = ""
    delivery: str = ""
    speed_factor: float | None = None
    gain_db: float | None = None
    lowpass_hz: float | None = None
    fade_out_ms: int | None = None
    reverb_wet_pct: float | None = None


class AudioQCResult(BaseModel):
    """Per-line QC result (design §4.4.3)."""
    label: str
    duration_s: float
    word_count: int
    expected_s: float
    within_tolerance: bool
    has_internal_silence_gt_1_5s: bool
    has_clipping: bool
    loudness_lufs: float | None = None
    flagged: bool = False


# ── client ─────────────────────────────────────────────────────────────────

class VoiceClientError(RuntimeError):
    """Voice Studio call failed."""


class VoiceClient:
    """HTTP client for Voice Studio (:5050) (design §4.4)."""

    def __init__(
        self,
        *,
        base_url: str = VOICE_STUDIO_URL,
        timeout: float = 120.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def _get(self, path: str) -> dict[str, Any]:
        url = f"{self._base}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                return json.loads(resp.read())
        except Exception as exc:
            raise VoiceClientError(f"GET {url} failed: {exc}") from exc

    def _get_bytes(self, path: str) -> bytes:
        url = f"{self._base}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                return resp.read()
        except Exception as exc:
            raise VoiceClientError(f"GET {url} failed: {exc}") from exc

    def healthy(self) -> bool:
        try:
            data = self._get("/api/health")
            return data.get("status") == "ok" and data.get("model_loaded", False)
        except Exception:
            return False

    def list_voices(self) -> list[str]:
        return self._get("/api/voices")

    def tts(self, *, text: str, voice: VoiceSpec) -> bytes:
        payload: dict[str, Any] = {
            "text": text,
            "voice": voice.base,
            "speed": voice.speed,
        }
        if voice.blend is not None:
            payload["blend_with"] = voice.blend.with_
            payload["blend_ratio"] = voice.blend.ratio
        if voice.pitch_semitones != 0.0:
            payload["pitch_semitones"] = voice.pitch_semitones
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base}/api/tts",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                ct = resp.headers.get("Content-Type", "")
                data = resp.read()
                if "audio/wav" in ct or data[:4] == b"RIFF":
                    return data
                try:
                    err = json.loads(data)
                    raise VoiceClientError(err.get("error", "unknown tts error"))
                except json.JSONDecodeError:
                    raise VoiceClientError(f"unexpected tts response: {data[:200]!r}")
        except VoiceClientError:
            raise
        except urllib.error.HTTPError as exc:
            body = exc.read() if exc.fp else b""
            raise VoiceClientError(f"TTS failed: {exc.code} {body[:500]!r}") from exc
        except Exception as exc:
            raise VoiceClientError(f"TTS failed: {exc}") from exc

    def tts_with_delivery(
        self,
        *,
        text: str,
        voice: VoiceSpec,
        delivery: DeliveryNote | None = None,
    ) -> bytes:
        speed = voice.speed
        if delivery is not None and delivery.speed_factor is not None:
            speed *= delivery.speed_factor
        vs = VoiceSpec(
            base=voice.base,
            blend=voice.blend,
            speed=speed,
            pitch_semitones=voice.pitch_semitones,
            assigned_by=voice.assigned_by,
        )
        wav = self.tts(text=text, voice=vs)
        if delivery is None:
            return wav
        return _apply_delivery(wav, delivery)

    def qc_line(
        self, wav_bytes: bytes, word_count: int, label: str = ""
    ) -> AudioQCResult:
        expected_s = word_count * 0.35
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                n_frames = wf.getnframes()
                sr = wf.getframerate()
                duration_s = n_frames / sr
                nchannels = wf.getnchannels()
                sw = wf.getsampwidth()
                frames = wf.readframes(n_frames)
        except Exception:
            return AudioQCResult(
                label=label, duration_s=0, word_count=word_count,
                expected_s=expected_s, within_tolerance=False,
                has_internal_silence_gt_1_5s=False, has_clipping=False, flagged=True,
            )
        within = 0.5 * expected_s <= duration_s <= 1.5 * expected_s
        clipping = False
        silence_over_1_5s = False
        if sw == 2 and nchannels >= 1:
            clip_samples = 0
            for i in range(0, len(frames), nchannels * 2):
                v = struct.unpack_from("<h", frames, i)[0]
                if abs(v) >= 32760:
                    clip_samples += 1
            clipping = clip_samples > n_frames * nchannels * 0.005
            silence_dur = _longest_silence(frames, sr, nchannels, sw)
            silence_over_1_5s = silence_dur > 1.5
        flagged = not within or clipping or silence_over_1_5s
        return AudioQCResult(
            label=label, duration_s=duration_s, word_count=word_count,
            expected_s=expected_s, within_tolerance=within,
            has_internal_silence_gt_1_5s=silence_over_1_5s,
            has_clipping=clipping, flagged=flagged,
        )

    def align_line(
        self, wav_path: Path, transcript: str, align_path: Path,
    ) -> float:
        from .align import write_alignment
        from .align import Aligner

        aligner = Aligner()
        return write_alignment(aligner, wav_path, transcript, align_path)


# ── delivery transforms (design §4.4.2) ────────────────────────────────────

def _apply_delivery(wav_bytes: bytes, delivery: DeliveryNote) -> bytes:
    try:
        import numpy as np   # type: ignore[import-untyped]
        import soundfile as sf  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("numpy/soundfile not available, skipping delivery transforms")
        return wav_bytes
    data, sr = sf.read(io.BytesIO(wav_bytes))
    if delivery.gain_db is not None:
        factor = 10 ** (delivery.gain_db / 20.0)
        data = data * factor
    if delivery.fade_out_ms is not None and delivery.fade_out_ms > 0:
        fade_samples = int(sr * delivery.fade_out_ms / 1000)
        if fade_samples > 0 and fade_samples < len(data):
            ramp = np.linspace(1.0, 0.0, fade_samples)
            data[-fade_samples:] = data[-fade_samples:] * ramp.reshape(-1, 1)
    if delivery.lowpass_hz is not None and delivery.lowpass_hz < sr / 2:
        try:
            from scipy.signal import butter, lfilter  # type: ignore[import-untyped]
            nyq = sr / 2
            b, a = butter(4, delivery.lowpass_hz / nyq, btype="low")
            for ch in range(data.shape[1]):
                data[:, ch] = lfilter(b, a, data[:, ch])
        except ImportError:
            pass
    buf = io.BytesIO()
    sf.write(buf, data, sr, format="WAV")
    return buf.getvalue()


def _longest_silence(
    frames: bytes, sr: int, nchannels: int, sw: int
) -> float:
    threshold = 200
    longest = 0.0
    current = 0
    step = nchannels * sw
    for i in range(0, len(frames), step):
        v = struct.unpack_from("<h", frames, i)[0]
        if abs(v) < threshold:
            current += 1
        else:
            longest = max(longest, current / sr)
            current = 0
    longest = max(longest, current / sr)
    return longest


# ── voice assignment (design §4.4.1) ───────────────────────────────────────

_ENVY_GUARD: float = 5.0
ENVY_THRESHOLD: int = 10

# rule table: gender × age × personality -> list[voice_id]
_VOICE_RULES: dict[str, dict[str, dict[str, list[str]]]] = {
    "female": {
        "young": {
            "default": ["af_heart", "af_bella", "af_sarah", "af_sky"],
            "shy": ["af_bella", "af_sarah"],
            "energetic": ["af_heart", "af_sky"],
            "mature": ["af_bella"],
        },
        "adult": {
            "default": ["af_sarah", "af_sky", "af_nova"],
            "authoritative": ["af_sarah", "af_nova"],
            "warm": ["af_sky"],
        },
    },
    "male": {
        "young": {
            "default": ["am_adam", "am_michael", "am_liam"],
            "energetic": ["am_adam", "am_liam"],
            "serious": ["am_michael"],
        },
        "adult": {
            "default": ["am_michael", "am_liam", "am_adam"],
            "authoritative": ["am_michael", "am_adam"],
            "warm": ["am_liam"],
        },
    },
}


def _hash(s: str) -> int:
    h = 5381
    for ch in s:
        h = ((h << 5) + h) + ord(ch)
    return h & 0x7FFFFFFF


def check_distinctness(
    voices: dict[str, VoiceSpec],
    co_occurring_pairs: list[tuple[str, str]],
) -> list[str]:
    violations: list[str] = []
    for a, b in co_occurring_pairs:
        va = voices.get(a)
        vb = voices.get(b)
        if va is None or vb is None:
            continue
        same_base = va.base == vb.base
        if va.blend is not None and vb.blend is not None:
            same_blend = (
                va.blend.with_ == vb.blend.with_
                and abs(va.blend.ratio - vb.blend.ratio) < 0.01
            )
        elif va.blend is None and vb.blend is None:
            same_blend = True
        else:
            same_blend = False
        if same_base and same_blend:
            ds = abs(va.speed - vb.speed)
            dp = abs(va.pitch_semitones - vb.pitch_semitones)
            if ds < 0.05 and dp < 1.0:
                violations.append(
                    f"{a} and {b} share base={va.base} blend={va.blend} "
                    f"|Δspeed|={ds:.3f} |Δpitch|={dp:.1f} — not distinct enough"
                )
    return violations


def assign_voices(
    characters: list[dict[str, Any]],
    voice_pool: list[str] | None = None,
    pinned: dict[str, VoiceSpec] | None = None,
) -> dict[str, VoiceSpec]:
    pinned = pinned or {}
    assigned: dict[str, VoiceSpec] = dict(pinned)
    unused: set[str] = set(voice_pool or [])

    sorted_chars = sorted(
        [c for c in characters if c.get("id", "").startswith("char-")],
        key=lambda c: c.get("dialogue_line_count", 0),
        reverse=True,
    )

    for char in sorted_chars:
        cid = char["id"]
        if cid in assigned:
            continue
        gender = char.get("gender", "female")
        age = char.get("age", "young")
        personality = char.get("personality", "default")

        rules_g = _VOICE_RULES.get(gender, _VOICE_RULES["female"])
        rules_a = rules_g.get(age, rules_g.get("young", {}))
        candidates = rules_a.get(
            personality,
            rules_a.get("default", ["af_heart"]),
        )

        chosen: str | None = None
        used_bases = {v.base for v in assigned.values()}
        for c in candidates:
            if c in unused or c not in used_bases:
                chosen = c
                if c in unused:
                    unused.discard(c)
                break
        if chosen is None:
            chosen = candidates[0]
            ratio = (_hash(cid) % 30) / 100 + 0.55
            blend = VoiceBlend(**{"with": candidates[-1], "ratio": ratio})
        else:
            blend = None

        assigned[cid] = VoiceSpec(
            base=chosen,
            blend=blend,
            speed=0.95 + (_hash(cid) % 15) / 100,
            pitch_semitones=((_hash(cid + "p") % 7) - 3),
            assigned_by="auto",
        )

    return assigned
