import json
import subprocess
import sys
from typing import Any, Dict, List
from unittest.mock import patch

import httpx
import pytest

from agno.models.aimlapi.constants import AIMLAPI_HEADERS
from agno.tools.function import ToolResult
from agno.tools.models.aimlapi import AIMLAPITools


class Gateway:
    """Records every request and answers with the gateway's documented shapes."""

    def __init__(self):
        self.calls: List[httpx.Request] = []
        self.video_statuses = ["queued", "generating", "completed"]
        self.stt_statuses = ["queued", "completed"]
        self.poll_failures: List[int] = []  # HTTP statuses to answer polls with, before the real one
        self.asset_content_type = "image/png"
        self.transcript: Any = "hello from agno"
        self.error_shape: Any = {"message": "content policy"}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host, path = request.url.host, request.url.path
        if host == "cdn.example":
            assert "authorization" not in request.headers, "asset downloads must not carry the account key"
            if path.endswith(".mp4"):
                return httpx.Response(200, content=b"\x00mp4", headers={"content-type": "video/mp4"})
            if path.endswith(".mp3"):
                return httpx.Response(200, content=b"\x00mp3", headers={"content-type": "audio/mpeg"})
            return httpx.Response(200, content=b"\x89PNG", headers={"content-type": self.asset_content_type})
        if path == "/v1/images/generations":
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example/out.png"}]})
        if path == "/v2/video/generations" and request.method == "POST":
            return httpx.Response(200, json={"id": "gen-1", "status": self.video_statuses.pop(0)})
        if path == "/v2/video/generations":
            if self.poll_failures:
                return httpx.Response(self.poll_failures.pop(0), json={"message": "try later"})
            status = self.video_statuses.pop(0)
            body: Dict[str, Any] = {"id": "gen-1", "status": status}
            if status == "completed":
                body["video"] = {"url": "https://cdn.example/out.mp4"}
            if status == "error":
                body["error"] = self.error_shape
            return httpx.Response(200, json=body)
        if path == "/v1/tts":
            return httpx.Response(200, json={"audio": {"url": "https://cdn.example/out.mp3"}})
        if path == "/v1/stt/create":
            return httpx.Response(200, json={"generation_id": "stt-1", "status": self.stt_statuses.pop(0)})
        if path == "/v1/stt/stt-1":
            status = self.stt_statuses.pop(0)
            body = {"generation_id": "stt-1", "status": status}
            if status == "completed":
                body["result"] = {"results": {"channels": [{"alternatives": [{"transcript": self.transcript}]}]}}
            return httpx.Response(200, json=body)
        return httpx.Response(404, json={"message": f"no route for {request.method} {path}"})


@pytest.fixture
def gateway():
    gw = Gateway()
    transport = httpx.MockTransport(lambda request: gw.handle(request))

    def post(url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.post(url, **kwargs)

    def get(url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.get(url, **kwargs)

    real_async_client = httpx.AsyncClient

    def async_client(**kwargs):
        kwargs.pop("timeout", None)
        return real_async_client(transport=transport, **kwargs)

    with (
        patch("agno.tools.models.aimlapi.httpx.post", side_effect=post),
        patch("agno.tools.models.aimlapi.httpx.get", side_effect=get),
        patch("agno.tools.models.aimlapi.httpx.AsyncClient", side_effect=async_client),
        patch("agno.tools.models.aimlapi.time.sleep"),
    ):
        yield gw


def tools(**kwargs) -> AIMLAPITools:
    return AIMLAPITools(api_key="sk-test", **kwargs)


def paths(gateway: Gateway):
    return [(c.method, c.url.path) for c in gateway.calls]


# --- construction --------------------------------------------------------------


def test_reads_key_from_env(monkeypatch):
    monkeypatch.setenv("AIMLAPI_API_KEY", "sk-env")
    assert AIMLAPITools().api_key == "sk-env"


def test_requires_a_key(monkeypatch):
    monkeypatch.delenv("AIMLAPI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AIMLAPI_API_KEY not set"):
        AIMLAPITools()


def test_rejects_an_unknown_speech_format():
    with pytest.raises(ValueError, match="speech_format"):
        tools(speech_format="ogg")


def test_registers_every_tool_with_async_variants():
    t = tools()
    assert set(t.functions) == {"generate_image", "generate_video", "generate_speech", "transcribe_audio"}
    assert set(t.async_functions) == set(t.functions)


def test_flags_select_tools():
    t = tools(enable_generate_video=False, enable_generate_speech=False, enable_transcribe_audio=False)
    assert list(t.functions) == ["generate_image"]
    assert set(tools(enable_generate_image=False, all=True).functions) == {
        "generate_image",
        "generate_video",
        "generate_speech",
        "transcribe_audio",
    }


def test_timeout_reaches_the_toolkit_and_the_requests():
    t = tools(timeout=15)
    assert t.timeout == 15
    assert t.request_timeout == 15


def test_accepts_the_chat_models_versioned_base_url():
    assert tools(base_url="https://api.aimlapi.com/v1").base_url == "https://api.aimlapi.com"
    assert tools(base_url="https://api.aimlapi.com/v1/").base_url == "https://api.aimlapi.com"
    assert tools(base_url="https://proxy.example/aimlapi").base_url == "https://proxy.example/aimlapi"


def test_importing_the_toolkit_does_not_need_openai():
    code = "import sys; sys.modules['openai'] = None; import agno.tools.models.aimlapi; print('ok')"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ok"


# --- attribution ---------------------------------------------------------------


def test_attribution_headers_ride_calls_to_the_gateway(gateway):
    tools().generate_image("a cat")
    submit = gateway.calls[0]
    assert submit.headers["authorization"] == "Bearer sk-test"
    for key, value in AIMLAPI_HEADERS.items():
        assert submit.headers[key] == value


def test_attribution_headers_stay_off_a_proxy(gateway):
    tools(base_url="https://proxy.example/aimlapi/").generate_speech("hi")
    submit = gateway.calls[0]
    assert submit.url.path == "/aimlapi/v1/tts"
    assert submit.headers["authorization"] == "Bearer sk-test"
    assert not any(key.lower().startswith("x-aimlapi-") for key in submit.headers)


# --- generate_image ------------------------------------------------------------


def test_generate_image_downloads_the_asset(gateway):
    result = tools(image_size="1024x1024").generate_image("a cat")
    assert isinstance(result, ToolResult)
    assert result.content == "Image generated successfully."
    image = result.images[0]
    assert (image.content, image.mime_type, image.format, image.original_prompt) == (
        b"\x89PNG",
        "image/png",
        "png",
        "a cat",
    )
    assert json.loads(gateway.calls[0].content) == {
        "model": "openai/gpt-image-2",
        "prompt": "a cat",
        "size": "1024x1024",
    }


@pytest.mark.asyncio
async def test_agenerate_image_matches_the_sync_tool(gateway):
    result = await tools().agenerate_image("a cat")
    assert result.content == "Image generated successfully."
    assert result.images[0].format == "png"
    assert paths(gateway) == [("POST", "/v1/images/generations"), ("GET", "/out.png")]


def test_octet_stream_assets_are_typed_from_the_url(gateway):
    gateway.asset_content_type = "application/octet-stream"
    image = tools().generate_image("a cat").images[0]
    assert (image.mime_type, image.format) == ("image/png", "png")


def test_generate_image_reports_gateway_errors(gateway):
    gateway.handle = lambda request: httpx.Response(400, json={"message": "Validation failed"})
    result = tools().generate_image("a cat")
    assert result.content == "Failed to generate image: AI/ML API returned HTTP 400: Validation failed"
    assert not result.images


def test_string_shaped_errors_are_readable(gateway):
    gateway.handle = lambda request: httpx.Response(400, json={"error": "bad prompt"})
    assert tools().generate_image("a cat").content.endswith("HTTP 400: bad prompt")


# --- generate_video ------------------------------------------------------------


def test_generate_video_submits_polls_and_collects(gateway):
    result = tools(video_duration=4, video_resolution="480p").generate_video("a boat")
    assert result.content == "Video generated successfully."
    video = result.videos[0]
    assert (video.content, video.mime_type, video.format) == (b"\x00mp4", "video/mp4", "mp4")
    assert paths(gateway) == [
        ("POST", "/v2/video/generations"),
        ("GET", "/v2/video/generations"),
        ("GET", "/v2/video/generations"),
        ("GET", "/out.mp4"),
    ]
    assert dict(gateway.calls[1].url.params) == {"generation_id": "gen-1"}
    assert json.loads(gateway.calls[0].content) == {
        "model": "bytedance/seedance-2-5",
        "prompt": "a boat",
        "duration": 4,
        "resolution": "480p",
    }


@pytest.mark.asyncio
async def test_agenerate_video_polls_without_blocking(gateway):
    with patch("agno.tools.models.aimlapi.asyncio.sleep") as sleep:
        result = await tools().agenerate_video("a boat")
    assert result.content == "Video generated successfully."
    assert result.videos[0].format == "mp4"
    assert sleep.await_count == 2
    assert paths(gateway)[-1] == ("GET", "/out.mp4")


def test_generate_video_reports_a_failed_job(gateway):
    gateway.video_statuses = ["queued", "error"]
    result = tools().generate_video("a boat")
    assert result.content == "Failed to generate video: content policy"
    assert not result.videos


def test_generate_video_reports_a_string_error(gateway):
    gateway.video_statuses = ["queued", "error"]
    gateway.error_shape = "quota exhausted"
    assert tools().generate_video("a boat").content == "Failed to generate video: quota exhausted"


def test_generate_video_stops_on_an_unknown_status(gateway):
    gateway.video_statuses = ["queued", "cancelled"] + ["cancelled"] * 50
    result = tools().generate_video("a boat")
    assert result.content == "Failed to generate video: job ended with status 'cancelled'"
    assert paths(gateway).count(("GET", "/v2/video/generations")) == 1


def test_generate_video_retries_a_transient_poll_error(gateway):
    gateway.poll_failures = [503, 429]
    result = tools().generate_video("a boat")
    assert result.content == "Video generated successfully."
    assert paths(gateway).count(("GET", "/v2/video/generations")) == 4


def test_generate_video_gives_up_on_a_persistent_poll_error(gateway):
    gateway.poll_failures = [503, 503, 503, 503]
    result = tools().generate_video("a boat")
    assert result.content == "Failed to generate video: AI/ML API returned HTTP 503: try later"


def test_generate_video_gives_up_after_the_timeout(gateway):
    gateway.video_statuses = ["queued"] * 50
    with patch("agno.tools.models.aimlapi.time.monotonic", side_effect=[0, 0, 1000]):
        result = tools(video_timeout=10).generate_video("a boat")
    assert result.content == "Failed to generate video: video generation still running after 10s"


# --- generate_speech -----------------------------------------------------------


def test_generate_speech_returns_audio(gateway):
    result = tools(speech_voice="nova", speech_speed=1.2).generate_speech("hello")
    assert result.content.startswith("Speech generated successfully with ID: ")
    audio = result.audios[0]
    assert (audio.content, audio.mime_type, audio.format) == (b"\x00mp3", "audio/mpeg", "mp3")
    assert json.loads(gateway.calls[0].content) == {
        "model": "openai/tts-1",
        "text": "hello",
        "response_format": "mp3",
        "voice": "nova",
        "speed": 1.2,
    }


@pytest.mark.asyncio
async def test_agenerate_speech_returns_audio(gateway):
    result = await tools().agenerate_speech("hello")
    assert result.audios[0].format == "mp3"


# --- transcribe_audio ----------------------------------------------------------


def test_transcribe_audio_uploads_a_file_from_the_base_dir(gateway, tmp_path):
    (tmp_path / "clip.mp3").write_bytes(b"\x00mp3")
    assert tools(base_dir=tmp_path).transcribe_audio("clip.mp3") == "hello from agno"
    submit = gateway.calls[0]
    assert submit.url.path == "/v1/stt/create"
    assert submit.headers["content-type"].startswith("multipart/form-data")
    assert b'name="model"' in submit.content and b"deepgram/nova-3" in submit.content
    assert b'filename="clip.mp3"' in submit.content
    assert paths(gateway)[1:] == [("GET", "/v1/stt/stt-1")]


@pytest.mark.asyncio
async def test_atranscribe_audio_uploads_a_file(gateway, tmp_path):
    (tmp_path / "clip.mp3").write_bytes(b"\x00mp3")
    assert await tools(base_dir=tmp_path).atranscribe_audio("clip.mp3") == "hello from agno"
    assert paths(gateway) == [("POST", "/v1/stt/create"), ("GET", "/v1/stt/stt-1")]


def test_transcribe_audio_refuses_paths_outside_the_base_dir(gateway, tmp_path):
    secret = tmp_path / "secret.key"
    secret.write_bytes(b"private")
    sandbox = tmp_path / "audio"
    sandbox.mkdir()
    result = tools(base_dir=sandbox).transcribe_audio("../secret.key")
    assert result.startswith("Failed to transcribe audio: ")
    assert "outside the allowed directory" in result
    assert gateway.calls == []


def test_transcribe_audio_passes_a_url_through(gateway):
    assert tools(transcription_language="en").transcribe_audio("https://files.example/clip.mp3") == "hello from agno"
    assert json.loads(gateway.calls[0].content) == {
        "model": "deepgram/nova-3",
        "language": "en",
        "url": "https://files.example/clip.mp3",
    }


def test_an_empty_transcript_is_a_transcript(gateway):
    gateway.transcript = ""
    assert tools().transcribe_audio("https://files.example/silence.mp3") == ""


def test_transcribe_audio_reports_a_missing_file(gateway, tmp_path):
    assert tools(base_dir=tmp_path).transcribe_audio("nowhere.mp3").startswith("Failed to transcribe audio: ")
    assert gateway.calls == []
