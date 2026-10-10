"""Deepgram, Soniox, and ElevenLabs adapters against scripted WebSockets; no network."""

import asyncio
import base64
import json
import struct

import pytest
from websockets.protocol import State

from agno.voice.base import SAMPLE_RATE, Transcript
from agno.voice.stt._turns import _TurnTimeline
from agno.voice.stt.deepgram import DeepgramSTT, _DeepgramSession
from agno.voice.stt.soniox import SonioxSTT, _SonioxSession
from agno.voice.tts.elevenlabs import ElevenLabsTTS, _ElevenLabsSession, _words


class FakeSocket:
    def __init__(self):
        self.sent = []
        self.incoming = asyncio.Queue()
        self.state = State.OPEN

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        item = await self.incoming.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self):
        self.state = State.CLOSED

    def control(self):
        return [json.loads(message) for message in self.sent if isinstance(message, str)]

    def push(self, **event):
        self.incoming.put_nowait(json.dumps(event))


def pcm(seconds):
    return bytes(int(SAMPLE_RATE * seconds) * 2)


async def take(events, count, timeout=2):
    return [await asyncio.wait_for(events.__anext__(), timeout) for _ in range(count)]


def test_timeline_attributes_results_to_the_turn_that_contains_them():
    timeline = _TurnTimeline()
    timeline.add_silence(SAMPLE_RATE // 10)
    timeline.add_audio(1, SAMPLE_RATE)
    timeline.add_audio(2, SAMPLE_RATE)
    assert timeline.turn_at(0.0) == 1
    assert timeline.turn_at(0.5) == 1
    assert timeline.turn_at(1.2) == 2
    timeline.add_final(1, "hello")
    timeline.add_final(2, "again")
    timeline.commit(1, timeout=10)
    timeline.commit(2, timeout=10)
    # Completion follows commit order and waits for the provider to pass each end.
    assert timeline.finish_through(1.0) == []
    assert timeline.finish_through(1.1) == [Transcript(1, "hello", True)]
    assert timeline.finish_through(2.1) == [Transcript(2, "again", True)]


def test_timeline_does_not_complete_a_short_turn_before_anything_is_finalized():
    timeline = _TurnTimeline()
    timeline.add_audio(1, 768)  # 32 ms, shorter than the alignment tolerance.
    timeline.commit(1, timeout=10)
    assert timeline.finish_through(0.0) == []


def test_timeline_falls_back_to_received_text_after_the_finalize_timeout():
    timeline = _TurnTimeline()
    timeline.add_audio(1, SAMPLE_RATE)
    timeline.add_final(1, "partial")
    timeline.commit(1, timeout=0)
    assert timeline.finish_expired() == [Transcript(1, "partial", True)]


def test_deepgram_url_selects_raw_pcm_and_the_language():
    url = DeepgramSTT(language="pt-BR", keyterms=["Agno OS", " "], endpointing=300)._url()
    assert url.startswith("wss://api.deepgram.com/v1/listen?model=nova-3&language=pt-BR&")
    assert "encoding=linear16" in url and f"sample_rate={SAMPLE_RATE}" in url
    assert "interim_results=true" in url and "endpointing=300" in url
    assert url.count("keyterm=") == 1 and "keyterm=Agno+OS" in url


@pytest.mark.asyncio
async def test_deepgram_requires_an_api_key(monkeypatch):
    monkeypatch.delenv("DEEPGRAM_API_KEY", raising=False)
    with pytest.raises(ValueError, match="DEEPGRAM_API_KEY"):
        async with DeepgramSTT()._connect():
            pass


def results(start, duration, text, is_final, **extra):
    return dict(
        type="Results",
        start=start,
        duration=duration,
        is_final=is_final,
        channel={"alternatives": [{"transcript": text}]},
        **extra,
    )


@pytest.mark.asyncio
async def test_deepgram_streams_interim_text_and_finalizes_the_committed_turn():
    socket = FakeSocket()
    session = _DeepgramSession(socket, DeepgramSTT(api_key="key"))
    events = session._events()
    try:
        await session._send_audio(pcm(1), turn_id=1)
        socket.push(**results(0.0, 0.5, "good morning every", False))
        assert await take(events, 1) == [Transcript(1, "good morning every")]
        await session._commit(1)
        assert socket.control()[-1] == {"type": "Finalize"}
        socket.push(**results(0.0, 1.0, "Good morning, everyone.", True, from_finalize=True))
        assert await take(events, 2) == [
            Transcript(1, "Good morning, everyone."),
            Transcript(1, "Good morning, everyone.", True),
        ]
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_deepgram_keeps_overlapping_turns_apart_by_audio_time():
    socket = FakeSocket()
    session = _DeepgramSession(socket, DeepgramSTT(api_key="key"))
    events = session._events()
    try:
        await session._send_audio(pcm(1), turn_id=1)
        await session._commit(1)
        # The user speaks again before the first turn's results arrive.
        await session._send_audio(pcm(1), turn_id=2)
        socket.push(**results(0.0, 1.0, "first", True))
        socket.push(**results(1.0, 0.6, "sec", False))
        assert await take(events, 3) == [
            Transcript(1, "first"),
            Transcript(1, "first", True),
            Transcript(2, "sec"),
        ]
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_deepgram_completes_immediately_when_audio_was_already_finalized():
    socket = FakeSocket()
    session = _DeepgramSession(socket, DeepgramSTT(api_key="key", finalize_timeout=30))
    events = session._events()
    try:
        await session._send_audio(pcm(1), turn_id=1)
        socket.push(**results(0.0, 1.0, "done already", True))
        assert await take(events, 1) == [Transcript(1, "done already")]
        # Deepgram may not answer Finalize when nothing is left; the commit
        # itself must complete the turn instead of waiting for the timeout.
        await session._commit(1)
        assert await take(events, 1, timeout=1) == [Transcript(1, "done already", True)]
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_deepgram_falls_back_when_finalize_gets_no_answer():
    socket = FakeSocket()
    session = _DeepgramSession(socket, DeepgramSTT(api_key="key", finalize_timeout=0.05))
    events = session._events()
    try:
        await session._send_audio(pcm(1), turn_id=1)
        socket.push(**results(0.0, 0.4, "only this", True))
        assert await take(events, 1) == [Transcript(1, "only this")]
        await session._commit(1)
        assert await take(events, 1) == [Transcript(1, "only this", True)]
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_deepgram_sends_keepalive_while_idle_and_reports_closure():
    from websockets.exceptions import ConnectionClosedError

    socket = FakeSocket()
    session = _DeepgramSession(socket, DeepgramSTT(api_key="key", keepalive_interval=0.05))
    session._start_keepalive()
    try:
        await asyncio.sleep(0.2)
        assert {"type": "KeepAlive"} in socket.control()
    finally:
        await session._stop_keepalive()
    socket.incoming.put_nowait(ConnectionClosedError(None, None))
    with pytest.raises(RuntimeError, match="Deepgram transcription closed"):
        await take(session._events(), 1)


@pytest.mark.asyncio
async def test_deepgram_connect_opens_with_silence_and_closes_the_stream(monkeypatch):
    import websockets.asyncio.client

    socket = FakeSocket()
    captured = {}

    class Connect:
        def __init__(self, url, **kwargs):
            captured.update(url=url, **kwargs)

        async def __aenter__(self):
            return socket

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(websockets.asyncio.client, "connect", Connect)
    async with DeepgramSTT(api_key="secret")._connect():
        # Deepgram closes streams without audio in the first ten seconds.
        assert socket.sent[0] == bytes(SAMPLE_RATE // 10 * 2)
    assert captured["additional_headers"] == {"Authorization": "Token secret"}
    assert socket.control()[-1] == {"type": "CloseStream"}


def test_soniox_config_authenticates_in_the_first_message():
    config = SonioxSTT(language_hints=["en", "es"], terms=["Agno"], context="Support call")._config("key")
    assert config == {
        "api_key": "key",
        "model": "stt-rt-v5",
        "audio_format": "pcm_s16le",
        "sample_rate": 16000,
        "num_channels": 1,
        "language_hints": ["en", "es"],
        "context": {"terms": ["Agno"], "text": "Support call"},
    }


def test_soniox_without_hints_recognizes_any_language():
    assert "language_hints" not in SonioxSTT()._config("key")


def test_soniox_resamples_each_frame_to_16_khz():
    import numpy

    session = _SonioxSession(FakeSocket(), SonioxSTT(api_key="key"), numpy)
    frame = struct.pack("<768h", *([1000] * 768))
    resampled = session._audio_payload(frame)
    assert len(resampled) == 512 * 2
    assert set(struct.unpack("<512h", resampled)) == {1000}


def tokens(*items, processed=None):
    event = {"tokens": [dict(zip(("text", "start_ms", "is_final"), item)) for item in items]}
    if processed is not None:
        event["final_audio_proc_ms"] = processed
    return event


@pytest.mark.asyncio
async def test_soniox_joins_final_tokens_and_replaces_the_provisional_tail():
    import numpy

    socket = FakeSocket()
    session = _SonioxSession(socket, SonioxSTT(api_key="key"), numpy)
    events = session._events()
    try:
        await session._send_audio(pcm(1), turn_id=1)
        socket.push(**tokens(("Hel", 0, False), ("lo", 100, False)))
        assert await take(events, 1) == [Transcript(1, "Hello")]
        socket.push(**tokens(("Hello", 0, True), (" wor", 400, False), processed=300))
        assert await take(events, 1) == [Transcript(1, "Hello wor")]
        await session._commit(1)
        assert socket.control()[-1] == {"type": "finalize"}
        socket.push(**tokens((" world", 400, True), ("<fin>", 1000, True), processed=1000))
        assert await take(events, 2) == [Transcript(1, "Hello world"), Transcript(1, "Hello world", True)]
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_soniox_errors_name_the_error_type():
    import numpy

    socket = FakeSocket()
    session = _SonioxSession(socket, SonioxSTT(api_key="key"), numpy)
    socket.push(error_code=401, error_type="unauthenticated", error_message="Invalid API key", request_id="r1")
    with pytest.raises(RuntimeError, match="unauthenticated: Invalid API key"):
        await take(session._events(), 1)


def alignment(text, start_ms=0.0, step_ms=10.0):
    return {
        "chars": list(text),
        "charStartTimesMs": [start_ms + index * step_ms for index in range(len(text))],
        "charDurationsMs": [step_ms] * len(text),
    }


def test_elevenlabs_words_carry_across_chunks():
    marks, word, end = _words(alignment("Hel"), 0, "", 0)
    assert marks == [] and word == "Hel"
    marks, word, end = _words(alignment("lo world"), 720, word, end)
    # "lo" ends 20 ms into the second chunk, which starts at sample 720.
    assert marks == [("Hello", 720 + 20 * 24)]
    assert word == "world"


@pytest.mark.asyncio
async def test_elevenlabs_defaults_to_the_toolkit_voice(monkeypatch):
    import websockets.asyncio.client

    for name in ("ELEVEN_LABS_VOICE_ID", "ELEVENLABS_VOICE_ID"):
        monkeypatch.delenv(name, raising=False)
    urls = []

    async def connect(url, **kwargs):
        urls.append(url)
        return FakeSocket()

    monkeypatch.setattr(websockets.asyncio.client, "connect", connect)
    async with ElevenLabsTTS(api_key="key")._connect():
        pass
    assert "/JBFqnCBsd6RMkjVDRZzb/multi-stream-input?" in urls[0]


@pytest.mark.asyncio
async def test_elevenlabs_reads_the_same_key_variable_as_the_toolkit(monkeypatch):
    for name in ("ELEVEN_LABS_API_KEY", "ELEVENLABS_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValueError, match="ELEVEN_LABS_API_KEY"):
        async with ElevenLabsTTS(voice="v")._connect():
            pass


async def tokens_from(*parts):
    for part in parts:
        yield part


@pytest.mark.asyncio
async def test_elevenlabs_streams_whole_words_and_marks_spoken_text():
    socket = FakeSocket()
    session = _ElevenLabsSession(None, ElevenLabsTTS(voice="v", api_key="key"))
    session._connection = socket
    stream = session._synthesize(tokens_from("Hel", "lo wor", "ld."))

    async def respond():
        while len(socket.control()) < 4:
            await asyncio.sleep(0.01)
        context = socket.control()[0]["context_id"]
        socket.push(contextId="stale", audio=base64.b64encode(bytes(96)).decode())
        socket.push(contextId=context, audio=base64.b64encode(bytes(480)).decode(), alignment=alignment("Hello world."))
        socket.push(contextId=context, isFinal=True)

    responder = asyncio.create_task(respond())
    chunks = [chunk async for chunk in stream]
    await responder
    sent = socket.control()
    assert [message.get("text") for message in sent[:3]] == [" ", "Hello ", "world. "]
    assert sent[3] == {"context_id": sent[0]["context_id"], "flush": True}
    assert sent[-1] == {"context_id": sent[0]["context_id"], "close_context": True}
    # Audio from another context is dropped; only this context's 240 samples play.
    assert [len(chunk.audio) for chunk in chunks if chunk.audio] == [480]
    assert [(chunk.text, chunk.end_sample) for chunk in chunks if chunk.text] == [
        ("Hello", 50 * 24),
        ("world.", 120 * 24),
    ]


@pytest.mark.asyncio
async def test_elevenlabs_reopens_a_socket_closed_while_idle():
    first, second = FakeSocket(), FakeSocket()
    opened = []

    async def open_socket():
        opened.append(second)
        return second

    session = _ElevenLabsSession(open_socket, ElevenLabsTTS(voice="v", api_key="key"))
    session._connection = first
    first.state = State.CLOSED
    await session._ensure_open()
    assert session._connection is second and opened == [second]


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------
def gemini_session(socket, **options):
    import numpy

    from agno.voice.stt.gemini import GeminiLiveSTT, _GeminiLiveSession

    model = GeminiLiveSTT(api_key="key", **options)
    return _GeminiLiveSession(socket, model, "key", numpy), model


def frame():
    return bytes(768 * 2)


@pytest.mark.asyncio
async def test_gemini_live_waits_for_setup_and_sends_the_documented_config(monkeypatch):
    import websockets.asyncio.client

    from agno.voice.stt.gemini import GeminiLiveSTT

    socket = FakeSocket()
    socket.push(setupComplete={})
    captured = {}

    async def connect(url, **kwargs):
        captured["url"] = url
        return socket

    monkeypatch.setattr(websockets.asyncio.client, "connect", connect)
    async with GeminiLiveSTT(api_key="secret", vocabulary=["Agno"])._connect():
        pass
    assert captured["url"].endswith("BidiGenerateContent?key=secret")
    assert socket.control()[0] == {
        "setup": {
            "model": "models/gemini-3.5-transcribe-live",
            "generationConfig": {"responseModalities": ["TEXT"]},
            # No language codes: Gemini detects the language itself.
            "inputAudioTranscription": {"mode": "VERBATIM", "customVocabulary": ["Agno"]},
        }
    }


@pytest.mark.asyncio
async def test_gemini_live_batches_16_khz_audio_and_ends_each_turn():
    socket = FakeSocket()
    session, _ = gemini_session(socket)
    await session._send_audio(frame(), turn_id=1)
    await session._send_audio(frame(), turn_id=1)
    assert socket.sent == []  # Buffered toward Google's recommended 100 ms.
    await session._send_audio(frame(), turn_id=1)
    audio = socket.control()[0]["realtimeInput"]["audio"]
    assert audio["mimeType"] == "audio/pcm;rate=16000"
    assert len(base64.b64decode(audio["data"])) == 3 * 512 * 2
    await session._send_audio(frame(), turn_id=1)
    await session._commit(1)
    # The remainder is flushed before the turn is finalized.
    assert len(base64.b64decode(socket.control()[1]["realtimeInput"]["audio"]["data"])) == 512 * 2
    assert socket.control()[2] == {"realtimeInput": {"audioStreamEnd": True}}


@pytest.mark.asyncio
async def test_gemini_live_appends_final_segments_and_completes_after_commit():
    socket = FakeSocket()
    session, _ = gemini_session(socket, finalize_timeout=30)
    events = session._events()
    try:
        await session._send_audio(frame(), turn_id=1)
        socket.push(serverContent={"interimInputTranscription": {"text": "Bonjour tout"}})
        assert await take(events, 1) == [Transcript(1, "Bonjour tout")]
        socket.push(serverContent={"inputTranscription": {"text": "Bonjour tout le monde."}})
        assert await take(events, 1) == [Transcript(1, "Bonjour tout le monde.")]
        await session._commit(1)
        socket.push(serverContent={"inputTranscription": {"text": "Comment allez-vous ?"}})
        assert await take(events, 2) == [
            Transcript(1, "Bonjour tout le monde. Comment allez-vous ?"),
            Transcript(1, "Bonjour tout le monde. Comment allez-vous ?", True),
        ]
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_gemini_live_falls_back_when_no_final_follows_the_commit():
    socket = FakeSocket()
    session, _ = gemini_session(socket, finalize_timeout=0.05)
    events = session._events()
    try:
        await session._send_audio(frame(), turn_id=1)
        socket.push(serverContent={"inputTranscription": {"text": "Already final."}})
        assert await take(events, 1) == [Transcript(1, "Already final.")]
        await session._commit(1)
        assert await take(events, 1) == [Transcript(1, "Already final.", True)]
    finally:
        await events.aclose()


@pytest.mark.asyncio
async def test_gemini_live_renews_the_session_between_turns_after_go_away():
    socket, replacement = FakeSocket(), FakeSocket()
    session, model = gemini_session(socket)
    opened = []

    async def reopen(api_key):
        opened.append(api_key)
        return replacement

    model._open = reopen
    events = session._events()
    try:
        await session._send_audio(frame(), turn_id=1)
        socket.push(goAway={"timeLeft": "5s"})
        await session._commit(1)
        socket.push(serverContent={"inputTranscription": {"text": "First."}})
        assert (await take(events, 2))[-1] == Transcript(1, "First.", True)
        # The next turn starts on a fresh session.
        await session._send_audio(frame() * 3, turn_id=2)
        assert opened == ["key"] and session._connection is replacement
        assert "realtimeInput" in replacement.control()[0]
        replacement.push(serverContent={"interimInputTranscription": {"text": "Second"}})
        assert await take(events, 1) == [Transcript(2, "Second")]
    finally:
        await events.aclose()


class FakeResponse:
    def __init__(self, status_code, lines, body=b""):
        self.status_code = status_code
        self._lines = lines
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeHTTP:
    def __init__(self, *responses):
        self.requests = []
        self._responses = list(responses)

    def stream(self, method, url, json):
        self.requests.append((method, url, json))
        return self._responses.pop(0)


def sse(event):
    return [f"event: {event['event_type']}", "data: " + json.dumps(event), ""]


@pytest.mark.asyncio
async def test_gemini_tts_streams_each_phrase_and_marks_it_spoken():
    from agno.voice.tts.gemini import GeminiTTS, _GeminiSpeechSession

    audio = base64.b64encode(bytes(480)).decode()
    response = FakeResponse(
        200,
        sse({"event_type": "step.start", "index": 0, "step": {"type": "model_output"}})
        + sse({"event_type": "step.delta", "index": 0, "delta": {"type": "audio", "data": audio}})
        + sse({"event_type": "interaction.completed", "interaction": {"status": "completed"}})
        + ["event: done", "data: [DONE]"],
    )
    client = FakeHTTP(response)
    session = _GeminiSpeechSession(client, GeminiTTS(api_key="key", style="calm"))
    chunks = [chunk async for chunk in session._synthesize(tokens_from("Hello there."))]
    assert [len(chunk.audio) for chunk in chunks if chunk.audio] == [480]
    assert [(chunk.text, chunk.end_sample) for chunk in chunks if chunk.text] == [("Hello there.", 240)]
    method, url, body = client.requests[0]
    assert method == "POST" and url.endswith("/v1beta/interactions")
    assert body["stream"] is True and body["generation_config"] == {"speech_config": [{"voice": "Kore"}]}
    assert body["input"][0]["content"][0]["annotations"] == [{"type": "speech_metadata", "style": "calm"}]


@pytest.mark.asyncio
async def test_gemini_tts_reports_stream_and_http_errors():
    from agno.voice.tts.gemini import GeminiTTS, _GeminiSpeechSession

    failing = FakeResponse(200, sse({"event_type": "error", "error": {"message": "Deadline expired", "code": "x"}}))
    with pytest.raises(RuntimeError, match="Gemini speech: Deadline expired"):
        session = _GeminiSpeechSession(FakeHTTP(failing), GeminiTTS(api_key="key"))
        [chunk async for chunk in session._synthesize(tokens_from("Hi."))]
    rejected = FakeResponse(403, [], body=b'{"error": {"message": "API key not valid"}}')
    with pytest.raises(RuntimeError, match="HTTP 403: API key not valid"):
        session = _GeminiSpeechSession(FakeHTTP(rejected), GeminiTTS(api_key="key"))
        [chunk async for chunk in session._synthesize(tokens_from("Hi."))]
