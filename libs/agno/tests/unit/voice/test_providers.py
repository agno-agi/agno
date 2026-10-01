import asyncio
import base64
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from agno.voice.stt.openai import OpenAIRealtimeSTT, _OpenAIRealtimeSession
from agno.voice.tts.cartesia import CartesiaTTS, _CartesiaSession
from agno.voice.tts.openai import OpenAITTS, _OpenAISpeechSession, _phrases
from agno.voice.vad.silero import SileroVAD, _SileroSession


async def tokens(*values):
    for value in values:
        yield value


class TranscriptionConnection:
    def __init__(self, *events):
        self.events = asyncio.Queue()
        for event in events:
            self.events.put_nowait(SimpleNamespace(**event))
        self.input_audio_buffer = SimpleNamespace(append=AsyncMock(), commit=AsyncMock())
        self.session = SimpleNamespace(update=AsyncMock())

    async def recv(self):
        return await self.events.get()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.recv()


def test_stt_uses_live_language_hints_and_no_server_vad():
    config = OpenAIRealtimeSTT()._session_config()["audio"]["input"]
    assert config["transcription"] == {"model": "gpt-live-transcribe", "languages": ["en"], "delay": "low"}
    assert config["turn_detection"] is None
    assert config["format"] == {"type": "audio/pcm", "rate": 24000}
    legacy = OpenAIRealtimeSTT(id="whisper-1", language="fr")._session_config()["audio"]["input"]["transcription"]
    assert legacy == {"model": "whisper-1", "language": "fr"}
    multilingual = OpenAIRealtimeSTT(languages=["en", "fr"])._session_config()["audio"]["input"]["transcription"]
    assert multilingual["languages"] == ["en", "fr"]
    assert "language" not in multilingual


@pytest.mark.asyncio
async def test_stt_deltas_before_commit_and_out_of_order_finals():
    connection = TranscriptionConnection()
    session = _OpenAIRealtimeSession(connection)
    stream = session._events()
    await session._send_audio(bytes(4800), turn_id=1)
    connection.events.put_nowait(
        SimpleNamespace(type="conversation.item.input_audio_transcription.delta", item_id="first", delta="Hello")
    )
    first = await stream.__anext__()
    assert (first.turn_id, first.text, first.is_final) == (1, "Hello", False)
    connection.events.put_nowait(
        SimpleNamespace(type="conversation.item.input_audio_transcription.delta", item_id="first", delta=" there")
    )
    assert (await stream.__anext__()).text == "Hello there"
    await session._commit(1)
    await session._send_audio(bytes(4800), turn_id=2)
    await session._commit(2)
    for item_id in ("first", "second"):
        connection.events.put_nowait(SimpleNamespace(type="input_audio_buffer.committed", item_id=item_id))
    for item_id, text in (("second", "Later"), ("first", "Hello there")):
        connection.events.put_nowait(
            SimpleNamespace(
                type="conversation.item.input_audio_transcription.completed", item_id=item_id, transcript=text
            )
        )
    second_final, first_final = await stream.__anext__(), await stream.__anext__()
    assert (second_final.turn_id, second_final.text, second_final.is_final) == (2, "Later", True)
    assert (first_final.turn_id, first_final.text, first_final.is_final) == (1, "Hello there", True)
    assert not session._items and not session._unbound and not session._partials
    await stream.aclose()


@pytest.mark.asyncio
async def test_stt_short_turn_is_padded_and_empty_turn_rejected():
    connection = TranscriptionConnection()
    session = _OpenAIRealtimeSession(connection)
    await session._send_audio(bytes(1536), 1)
    await session._commit(1)
    chunks = [base64.b64decode(call.kwargs["audio"]) for call in connection.input_audio_buffer.append.await_args_list]
    assert sum(map(len, chunks)) == 4800
    with pytest.raises(ValueError, match="without microphone audio"):
        await session._commit(2)
    with pytest.raises(ValueError, match="complete PCM16"):
        await session._send_audio(b"x", 2)


@pytest.mark.asyncio
async def test_stt_final_before_commit_ack_keeps_turn_association():
    connection = TranscriptionConnection()
    session = _OpenAIRealtimeSession(connection)
    stream = session._events()
    await session._send_audio(bytes(4800), 1)
    await session._commit(1)
    connection.events.put_nowait(
        SimpleNamespace(
            type="conversation.item.input_audio_transcription.completed", item_id="first", transcript="Hello"
        )
    )
    first = await stream.__anext__()
    assert (first.turn_id, first.is_final) == (1, True)
    connection.events.put_nowait(SimpleNamespace(type="input_audio_buffer.committed", item_id="first"))
    await session._send_audio(bytes(4800), 2)
    connection.events.put_nowait(
        SimpleNamespace(type="conversation.item.input_audio_transcription.delta", item_id="second", delta="Next")
    )
    second = await stream.__anext__()
    assert (second.turn_id, second.text) == (2, "Next")
    assert "first" not in session._items
    assert not session._completed and not session._acknowledged
    await stream.aclose()


@pytest.mark.asyncio
async def test_stt_waits_for_server_configuration_and_preserves_injected_client():
    connection = TranscriptionConnection({"type": "session.created"}, {"type": "session.updated"})

    @asynccontextmanager
    async def connect(**kwargs):
        assert kwargs == {"extra_query": {"intent": "transcription"}}
        yield connection

    client = SimpleNamespace(realtime=SimpleNamespace(connect=connect), close=AsyncMock())
    async with OpenAIRealtimeSTT(async_client=client)._connect() as session:
        assert isinstance(session, _OpenAIRealtimeSession)
        connection.session.update.assert_awaited_once()
    client.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_stt_configuration_error_is_not_announced_ready():
    connection = TranscriptionConnection({"type": "error", "error": SimpleNamespace(message="Unsupported model")})

    @asynccontextmanager
    async def connect(**kwargs):
        yield connection

    client = SimpleNamespace(realtime=SimpleNamespace(connect=connect), close=AsyncMock())
    with pytest.raises(RuntimeError, match="Unsupported model"):
        async with OpenAIRealtimeSTT(async_client=client)._connect():
            pytest.fail("The session should not be ready")


class CartesiaConnection:
    def __init__(self):
        self.events = asyncio.Queue()
        self.sent = []
        self.closed_context = asyncio.Event()

    async def send(self, message):
        request = json.loads(message)
        self.sent.append(request)
        context_id = request["context_id"]
        if request.get("cancel"):
            return
        if request["transcript"]:
            await self.events.put(
                json.dumps({"type": "chunk", "context_id": context_id, "data": base64.b64encode(bytes(480)).decode()})
            )
            await self.events.put(
                json.dumps(
                    {
                        "type": "timestamps",
                        "context_id": context_id,
                        "word_timestamps": {"words": [request["transcript"]], "end": [0.01]},
                    }
                )
            )
        if not request["continue"]:
            self.closed_context.set()
            await self.events.put(json.dumps({"type": "done", "context_id": context_id}))

    async def recv(self):
        return await self.events.get()


@pytest.mark.asyncio
async def test_cartesia_streams_before_text_completes_and_marks_words():
    connection = CartesiaConnection()
    finished = asyncio.Event()

    async def text():
        yield "Hello "
        await finished.wait()
        yield "world."

    stream = _CartesiaSession(connection, CartesiaTTS())._synthesize(text())
    first = await asyncio.wait_for(stream.__anext__(), 1)
    assert first.audio == bytes(480)
    assert not finished.is_set()
    finished.set()
    rest = [chunk async for chunk in stream]
    assert any(chunk.text == "Hello " and chunk.end_sample == 240 for chunk in rest)
    requests = [request for request in connection.sent if "transcript" in request]
    assert "".join(request["transcript"] for request in requests) == "Hello world."
    assert len({request["context_id"] for request in requests}) == 1
    assert requests[-1]["continue"] is False
    assert requests[0]["language"] == "en"
    assert requests[0]["output_format"]["encoding"] == "pcm_s16le"


@pytest.mark.asyncio
async def test_cartesia_cancellation_discards_late_audio_and_reuses_connection():
    connection = CartesiaConnection()

    async def text():
        yield "First"
        await asyncio.Event().wait()

    session = _CartesiaSession(connection, CartesiaTTS())
    first = session._synthesize(text())
    await first.__anext__()
    old_context = connection.sent[0]["context_id"]
    await first.aclose()
    assert {"context_id": old_context, "cancel": True} in connection.sent
    await connection.events.put(
        json.dumps({"type": "chunk", "context_id": old_context, "data": base64.b64encode(b"old!").decode()})
    )
    chunks = [chunk async for chunk in session._synthesize(tokens("Second"))]
    assert b"".join(chunk.audio for chunk in chunks) == bytes(480)
    assert [chunk.text for chunk in chunks if chunk.text] == ["Second"]


@pytest.mark.asyncio
async def test_cartesia_tool_pause_restarts_context_and_offsets_timestamps():
    connection = CartesiaConnection()

    async def text():
        yield "Checking."
        # The first context must finish without waiting for this tool result.
        await connection.closed_context.wait()
        yield "Found it."

    chunks = [chunk async for chunk in _CartesiaSession(connection, CartesiaTTS())._synthesize(text())]
    requests = [request for request in connection.sent if request.get("transcript")]
    assert len({request["context_id"] for request in requests}) == 2
    assert [(chunk.text, chunk.end_sample) for chunk in chunks if chunk.text] == [
        ("Checking.", 240),
        ("Found it.", 480),
    ]


@pytest.mark.asyncio
async def test_cartesia_propagates_text_failure_without_hanging_receiver():
    async def text():
        yield "Hello"
        raise ValueError("agent failed")

    async def consume():
        return [chunk async for chunk in _CartesiaSession(CartesiaConnection(), CartesiaTTS())._synthesize(text())]

    with pytest.raises(ValueError, match="agent failed"):
        await asyncio.wait_for(consume(), 1)


@pytest.mark.asyncio
async def test_openai_phrase_buffer_handles_non_latin_punctuation_and_long_text():
    result = [phrase async for phrase in _phrases(tokens("नमस्ते। ", "你好。 ", "One two three " * 12), 32, 0.2)]
    assert result[:2] == ["नमस्ते।", "你好。"]
    assert all(len(phrase) <= 32 for phrase in result)
    assert " ".join(result[2:]) == ("One two three " * 12).strip()


@pytest.mark.asyncio
async def test_openai_phrase_buffer_flushes_before_late_next_token():
    ready = asyncio.Event()

    async def text():
        yield "A few words "
        await ready.wait()
        yield "follow."

    phrases = _phrases(text(), 160, 0.01)
    assert await asyncio.wait_for(phrases.__anext__(), 1) == "A few words"
    ready.set()
    assert [phrase async for phrase in phrases] == ["follow."]


@pytest.mark.asyncio
async def test_openai_pcm_alignment_and_phrase_markers():
    class Response:
        async def iter_bytes(self):
            yield b"\x01"
            yield b"\x02\x03\x04"

    @asynccontextmanager
    async def create(**kwargs):
        assert kwargs["response_format"] == "pcm"
        yield Response()

    client = SimpleNamespace(
        audio=SimpleNamespace(speech=SimpleNamespace(with_streaming_response=SimpleNamespace(create=create)))
    )
    chunks = [chunk async for chunk in _OpenAISpeechSession(client, OpenAITTS())._synthesize(tokens("One. Two."))]
    assert [chunk.audio for chunk in chunks if chunk.audio] == [b"\x01\x02\x03\x04"] * 2
    assert [(chunk.text, chunk.end_sample) for chunk in chunks if chunk.text] == [("One.", 2), ("Two.", 4)]


@pytest.mark.asyncio
async def test_openai_text_failure_propagates_without_hanging_phrase_consumer():
    async def text():
        raise ValueError("agent failed")
        yield "unreachable"

    async def consume():
        return [chunk async for chunk in _OpenAISpeechSession(None, OpenAITTS())._synthesize(text())]

    with pytest.raises(ValueError, match="agent failed"):
        await asyncio.wait_for(consume(), 1)


@pytest.mark.asyncio
async def test_silero_pcm_resampling_and_frame_validation():
    numpy = pytest.importorskip("numpy")
    tensor = SimpleNamespace(from_numpy=lambda value: value)
    detector = Mock(side_effect=[{"start": 0}, {"end": 512}, None])
    session = _SileroSession(detector, numpy, tensor)
    assert await session._process(bytes(1536)) == "start"
    assert await session._process(bytes(1536)) == "stop"
    assert await session._process(bytes(1536)) is None
    assert all(call.args[0].shape == (512,) for call in detector.call_args_list)
    with pytest.raises(ValueError, match="768"):
        await session._process(bytes(512))


@pytest.mark.parametrize(
    "constructor,kwargs",
    [
        (OpenAIRealtimeSTT, {"delay": "fastest"}),
        (OpenAIRealtimeSTT, {"languages": []}),
        (OpenAITTS, {"max_phrase_chars": 0}),
        (OpenAITTS, {"speed": 5}),
        (CartesiaTTS, {"max_buffer_delay_ms": -1}),
        (SileroVAD, {"threshold": 0}),
        (SileroVAD, {"min_silence_duration_ms": -1}),
    ],
)
def test_provider_settings_are_validated(constructor, kwargs):
    with pytest.raises(ValueError):
        constructor(**kwargs)
