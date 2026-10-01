"""Exercise the voice pipeline without microphones or paid provider calls."""

import asyncio
import json
import struct
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from agno.voice import VoicePipe
from agno.voice.base import SpeechChunk, Transcript


def pcm(value):
    return struct.pack("<h", value) * 768


class Socket:
    def __init__(self):
        self.incoming = asyncio.Queue()
        self.events = asyncio.Queue()
        self.sent = []
        self.closed = False

    async def receive(self):
        return await self.incoming.get()

    async def send_json(self, event):
        self.sent.append(event)
        await self.events.put(event)

    async def send_bytes(self, data):
        event = {"type": "audio", "data": data}
        self.sent.append(event)
        await self.events.put(event)

    async def close(self):
        self.closed = True

    async def next(self, kind):
        async def find():
            while True:
                event = await self.events.get()
                if event["type"] == kind:
                    return event

        return await asyncio.wait_for(find(), 3)

    def audio(self, value):
        self.incoming.put_nowait({"type": "websocket.receive", "bytes": pcm(value)})

    def control(self, **data):
        self.incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(data)})


class Recognition:
    def __init__(self):
        self.transcripts = asyncio.Queue()
        self.frames = []
        self.commits = []

    async def _send_audio(self, audio, turn_id):
        self.frames.append((turn_id, audio))

    async def _commit(self, turn_id):
        self.commits.append(turn_id)

    async def _events(self):
        while True:
            event = await self.transcripts.get()
            if isinstance(event, Exception):
                raise event
            yield event


class RecognitionModel:
    def __init__(self):
        self.sessions = []
        self.closed = 0

    @asynccontextmanager
    async def _connect(self):
        session = Recognition()
        self.sessions.append(session)
        try:
            yield session
        finally:
            self.closed += 1


class Speech:
    def __init__(self):
        self.cancelled = asyncio.Event()
        self.fail = False

    async def _synthesize(self, text):
        samples = 0
        try:
            async for token in text:
                if self.fail:
                    raise RuntimeError("speech offline")
                samples += 240
                yield SpeechChunk(audio=bytes(480))
                yield SpeechChunk(text=token.strip(), end_sample=samples)
        finally:
            self.cancelled.set()


class SpeechModel:
    def __init__(self):
        self.sessions = []
        self.closed = 0

    @asynccontextmanager
    async def _connect(self):
        session = Speech()
        self.sessions.append(session)
        try:
            yield session
        finally:
            self.closed += 1


class Detector:
    async def _process(self, audio):
        return {1: "start", 0: "stop"}.get(struct.unpack("<h", audio[:2])[0])

    async def _close(self):
        pass


class Detection:
    async def _create_session(self):
        return Detector()


class Talker:
    output_schema = None

    def __init__(self):
        self.calls = []
        self.finish = asyncio.Event()
        self.finish.set()
        self.cancel_cleanup = None

    async def arun(self, messages, **kwargs):
        self.calls.append(([m.content for m in messages], kwargs))
        try:
            yield SimpleNamespace(event="RunContent", content="Hello. ")
            await self.finish.wait()
            yield SimpleNamespace(event="RunContent", content="Goodbye.")
        finally:
            if self.cancel_cleanup is not None:
                await self.cancel_cleanup.wait()


def make_pipe(**kwargs):
    return VoicePipe(agent=Talker(), vad=Detection(), stt_model=RecognitionModel(), tts_model=SpeechModel(), **kwargs)


async def utterance(socket, recognizer, text, turn_id=1):
    socket.audio(1)
    await socket.next("speech_started")
    socket.audio(0)
    await socket.next("speech_stopped")
    await recognizer.transcripts.put(Transcript(turn_id, text, True))


@pytest.mark.asyncio
async def test_live_transcript_and_audio_arrive_before_agent_finishes():
    pipe, socket = make_pipe(), Socket()
    pipe.agent.finish.clear()
    task = asyncio.create_task(pipe._serve(socket, user_id="caller", session_id="server-session"))
    try:
        ready = await socket.next("ready")
        assert ready["sample_rate"] == 24000
        recognizer = pipe.stt_model.sessions[0]
        socket.audio(1)
        await socket.next("speech_started")
        await recognizer.transcripts.put(Transcript(1, "What are"))
        assert (await socket.next("transcript_delta"))["text"] == "What are"
        assert pipe.agent.calls == []
        socket.audio(0)
        await socket.next("speech_stopped")
        await recognizer.transcripts.put(Transcript(1, "What are you?", True))
        packet = (await socket.next("audio"))["data"]
        assert struct.unpack("<II", packet[:8]) == (1, 0)
        assert not any(event["type"] == "reply_done" for event in socket.sent)
        messages, args = pipe.agent.calls[0]
        assert messages == ["What are you?"]
        assert args == {
            "stream": True,
            "stream_events": True,
            "session_id": "server-session",
            "user_id": "caller",
            "add_history_to_context": False,
        }
        pipe.agent.finish.set()
        await socket.next("reply_done")
        assert recognizer.commits == [1]
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
        assert socket.closed
        assert pipe.stt_model.closed == pipe.tts_model.closed == 1
    finally:
        pipe.agent.finish.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_interrupt_flushes_before_cancel_cleanup_and_history_uses_playback():
    pipe, socket = make_pipe(), Socket()
    pipe.agent.finish.clear()
    cleanup = asyncio.Event()
    pipe.agent.cancel_cleanup = cleanup
    task = asyncio.create_task(pipe._serve(socket))
    try:
        await socket.next("ready")
        recognizer = pipe.stt_model.sessions[0]
        await utterance(socket, recognizer, "First")
        await socket.next("audio")
        socket.control(type="played", reply_id=1, samples=240)
        socket.audio(1)
        stopped = await socket.next("stop_playback")
        assert stopped["reply_id"] == 1
        await socket.next("speech_started")
        assert not cleanup.is_set()
        cleanup.set()
        pipe.agent.finish.set()
        socket.audio(0)
        await socket.next("speech_stopped")
        await recognizer.transcripts.put(Transcript(2, "Second", True))
        await socket.next("reply_done")
        history = pipe.agent.calls[-1][0]
        assert history == ["First", "Hello. [The user interrupted the reply.]", "Second"]
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
    finally:
        cleanup.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_out_of_order_finals_preserve_spoken_turn_order():
    pipe, socket = make_pipe(), Socket()
    task = asyncio.create_task(pipe._serve(socket))
    try:
        await socket.next("ready")
        recognizer = pipe.stt_model.sessions[0]
        for _ in range(2):
            socket.audio(1)
            await socket.next("speech_started")
            socket.audio(0)
            await socket.next("speech_stopped")
        await recognizer.transcripts.put(Transcript(2, "second half", True))
        await socket.next("transcript")
        assert not pipe.agent.calls
        await recognizer.transcripts.put(Transcript(1, "first half", True))
        await socket.next("reply_done")
        assert pipe.agent.calls[0][0] == ["first half second half"]
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_concurrent_callers_have_separate_sessions_and_context():
    pipe, first, second = make_pipe(), Socket(), Socket()
    tasks = [asyncio.create_task(pipe._serve(first)), asyncio.create_task(pipe._serve(second))]
    try:
        ready1, ready2 = await asyncio.gather(first.next("ready"), second.next("ready"))
        assert ready1["session_id"] != ready2["session_id"]
        await utterance(first, pipe.stt_model.sessions[0], "Alice")
        await first.next("reply_done")
        await utterance(second, pipe.stt_model.sessions[1], "Bob")
        await second.next("reply_done")
        assert [call[0] for call in pipe.agent.calls] == [["Alice"], ["Bob"]]
        first.control(type="stop")
        second.control(type="stop")
        await asyncio.wait_for(asyncio.gather(*tasks), 3)
        assert pipe.stt_model.closed == pipe.tts_model.closed == 2
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["frame", "transcription", "timeout", "control"])
async def test_failed_calls_close_all_resources(failure):
    pipe, socket = make_pipe(transcription_timeout=0.01), Socket()
    task = asyncio.create_task(pipe._serve(socket))
    await socket.next("ready")
    if failure == "frame":
        socket.incoming.put_nowait({"type": "websocket.receive", "bytes": b"bad"})
    elif failure == "transcription":
        await pipe.stt_model.sessions[0].transcripts.put(RuntimeError("provider failed"))
    elif failure == "control":
        socket.incoming.put_nowait({"type": "websocket.receive", "text": "[]"})
    else:
        socket.audio(1)
        await socket.next("speech_started")
        socket.audio(0)
    assert (await socket.next("error"))["fatal"] is True
    await asyncio.wait_for(task, 3)
    assert socket.closed
    assert pipe.stt_model.closed == pipe.tts_model.closed == 1


@pytest.mark.asyncio
async def test_synthesis_error_is_reported_and_next_turn_can_reply():
    pipe, socket = make_pipe(), Socket()
    task = asyncio.create_task(pipe._serve(socket))
    try:
        await socket.next("ready")
        synthesizer = pipe.tts_model.sessions[0]
        synthesizer.fail = True
        await utterance(socket, pipe.stt_model.sessions[0], "First")
        assert (await socket.next("error"))["fatal"] is False
        synthesizer.fail = False
        await utterance(socket, pipe.stt_model.sessions[0], "Second", 2)
        await socket.next("reply_done")
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("pipe_id", ["", "../secret", "with space", "x" * 65])
def test_pipe_rejects_unsafe_ids(pipe_id):
    with pytest.raises(ValueError, match="URL-safe"):
        make_pipe(id=pipe_id)


@pytest.mark.asyncio
async def test_playback_metric_is_reported_once_for_current_reply():
    pipe, socket = make_pipe(), Socket()
    task = asyncio.create_task(pipe._serve(socket))
    try:
        await socket.next("ready")
        await utterance(socket, pipe.stt_model.sessions[0], "Hello")
        await socket.next("reply_done")
        socket.control(type="playback_started", reply_id=1)
        socket.control(type="playback_started", reply_id=1)
        socket.control(type="ping")
        await socket.next("pong")
        metrics = [event for event in socket.sent if event.get("name") == "total_to_playback"]
        assert len(metrics) == 1
        assert metrics[0]["reply_id"] == 1
        assert metrics[0]["ms"] >= 0
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_response_timeout_cancels_both_streams_and_reports_failure():
    pipe, socket = make_pipe(response_timeout=0.05), Socket()
    pipe.agent.finish.clear()
    task = asyncio.create_task(pipe._serve(socket))
    try:
        await socket.next("ready")
        await utterance(socket, pipe.stt_model.sessions[0], "Hello")
        assert (await socket.next("error"))["fatal"] is False
        assert pipe.tts_model.sessions[0].cancelled.is_set()
        pipe.agent.finish.set()
        await utterance(socket, pipe.stt_model.sessions[0], "Try again", 2)
        await socket.next("reply_done")
        assert "reply failed" in pipe.agent.calls[-1][0][1]
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
