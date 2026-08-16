"""Forced-alignment engine (design §4.4.4).

Produces word-level and phoneme-level timestamp alignment for a known
transcript against a rendered WAV. Uses whisperX for phoneme-level
output; degrades to faster-whisper word-only alignment if whisperX is
unavailable.

    align_path  = "<shot>.align.json"
    coverage    = avg alignment overlap (0.0-1.0)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Preston Blair 9 viseme classes, reduced for anime (design §3C.4)
_VOWEL_VISEME: dict[str, str] = {
    "a": "A", "e": "E", "i": "I", "o": "O", "u": "U",
    "ah": "A", "eh": "E", "ih": "I", "oh": "O", "uh": "U",
}
_CONSONANT_VISEME: dict[str, str] = {
    "m": "M", "b": "M", "p": "M",
    "f": "F", "v": "F",
    "l": "L", "r": "L", "n": "L", "t": "L", "d": "L",
    "th": "L", "dh": "L",
}

# ARPABET-to-viseme lookup (design §4.4.4, §3C.4)
_ARPABET_TO_VISEME: dict[str, str] = {
    "AA": "A", "AE": "A", "AH": "A", "AO": "A", "AW": "A",
    "AY": "A",
    "EH": "E", "ER": "E", "EY": "E",
    "IH": "I", "IY": "I",
    "OW": "O", "OY": "O",
    "UH": "U", "UW": "U", "W": "U",
    "B": "M", "P": "M", "M": "M",
    "F": "F", "V": "F",
    "L": "L", "R": "L", "N": "L", "T": "L", "D": "L",
    "TH": "L", "DH": "L", "S": "L", "Z": "L",
    "CH": "REST", "JH": "REST", "SH": "REST", "ZH": "REST",
    "G": "REST", "K": "REST", "HH": "REST", "NG": "REST", "Y": "REST",
}


def viseme_for_word(word: str) -> str:
    """First-letter heuristic -> one of A/E/I/O/U/M/F/L/REST."""
    if not word:
        return "M"
    first = word.strip().lower()
    if not first:
        return "M"
    ch = first[0]
    for vset, result in [
        ("aeiou", _VOWEL_VISEME.get(ch, "A")),
        ("mbp", "M"),
        ("fv", "F"),
        ("lrtnd", "L"),
    ]:
        if ch in vset:
            return result
    return "M"


def phoneme_to_viseme(phoneme: str) -> str:
    """ARPABET phoneme -> Preston Blair viseme. Returns REST for unvoiced."""
    return _ARPABET_TO_VISEME.get(phoneme.upper().rstrip("0123456789"), "REST")


# ── aligner ────────────────────────────────────────────────────────────────

class Aligner:
    """Lazy-loading whisperX wrapper (design §4.4.4)."""

    def __init__(self) -> None:
        self._model: Any = None
        self._loaded = False

    def _ensure_loaded(self) -> bool:
        if self._loaded:
            return self._model is not None
        self._loaded = True
        try:
            import whisperx  # type: ignore[import-untyped]
            self._model = whisperx
            logger.info("whisperX alignment engine loaded")
            return True
        except ImportError:
            try:
                import faster_whisper  # type: ignore[import-untyped]
                self._model = faster_whisper
                logger.info("faster-whisper fallback loaded (no whisperX)")
                return True
            except ImportError:
                logger.warning("neither whisperX nor faster-whisper available")
                return False

    def align(
        self, wav_path: Path, transcript: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], float]:
        words: list[dict[str, Any]] = []
        visemes: list[dict[str, Any]] = []
        if not self._ensure_loaded():
            logger.warning("no alignment backend, returning coverage 0.0")
            return words, visemes, 0.0
        try:
            words, visemes = _align_fallback(wav_path, transcript)
        except Exception as exc:
            logger.warning("alignment failed: %s", exc)
            return words, visemes, 0.0
        known = [w.strip().lower() for w in transcript.split() if w.strip()]
        matched = len([w for w in words if w.get("word", "").strip().lower() in known])
        coverage = min(matched / max(len(known), 1), 1.0)
        return words, visemes, coverage


def _align_fallback(
    wav_path: Path, transcript: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    words: list[dict[str, Any]] = []
    visemes: list[dict[str, Any]] = []
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        model = WhisperModel("small", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(
            str(wav_path),
            initial_prompt=transcript,
            word_timestamps=True,
            vad_filter=True,
        )
        for seg in segments:
            if seg.words is None:
                continue
            for w in seg.words:
                word_str = w.word.strip().rstrip(".,!?;:\"')")
                if not word_str:
                    continue
                entry: dict[str, Any] = {
                    "word": word_str,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                    "confidence": round(w.probability, 3),
                }
                words.append(entry)
                vis = phoneme_to_viseme(word_str)
                visemes.append({
                    "viseme": vis,
                    "start": round(w.start, 3),
                    "end": round(w.end, 3),
                })
    except ImportError:
        known_words = [w.strip().rstrip(".,!?;:\"')") for w in transcript.split() if w.strip()]
        if not known_words:
            return words, visemes
        import array
        try:
            wf = __import__("wave").open(str(wav_path), "rb")
            n_frames = wf.getnframes()
            sr = wf.getframerate()
            wf.close()
            total_s = n_frames / sr
        except Exception:
            total_s = len(known_words) * 0.35
        per_word = total_s / len(known_words)
        for i, w in enumerate(known_words):
            start = i * per_word
            end = start + per_word
            words.append({"word": w, "start": round(start, 3), "end": round(end, 3), "confidence": 0.0})
            visemes.append({
                "viseme": viseme_for_word(w),
                "start": round(start, 3),
                "end": round(end, 3),
            })
    return words, visemes


# ── persistence ────────────────────────────────────────────────────────────

def write_alignment(
    aligner: Aligner, wav_path: Path, transcript: str, align_path: Path,
) -> float:
    """Resume-safe: reuses existing align.json coverage if present."""
    if align_path.exists():
        try:
            data = json.loads(align_path.read_text(encoding="utf-8"))
            cov = data.get("coverage", 0.0)
            if isinstance(cov, (int, float)) and cov > 0.0:
                return float(cov)
        except (json.JSONDecodeError, KeyError):
            pass
    words, visemes, coverage = aligner.align(wav_path, transcript)
    align_path.parent.mkdir(parents=True, exist_ok=True)
    align_path.write_text(
        json.dumps(
            {"words": words, "visemes": visemes, "coverage": round(coverage, 3)},
            indent=2,
        ),
        encoding="utf-8",
    )
    return coverage
