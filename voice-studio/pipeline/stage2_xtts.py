"""
Stage 2: XTTS-v2 (Coqui TTS) -- re-synthesize Stage 1's clean speech in a
cloned reference voice.

This didn't previously exist anywhere in the stack: real-natural-voices'
/api/humanize imported `pipeline.stage2_xtts`, but neither that module nor
a pipeline/ package shipped with it -- the endpoint was broken even though
HAS_XTTS gated it as "available". This is a straightforward wrapper around
Coqui TTS's documented XTTS-v2 voice-cloning API, written to complete the
feature the app already advertised rather than carry the broken import
forward.

Install: pip install TTS
"""

_tts = None


def _get_model(device: str = "cuda"):
    global _tts
    if _tts is None:
        try:
            from TTS.api import TTS
        except ImportError:
            raise ImportError("TTS is not installed. Run:\n  pip install TTS")
        _tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    return _tts


def generate(text: str, reference_audio: str, reference_text: str, output_path: str,
             device: str = "cuda", language: str = "en") -> None:
    """
    Re-synthesize `text` in the voice heard in `reference_audio`, writing a
    WAV to `output_path`. `reference_text` is accepted for API-shape
    compatibility with the rest of the humanize pipeline but XTTS-v2 only
    needs the reference audio itself (no transcript required for cloning).
    """
    model = _get_model(device)
    model.tts_to_file(
        text=text,
        speaker_wav=reference_audio,
        language=language,
        file_path=output_path,
    )
