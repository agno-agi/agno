"""Speak streamed agent text one phrase at a time for providers that need whole text."""

import asyncio
import re
from abc import abstractmethod
from typing import AsyncIterator, Optional

from agno.voice.base import SpeechChunk, TTSSession


class _PhraseSession(TTSSession):
    """Synthesize bounded phrases in order while the agent keeps generating.

    For speech APIs that need each request's full text up front. Each phrase is
    marked as spoken once its audio has been sent, so playback acknowledgments
    can still track what was heard.
    """

    _provider = "Speech"

    def __init__(self, max_phrase_chars: int, max_phrase_delay_ms: int) -> None:
        self._max_phrase_chars = max_phrase_chars
        self._max_phrase_delay = max_phrase_delay_ms / 1000

    @abstractmethod
    def _stream_phrase(self, phrase: str) -> AsyncIterator[bytes]:
        """Yield raw PCM16 bytes for one phrase; chunks need not align to samples."""

    async def _synthesize(self, text: AsyncIterator[str]) -> AsyncIterator[SpeechChunk]:
        # Continue consuming agent tokens while the preceding phrase is spoken.
        # The bounded queue applies backpressure if speech falls behind the LLM.
        phrases: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=8)

        async def collect() -> None:
            async for phrase in _phrases(text, self._max_phrase_chars, self._max_phrase_delay):
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
                pending_byte = b""
                stream = self._stream_phrase(phrase)
                try:
                    async for data in stream:
                        audio = pending_byte + data
                        whole = len(audio) - len(audio) % 2
                        pending_byte = audio[whole:]
                        if whole:
                            samples += whole // 2
                            yield SpeechChunk(audio=audio[:whole])
                finally:
                    close = getattr(stream, "aclose", None)
                    if close is not None:
                        await close()
                if pending_byte:
                    raise RuntimeError(f"{self._provider} returned an incomplete PCM16 sample.")
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
