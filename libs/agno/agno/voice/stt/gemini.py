"""Gemini Live transcription over a persistent WebSocket."""

import asyncio
import base64
import json
import time
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from os import getenv
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import quote

from agno.voice.base import FRAME_SAMPLES, STTModel, STTSession, Transcript
from agno.voice.stt._turns import _TimelineSession, _to_16k

# Google recommends sending about 100 ms of audio per message.
_FRAMES_PER_MESSAGE = 3


@dataclass
class GeminiLiveSTT(STTModel):
    """Stream microphone audio to Gemini Live transcription.

    Without ``languages``, the model detects the spoken language, including
    speakers who switch languages; BCP-47 codes such as ``["fr-FR"]`` bias it
    toward expected languages. ``mode="SMART"`` removes filler words and
    formats text. ``vocabulary`` biases recognition toward names and terms.
    Reads ``GOOGLE_API_KEY`` or ``GEMINI_API_KEY``.

    Gemini's own voice activity detection stays on, and each turn the pipe
    commits is finalized immediately with ``audioStreamEnd``. Sessions are
    renewed between turns before Google's ten-minute streaming limit.
    """

    id: str = "gemini-3.5-transcribe-live"
    languages: Optional[List[str]] = None
    mode: str = "VERBATIM"
    vocabulary: Optional[List[str]] = None
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: str = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
    connect_timeout: float = 15.0
    # Without word timestamps, a committed turn whose final transcript does not
    # arrive in time falls back to the text received so far.
    finalize_timeout: float = 2.0
    session_seconds: float = 540.0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("The Gemini transcription model id must not be empty.")
        if self.mode not in ("VERBATIM", "SMART"):
            raise ValueError("mode must be VERBATIM or SMART.")
        if self.languages is not None and any(not code.strip() for code in self.languages):
            raise ValueError("languages must not contain empty codes.")
        if self.connect_timeout <= 0 or self.finalize_timeout <= 0:
            raise ValueError("Gemini timeouts must be positive.")
        if not 0 < self.session_seconds < 600:
            raise ValueError("session_seconds must be under Google's 600-second session limit.")

    def _setup(self) -> Dict[str, Any]:
        transcription: Dict[str, Any] = {"mode": self.mode}
        if self.languages:
            transcription["languageCodes"] = self.languages
        if self.vocabulary:
            transcription["customVocabulary"] = [term for term in self.vocabulary if term.strip()]
        return {
            "setup": {
                "model": f"models/{self.id}",
                "generationConfig": {"responseModalities": ["TEXT"]},
                "inputAudioTranscription": transcription,
            }
        }

    async def _open(self, api_key: str) -> Any:
        from websockets.asyncio.client import connect

        connection = await connect(
            f"{self.base_url}?key={quote(api_key, safe='')}",
            open_timeout=self.connect_timeout,
            close_timeout=2,
            max_size=2**22,
        )
        try:
            await connection.send(json.dumps(self._setup()))

            # Do not report readiness before Google accepts the setup.
            async def wait_until_ready() -> None:
                while True:
                    message = json.loads(await connection.recv())
                    if "setupComplete" in message:
                        return

            await asyncio.wait_for(wait_until_ready(), timeout=self.connect_timeout)
        except BaseException:
            with suppress(Exception):
                await connection.close()
            raise
        return connection

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[STTSession]:
        try:
            import numpy
            import websockets  # noqa: F401
        except ImportError as exc:
            raise ImportError("GeminiLiveSTT requires `pip install 'websockets>=13' numpy`.") from exc
        api_key = self.api_key or getenv("GOOGLE_API_KEY") or getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Set GOOGLE_API_KEY or pass api_key to GeminiLiveSTT.")
        session = _GeminiLiveSession(await self._open(api_key), self, api_key, numpy)
        try:
            yield session
        finally:
            with suppress(Exception):
                await session._connection.close()


class _GeminiLiveSession(_TimelineSession):
    _provider = "Gemini transcription"

    def __init__(self, connection: Any, model: GeminiLiveSTT, api_key: str, numpy: Any) -> None:
        # Gemini documents no keepalive message, so none is started.
        super().__init__(connection, model.finalize_timeout, keepalive_interval=1.0, join=" ")
        self._model = model
        self._api_key = api_key
        self._numpy = numpy
        self._opened_at = time.monotonic()
        self._expiring = False
        self._buffer = b""

    def _audio_payload(self, audio: bytes) -> bytes:
        return audio

    def _keepalive_payload(self) -> str:
        return ""

    def _finalize_payload(self) -> str:
        return json.dumps({"realtimeInput": {"audioStreamEnd": True}})

    def _audio_message(self, audio: bytes) -> str:
        data = base64.b64encode(_to_16k(self._numpy, audio)).decode("ascii")
        return json.dumps({"realtimeInput": {"audio": {"data": data, "mimeType": "audio/pcm;rate=16000"}}})

    async def _renew_if_due(self, turn_id: int) -> None:
        # Renew only between turns: no other turn may still be in flight.
        due = self._expiring or time.monotonic() - self._opened_at > self._model.session_seconds
        if not due or self._timeline.open_turns() != [turn_id]:
            return
        old = self._connection
        self._connection = await self._model._open(self._api_key)
        self._opened_at = time.monotonic()
        self._expiring = False
        self._wake.set()
        with suppress(Exception):
            await old.close()

    async def _send_audio(self, audio: bytes, turn_id: int) -> None:
        if len(audio) % 2:
            raise ValueError("Transcription audio must contain complete PCM16 samples.")
        if not audio:
            return
        first = turn_id not in self._timeline.open_turns()
        self._timeline.add_audio(turn_id, len(audio) // 2)
        if first:
            await self._renew_if_due(turn_id)
        self._buffer += audio
        if len(self._buffer) >= _FRAMES_PER_MESSAGE * FRAME_SAMPLES * 2:
            await self._flush()

    async def _flush(self) -> None:
        if self._buffer:
            audio, self._buffer = self._buffer, b""
            await self._send(self._audio_message(audio))

    async def _commit(self, turn_id: int) -> None:
        await self._flush()
        await super()._commit(turn_id)

    def _parse(self, message: Any) -> List[Transcript]:
        event = json.loads(message)
        if "goAway" in event:
            # Renew before the next turn instead of losing this connection mid-turn.
            self._expiring = True
            return []
        content = event.get("serverContent") or {}
        turns = self._timeline.open_turns()
        if not turns:
            return []
        transcripts: List[Optional[Transcript]] = []
        interim = (content.get("interimInputTranscription") or {}).get("text")
        if interim is not None:
            # Partial text belongs to the speech still being spoken.
            transcripts.append(self._timeline.set_interim(turns[-1], interim.strip()))
        final = (content.get("inputTranscription") or {}).get("text")
        if final is not None:
            # Final segments arrive in order, so they belong to the oldest open turn.
            oldest = turns[0]
            transcripts.append(self._timeline.add_final(oldest, final.strip()))
            if self._timeline.is_committed(oldest):
                self._finalized_through = max(self._finalized_through, self._timeline.end_of(oldest))
        return [transcript for transcript in transcripts if transcript is not None]
