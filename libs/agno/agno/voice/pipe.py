"""A streaming voice session around an existing Agno agent."""

import asyncio
import json
import math
import re
import struct
import time
from collections import deque
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, AsyncIterator, Deque, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from agno.agent import Agent
from agno.models.message import Message
from agno.voice.base import FRAME_SAMPLES, SAMPLE_RATE, STTModel, STTSession, TTSModel, TTSSession, VAD, VADSession

if TYPE_CHECKING:
    from fastapi import WebSocket


@dataclass
class VoicePipe:
    """Give an existing text agent a streaming microphone and voice.

    Register with ``AgentOS(live_sockets=[pipe])`` to serve it at the WebSocket
    route ``/voice/{id}/pipe``. Clients send PCM16, mono, 24 kHz audio in
    768-sample frames. Each connection owns its speech provider
    sessions, VAD, conversation context, and server-generated agent session ID.
    The agent's model, instructions, and tools are reused without modification.
    """

    agent: Agent
    vad: VAD
    stt_model: STTModel
    tts_model: TTSModel
    id: str = "voice"
    max_history_turns: int = 10
    max_audio_frames: int = 64
    max_utterance_seconds: float = 60.0
    transcription_timeout: float = 15.0
    connection_timeout: float = 30.0
    response_timeout: float = 60.0
    # Limit audio scheduled ahead of acknowledged playback, even when a speech
    # provider generates much faster than the listener consumes it.
    max_playback_buffer_seconds: float = 2.0
    playback_timeout: float = 15.0

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", self.id):
            raise ValueError("VoicePipe id must be a URL-safe name of 1-64 characters.")
        if self.max_history_turns < 1 or self.max_audio_frames < 1:
            raise ValueError("VoicePipe history and audio queue limits must be positive.")
        if (
            min(self.max_utterance_seconds, self.transcription_timeout, self.connection_timeout, self.response_timeout)
            <= 0
        ):
            raise ValueError("VoicePipe timeouts must be positive.")
        if not math.isfinite(self.max_playback_buffer_seconds) or self.max_playback_buffer_seconds < 0.1:
            raise ValueError("max_playback_buffer_seconds must be finite and at least 0.1 seconds.")
        if not math.isfinite(self.playback_timeout) or self.playback_timeout <= 0:
            raise ValueError("playback_timeout must be finite and positive.")
        if self.agent.output_schema is not None:
            raise ValueError("VoicePipe requires an agent with text output; remove its output_schema.")

    async def _serve(
        self, websocket: "WebSocket", user_id: Optional[str] = None, session_id: Optional[str] = None
    ) -> None:
        # AgentOS accepts and authenticates the connection before entering here.
        try:
            async with AsyncExitStack() as stack:
                vad = await asyncio.wait_for(self.vad._create_session(), timeout=self.connection_timeout)
                stack.push_async_callback(vad._close)
                stt = await asyncio.wait_for(
                    stack.enter_async_context(self.stt_model._connect()), timeout=self.connection_timeout
                )
                tts = await asyncio.wait_for(
                    stack.enter_async_context(self.tts_model._connect()), timeout=self.connection_timeout
                )
                await _VoiceSession(self, websocket, vad, stt, tts, user_id, session_id or str(uuid4()))._run()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from starlette.websockets import WebSocketDisconnect

            if not isinstance(exc, WebSocketDisconnect):
                from agno.utils.log import log_error

                log_error(f"Voice session failed: {type(exc).__name__}: {exc}")
                with suppress(Exception):
                    await asyncio.wait_for(
                        websocket.send_json(
                            {
                                "type": "error",
                                "fatal": True,
                                "message": "Voice connection failed. Check the server logs.",
                            }
                        ),
                        timeout=2,
                    )
        finally:
            with suppress(Exception):
                await asyncio.wait_for(websocket.close(), timeout=2)


@dataclass
class _Turn:
    id: int
    started_at: float = field(default_factory=time.perf_counter)
    stopped_at: Optional[float] = None
    text: Optional[str] = None


@dataclass
class _Reply:
    id: int
    stopped_at: float
    assistant: Message
    started_at: float = field(default_factory=time.perf_counter)
    text: str = ""
    sent_samples: int = 0
    played_samples: int = 0
    marks: List[Tuple[int, str]] = field(default_factory=list)
    interrupted: bool = False
    interruption_note: str = "The user interrupted the reply."
    playback_started: bool = False
    playback_progress: asyncio.Event = field(default_factory=asyncio.Event)
    task: Optional[asyncio.Task] = None


class _PlaybackStalledError(TimeoutError):
    """The browser stopped acknowledging audio while the send window was full."""


class _VoiceSession:
    def __init__(
        self,
        pipe: VoicePipe,
        websocket: "WebSocket",
        vad: VADSession,
        stt: STTSession,
        tts: TTSSession,
        user_id: Optional[str],
        session_id: str,
    ) -> None:
        self.pipe, self.ws, self.vad, self.stt, self.tts = pipe, websocket, vad, stt, tts
        self.user_id, self.session_id = user_id, session_id
        self.send_lock, self.tts_lock = asyncio.Lock(), asyncio.Lock()
        self.audio: asyncio.Queue = asyncio.Queue(maxsize=pipe.max_audio_frames)
        self.stt_audio: asyncio.Queue = asyncio.Queue(maxsize=pipe.max_audio_frames)
        self.preroll: Deque[bytes] = deque(maxlen=8)
        self.turns: Dict[int, _Turn] = {}
        self.turn_id, self.reply_id = 0, 0
        self.speaking = False
        self.history: List[Message] = []
        self.current: Optional[_Reply] = None
        self.replies: Dict[int, _Reply] = {}
        self.responses: Set[asyncio.Task] = set()
        self.failures: asyncio.Queue = asyncio.Queue()

    async def _send(self, kind: str, **data: Any) -> None:
        async with self.send_lock:
            await asyncio.wait_for(self.ws.send_json({"type": kind, **data}), timeout=5)

    async def _reply_send(self, reply: _Reply, kind: str, **data: Any) -> None:
        async with self.send_lock:
            if self.current is reply and not reply.interrupted:
                await asyncio.wait_for(self.ws.send_json({"type": kind, "reply_id": reply.id, **data}), timeout=5)

    async def _metric(self, reply: _Reply, name: str, start: Optional[float] = None) -> None:
        await self._reply_send(
            reply, "metric", name=name, ms=round((time.perf_counter() - (start or reply.stopped_at)) * 1000)
        )

    def _update_heard(self, reply: _Reply) -> None:
        heard = " ".join(text for end, text in reply.marks if end <= reply.played_samples).strip()
        if reply.interrupted:
            heard = (heard + f" [{reply.interruption_note}]").strip()
        reply.assistant.content = heard

    async def _interrupt(self, note: str = "The user interrupted the reply.") -> None:
        reply = self.current
        if reply is None:
            return
        reply.interrupted = reply.played_samples < reply.sent_samples or (
            reply.task is not None and not reply.task.done()
        )
        reply.interruption_note = note
        self.current = None
        self._update_heard(reply)
        # Flushing the browser must not wait for a remote model's cancellation cleanup.
        if reply.task is not None and reply.task is not asyncio.current_task():
            reply.task.cancel()
        await self._send("stop_playback", reply_id=reply.id)

    async def _receive(self) -> None:
        while True:
            message = await self.ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            pcm = message.get("bytes")
            if pcm is not None:
                if len(pcm) != FRAME_SAMPLES * 2:
                    raise ValueError("Microphone frames must contain exactly 768 PCM16 mono samples.")
                try:
                    self.audio.put_nowait(pcm)
                except asyncio.QueueFull:
                    raise RuntimeError("Microphone processing cannot keep up; audio queue limit reached.") from None
            elif message.get("text") is not None:
                if len(message["text"]) > 4096:
                    raise ValueError("Voice control message is too large.")
                data = json.loads(message["text"])
                if not isinstance(data, dict):
                    raise ValueError("Voice control message must be an object.")
                kind = data.get("type")
                if kind == "stop":
                    return
                if kind == "ping":
                    await self._send("pong")
                elif kind == "played":
                    rid, samples = data.get("reply_id"), data.get("samples")
                    if type(rid) is not int or type(samples) is not int:
                        raise ValueError("Playback acknowledgement requires integer reply_id and samples.")
                    reply = self.replies.get(rid)
                    if reply and reply.played_samples < samples <= reply.sent_samples:
                        reply.played_samples = samples
                        reply.playback_progress.set()
                        self._update_heard(reply)
                elif kind == "playback_started":
                    rid = data.get("reply_id")
                    reply = self.replies.get(rid) if type(rid) is int else None
                    if reply is not None and not reply.playback_started and reply.sent_samples:
                        reply.playback_started = True
                        await self._metric(reply, "total_to_playback")

    def _queue_audio(self, audio: Optional[bytes], turn_id: int) -> None:
        try:
            self.stt_audio.put_nowait((audio, turn_id))
        except asyncio.QueueFull:
            raise RuntimeError("Speech recognition cannot keep up; audio queue limit reached.") from None

    async def _listen(self) -> None:
        while True:
            pcm = await self.audio.get()
            was_speaking = self.speaking
            if not was_speaking:
                self.preroll.append(pcm)
            event = await self.vad._process(pcm)
            if event == "start" and not was_speaking:
                self.speaking = True
                self.turn_id += 1
                self.turns[self.turn_id] = _Turn(self.turn_id)
                await self._interrupt()
                await self._send("speech_started", turn_id=self.turn_id)
                for frame in self.preroll:
                    self._queue_audio(frame, self.turn_id)
                self.preroll.clear()
            elif was_speaking:
                self._queue_audio(pcm, self.turn_id)
            if event == "stop" and self.speaking:
                self.speaking = False
                self.turns[self.turn_id].stopped_at = time.perf_counter()
                self._queue_audio(None, self.turn_id)
                await self._send("speech_stopped", turn_id=self.turn_id)
                await self._maybe_respond()

    async def _transmit(self) -> None:
        while True:
            audio, turn_id = await self.stt_audio.get()
            if audio is None:
                await self.stt._commit(turn_id)
            else:
                await self.stt._send_audio(audio, turn_id)

    async def _transcripts(self) -> None:
        async for event in self.stt._events():
            turn = self.turns.get(event.turn_id)
            if turn is None or turn.text is not None:
                continue
            await self._send(
                "transcript" if event.is_final else "transcript_delta", turn_id=event.turn_id, text=event.text
            )
            if event.is_final:
                turn.text = event.text.strip()
                await self._maybe_respond()
        raise RuntimeError("Speech recognition disconnected.")

    async def _maybe_respond(self) -> None:
        if self.speaking or not self.turns:
            return
        turns = list(self.turns.values())
        if any(turn.text is None or turn.stopped_at is None for turn in turns):
            return
        prompt = " ".join(turn.text for turn in turns if turn.text).strip()
        stopped_at = turns[-1].stopped_at
        self.turns.clear()
        if not prompt:
            await self._send("listening")
            return
        self.history = self.history[-self.pipe.max_history_turns * 2 :]
        self.history.append(Message(role="user", content=prompt))
        context = [Message(role=m.role, content=m.content) for m in self.history if m.content]
        assistant = Message(role="assistant", content="")
        self.history.append(assistant)
        self.reply_id += 1
        reply = _Reply(self.reply_id, stopped_at or time.perf_counter(), assistant)
        self.current = reply
        self.replies[reply.id] = reply
        # Retain recent replies to accept the browser's final ACK after a flush.
        for old_id in list(self.replies)[:-4]:
            del self.replies[old_id]
        reply.task = asyncio.create_task(self._respond(reply, context))
        self.responses.add(reply.task)
        reply.task.add_done_callback(self._response_finished)

    def _response_finished(self, task: asyncio.Task) -> None:
        self.responses.discard(task)
        if not task.cancelled():
            error = task.exception()
            if error is not None:
                self.failures.put_nowait(error)

    async def _response_errors(self) -> None:
        raise await self.failures.get()

    async def _respond(self, reply: _Reply, context: List[Message]) -> None:
        if self.current is not reply or reply.interrupted:
            return
        tokens: asyncio.Queue = asyncio.Queue(maxsize=64)
        tasks: List[asyncio.Task] = []
        try:
            await self._reply_send(reply, "reply_started")
            await self._metric(reply, "transcript_final")
            tasks = [
                asyncio.create_task(self._think(reply, context, tokens)),
                asyncio.create_task(self._speak(reply, tokens)),
            ]
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=self.pipe.response_timeout)
            await self._reply_send(reply, "reply_done")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from agno.utils.log import log_error

            log_error(f"Voice reply failed: {type(exc).__name__}: {exc}")
            if self.current is reply:
                await self._interrupt("The reply failed before playback completed.")
                message = (
                    str(exc) if isinstance(exc, _PlaybackStalledError) else "The voice reply failed. Please try again."
                )
                await self._send("error", fatal=False, message=message)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _think(self, reply: _Reply, context: List[Message], tokens: asyncio.Queue) -> None:
        started_at = time.perf_counter()
        stream = self.pipe.agent.arun(
            context,
            stream=True,
            stream_events=True,
            session_id=self.session_id,
            user_id=self.user_id,
            # Voice history is based on playback, rather than unplayed generated text.
            add_history_to_context=False,
        )
        try:
            async for event in stream:
                kind = getattr(event, "event", "")
                content = getattr(event, "content", None)
                if kind == "RunError":
                    raise RuntimeError("Agent run failed.")
                if kind == "RunContent" and isinstance(content, str) and content:
                    if not reply.text:
                        await self._metric(reply, "first_token")
                        await self._metric(reply, "agent_first_token", started_at)
                    reply.text += content
                    await self._reply_send(reply, "assistant_delta", text=content)
                    await tokens.put(content)
                elif kind in ("ToolCallStarted", "ToolCallCompleted"):
                    tool = getattr(event, "tool", None)
                    name = getattr(tool, "tool_name", None) or "tool"
                    await self._reply_send(
                        reply, "tool_started" if kind == "ToolCallStarted" else "tool_completed", name=name
                    )
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        await tokens.put(None)
        await self._reply_send(reply, "assistant_complete", text=reply.text)

    async def _wait_for_playback(self, reply: _Reply, next_samples: int) -> bool:
        limit = int(self.pipe.max_playback_buffer_seconds * SAMPLE_RATE)
        while reply.sent_samples + next_samples - reply.played_samples > limit:
            if self.current is not reply or reply.interrupted:
                return False
            # No await between checking the credit and clearing the event: an
            # advancing ACK cannot be lost. Repeated/stale ACKs do not wake us.
            reply.playback_progress.clear()
            try:
                await asyncio.wait_for(reply.playback_progress.wait(), timeout=self.pipe.playback_timeout)
            except asyncio.TimeoutError as exc:
                raise _PlaybackStalledError(
                    "Audio playback stopped responding. Check your audio output and start a new conversation."
                ) from exc
        return self.current is reply and not reply.interrupted

    async def _speak(self, reply: _Reply, tokens: asyncio.Queue) -> None:
        synthesis_started: Optional[float] = None

        async def text() -> AsyncIterator[str]:
            nonlocal synthesis_started
            while True:
                token = await tokens.get()
                if token is None:
                    return
                if synthesis_started is None:
                    synthesis_started = time.perf_counter()
                yield token

        # A provider session handles one reply at a time, including cancellation cleanup.
        async with self.tts_lock:
            first = True
            stream = self.tts._synthesize(text())
            try:
                async for chunk in stream:
                    if self.current is not reply or reply.interrupted:
                        return
                    if chunk.text is not None and chunk.end_sample is not None:
                        if chunk.end_sample < 0:
                            raise ValueError("Negative speech alignment offset.")
                        reply.marks.append((chunk.end_sample, chunk.text))
                        self._update_heard(reply)
                    if not chunk.audio:
                        continue
                    if len(chunk.audio) % 2:
                        raise ValueError("TTS returned incomplete PCM16 samples.")
                    if first:
                        first = False
                        await self._metric(reply, "first_audio_sent")
                        await self._metric(reply, "tts_first_audio", synthesis_started)
                    # Bound packet sizes for predictable playback and interruption.
                    for offset in range(0, len(chunk.audio), 4800):
                        audio = chunk.audio[offset : offset + 4800]
                        if not await self._wait_for_playback(reply, len(audio) // 2):
                            return
                        async with self.send_lock:
                            if self.current is not reply or reply.interrupted:
                                return
                            await asyncio.wait_for(
                                self.ws.send_bytes(struct.pack("<II", reply.id, reply.sent_samples) + audio), timeout=5
                            )
                            reply.sent_samples += len(audio) // 2
            finally:
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
        # Without provider alignment, the complete utterance is the acknowledgement unit.
        if not reply.marks and reply.sent_samples:
            reply.marks.append((reply.sent_samples, reply.text))
            self._update_heard(reply)

    async def _watchdog(self) -> None:
        while True:
            await asyncio.sleep(0.25)
            now = time.perf_counter()
            for turn in self.turns.values():
                if turn.stopped_at is None and now - turn.started_at > self.pipe.max_utterance_seconds:
                    raise RuntimeError("Maximum continuous speech duration exceeded.")
                if (
                    turn.stopped_at is not None
                    and turn.text is None
                    and now - turn.stopped_at > self.pipe.transcription_timeout
                ):
                    raise TimeoutError("Speech recognition timed out.")

    async def _run(self) -> None:
        await self._send(
            "ready",
            pipe_id=self.pipe.id,
            session_id=self.session_id,
            sample_rate=SAMPLE_RATE,
            frame_samples=FRAME_SAMPLES,
        )
        tasks = [
            asyncio.create_task(self._receive()),
            asyncio.create_task(self._listen()),
            asyncio.create_task(self._transmit()),
            asyncio.create_task(self._transcripts()),
            asyncio.create_task(self._watchdog()),
            asyncio.create_task(self._response_errors()),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            pending = tasks + list(self.responses)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
