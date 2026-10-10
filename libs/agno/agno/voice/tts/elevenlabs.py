"""Incremental text and audio streaming on a reusable ElevenLabs WebSocket."""

import asyncio
import base64
import json
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from os import getenv
from typing import Any, AsyncGenerator, AsyncIterator, Dict, List, Optional, Tuple
from urllib.parse import quote, urlencode
from uuid import uuid4

from agno.voice.base import SAMPLE_RATE, SpeechChunk, TTSModel, TTSSession
from agno.voice.tts.cartesia import _TextContexts

_SAMPLES_PER_MS = SAMPLE_RATE // 1000
# The same default voice as ElevenLabsTools.
_DEFAULT_VOICE = "JBFqnCBsd6RMkjVDRZzb"


@dataclass
class ElevenLabsTTS(TTSModel):
    """Send agent tokens to an ElevenLabs multi-context speech stream.

    A WebSocket is opened once per voice call and reused between replies, with
    one context per reply so an interruption only closes that reply. Character
    timings let playback acknowledgments track which words were heard.
    ``voice`` is an ElevenLabs voice ID; otherwise ``ELEVEN_LABS_VOICE_ID`` or the
    same default voice as ``ElevenLabsTools`` is used. The key comes from
    ``ELEVEN_LABS_API_KEY``, the same variable as ``ElevenLabsTools``.
    """

    voice: str = ""
    id: str = "eleven_flash_v2_5"
    language: Optional[str] = None
    voice_settings: Optional[Dict[str, Any]] = None
    chunk_length_schedule: Optional[List[int]] = None
    api_key: str = field(default="", repr=False)
    base_url: str = "wss://api.elevenlabs.io/v1/text-to-speech"
    connect_timeout: float = 15.0
    response_timeout: float = 30.0
    # Seconds the socket may stay idle between replies; ElevenLabs allows 180.
    inactivity_timeout: int = 180

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("The ElevenLabs model id must not be empty.")
        if self.connect_timeout <= 0 or self.response_timeout <= 0:
            raise ValueError("ElevenLabs timeouts must be positive.")
        if not 1 <= self.inactivity_timeout <= 180:
            raise ValueError("inactivity_timeout must be between 1 and 180 seconds.")
        if self.chunk_length_schedule is not None and any(
            not 50 <= value <= 500 for value in self.chunk_length_schedule
        ):
            raise ValueError("chunk_length_schedule values must be between 50 and 500.")

    def _url(self, voice: str) -> str:
        params: Dict[str, Any] = {
            "model_id": self.id,
            "output_format": f"pcm_{SAMPLE_RATE}",
            "inactivity_timeout": self.inactivity_timeout,
        }
        if self.language:
            params["language_code"] = self.language
        return f"{self.base_url.rstrip('/')}/{quote(voice, safe='')}/multi-stream-input?{urlencode(params)}"

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[TTSSession]:
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:
            raise ImportError("ElevenLabsTTS requires `pip install 'websockets>=13'`.") from exc
        # ELEVEN_LABS_* matches ElevenLabsTools; ELEVENLABS_* is ElevenLabs' own naming.
        api_key = self.api_key or getenv("ELEVEN_LABS_API_KEY") or getenv("ELEVENLABS_API_KEY")
        if not api_key:
            raise ValueError("Set ELEVEN_LABS_API_KEY or pass api_key to ElevenLabsTTS.")
        voice = self.voice or getenv("ELEVEN_LABS_VOICE_ID") or getenv("ELEVENLABS_VOICE_ID") or _DEFAULT_VOICE
        url = self._url(voice)

        async def open_socket() -> Any:
            return await connect(
                url,
                additional_headers={"xi-api-key": api_key},
                open_timeout=self.connect_timeout,
                close_timeout=2,
                max_size=2**24,
                max_queue=16,
            )

        session = _ElevenLabsSession(open_socket, self)
        session._connection = await open_socket()
        try:
            yield session
        finally:
            await session._close()


class _ElevenLabsSession(TTSSession):
    def __init__(self, open_socket: Any, model: ElevenLabsTTS) -> None:
        self._open_socket = open_socket
        self._model = model
        self._connection: Any = None
        self._lock = asyncio.Lock()

    async def _ensure_open(self) -> None:
        from websockets.protocol import State

        # A long silence can outlast the socket's inactivity timeout.
        if self._connection is None or self._connection.state is not State.OPEN:
            if self._connection is not None:
                with suppress(Exception):
                    await self._connection.close()
            self._connection = await self._open_socket()

    async def _close(self) -> None:
        if self._connection is None:
            return
        with suppress(Exception):
            await asyncio.wait_for(self._connection.send(json.dumps({"close_socket": True})), timeout=1)
        with suppress(Exception):
            await self._connection.close()

    async def _synthesize(self, text: AsyncIterator[str]) -> AsyncIterator[SpeechChunk]:
        # Responses still arriving for a closed context are discarded by ID.
        async with self._lock:
            tokens = _TextContexts(text)
            samples = 0
            try:
                while True:
                    first = await tokens._next()
                    if first is None:
                        return
                    await self._ensure_open()
                    offset = samples
                    stream = self._synthesize_context(tokens._segment(first))
                    try:
                        async for chunk in stream:
                            samples += len(chunk.audio) // 2
                            yield SpeechChunk(
                                audio=chunk.audio,
                                text=chunk.text,
                                end_sample=offset + chunk.end_sample if chunk.end_sample is not None else None,
                            )
                    finally:
                        await stream.aclose()
            finally:
                await tokens._close()

    def _context_start(self, context_id: str) -> Dict[str, Any]:
        message: Dict[str, Any] = {"text": " ", "context_id": context_id}
        if self._model.voice_settings:
            message["voice_settings"] = self._model.voice_settings
        if self._model.chunk_length_schedule:
            message["generation_config"] = {"chunk_length_schedule": self._model.chunk_length_schedule}
        return message

    async def _synthesize_context(self, text: AsyncIterator[str]) -> AsyncGenerator[SpeechChunk, None]:
        context_id = str(uuid4())
        connection = self._connection
        started = False

        async def send(message: Dict[str, Any]) -> None:
            await connection.send(json.dumps(message))

        async def send_text() -> bool:
            nonlocal started
            buffer = ""
            async for delta in text:
                buffer += delta
                # Send whole words; each chunk must end with a single space.
                cut = max(buffer.rfind(" "), buffer.rfind("\n"))
                if cut < 0:
                    continue
                words, buffer = buffer[: cut + 1].strip(), buffer[cut + 1 :]
                if words:
                    if not started:
                        started = True
                        await send(self._context_start(context_id))
                    await send({"text": words + " ", "context_id": context_id})
            if buffer.strip():
                if not started:
                    started = True
                    await send(self._context_start(context_id))
                await send({"text": buffer.strip() + " ", "context_id": context_id})
            if started:
                await send({"context_id": context_id, "flush": True})
            return started

        sender = asyncio.create_task(send_text())
        receiver = asyncio.create_task(connection.recv())
        sending = True
        pending_byte = b""
        received = 0
        word = ""
        word_end = 0
        try:
            while True:
                waiting = {receiver, sender} if sending else {receiver}
                done, _ = await asyncio.wait(
                    waiting, timeout=self._model.response_timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if not done:
                    raise TimeoutError("ElevenLabs did not produce audio within response_timeout.")
                if sender in done:
                    sending = False
                    if not sender.result():
                        return
                if receiver not in done:
                    continue
                event = json.loads(receiver.result())
                receiver = asyncio.create_task(connection.recv())
                if event.get("contextId") not in (None, context_id):
                    continue
                if event.get("error"):
                    raise RuntimeError(f"ElevenLabs speech: {event.get('message') or event['error']}")
                chunk_start = received
                if event.get("audio"):
                    audio = pending_byte + base64.b64decode(event["audio"], validate=True)
                    whole = len(audio) - len(audio) % 2
                    pending_byte = audio[whole:]
                    received += whole // 2
                    if whole:
                        yield SpeechChunk(audio=audio[:whole])
                # Character timings are relative to the chunk they arrive with.
                alignment = event.get("alignment") or event.get("normalizedAlignment")
                if alignment:
                    marks, word, word_end = _words(alignment, chunk_start, word, word_end)
                    for mark, end in marks:
                        yield SpeechChunk(text=mark, end_sample=end)
                if event.get("isFinal") or event.get("is_final"):
                    if pending_byte:
                        raise RuntimeError("ElevenLabs returned an incomplete PCM16 sample.")
                    if word:
                        yield SpeechChunk(text=word, end_sample=word_end)
                    return
        finally:
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
            if started:
                # Free the context slot, or stop generation after an interruption.
                with suppress(Exception):
                    await asyncio.wait_for(send({"context_id": context_id, "close_context": True}), timeout=1)


def _timed_chars(alignment: Dict[str, Any], chunk_start: int) -> List[Tuple[str, int]]:
    chars = alignment.get("chars") or []
    starts = alignment.get("charStartTimesMs") or []
    durations = alignment.get("charDurationsMs") or []
    return [
        (char, chunk_start + round((float(start) + float(duration)) * _SAMPLES_PER_MS))
        for char, start, duration in zip(chars, starts, durations)
    ]


def _words(
    alignment: Dict[str, Any], chunk_start: int, word: str, word_end: int
) -> Tuple[List[Tuple[str, int]], str, int]:
    """Return words completed in this chunk and the word still being spoken.

    A word can start in one chunk and finish in the next, so the unfinished
    word and its latest end sample carry over between calls.
    """
    marks: List[Tuple[str, int]] = []
    chars = alignment.get("chars") or []
    starts = alignment.get("charStartTimesMs") or []
    durations = alignment.get("charDurationsMs") or []
    for char, start, duration in zip(chars, starts, durations):
        if char.isspace():
            if word:
                marks.append((word, word_end))
                word = ""
        else:
            word += char
            word_end = chunk_start + round((float(start) + float(duration)) * _SAMPLES_PER_MS)
    return marks, word, word_end
