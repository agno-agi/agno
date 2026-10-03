"""The reply side of a voice call: run the agent, speak its reply, handle interruptions."""

import asyncio
import struct
import time
from typing import TYPE_CHECKING, AsyncIterator, Dict, List, Optional, Set

from agno.utils.log import log_error
from agno.voice._channel import _ClientChannel
from agno.voice._listener import _Listener
from agno.voice._state import _PlaybackStalledError, _Reply, describe_interruption
from agno.voice.base import SAMPLE_RATE, TTSSession

if TYPE_CHECKING:
    from agno.voice.pipe import VoicePipe

# Audio is sent in bounded packets for predictable playback and interruption.
_PACKET_BYTES = 4800
# Recent replies are kept to accept the browser's final ACK after a flush.
_KEPT_REPLIES = 4


class _Responder:
    """Answer completed user turns, one reply at a time.

    The agent's text streams into speech as it is generated. Audio is paced by
    the client's playback acknowledgments, which also decide what was heard.
    """

    def __init__(
        self,
        pipe: "VoicePipe",
        tts: TTSSession,
        channel: _ClientChannel,
        listener: _Listener,
        user_id: Optional[str],
        session_id: str,
    ) -> None:
        self._pipe, self._tts, self._channel, self._listener = pipe, tts, channel, listener
        self._user_id, self._session_id = user_id, session_id
        self._tts_lock = asyncio.Lock()
        self._reply_id = 0
        self.current: Optional[_Reply] = None
        self.replies: Dict[int, _Reply] = {}
        # The last interrupted reply, described to the agent on the next turn.
        self._interrupted: Optional[_Reply] = None
        self.tasks: Set[asyncio.Task] = set()
        self._failures: asyncio.Queue = asyncio.Queue()

    # -- Client feedback ------------------------------------------------------

    def on_played(self, reply_id: int, samples: int) -> None:
        reply = self.replies.get(reply_id)
        if reply and reply.played_samples < samples <= reply.sent_samples:
            reply.played_samples = samples
            reply.playback_progress.set()
            reply.update_heard()

    async def on_playback_started(self, reply_id: int) -> None:
        reply = self.replies.get(reply_id)
        if reply is not None and not reply.playback_started and reply.sent_samples:
            reply.playback_started = True
            await self._metric(reply, "total_to_playback")

    async def raise_failures(self) -> None:
        """Surface an error from a reply task so the call can end."""
        raise await self._failures.get()

    # -- Starting and stopping replies -----------------------------------------

    async def _maybe_respond(self) -> None:
        ready = self._listener.take_prompt()
        if ready is None:
            return
        prompt, stopped_at = ready
        if not prompt:
            await self._channel.send("listening")
            return
        message = prompt
        if self._interrupted is not None:
            # Built now rather than at interruption, so final playback ACKs count.
            message = f"{describe_interruption(self._interrupted)}\n\n{prompt}"
            self._interrupted = None
        self._reply_id += 1
        reply = _Reply(self._reply_id, stopped_at, prompt)
        self.current = reply
        self.replies[reply.id] = reply
        for old_id in list(self.replies)[:-_KEPT_REPLIES]:
            del self.replies[old_id]
        reply.task = asyncio.create_task(self._respond(reply, message))
        self.tasks.add(reply.task)
        reply.task.add_done_callback(self._reply_finished)

    def _reply_finished(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            self._failures.put_nowait(task.exception())

    async def _interrupt(self, note: str = "The user interrupted the reply.") -> None:
        reply = self.current
        if reply is None:
            return
        reply.run_cancelled = reply.task is not None and not reply.task.done()
        reply.interrupted = reply.played_samples < reply.sent_samples or reply.run_cancelled
        reply.interruption_note = note
        self.current = None
        reply.update_heard()
        if reply.interrupted:
            self._interrupted = reply
        # Flushing the browser must not wait for a remote model's cancellation cleanup.
        if reply.task is not None and reply.task is not asyncio.current_task():
            reply.task.cancel()
        await self._channel.send("stop_playback", reply_id=reply.id)

    # -- Producing a reply -----------------------------------------------------

    def _is_live(self, reply: _Reply) -> bool:
        return self.current is reply and not reply.interrupted

    async def _send(self, reply: _Reply, kind: str, **data) -> None:
        await self._channel.send_while(lambda: self._is_live(reply), kind, reply_id=reply.id, **data)

    async def _metric(self, reply: _Reply, name: str, start: Optional[float] = None) -> None:
        elapsed_ms = round((time.perf_counter() - (start or reply.stopped_at)) * 1000)
        await self._send(reply, "metric", name=name, ms=elapsed_ms)

    async def _respond(self, reply: _Reply, message: str) -> None:
        if not self._is_live(reply):
            return
        tokens: asyncio.Queue = asyncio.Queue(maxsize=64)
        tasks: List[asyncio.Task] = []
        try:
            await self._send(reply, "reply_started")
            await self._metric(reply, "transcript_final")
            tasks = [
                asyncio.create_task(self._think(reply, message, tokens)),
                asyncio.create_task(self._speak(reply, tokens)),
            ]
            await asyncio.wait_for(asyncio.gather(*tasks), timeout=self._pipe.response_timeout)
            await self._send(reply, "reply_done")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_error(f"Voice reply failed: {type(exc).__name__}: {exc}")
            if self.current is reply:
                await self._interrupt("The reply failed before playback completed.")
                detail = (
                    str(exc) if isinstance(exc, _PlaybackStalledError) else "The voice reply failed. Please try again."
                )
                await self._channel.send("error", fatal=False, message=detail)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _think(self, reply: _Reply, message: str, tokens: asyncio.Queue) -> None:
        """Stream the agent's reply text into ``tokens``; ``None`` marks the end."""
        started_at = time.perf_counter()
        stream = self._pipe.agent.arun(
            message,
            stream=True,
            stream_events=True,
            session_id=self._session_id,
            user_id=self._user_id,
            # A voice call needs memory even when the agent's default leaves it off.
            add_history_to_context=True,
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
                    await self._send(reply, "assistant_delta", text=content)
                    await tokens.put(content)
                elif kind in ("ToolCallStarted", "ToolCallCompleted"):
                    name = getattr(getattr(event, "tool", None), "tool_name", None) or "tool"
                    await self._send(
                        reply, "tool_started" if kind == "ToolCallStarted" else "tool_completed", name=name
                    )
        finally:
            close = getattr(stream, "aclose", None)
            if close is not None:
                await close()
        await tokens.put(None)
        await self._send(reply, "assistant_complete", text=reply.text)

    async def _speak(self, reply: _Reply, tokens: asyncio.Queue) -> None:
        """Synthesize ``tokens`` and send the audio, paced by playback."""
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
        async with self._tts_lock:
            first = True
            stream = self._tts._synthesize(text())
            try:
                async for chunk in stream:
                    if not self._is_live(reply):
                        return
                    if chunk.text is not None and chunk.end_sample is not None:
                        if chunk.end_sample < 0:
                            raise ValueError("Negative speech alignment offset.")
                        reply.marks.append((chunk.end_sample, chunk.text))
                        reply.update_heard()
                    if not chunk.audio:
                        continue
                    if len(chunk.audio) % 2:
                        raise ValueError("TTS returned incomplete PCM16 samples.")
                    if first:
                        first = False
                        await self._metric(reply, "first_audio_sent")
                        await self._metric(reply, "tts_first_audio", synthesis_started)
                    for offset in range(0, len(chunk.audio), _PACKET_BYTES):
                        if not await self._send_audio(reply, chunk.audio[offset : offset + _PACKET_BYTES]):
                            return
            finally:
                close = getattr(stream, "aclose", None)
                if close is not None:
                    await close()
        # Without provider alignment, the complete utterance is the acknowledgement unit.
        if not reply.marks and reply.sent_samples:
            reply.marks.append((reply.sent_samples, reply.text))
            reply.update_heard()

    async def _send_audio(self, reply: _Reply, audio: bytes) -> bool:
        """Send one packet once playback has room for it; False if the reply ended."""
        if not await self._wait_for_playback(reply, len(audio) // 2):
            return False
        # Each packet starts with the reply ID and its sample offset in the reply.
        packet = struct.pack("<II", reply.id, reply.sent_samples) + audio
        if not await self._channel.send_audio_while(lambda: self._is_live(reply), packet):
            return False
        reply.sent_samples += len(audio) // 2
        return True

    async def _wait_for_playback(self, reply: _Reply, next_samples: int) -> bool:
        limit = int(self._pipe.max_playback_buffer_seconds * SAMPLE_RATE)
        while reply.sent_samples + next_samples - reply.played_samples > limit:
            if not self._is_live(reply):
                return False
            # No await between checking the credit and clearing the event: an
            # advancing ACK cannot be lost. Repeated/stale ACKs do not wake us.
            reply.playback_progress.clear()
            try:
                await asyncio.wait_for(reply.playback_progress.wait(), timeout=self._pipe.playback_timeout)
            except asyncio.TimeoutError as exc:
                raise _PlaybackStalledError(
                    "Audio playback stopped responding. Check your audio output and start a new conversation."
                ) from exc
        return self._is_live(reply)
