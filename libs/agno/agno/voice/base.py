"""Streaming speech contracts. Provider configuration is reusable; sessions are per call."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncContextManager, AsyncIterator, Literal, Optional

SAMPLE_RATE = 24000
FRAME_SAMPLES = 768


@dataclass(frozen=True)
class Transcript:
    """A cumulative transcript for one microphone turn."""

    turn_id: int
    text: str
    is_final: bool = False


@dataclass(frozen=True)
class SpeechChunk:
    """PCM16 audio or a spoken-text marker ending at a sample offset in the reply.

    Markers let the pipeline retain only acknowledged speech in conversation context.
    Providers without word alignment can mark complete phrases instead.
    """

    audio: bytes = b""
    text: Optional[str] = None
    end_sample: Optional[int] = None


class STTSession(ABC):
    @abstractmethod
    async def _send_audio(self, audio: bytes, turn_id: int) -> None: ...

    @abstractmethod
    async def _commit(self, turn_id: int) -> None: ...

    @abstractmethod
    def _events(self) -> AsyncIterator[Transcript]: ...


class STTModel(ABC):
    """Configuration for streaming recognition at 24 kHz, mono PCM16."""

    @abstractmethod
    def _connect(self) -> AsyncContextManager[STTSession]: ...


class TTSSession(ABC):
    @abstractmethod
    def _synthesize(self, text: AsyncIterator[str]) -> AsyncIterator[SpeechChunk]: ...


class TTSModel(ABC):
    """Configuration for speech synthesis at 24 kHz, mono PCM16."""

    @abstractmethod
    def _connect(self) -> AsyncContextManager[TTSSession]: ...


class VADSession(ABC):
    @abstractmethod
    async def _process(self, audio: bytes) -> Optional[Literal["start", "stop"]]: ...

    async def _close(self) -> None:
        pass


class VAD(ABC):
    """Creates an independent speech detector for each microphone connection."""

    @abstractmethod
    async def _create_session(self) -> VADSession: ...
