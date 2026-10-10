"""Audio delivery follows browser playback progress, not synthesis speed."""

import asyncio
import struct
from contextlib import asynccontextmanager

import pytest
from test_pipe import Socket, make_pipe, utterance

from agno.voice.base import SAMPLE_RATE, SpeechChunk


class BurstSpeech:
    def __init__(self, seconds):
        self.seconds = seconds
        self.closed = asyncio.Event()

    async def _synthesize(self, text):
        emitted = False
        try:
            async for _ in text:
                if emitted:
                    continue
                emitted = True
                yield SpeechChunk(text="Hello.", end_sample=1200)
                # A fast provider can return a long answer before playback has
                # consumed its first second. All of it must eventually arrive.
                yield SpeechChunk(audio=bytes(round(self.seconds * SAMPLE_RATE) * 2))
        finally:
            self.closed.set()


class BurstModel:
    def __init__(self, seconds=40):
        self.seconds = seconds
        self.sessions = []

    @asynccontextmanager
    async def _connect(self):
        session = BurstSpeech(self.seconds)
        self.sessions.append(session)
        yield session


class PlaybackSocket(Socket):
    def __init__(self):
        super().__init__()
        self.acknowledged = 0
        self.max_outstanding = 0
        self.packets = []

    async def send_bytes(self, data):
        reply_id, offset = struct.unpack("<II", data[:8])
        samples = (len(data) - 8) // 2
        self.max_outstanding = max(self.max_outstanding, offset + samples - self.acknowledged)
        self.packets.append((reply_id, offset, samples))
        await super().send_bytes(data)

    def acknowledge(self, samples, reply_id=1):
        self.acknowledged = max(self.acknowledged, samples)
        self.control(type="played", reply_id=reply_id, samples=samples)


async def begin(pipe, socket):
    task = asyncio.create_task(pipe._serve(socket))
    await socket.next("ready")
    await utterance(socket, pipe.stt_model.sessions[0], "Give me a long reply")
    return task


async def fill_window(socket, seconds=2):
    packets = round(seconds * 10)  # The server emits at most 100 ms per packet.
    for _ in range(packets):
        await socket.next("audio")
    # Round-trip a control message while the audio sender waits. This also
    # checks that backpressure does not hold the WebSocket send lock.
    socket.control(type="ping")
    await socket.next("pong")
    assert len(socket.packets) == packets


@pytest.mark.asyncio
async def test_fast_forty_second_burst_is_paced_by_playback_acknowledgements():
    pipe, socket = make_pipe(), PlaybackSocket()
    pipe.tts_model = BurstModel()
    task = await begin(pipe, socket)
    try:
        await fill_window(socket)
        assert socket.max_outstanding == 2 * SAMPLE_RATE
        assert not pipe.tts_model.sessions[0].closed.is_set()
        socket.acknowledge(2 * SAMPLE_RATE)

        async def consume():
            while True:
                event = await socket.events.get()
                if event["type"] == "reply_done":
                    return
                if event["type"] == "audio":
                    _, offset = struct.unpack("<II", event["data"][:8])
                    socket.acknowledge(offset + (len(event["data"]) - 8) // 2)

        await asyncio.wait_for(consume(), 3)
        assert sum(samples for _, _, samples in socket.packets) == 40 * SAMPLE_RATE
        assert socket.max_outstanding <= 2 * SAMPLE_RATE
        assert [offset for _, offset, _ in socket.packets] == list(range(0, 40 * SAMPLE_RATE, 2400))
        assert pipe.tts_model.sessions[0].closed.is_set()
        assert not any(event["type"] == "error" for event in socket.sent)
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_barge_in_cancels_a_sender_waiting_for_playback():
    pipe, socket = make_pipe(), PlaybackSocket()
    pipe.tts_model = BurstModel()
    task = await begin(pipe, socket)
    try:
        await fill_window(socket)
        socket.audio(1)
        assert (await socket.next("stop_playback"))["reply_id"] == 1
        await socket.next("speech_started")
        await asyncio.wait_for(pipe.tts_model.sessions[0].closed.wait(), 1)
        # A final playback ACK after interruption must not revive the sender.
        socket.acknowledge(2 * SAMPLE_RATE)
        socket.control(type="ping")
        await socket.next("pong")
        assert len(socket.packets) == 20
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_stalled_playback_reports_a_clear_error_and_closes_synthesis():
    pipe, socket = make_pipe(playback_timeout=0.05), PlaybackSocket()
    pipe.tts_model = BurstModel()
    task = await begin(pipe, socket)
    try:
        await fill_window(socket)
        # Neither duplicate, invalid, nor another reply's ACK grants credit.
        socket.control(type="played", reply_id=1, samples=0)
        socket.control(type="played", reply_id=1, samples=40 * SAMPLE_RATE)
        socket.control(type="played", reply_id=99, samples=2 * SAMPLE_RATE)
        failure = await socket.next("error")
        assert failure["fatal"] is False
        assert "Audio playback stopped responding" in failure["message"]
        await asyncio.wait_for(pipe.tts_model.sessions[0].closed.wait(), 1)
        assert len(socket.packets) == 20
        socket.control(type="stop")
        await asyncio.wait_for(task, 3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "options",
    [
        {"max_playback_buffer_seconds": 0},
        {"max_playback_buffer_seconds": float("nan")},
        {"max_playback_buffer_seconds": float("inf")},
        {"playback_timeout": 0},
        {"playback_timeout": float("nan")},
    ],
)
def test_playback_flow_settings_are_validated(options):
    with pytest.raises(ValueError):
        make_pipe(**options)
