"""Validation shared by WAV uploads and normalized WebSocket audio."""

from io import BytesIO
from math import gcd
import wave

import numpy as np
from scipy.signal import resample_poly

MAX_AUDIO_SECONDS = 60
MAX_UPLOAD_BYTES = 12 * 1024 * 1024


def validate_audio(
    samples, sample_rate: int = 16000, *, allow_silence: bool = False
) -> np.ndarray:
    try:
        audio = np.asarray(samples, dtype=np.float32)
    except (TypeError, ValueError) as error:
        raise ValueError("Invalid audio samples. Please record again.") from error
    if audio.ndim != 1 or audio.size == 0:
        raise ValueError("Empty or invalid audio. Please speak or use text input.")
    if audio.size > sample_rate * MAX_AUDIO_SECONDS:
        raise ValueError(
            "Audio is too long. Please keep each recording under 60 seconds."
        )
    if not np.isfinite(audio).all() or np.max(np.abs(audio)) > 1.0:
        raise ValueError(
            "Audio samples must be finite and normalized between -1 and 1."
        )
    if not allow_silence and not np.any(audio):
        raise ValueError(
            "No speech audio received. Check your microphone or use text input."
        )
    return audio


def decode_wav(contents: bytes, target_rate: int = 16000) -> np.ndarray:
    if len(contents) > MAX_UPLOAD_BYTES:
        raise ValueError("Audio upload is too large.")
    try:
        with wave.open(BytesIO(contents), "rb") as source:
            channels, width, rate, frames, compression, _ = source.getparams()
            if compression != "NONE" or width != 2 or channels not in (1, 2):
                raise ValueError("Please upload a mono or stereo 16-bit PCM WAV file.")
            if rate < 8000 or rate > 48000:
                raise ValueError("WAV sample rate must be between 8000 and 48000 Hz.")
            if frames == 0 or frames > rate * MAX_AUDIO_SECONDS:
                raise ValueError("WAV must contain between 0 and 60 seconds of audio.")
            data = source.readframes(frames)
            if len(data) != frames * channels * width:
                raise ValueError("Incomplete WAV audio. Please record again.")
    except (wave.Error, EOFError) as error:
        raise ValueError(
            "Invalid WAV file. Please upload 16-bit PCM WAV audio."
        ) from error
    audio = np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0
    if channels == 2:
        audio = audio.reshape(-1, 2).mean(axis=1)
    if rate != target_rate:
        factor = gcd(rate, target_rate)
        audio = resample_poly(audio, target_rate // factor, rate // factor)
        audio = np.clip(audio, -1, 1)
    return validate_audio(audio, target_rate)
