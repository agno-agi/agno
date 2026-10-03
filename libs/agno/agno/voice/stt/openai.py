"""Persistent OpenAI transcription sessions with explicit language hints."""

import asyncio
import base64
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Deque, Dict, List, Optional, Set

from agno.voice.base import STTModel, STTSession, Transcript


@dataclass
class OpenAIRealtimeSTT(STTModel):
    """Stream microphone audio and receive incremental transcripts.

    ``gpt-live-transcribe`` emits text while audio arrives. Older transcription
    models can be selected explicitly, but may wait for a committed turn.
    ``async_client`` may reuse an existing OpenAI SDK client; it remains owned
    by the caller. Otherwise, each voice call owns and closes its own client.
    """

    id: str = "gpt-live-transcribe"
    language: Optional[str] = "en"
    languages: Optional[List[str]] = None
    delay: Optional[str] = "low"
    prompt: Optional[str] = None
    keywords: Optional[List[str]] = None
    noise_reduction: Optional[str] = "near_field"
    api_key: Optional[str] = field(default=None, repr=False)
    base_url: Optional[str] = None
    async_client: Optional[Any] = field(default=None, repr=False)
    connect_timeout: float = 15.0

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("The transcription model id must not be empty.")
        if self.connect_timeout <= 0:
            raise ValueError("connect_timeout must be positive.")
        if self.delay not in (None, "minimal", "low", "medium", "high", "xhigh"):
            raise ValueError("delay must be minimal, low, medium, high, xhigh, or None.")
        if self.noise_reduction not in (None, "near_field", "far_field"):
            raise ValueError("noise_reduction must be near_field, far_field, or None.")
        if self.languages is not None and (not self.languages or any(not value.strip() for value in self.languages)):
            raise ValueError("languages must contain at least one nonempty language code.")

    def _session_config(self) -> Dict[str, Any]:
        transcription: Dict[str, Any] = {"model": self.id}
        if self.id.startswith(("gpt-live-transcribe", "gpt-transcribe")):
            languages = self.languages if self.languages is not None else ([self.language] if self.language else None)
            if languages:
                transcription["languages"] = languages
        elif self.languages is not None:
            raise ValueError("Multiple language hints require gpt-live-transcribe or gpt-transcribe.")
        elif self.language:
            transcription["language"] = self.language
        if self.delay and self.id.startswith(("gpt-live-transcribe", "gpt-realtime-whisper")):
            transcription["delay"] = self.delay
        if self.prompt:
            transcription["prompt"] = self.prompt
        if self.keywords:
            transcription["keywords"] = self.keywords
        return {
            "type": "transcription",
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": 24000},
                    "transcription": transcription,
                    "turn_detection": None,
                    "noise_reduction": {"type": self.noise_reduction} if self.noise_reduction else None,
                }
            },
        }

    @asynccontextmanager
    async def _connect(self) -> AsyncIterator[STTSession]:
        config = self._session_config()
        client: Any = self.async_client
        owned = client is None
        if owned:
            try:
                from openai import AsyncOpenAI
            except ImportError as exc:
                raise ImportError("OpenAIRealtimeSTT requires `pip install 'agno[openai]'`.") from exc
            client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        try:
            async with client.realtime.connect(extra_query={"intent": "transcription"}) as connection:
                await connection.session.update(session=config)

                # Do not announce readiness before the server accepts the model
                # and language settings. There is only one receiver at a time.
                async def wait_until_ready() -> None:
                    while True:
                        event = await connection.recv()
                        if event.type == "error":
                            raise RuntimeError(f"OpenAI transcription: {event.error.message}")
                        if event.type in ("session.updated", "transcription_session.updated"):
                            return

                await asyncio.wait_for(wait_until_ready(), timeout=self.connect_timeout)
                yield _OpenAIRealtimeSession(connection)
        finally:
            if owned:
                await client.close()


class _OpenAIRealtimeSession(STTSession):
    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._unbound: Deque[int] = deque()
        self._committing: Deque[int] = deque()
        self._turns: Set[int] = set()
        self._items: Dict[str, int] = {}
        self._partials: Dict[str, str] = {}
        self._audio_bytes: Dict[int, int] = {}
        self._acknowledged: Set[str] = set()
        self._completed: Set[str] = set()

    async def _send_audio(self, audio: bytes, turn_id: int) -> None:
        if len(audio) % 2:
            raise ValueError("Transcription audio must contain complete PCM16 samples.")
        if not audio:
            return
        if turn_id not in self._turns:
            self._turns.add(turn_id)
            self._unbound.append(turn_id)
        self._audio_bytes[turn_id] = self._audio_bytes.get(turn_id, 0) + len(audio)
        await self._connection.input_audio_buffer.append(audio=base64.b64encode(audio).decode("ascii"))

    async def _commit(self, turn_id: int) -> None:
        size = self._audio_bytes.pop(turn_id, 0)
        if not size:
            raise ValueError("Cannot commit a turn without microphone audio.")
        # The Realtime API requires at least 100 ms in a committed buffer.
        if size < 4800:
            await self._connection.input_audio_buffer.append(audio=base64.b64encode(bytes(4800 - size)).decode("ascii"))
        self._committing.append(turn_id)
        await self._connection.input_audio_buffer.commit()

    def _bind_item(self, item_id: str) -> int:
        if item_id not in self._items:
            if not self._unbound:
                raise RuntimeError("Received transcription for an unknown audio turn.")
            self._items[item_id] = self._unbound.popleft()
        return self._items[item_id]

    def _release_item(self, item_id: str) -> None:
        if item_id in self._acknowledged and item_id in self._completed:
            self._turns.discard(self._items.pop(item_id))
            self._acknowledged.remove(item_id)
            self._completed.remove(item_id)

    async def _events(self) -> AsyncIterator[Transcript]:
        async for event in self._connection:
            if event.type == "error":
                raise RuntimeError(f"OpenAI transcription: {event.error.message}")
            if event.type == "input_audio_buffer.committed":
                if not self._committing:
                    raise RuntimeError("Received an unexpected transcription commit.")
                turn_id = self._committing.popleft()
                if event.item_id in self._items:
                    if self._items[event.item_id] != turn_id:
                        raise RuntimeError("Transcription turn order does not match committed audio.")
                else:
                    self._items[event.item_id] = turn_id
                    self._unbound.remove(turn_id)
                self._acknowledged.add(event.item_id)
                self._release_item(event.item_id)
            elif event.type == "conversation.item.input_audio_transcription.delta":
                if event.item_id in self._completed:
                    continue
                turn_id = self._bind_item(event.item_id)
                text = self._partials.get(event.item_id, "") + event.delta
                self._partials[event.item_id] = text
                yield Transcript(turn_id=turn_id, text=text)
            elif event.type == "conversation.item.input_audio_transcription.completed":
                turn_id = self._bind_item(event.item_id)
                self._partials.pop(event.item_id, None)
                # Keep the association until both messages arrive. A final
                # transcript can be delivered before the commit acknowledgement.
                self._completed.add(event.item_id)
                self._release_item(event.item_id)
                yield Transcript(turn_id=turn_id, text=event.transcript.strip(), is_final=True)
            elif event.type == "conversation.item.input_audio_transcription.failed":
                raise RuntimeError(f"OpenAI transcription: {event.error.message}")
        raise RuntimeError("OpenAI transcription disconnected before the voice call ended.")
