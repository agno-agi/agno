"""Streaming Soniox transcription over a persistent WebSocket."""

import json
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from os import getenv
from typing import Any, AsyncIterator, Dict, List, Optional

from agno.voice.base import STTModel, STTSession, Transcript
from agno.voice.stt._turns import _TimelineSession, _to_16k

# Soniox documents 16 kHz input.
_SONIOX_SAMPLE_RATE = 16000
_MARKERS = ("<end>", "<fin>")


@dataclass
class SonioxSTT(STTModel):
    """Stream microphone audio to Soniox and receive incremental transcripts.

    Without ``language_hints``, every supported language is recognized,
    including speech that switches languages. Hints bias recognition toward the
    expected languages; others are still recognized unless
    ``language_hints_strict`` is set. ``terms`` and ``context`` add
    domain vocabulary and background text.
    """

    id: str = "stt-rt-v5"
    language_hints: Optional[List[str]] = None
    language_hints_strict: bool = False
    terms: Optional[List[str]] = None
    context: Optional[str] = None
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: str = "wss://stt-rt.soniox.com/transcribe-websocket"
    connect_timeout: float = 15.0
    # Soniox answers each finalize request; this only guards a stalled reply.
    finalize_timeout: float = 3.0
    keepalive_interval: float = 10.0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("The Soniox model id must not be empty.")
        if self.language_hints is not None and any(not hint.strip() for hint in self.language_hints):
            raise ValueError("language_hints must not contain empty codes.")
        if self.connect_timeout <= 0 or self.finalize_timeout <= 0:
            raise ValueError("Soniox timeouts must be positive.")
        if not 0 < self.keepalive_interval < 20:
            raise ValueError("keepalive_interval must be between 0 and 20 seconds.")

    def _config(self, api_key: str) -> Dict[str, Any]:
        config: Dict[str, Any] = {
            "api_key": api_key,
            "model": self.id,
            "audio_format": "pcm_s16le",
            "sample_rate": _SONIOX_SAMPLE_RATE,
            "num_channels": 1,
        }
        if self.language_hints:
            config["language_hints"] = self.language_hints
            if self.language_hints_strict:
                config["language_hints_strict"] = True
        context: Dict[str, Any] = {}
        if self.terms:
            context["terms"] = [term for term in self.terms if term.strip()]
        if self.context:
            context["text"] = self.context
        if context:
            config["context"] = context
        return config

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[STTSession]:
        try:
            import numpy
            from websockets.asyncio.client import connect
        except ImportError as exc:
            raise ImportError("SonioxSTT requires `pip install 'websockets>=13' numpy`.") from exc
        api_key = self.api_key or getenv("SONIOX_API_KEY")
        if not api_key:
            raise ValueError("Set SONIOX_API_KEY or pass api_key to SonioxSTT.")
        async with connect(
            self.base_url, open_timeout=self.connect_timeout, close_timeout=2, max_size=2**22
        ) as connection:
            # Soniox authenticates with the first message instead of a header.
            await connection.send(json.dumps(self._config(api_key)))
            session = _SonioxSession(connection, self, numpy)
            session._start_keepalive()
            try:
                yield session
            finally:
                await session._stop_keepalive()
                with suppress(Exception):
                    # An empty frame ends the stream.
                    await session._send(b"")


class _SonioxSession(_TimelineSession):
    _provider = "Soniox transcription"

    def __init__(self, connection: Any, model: SonioxSTT, numpy: Any) -> None:
        super().__init__(connection, model.finalize_timeout, model.keepalive_interval, join="")
        self._numpy = numpy

    def _audio_payload(self, audio: bytes) -> bytes:
        return _to_16k(self._numpy, audio)

    def _keepalive_payload(self) -> str:
        return json.dumps({"type": "keepalive"})

    def _finalize_payload(self) -> str:
        return json.dumps({"type": "finalize"})

    def _parse(self, message: Any) -> List[Transcript]:
        event = json.loads(message)
        if event.get("error_code") is not None or event.get("error_type"):
            raise RuntimeError(
                f"Soniox transcription: {event.get('error_type') or event.get('error_code')}: "
                f"{event.get('error_message', 'request failed')} (request {event.get('request_id')})"
            )
        # Final tokens arrive once; non-final tokens are re-sent and revised in
        # each message, so they replace the previous tail.
        finals: Dict[int, str] = {}
        interims: Dict[int, str] = {}
        for token in event.get("tokens") or []:
            text = token.get("text") or ""
            if not text or text in _MARKERS:
                continue
            turn_id = self._timeline.turn_at(float(token.get("start_ms") or 0) / 1000)
            if turn_id is None:
                continue
            target = finals if token.get("is_final") else interims
            target[turn_id] = target.get(turn_id, "") + text
        stale = [turn_id for turn_id in self._timeline.interim_turns() if turn_id not in interims]
        transcripts: List[Optional[Transcript]] = [
            self._timeline.add_final(turn_id, text) for turn_id, text in finals.items()
        ]
        transcripts += [self._timeline.set_interim(turn_id, text) for turn_id, text in interims.items()]
        transcripts += [self._timeline.set_interim(turn_id, "") for turn_id in stale]
        processed = event.get("final_audio_proc_ms")
        if processed is not None:
            self._finalized_through = max(self._finalized_through, float(processed) / 1000)
        # One message can update a turn's finals and its tail; report only the latest text.
        latest: Dict[int, Transcript] = {}
        for transcript in transcripts:
            if transcript is not None:
                latest[transcript.turn_id] = transcript
        return list(latest.values())
