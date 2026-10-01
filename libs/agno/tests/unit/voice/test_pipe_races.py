"""Scheduling checks around speech-start and delayed transcription events."""

import asyncio

import pytest

from agno.voice.base import Transcript
from agno.voice.pipe import _VoiceSession
from tests.unit.voice.test_pipe import Socket, make_pipe


@pytest.mark.asyncio
async def test_final_transcript_cannot_start_reply_while_speech_start_is_suspended(monkeypatch):
    """Even a yielding interruption hook must preserve the active-user-turn guard."""
    pipe, socket = make_pipe(), Socket()
    interrupt_entered, release_interrupt, final_processed = asyncio.Event(), asyncio.Event(), asyncio.Event()
    delay_interrupt = False
    original_interrupt = _VoiceSession._interrupt
    original_maybe_respond = _VoiceSession._maybe_respond
    original_respond = _VoiceSession._respond
    started_replies = []

    async def delayed_interrupt(session):
        await original_interrupt(session)
        if delay_interrupt:
            interrupt_entered.set()
            await release_interrupt.wait()

    async def observe_final(session):
        await original_maybe_respond(session)
        if interrupt_entered.is_set() and not release_interrupt.is_set():
            final_processed.set()

    async def observe_reply(session, reply, context):
        started_replies.append(reply.id)
        await original_respond(session, reply, context)

    monkeypatch.setattr(_VoiceSession, "_interrupt", delayed_interrupt)
    monkeypatch.setattr(_VoiceSession, "_maybe_respond", observe_final)
    monkeypatch.setattr(_VoiceSession, "_respond", observe_reply)

    task = asyncio.create_task(pipe._serve(socket))
    try:
        await socket.next("ready")
        recognizer = pipe.stt_model.sessions[0]
        socket.audio(1)
        await socket.next("speech_started")
        socket.audio(0)
        await socket.next("speech_stopped")

        # The user continues before the first segment's final transcript arrives.
        delay_interrupt = True
        socket.audio(1)
        await asyncio.wait_for(interrupt_entered.wait(), 1)
        await recognizer.transcripts.put(Transcript(1, "What are you", True))
        await asyncio.wait_for(final_processed.wait(), 1)
        assert started_replies == []

        release_interrupt.set()
        await socket.next("speech_started")
        socket.audio(0)
        await socket.next("speech_stopped")
        await recognizer.transcripts.put(Transcript(2, "and what can you do?", True))
        await socket.next("reply_done")
        assert len(started_replies) == 1
        assert pipe.agent.calls[0][0] == ["What are you and what can you do?"]
    finally:
        release_interrupt.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
