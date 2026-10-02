"""Incremental text and audio streaming on a reusable Cartesia WebSocket."""

import asyncio
import base64
import json
import math
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from os import getenv
from typing import Any, AsyncGenerator, AsyncIterator, Dict, Optional
from urllib.parse import urlencode
from uuid import uuid4

from agno.voice.base import SpeechChunk, TTSModel, TTSSession


@dataclass
class CartesiaTTS(TTSModel):
    """Send agent tokens directly to a streaming speech context.

    A WebSocket is opened once per voice call and reused between replies.
    Word timestamps allow playback acknowledgments to track what was heard.
    API credentials stay on the server.
    """

    id: str = "sonic-3.6"
    voice: str = "db6b0ed5-d5d3-463d-ae85-518a07d3c2b4"
    language: str = "en"
    api_key: str = field(default="", repr=False)
    api_version: str = "2026-08-14"
    base_url: str = "wss://api.cartesia.ai/tts/websocket"
    max_buffer_delay_ms: int = 80
    connect_timeout: float = 15.0
    response_timeout: float = 30.0

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.voice.strip() or not self.language.strip():
            raise ValueError("Cartesia model, voice, and language must not be empty.")
        if self.max_buffer_delay_ms < 0:
            raise ValueError("max_buffer_delay_ms must be nonnegative.")
        if self.connect_timeout <= 0 or self.response_timeout <= 0:
            raise ValueError("Cartesia timeouts must be positive.")

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[TTSSession]:
        try:
            from websockets.asyncio.client import connect
        except ImportError as exc:
            raise ImportError("CartesiaTTS requires `pip install 'websockets>=13'`.") from exc
        api_key = self.api_key or getenv("CARTESIA_API_KEY")
        if not api_key:
            raise ValueError("Set CARTESIA_API_KEY or pass api_key to CartesiaTTS.")
        separator = "&" if "?" in self.base_url else "?"
        url = self.base_url + separator + urlencode({"cartesia_version": self.api_version})

        async def open_socket() -> Any:
            return await connect(
                url,
                additional_headers={"X-API-Key": api_key},
                open_timeout=self.connect_timeout,
                close_timeout=2,
                max_size=2**22,
                max_queue=16,
            )

        session = _CartesiaSession(await open_socket(), self, open_socket)
        try:
            yield session
        finally:
            with suppress(Exception):
                await session._connection.close()


class _CartesiaSession(TTSSession):
    def __init__(self, connection: Any, model: CartesiaTTS, open_socket: Optional[Any] = None) -> None:
        self._connection = connection
        self._model = model
        self._open_socket = open_socket
        self._lock = asyncio.Lock()

    async def _ensure_open(self) -> None:
        from websockets.protocol import State

        # The socket can die while the call is idle, for example a keepalive ping
        # timeout during a long tool run. Reopen it so one dropped connection costs
        # at most the reply in progress, not every reply for the rest of the call.
        if self._open_socket is None or self._connection.state is State.OPEN:
            return
        with suppress(Exception):
            await self._connection.close()
        self._connection = await self._open_socket()

    def _request(self, context_id: str, text: str, continuation: bool) -> Dict[str, Any]:
        return {
            "model_id": self._model.id,
            "voice": self._model.voice,
            "language": self._model.language,
            "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 24000},
            "context_id": context_id,
            "transcript": text,
            "continue": continuation,
            "add_timestamps": True,
            "max_buffer_delay_ms": self._model.max_buffer_delay_ms,
        }

    async def _synthesize(self, text: AsyncIterator[str]) -> AsyncIterator[SpeechChunk]:
        # Cancellation releases the receiver before another reply uses the same
        # socket. Responses still arriving for a cancelled context are discarded.
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

    async def _synthesize_context(self, text: AsyncIterator[str]) -> AsyncGenerator[SpeechChunk, None]:
        context_id = str(uuid4())
        started = False
        completed = False

        async def send_text() -> bool:
            nonlocal started
            async for delta in text:
                if delta:
                    started = True
                    await self._connection.send(json.dumps(self._request(context_id, delta, True)))
            if started:
                await self._connection.send(json.dumps(self._request(context_id, "", False)))
            return started

        sender = asyncio.create_task(send_text())
        receiver = asyncio.create_task(self._connection.recv())
        sending = True
        pending_byte = b""
        try:
            while True:
                waiting = {receiver, sender} if sending else {receiver}
                done, _ = await asyncio.wait(
                    waiting, timeout=self._model.response_timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if not done:
                    raise TimeoutError("Cartesia did not produce audio within response_timeout.")
                if sender in done:
                    sending = False
                    if not sender.result():
                        completed = True
                        return
                if receiver not in done:
                    continue
                event = json.loads(receiver.result())
                if event.get("context_id") not in (None, context_id):
                    receiver = asyncio.create_task(self._connection.recv())
                    continue
                kind = event.get("type")
                if kind == "error":
                    raise RuntimeError(f"Cartesia speech: {event.get('message', 'Speech generation failed')}")
                if kind == "chunk":
                    audio = pending_byte + base64.b64decode(event["data"], validate=True)
                    whole = len(audio) - len(audio) % 2
                    pending_byte = audio[whole:]
                    if whole:
                        yield SpeechChunk(audio=audio[:whole])
                elif kind == "timestamps":
                    timestamps = event["word_timestamps"]
                    for word, end in zip(timestamps["words"], timestamps["end"]):
                        if not math.isfinite(end) or end < 0:
                            raise RuntimeError("Cartesia returned invalid word timestamps.")
                        yield SpeechChunk(text=word, end_sample=round(end * 24000))
                elif kind == "done":
                    if pending_byte:
                        raise RuntimeError("Cartesia returned an incomplete PCM16 sample.")
                    completed = True
                    return
                receiver = asyncio.create_task(self._connection.recv())
        finally:
            sender.cancel()
            receiver.cancel()
            await asyncio.gather(sender, receiver, return_exceptions=True)
            if started and not completed:
                with suppress(Exception):
                    await asyncio.wait_for(
                        self._connection.send(json.dumps({"context_id": context_id, "cancel": True})), timeout=1
                    )


class _TextContexts:
    """Finish contexts across tool pauses before Cartesia expires them.

    A pending token read survives the pause, so a slow tool doesn't lose its
    result. Each subsequent context's word timings are offset by prior audio.
    """

    def __init__(self, text: AsyncIterator[str]) -> None:
        self._text = text.__aiter__()
        self._pending: Optional[asyncio.Future] = None
        self._exhausted = False

    async def _next(self, timeout: Optional[float] = None) -> Optional[str]:
        while not self._exhausted:
            if self._pending is None:
                self._pending = asyncio.ensure_future(self._text.__anext__())
            done, _ = await asyncio.wait({self._pending}, timeout=timeout)
            if not done:
                raise asyncio.TimeoutError
            try:
                delta = self._pending.result()
            except StopAsyncIteration:
                self._exhausted = True
                return None
            finally:
                self._pending = None
            if delta:
                return delta
        return None

    async def _segment(self, first: str) -> AsyncIterator[str]:
        yield first
        while True:
            try:
                # Contexts expire a second after their last audio output. End
                # explicitly when input pauses, then open another when it resumes.
                delta = await self._next(timeout=0.75)
            except asyncio.TimeoutError:
                return
            if delta is None:
                return
            yield delta

    async def _close(self) -> None:
        if self._pending is not None:
            self._pending.cancel()
            await asyncio.gather(self._pending, return_exceptions=True)
