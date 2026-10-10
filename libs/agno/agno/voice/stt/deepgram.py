"""Streaming Deepgram transcription over a persistent WebSocket."""

import json
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from os import getenv
from typing import Any, AsyncIterator, List, Optional, Tuple
from urllib.parse import urlencode

from agno.voice.base import SAMPLE_RATE, STTModel, STTSession, Transcript
from agno.voice.stt._turns import _TimelineSession

# Deepgram closes a stream that has not received audio within ten seconds of
# opening, and KeepAlive alone does not prevent that, so connect with silence.
_OPENING_SILENCE_SAMPLES = SAMPLE_RATE // 10


@dataclass
class DeepgramSTT(STTModel):
    """Stream microphone audio to Deepgram and receive incremental transcripts.

    ``language`` takes any language or regional code Deepgram supports.
    ``language="multi"`` with ``nova-3`` handles speakers who switch languages.
    ``keyterms`` boosts names and jargon.
    """

    id: str = "nova-3"
    language: str = "en"
    keyterms: Optional[List[str]] = None
    smart_format: bool = True
    # Silence in milliseconds before Deepgram finalizes a segment on its own.
    # The voice pipe's VAD still decides when a turn ends.
    endpointing: Optional[int] = None
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: str = "wss://api.deepgram.com/v1/listen"
    connect_timeout: float = 15.0
    # Deepgram does not always answer Finalize, so a turn falls back to the
    # transcript received so far after this many seconds.
    finalize_timeout: float = 1.5
    keepalive_interval: float = 4.0

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.language.strip():
            raise ValueError("Deepgram model and language must not be empty.")
        if self.connect_timeout <= 0 or self.finalize_timeout <= 0:
            raise ValueError("Deepgram timeouts must be positive.")
        if not 0 < self.keepalive_interval < 10:
            raise ValueError("keepalive_interval must be between 0 and 10 seconds.")
        if self.endpointing is not None and self.endpointing < 0:
            raise ValueError("endpointing must be nonnegative.")

    def _url(self) -> str:
        params: List[Tuple[str, str]] = [
            ("model", self.id),
            ("language", self.language),
            ("encoding", "linear16"),
            ("sample_rate", str(SAMPLE_RATE)),
            ("channels", "1"),
            ("interim_results", "true"),
            ("punctuate", "true"),
            ("smart_format", "true" if self.smart_format else "false"),
        ]
        if self.endpointing is not None:
            params.append(("endpointing", str(self.endpointing)))
        params.extend(("keyterm", term) for term in self.keyterms or [] if term.strip())
        separator = "&" if "?" in self.base_url else "?"
        return self.base_url + separator + urlencode(params)

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[STTSession]:
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:
            raise ImportError("DeepgramSTT requires `pip install 'websockets>=13'`.") from exc
        api_key = self.api_key or getenv("DEEPGRAM_API_KEY")
        if not api_key:
            raise ValueError("Set DEEPGRAM_API_KEY or pass api_key to DeepgramSTT.")
        async with connect(
            self._url(),
            additional_headers={"Authorization": f"Token {api_key}"},
            open_timeout=self.connect_timeout,
            close_timeout=2,
            max_size=2**22,
        ) as connection:
            session = _DeepgramSession(connection, self)
            await session._send(bytes(_OPENING_SILENCE_SAMPLES * 2))
            session._timeline.add_silence(_OPENING_SILENCE_SAMPLES)
            session._start_keepalive()
            try:
                yield session
            finally:
                await session._stop_keepalive()
                with suppress(Exception):
                    await session._send(json.dumps({"type": "CloseStream"}))


class _DeepgramSession(_TimelineSession):
    _provider = "Deepgram transcription"

    def __init__(self, connection: Any, model: DeepgramSTT) -> None:
        super().__init__(connection, model.finalize_timeout, model.keepalive_interval, join=" ")

    def _audio_payload(self, audio: bytes) -> bytes:
        return audio

    def _keepalive_payload(self) -> str:
        return json.dumps({"type": "KeepAlive"})

    def _finalize_payload(self) -> str:
        return json.dumps({"type": "Finalize"})

    def _parse(self, message: Any) -> List[Transcript]:
        event = json.loads(message)
        kind = event.get("type")
        if kind == "Error":
            raise RuntimeError(f"Deepgram transcription: {event.get('description') or event}")
        if kind != "Results":
            return []
        alternatives = (event.get("channel") or {}).get("alternatives") or [{}]
        text = (alternatives[0].get("transcript") or "").strip()
        start = float(event.get("start") or 0.0)
        turn_id = self._timeline.turn_at(start)
        if not event.get("is_final"):
            interim = self._timeline.set_interim(turn_id, text)
            return [interim] if interim is not None else []
        final = self._timeline.add_final(turn_id, text)
        # Each final result covers a window of stream audio; everything before
        # its end is now settled.
        self._finalized_through = max(self._finalized_through, start + float(event.get("duration") or 0.0))
        return [final] if final is not None else []
