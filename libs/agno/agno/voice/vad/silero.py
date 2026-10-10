"""Local Silero speech detection with independent state for each microphone."""

import asyncio
from dataclasses import dataclass
from typing import Any, Literal, Optional

from agno.voice.base import VAD, VADSession


@dataclass
class SileroVAD(VAD):
    """Detect speech in 32 ms frames of 24 kHz mono PCM16.

    Only the detector's input is downsampled to 16 kHz. Original microphone
    samples continue to transcription unchanged. Model loading and inference
    run off the event loop, and every voice call has separate model state.
    """

    threshold: float = 0.5
    min_silence_duration_ms: int = 320
    speech_pad_ms: int = 30

    def __post_init__(self) -> None:
        if not 0 < self.threshold < 1:
            raise ValueError("threshold must be between 0 and 1.")
        if self.min_silence_duration_ms < 0 or self.speech_pad_ms < 0:
            raise ValueError("Silence duration and speech padding must be nonnegative.")

    async def _create_session(self) -> VADSession:
        return await asyncio.to_thread(self._load)

    def _load(self) -> VADSession:
        try:
            import numpy as np
            import torch
            from silero_vad import VADIterator, load_silero_vad  # type: ignore[import-untyped, import-not-found]
        except ImportError as exc:
            raise ImportError("SileroVAD requires `pip install silero-vad onnxruntime numpy`.") from exc
        detector = VADIterator(
            load_silero_vad(onnx=True),
            threshold=self.threshold,
            sampling_rate=16000,
            min_silence_duration_ms=self.min_silence_duration_ms,
            speech_pad_ms=self.speech_pad_ms,
        )
        return _SileroSession(detector, np, torch)


class _SileroSession(VADSession):
    frame_samples = 768

    def __init__(self, detector: Any, numpy: Any, torch: Any) -> None:
        self._detector = detector
        self._numpy = numpy
        self._torch = torch
        self._source = numpy.arange(self.frame_samples)
        self._target = numpy.arange(512) * 1.5

    def _detect(self, audio: bytes) -> Optional[Literal["start", "stop"]]:
        samples = self._numpy.frombuffer(audio, dtype="<i2").astype(self._numpy.float32) / 32768.0
        resampled = self._numpy.interp(self._target, self._source, samples).astype(self._numpy.float32)
        event = self._detector(self._torch.from_numpy(resampled))
        if event:
            return "start" if "start" in event else "stop"
        return None

    async def _process(self, audio: bytes) -> Optional[Literal["start", "stop"]]:
        if len(audio) != self.frame_samples * 2:
            raise ValueError("SileroVAD expects exactly 768 PCM16 samples per frame.")
        return await asyncio.to_thread(self._detect, audio)
