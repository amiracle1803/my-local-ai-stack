"""
Stage 1: Kokoro TTS — fast clean speech from text.
Install: pip install kokoro soundfile
"""
import re
import numpy as np

SAMPLE_RATE = 24000

_pipeline = None


def _get_pipeline():
    global _pipeline
    if _pipeline is None:
        try:
            from kokoro import KPipeline
        except ImportError:
            raise ImportError(
                "kokoro is not installed. Run:\n"
                "  pip install kokoro soundfile"
            )
        _pipeline = KPipeline(lang_code='a')  # 'a' = American English
    return _pipeline


def split_sentences(text):
    text = text.strip()
    sentences = re.split(r'(?<=[.!?])\s+', text)
    merged = []
    buffer = ""
    for s in sentences:
        buffer = (buffer + " " + s).strip()
        if len(buffer) >= 20:
            merged.append(buffer)
            buffer = ""
    if buffer:
        merged.append(buffer)
    return merged or [text]


def generate(text, voice='af_heart', speed=0.88):
    """
    Generate audio from text using Kokoro TTS.

    Args:
        text:  Input text string.
        voice: Kokoro voice name (e.g. 'af_heart', 'am_adam', 'bm_george').
        speed: Speaking speed multiplier; 0.88 gives a slightly slower,
               more natural base that Stage 2 can build on.

    Returns:
        (numpy float32 array, sample_rate int)
    """
    pipeline = _get_pipeline()
    sentences = split_sentences(text)
    chunks = []
    for sentence in sentences:
        gen = pipeline(sentence, voice=voice, speed=speed)
        for _, _, audio in gen:
            chunks.append(audio)
    if not chunks:
        raise RuntimeError("Kokoro generated no audio for the given text.")
    return np.concatenate(chunks).astype(np.float32), SAMPLE_RATE
