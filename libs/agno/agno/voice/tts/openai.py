"""OpenAI streaming audio output with bounded phrase buffering."""

import asyncio
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional

from agno.voice.base import SpeechChunk, TTSModel, TTSSession


@dataclass
class OpenAITTS(TTSModel):
    """Stream PCM speech for short phrases on a reused OpenAI SDK client.

    The Speech API accepts complete text per request, not incremental input.
    Phrases are bounded by punctuation, length, and time; CartesiaTTS can be
    used when streaming both text input and audio output is required.
    Playback alignment is phrase-level because this API has no word timings.
    """

    id: str = "gpt-4o-mini-tts"
    voice: str = "coral"
    instructions: Optional[str] = None
    speed: float = 1.0
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None
    async_client: Optional[Any] = field(default=None, repr=False)
    max_phrase_chars: int = 160
    max_phrase_delay_ms: int = 200

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.voice.strip():
            raise ValueError("OpenAI speech model and voice must not be empty.")
        if not 0.25 <= self.speed <= 4:
            raise ValueError("speed must be between 0.25 and 4.")
        if self.max_phrase_chars < 16 or self.max_phrase_chars > 4096:
            raise ValueError("max_phrase_chars must be between 16 and 4096.")
        if self.max_phrase_delay_ms <= 0:
            raise ValueError("max_phrase_delay_ms must be positive.")

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[TTSSession]:
        client: Any = self.async_client
        owned = client is None
        if owned:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError("OpenAITTS requires `pip install 'agno[openai]'`.") from exc
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        try:
            yield _OpenAISpeechSession(client, self)
        finally:
            if owned:
                await client.close()


class _OpenAISpeechSession(TTSSession):
    def __init__(self, client: Any, model: OpenAITTS) -> None:
        self._client = client
        self._model = model

    async def _synthesize(self, text: AsyncIterator[str]) -> AsyncIterator[SpeechChunk]:
        # Continue consuming agent tokens while the preceding phrase is spoken.
        # The bounded queue applies backpressure if speech falls behind the LLM.
        phrases: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=8)

        async def collect() -> None:
            async for phrase in _phrases(text, self._model.max_phrase_chars, self._model.max_phrase_delay_ms / 1000):
                await phrases.put(phrase)
            await phrases.put(None)

        producer = asyncio.create_task(collect())
        getter: Optional[asyncio.Task] = None
        samples = 0
        try:
            while True:
                getter = asyncio.create_task(phrases.get())
                done, _ = await asyncio.wait({producer, getter}, return_when=asyncio.FIRST_COMPLETED)
                if producer in done:
                    producer.result()
                phrase = await getter
                if phrase is None:
                    return
                parameters = {
                    "model": self._model.id,
                    "voice": self._model.voice,
                    "input": phrase,
                    "response_format": "pcm",
                    "speed": self._model.speed,
                }
                if self._model.instructions:
                    parameters["instructions"] = self._model.instructions
                pending_byte = b""
                async with self._client.audio.speech.with_streaming_response.create(**parameters) as response:
                    # Native network chunks avoid waiting to fill a large fixed
                    # buffer before forwarding the first audible samples.
                    async for data in response.iter_bytes():
                        audio = pending_byte + data
                        whole = len(audio) - len(audio) % 2
                        pending_byte = audio[whole:]
                        if whole:
                            samples += whole // 2
                            yield SpeechChunk(audio=audio[:whole])
                if pending_byte:
                    raise RuntimeError("OpenAI returned an incomplete PCM16 sample.")
                yield SpeechChunk(text=phrase, end_sample=samples)
        finally:
            producer.cancel()
            if getter is not None:
                getter.cancel()
                await asyncio.gather(getter, return_exceptions=True)
            await asyncio.gather(producer, return_exceptions=True)


def _boundary(text: str, max_chars: int, timed_out: bool = False) -> int:
    # Include non-Latin punctuation so a language change cannot hold an entire
    # response in the buffer. A period inside a decimal is not a boundary.
    match = re.search(r"[.!?。！？।](?:\s|$)|\n", text)
    if match and match.end() <= max_chars:
        return match.end()
    if len(text) >= max_chars:
        split = text.rfind(" ", 0, max_chars + 1)
        return split + 1 if split > 0 else max_chars
    if timed_out and text.strip():
        split = text.rfind(" ")
        return split + 1 if split > 0 else len(text)
    return 0


async def _phrases(text: AsyncIterator[str], max_chars: int, max_delay: float) -> AsyncIterator[str]:
    iterator = text.__aiter__()
    pending: Optional[asyncio.Future] = None
    buffer = ""
    deadline: Optional[float] = None
    exhausted = False
    loop = asyncio.get_running_loop()
    try:
        while not exhausted or buffer:
            cut = _boundary(buffer, max_chars)
            if cut or exhausted:
                cut = cut or len(buffer)
                phrase, buffer = buffer[:cut].strip(), buffer[cut:]
                deadline = loop.time() + max_delay if buffer else None
                if phrase:
                    yield phrase
                continue
            if pending is None:
                pending = asyncio.ensure_future(iterator.__anext__())
            timeout = max(0, deadline - loop.time()) if deadline is not None else None
            done, _ = await asyncio.wait({pending}, timeout=timeout)
            if not done:
                cut = _boundary(buffer, max_chars, timed_out=True)
                phrase, buffer = buffer[:cut].strip(), buffer[cut:]
                deadline = loop.time() + max_delay if buffer else None
                if phrase:
                    yield phrase
                continue
            try:
                delta = pending.result()
            except StopAsyncIteration:
                exhausted = True
            else:
                buffer += delta
                if buffer and deadline is None:
                    deadline = loop.time() + max_delay
            pending = None
    finally:
        if pending is not None:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
