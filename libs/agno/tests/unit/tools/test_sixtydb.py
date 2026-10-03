"""Serialized HTTP and audio artifact checks for the 60db toolkit."""

import base64
import io
import json
import threading
import time
import wave
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agno.agent import Agent
from agno.tools import sixtydb as provider
from agno.tools.sixtydb import SixtyDBTools

PCM = b"\x01\x00" * 480


def wav_bytes(rate=24000, channels=1):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        wav.writeframes(PCM)
    return buffer.getvalue()


@contextmanager
def endpoint(body=PCM, content_type="audio/pcm", status=200, delay=0, headers=None):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.respond()

        def do_POST(self):
            self.respond()

        def respond(self):
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            requests.append(
                (self.command, self.path, self.headers.get("Authorization"), json.loads(data) if data else None)
            )
            time.sleep(delay)
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for key, value in (headers or {}).items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def tool(url, **kwargs):
    return SixtyDBTools(api_key="private-test-key", default_voice_id="workspace-voice", base_url=url, **kwargs)


@pytest.mark.parametrize("kind", ["pcm", "wav", "json", "ndjson", "envelope"])
def test_audio_artifact_and_request(kind):
    encoded = base64.b64encode(PCM).decode()
    body, content_type = PCM, "audio/pcm"
    if kind == "wav":
        body, content_type = wav_bytes(), "audio/wav"
    elif kind == "json":
        body, content_type = (
            json.dumps({"success": True, "audio_base64": encoded, "sample_rate": 24000}).encode(),
            "application/json",
        )
    elif kind in {"ndjson", "envelope"}:
        if kind == "envelope":
            encoded = base64.b64encode(json.dumps({"result": {"audioContent": encoded}}).encode()).decode()
        body = (json.dumps({"result": {"audioContent": encoded}}) + '\n{"type":"complete"}\n').encode()
        content_type = "application/x-ndjson"
    with endpoint(body, content_type) as (url, requests):
        result = tool(url, speed=1.2).text_to_speech(Agent(), "Hello", voice_id="selected-voice")
    assert result.audios and len(result.audios) == 1
    audio = result.audios[0]
    assert (audio.mime_type, audio.format, audio.sample_rate) == ("audio/wav", "wav", 24000)
    with wave.open(io.BytesIO(audio.content), "rb") as wav:
        assert (wav.getframerate(), wav.getnchannels(), wav.getsampwidth()) == (24000, 1, 2)
        assert wav.readframes(wav.getnframes()) == PCM
    assert requests == [
        (
            "POST",
            "/tts-synthesize",
            "Bearer private-test-key",
            {
                "text": "Hello",
                "voice_id": "selected-voice",
                "speed": 1.2,
                "timestamp_type": "NONE",
                "audio_config": {"audio_encoding": "LINEAR16", "sample_rate_hertz": 24000},
            },
        )
    ]


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_http_errors_and_redirects(status):
    with endpoint(b"private-test-key", "text/plain", status=status, headers={"Location": "/other"}) as (url, requests):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert not result.audios
    assert "private-test-key" not in result.content
    assert len(requests) == 1


@pytest.mark.parametrize(
    "body,content_type",
    [
        (b'{"success":false,"message":"private-test-key"}', "application/json"),
        (b'{"audio_base64":"bad!"}', "application/json"),
        (b'{"audio_base64":"AQ=="}', "application/json"),
        (b'{"audio_base64":"AQAAAg==","sample_rate":16000}', "application/json"),
        (b'{"audio_base64":"AQAAAg==","encoding":"mp3"}', "application/json"),
        (b"RIFFbroken", "audio/wav"),
        (b"ID3broken", "audio/pcm"),
        (wav_bytes(rate=16000), "audio/wav"),
        (wav_bytes(channels=2), "audio/wav"),
        (b"<html>private-test-key</html>", "text/html"),
        (
            (json.dumps({"audioContent": base64.b64encode(PCM).decode()}) + '\n{"type":"error"}\n').encode(),
            "application/x-ndjson",
        ),
    ],
)
def test_invalid_responses_create_no_artifact(body, content_type):
    with endpoint(body, content_type) as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert not result.audios
    assert "private-test-key" not in result.content


def test_catalog_and_tool_flags():
    voice = {"voice_id": "voice", "name": "Test", "model": "60db Fast", "labels": {"language": "en"}}
    with endpoint(json.dumps({"success": True, "data": [voice]}).encode(), "application/json") as (url, requests):
        toolkit = tool(url)
        assert json.loads(toolkit.get_voices("fast"))[0]["voice_id"] == "voice"
        assert requests[0][:3] == ("GET", "/voices?model=fast", "Bearer private-test-key")
        assert set(toolkit.get_functions()) == {"text_to_speech", "get_voices"}
        assert "error" in json.loads(toolkit.get_voices("invalid"))
        assert len(requests) == 1
    assert not SixtyDBTools(api_key="key", enable_text_to_speech=False, enable_get_voices=False).get_functions()
    assert (
        len(SixtyDBTools(api_key="key", enable_text_to_speech=False, enable_get_voices=False, all=True).get_functions())
        == 2
    )


@pytest.mark.parametrize(
    "catalog",
    [
        {"success": False, "message": "private-test-key"},
        {"success": True, "data": {}},
        {"success": True, "data": [None]},
    ],
)
def test_bad_catalog(catalog):
    with endpoint(json.dumps(catalog).encode(), "application/json") as (url, _):
        result = tool(url).get_voices()
    assert "error" in json.loads(result)
    assert "private-test-key" not in result


def test_timeout_and_response_limit(monkeypatch):
    with endpoint(delay=0.2) as (url, _):
        assert not tool(url, timeout=0.03).text_to_speech(Agent(), "Hello").audios
    monkeypatch.setattr(provider, "MAX_RESPONSE_BYTES", 100)
    with endpoint() as (url, _):
        assert not tool(url).text_to_speech(Agent(), "Hello").audios


def test_invalid_input_makes_no_request():
    with endpoint() as (url, requests):
        toolkit = tool(url)
        for text in ("", " ", "x" * 5001):
            assert not toolkit.text_to_speech(Agent(), text).audios
        assert not toolkit.text_to_speech(Agent(), "Hello", voice_id="").audios
        assert requests == []
    assert not SixtyDBTools(api_key="key").text_to_speech(Agent(), "Hello").audios


@pytest.mark.parametrize(
    "kwargs",
    [
        {"speed": float("nan")},
        {"speed": True},
        {"speed": 3},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"base_url": "http://example.com"},
        {"base_url": "https://user:pass@example.com"},
        {"base_url": "https://example.com?key=x"},
        {"default_voice_id": " "},
    ],
)
def test_configuration_validation(kwargs):
    with pytest.raises(ValueError):
        SixtyDBTools(api_key="key", **kwargs)


def test_environment_credentials(monkeypatch):
    monkeypatch.delenv("SIXTYDB_API_KEY", raising=False)
    with pytest.raises(ValueError):
        SixtyDBTools()
    monkeypatch.setenv("SIXTYDB_API_KEY", "environment-key")
    assert SixtyDBTools().api_key == "environment-key"
    assert SixtyDBTools(api_key="explicit-key").api_key == "explicit-key"
    with pytest.raises(ValueError):
        SixtyDBTools(api_key="")


def test_registered_tool_schema():
    tools = SixtyDBTools(api_key="private-test-key")
    speech = tools.functions["text_to_speech"]
    speech.process_entrypoint()
    assert set(speech.parameters["properties"]) == {"text", "voice_id"}
    assert speech.parameters["required"] == ["text"]
    voices = tools.functions["get_voices"]
    voices.process_entrypoint()
    assert voices.parameters["properties"]["model"]["enum"] == ["quality", "fast"]


@pytest.mark.parametrize("headers", [{"X-Sample-Rate": "16000"}, {"X-Channels": "2"}, {"X-Bit-Depth": "bad"}])
def test_invalid_http_audio_metadata(headers):
    with endpoint(headers=headers) as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert not result.audios


def test_ndjson_wav_chunks_preserve_all_audio():
    body = (
        b"\n".join(json.dumps({"audioContent": base64.b64encode(wav_bytes()).decode()}).encode() for _ in range(2))
        + b'\n{"type":"complete"}\n'
    )
    with endpoint(body, "application/x-ndjson") as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert result.audios
    with wave.open(io.BytesIO(result.audios[0].content), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == PCM * 2


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("pcm", [PCM, b"RIFF" + PCM], ids=["ordinary", "riff_samples"])
def test_ndjson_split_wav_preserves_audio(pcm, split):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(pcm)
    wav_payload = buffer.getvalue()
    chunks = [wav_payload[:13], wav_payload[13:45], wav_payload[45:]] if split else [wav_payload]
    body = b"\n".join(json.dumps({"audioContent": base64.b64encode(chunk).decode()}).encode() for chunk in chunks)
    with endpoint(body, "application/x-ndjson") as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert result.audios
    with wave.open(io.BytesIO(result.audios[0].content), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == pcm


@pytest.mark.parametrize(
    "chunks,expected",
    [
        ([wav_bytes(), PCM], PCM * 2),
        ([PCM, wav_bytes()], PCM * 2),
        ([b"\x01\x00", b"RIFF\x01\x00\x02\x00"], b"\x01\x00RIFF\x01\x00\x02\x00"),
    ],
    ids=["wav_first", "pcm_first", "riff_pcm"],
)
def test_ndjson_mixed_audio_records(chunks, expected):
    body = b"\n".join(json.dumps({"audioContent": base64.b64encode(chunk).decode()}).encode() for chunk in chunks)
    with endpoint(body, "application/x-ndjson") as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert result.audios
    with wave.open(io.BytesIO(result.audios[0].content), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == expected


@pytest.mark.parametrize("content_type", ["application/x-ndjson", "application/json"])
@pytest.mark.parametrize("encoding,signature", [("wav", b"NOPE"), ("pcm", b"WAVE")])
def test_ndjson_declared_format_controls_decoding(encoding, signature, content_type):
    payload = b"RIFF\x08\x00\x00\x00" + signature + b"abcd"
    body = json.dumps({"encoding": encoding, "audioContent": base64.b64encode(payload).decode()}).encode()
    with endpoint(body, content_type) as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    if encoding == "wav":
        assert not result.audios
    else:
        assert result.audios
        with wave.open(io.BytesIO(result.audios[0].content), "rb") as wav:
            assert wav.readframes(wav.getnframes()) == payload


def test_labeled_pcm_followed_by_unlabeled_wav():
    body = b"\n".join(
        [
            json.dumps({"encoding": "pcm", "audioContent": base64.b64encode(PCM).decode()}).encode(),
            json.dumps({"audioContent": base64.b64encode(wav_bytes()).decode()}).encode(),
        ]
    )
    with endpoint(body, "application/x-ndjson") as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert result.audios
    with wave.open(io.BytesIO(result.audios[0].content), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == PCM * 2


@pytest.mark.parametrize("tail", [b"ID3\x00", b"RIFF\x00\x00\x00\x00WAVE"])
def test_unlabeled_pcm_continuation_preserves_signature_samples(tail):
    body = b"\n".join(
        [
            json.dumps({"encoding": "pcm", "audioContent": base64.b64encode(PCM).decode()}).encode(),
            json.dumps({"audioContent": base64.b64encode(tail).decode()}).encode(),
        ]
    )
    with endpoint(body, "application/x-ndjson") as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert result.audios
    with wave.open(io.BytesIO(result.audios[0].content), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == PCM + tail


@pytest.mark.parametrize("content_type", ["application/json", "application/x-ndjson"])
@pytest.mark.parametrize("nested", [False, True])
def test_wav_container_precedes_linear16_sample_encoding(content_type, nested):
    audio = base64.b64encode(wav_bytes()).decode()
    if nested:
        audio = base64.b64encode(json.dumps({"audio_encoding": "LINEAR16", "audioContent": audio}).encode()).decode()
    body = json.dumps(
        {"output_format": "wav", "audio_config": {"audio_encoding": "LINEAR16"}, "audioContent": audio}
    ).encode()
    with endpoint(body, content_type) as (url, _):
        result = tool(url).text_to_speech(Agent(), "Hello")
    assert result.audios
    with wave.open(io.BytesIO(result.audios[0].content), "rb") as wav:
        assert wav.readframes(wav.getnframes()) == PCM
