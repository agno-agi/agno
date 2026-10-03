"""One voice call: connect the client, the listener, and the responder."""

import asyncio
import json
from typing import TYPE_CHECKING, Any, Dict, Optional

from agno.voice._channel import _ClientChannel
from agno.voice._listener import _Listener
from agno.voice._responder import _Responder
from agno.voice.base import FRAME_SAMPLES, SAMPLE_RATE, STTSession, TTSSession, VADSession

if TYPE_CHECKING:
    from fastapi import WebSocket

    from agno.voice.pipe import VoicePipe

_MAX_CONTROL_MESSAGE_CHARS = 4096


class _VoiceSession:
    """Run one connected call until the client leaves or something fails."""

    def __init__(
        self,
        pipe: "VoicePipe",
        websocket: "WebSocket",
        vad: VADSession,
        stt: STTSession,
        tts: TTSSession,
        user_id: Optional[str],
        session_id: str,
    ) -> None:
        self._pipe, self._ws, self._session_id = pipe, websocket, session_id
        self._channel = _ClientChannel(websocket)
        self._listener = _Listener(
            pipe,
            vad,
            stt,
            self._channel,
            on_speech_started=self._on_speech_started,
            on_turn_ready=self._on_turn_ready,
        )
        self._responder = _Responder(pipe, tts, self._channel, self._listener, user_id, session_id)

    async def _on_speech_started(self) -> None:
        # Speaking over a reply interrupts it.
        await self._responder._interrupt()

    async def _on_turn_ready(self) -> None:
        await self._responder._maybe_respond()

    async def _run(self) -> None:
        await self._channel.send(
            "ready",
            pipe_id=self._pipe.id,
            session_id=self._session_id,
            sample_rate=SAMPLE_RATE,
            frame_samples=FRAME_SAMPLES,
        )
        # Any loop ending, normally or with an error, ends the call.
        tasks = [
            asyncio.create_task(self._receive()),
            asyncio.create_task(self._listener.listen()),
            asyncio.create_task(self._listener.transmit()),
            asyncio.create_task(self._listener.transcripts()),
            asyncio.create_task(self._listener.watchdog()),
            asyncio.create_task(self._responder.raise_failures()),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            pending = tasks + list(self._responder.tasks)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    async def _receive(self) -> None:
        """Route client messages: binary microphone frames and JSON control messages."""
        while True:
            message = await self._ws.receive()
            if message["type"] == "websocket.disconnect":
                return
            pcm = message.get("bytes")
            if pcm is not None:
                if len(pcm) != FRAME_SAMPLES * 2:
                    raise ValueError("Microphone frames must contain exactly 768 PCM16 mono samples.")
                self._listener.accept_frame(pcm)
            elif message.get("text") is not None:
                if await self._handle_control(_parse_control(message["text"])):
                    return

    async def _handle_control(self, data: Dict[str, Any]) -> bool:
        """Apply one control message; True when the client asked to stop."""
        kind = data.get("type")
        if kind == "stop":
            return True
        if kind == "ping":
            await self._channel.send("pong")
        elif kind == "played":
            reply_id, samples = data.get("reply_id"), data.get("samples")
            if type(reply_id) is not int or type(samples) is not int:
                raise ValueError("Playback acknowledgement requires integer reply_id and samples.")
            self._responder.on_played(reply_id, samples)
        elif kind == "playback_started":
            reply_id = data.get("reply_id")
            if type(reply_id) is int:
                await self._responder.on_playback_started(reply_id)
        return False


def _parse_control(text: str) -> Dict[str, Any]:
    if len(text) > _MAX_CONTROL_MESSAGE_CHARS:
        raise ValueError("Voice control message is too large.")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Voice control message must be an object.")
    return data
