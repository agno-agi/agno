"""A streaming voice session around an existing Agno agent."""

import asyncio
import math
import re
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional
from uuid import uuid4

from agno.agent import Agent
from agno.voice._session import _VoiceSession
from agno.voice.base import STTModel, TTSModel, VAD

if TYPE_CHECKING:
    from fastapi import WebSocket


@dataclass
class VoicePipe:
    """Give an existing text agent a streaming microphone and voice.

    Register with ``AgentOS(live_sockets=[pipe])`` to serve it at the WebSocket
    route ``/voice/{id}/ws``. Clients send PCM16, mono, 24 kHz audio in
    768-sample frames. Each connection owns its speech provider
    sessions, VAD, and server-generated agent session ID.
    The agent's model, instructions, and tools are reused without modification.
    Conversation history comes from the agent's own session storage, so voice
    turns are saved as normal runs; the agent's num_history_runs and
    num_history_messages decide how much history each turn includes.
    """

    agent: Agent
    vad: VAD
    stt_model: STTModel
    tts_model: TTSModel
    id: str = "voice"
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
        if self.max_audio_frames < 1:
            raise ValueError("VoicePipe max_audio_frames must be positive.")
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
        # Agno only keeps history through a db. Check at connect time, after
        # AgentOS has had the chance to assign its own db to the agent.
        if self.agent.db is None:
            from agno.db.in_memory import InMemoryDb
            from agno.utils.log import log_warning

            log_warning(
                f"Voice pipe '{self.id}': agent has no db, using an in-memory db. "
                "Voice history and runs will not survive a restart."
            )
            self.agent.db = InMemoryDb()
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
