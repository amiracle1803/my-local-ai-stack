"""
F5-TTS re-synthesis — upload audio, get a clean version back.

Install: pip install f5-tts cached-path matplotlib pydub vocos
Model:   ~1.5 GB, downloads automatically on first use from Hugging Face
License: MIT
"""
import os
import sys
import tempfile
import logging
import numpy as np

log = logging.getLogger(__name__)

_model = None
_device_loaded = None

# F5-TTS reference clip. Longer clips give more voice context but slow inference.
_REF_MAX_SEC = 60


def _get_model(device=None):
    global _model, _device_loaded
    if device is None:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    if _model is not None and _device_loaded == device:
        return _model
    try:
        from f5_tts.api import F5TTS
    except ImportError:
        raise ImportError(
            "f5-tts is not installed. Run:\n"
            "  pip install f5-tts cached-path matplotlib pydub vocos"
        )
    log.info("[F5-TTS] Loading model on %s (first run downloads ~1.5 GB)...", device)
    try:
        _model = F5TTS(device=device)
    except Exception as e:
        log.error("[F5-TTS] Model load failed: %s", e, exc_info=True)
        raise
    _device_loaded = device
    log.info("[F5-TTS] Model ready.")
    return _model


def _trim_reference(wav_path, max_sec=_REF_MAX_SEC):
    """Return (path, created_tmp) — trim to max_sec if longer."""
    try:
        import soundfile as sf
        data, sr = sf.read(wav_path, dtype="float32")
    except Exception:
        try:
            import torchaudio
            t, sr = torchaudio.load(wav_path)
            data = t.squeeze(0).numpy().astype("float32")
        except Exception:
            return wav_path, False

    max_samples = int(max_sec * sr)
    if len(data) <= max_samples:
        return wav_path, False

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    try:
        import soundfile as sf
        sf.write(tmp.name, data[:max_samples], sr)
    except Exception:
        import torchaudio, torch
        torchaudio.save(tmp.name, torch.from_numpy(data[:max_samples]).unsqueeze(0), sr)
    tmp.close()
    return tmp.name, True


def _auto_transcribe(audio_path):
    """Transcribe audio using faster-whisper when no transcript is provided."""
    try:
        from faster_whisper import WhisperModel
        log.info("[Whisper] Transcribing audio...")
        model = WhisperModel("base", device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, beam_size=5)
        result = " ".join(s.text.strip() for s in segments).strip()
        log.info("[Whisper] Transcript: %s", result[:120])
        return result
    except Exception as e:
        log.warning("[Whisper] Auto-transcribe failed: %s", e)
        return ""


def generate(text, reference_audio, reference_text, output_path,
             model_path=None, device=None, **kwargs):
    """
    Re-synthesize audio cleanly using F5-TTS.

    Args:
        text:            Transcript of what is being said (gen_text).
                         If empty, auto-transcribed via faster-whisper.
        reference_audio: The uploaded audio to clean (voice identity source).
        reference_text:  Same transcript — used for phoneme alignment.
        output_path:     Where to write the cleaned WAV.
        device:          'cuda', 'cpu', or None (auto-detect).

    Returns:
        (numpy float32 array, sample_rate int)
    """
    # If no transcript supplied, auto-detect so gen_text is never empty
    if not text:
        print("  [F5-TTS] No transcript provided — auto-transcribing...")
        text = _auto_transcribe(reference_audio)
        reference_text = text
        if not text:
            raise ValueError(
                "Could not auto-detect transcript. "
                "Please type what the audio is saying in the Transcript field."
            )
        print(f"  [F5-TTS] Auto-transcript: {text[:80]}")

    ref_path, did_create_tmp = _trim_reference(reference_audio)
    try:
        model = _get_model(device)
        log.info("[F5-TTS] Running inference (gen_text=%r)...", text[:80])
        wav, sr, _ = model.infer(
            ref_file=ref_path,
            ref_text=reference_text,
            gen_text=text,
            file_wave=output_path,
        )
        log.info("[F5-TTS] Inference complete.")
    finally:
        if did_create_tmp and os.path.exists(ref_path):
            try:
                os.unlink(ref_path)
            except OSError:
                pass

    return _read_wav(output_path)


def _read_wav(path):
    try:
        import soundfile as sf
        data, sr = sf.read(path, dtype="float32")
        return data, int(sr)
    except Exception:
        import torchaudio
        wav, sr = torchaudio.load(path)
        return wav.squeeze(0).numpy().astype(np.float32), int(sr)
