import json
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import httpx
import pytest

from agno.models.aimlapi.constants import AIMLAPI_HEADERS
from agno.tools.function import ToolResult
from agno.tools.models.aimlapi import AIMLAPITools


class Gateway:
    """Records every request and answers with the gateway's documented shapes."""

    def __init__(self, video_statuses: Optional[List[str]] = None, stt_statuses: Optional[List[str]] = None):
        self.calls: List[httpx.Request] = []
        self.video_statuses = list(video_statuses or ["queued", "generating", "completed"])
        self.stt_statuses = list(stt_statuses or ["queued", "completed"])

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        host, path = request.url.host, request.url.path
        if host == "cdn.example":
            assert "authorization" not in request.headers, "asset downloads must not carry the account key"
            if path.endswith(".mp4"):
                return httpx.Response(200, content=b"\x00mp4", headers={"content-type": "video/mp4"})
            if path.endswith(".mp3"):
                return httpx.Response(200, content=b"\x00mp3", headers={"content-type": "audio/mpeg"})
            return httpx.Response(200, content=b"\x89PNG", headers={"content-type": "image/png"})
        if path == "/v1/images/generations":
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example/out.png"}]})
        if path == "/v2/video/generations" and request.method == "POST":
            return httpx.Response(200, json={"id": "gen-1", "status": self.video_statuses.pop(0)})
        if path == "/v2/video/generations":
            status = self.video_statuses.pop(0)
            body: Dict[str, Any] = {"id": "gen-1", "status": status}
            if status == "completed":
                body["video"] = {"url": "https://cdn.example/out.mp4"}
            if status == "error":
                body["error"] = {"message": "content policy"}
            return httpx.Response(200, json=body)
        if path == "/v1/tts":
            return httpx.Response(200, json={"audio": {"url": "https://cdn.example/out.mp3"}})
        if path == "/v1/stt/create":
            return httpx.Response(200, json={"generation_id": "stt-1", "status": self.stt_statuses.pop(0)})
        if path == "/v1/stt/stt-1":
            status = self.stt_statuses.pop(0)
            body = {"generation_id": "stt-1", "status": status}
            if status == "completed":
                body["result"] = {"results": {"channels": [{"alternatives": [{"transcript": "hello from agno"}]}]}}
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

    with (
        patch("agno.tools.models.aimlapi.httpx.post", side_effect=post),
        patch("agno.tools.models.aimlapi.httpx.get", side_effect=get),
        patch("agno.tools.models.aimlapi.time.sleep"),
    ):
        yield gw


def tools(**kwargs) -> AIMLAPITools:
    return AIMLAPITools(api_key="sk-test", **kwargs)


# --- construction --------------------------------------------------------------


def test_reads_key_from_env(monkeypatch):
    monkeypatch.setenv("AIMLAPI_API_KEY", "sk-env")
    assert AIMLAPITools().api_key == "sk-env"


def test_requires_a_key(monkeypatch):
    monkeypatch.delenv("AIMLAPI_API_KEY", raising=False)
    with pytest.raises(ValueError, match="AIMLAPI_API_KEY not set"):
        AIMLAPITools()


def test_registers_every_tool_by_default():
    assert set(tools().functions) == {"generate_image", "generate_video", "generate_speech", "transcribe_audio"}


def test_flags_select_tools():
    t = tools(enable_generate_video=False, enable_generate_speech=False, enable_transcribe_audio=False)
    assert list(t.functions) == ["generate_image"]
    assert set(tools(enable_generate_image=False, all=True).functions) == {
        "generate_image",
        "generate_video",
        "generate_speech",
        "transcribe_audio",
    }


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
    assert result.images and result.images[0].content == b"\x89PNG"
    assert result.images[0].mime_type == "image/png"
    assert result.images[0].original_prompt == "a cat"
    assert json.loads(gateway.calls[0].content) == {
        "model": "openai/gpt-image-2",
        "prompt": "a cat",
        "size": "1024x1024",
    }


def test_generate_image_reports_gateway_errors(gateway):
    gateway.handle = lambda request: httpx.Response(400, json={"message": "Validation failed"})
    result = tools().generate_image("a cat")
    assert result.content == "Failed to generate image: AI/ML API returned HTTP 400: Validation failed"
    assert not result.images


# --- generate_video ------------------------------------------------------------


def test_generate_video_submits_polls_and_collects(gateway):
    result = tools(video_duration=4, video_resolution="480p").generate_video("a boat")
    assert result.content == "Video generated successfully."
    assert result.videos and result.videos[0].content == b"\x00mp4"
    assert result.videos[0].mime_type == "video/mp4"
    paths = [(c.method, c.url.path, dict(c.url.params)) for c in gateway.calls]
    assert paths == [
        ("POST", "/v2/video/generations", {}),
        ("GET", "/v2/video/generations", {"generation_id": "gen-1"}),
        ("GET", "/v2/video/generations", {"generation_id": "gen-1"}),
        ("GET", "/out.mp4", {}),
    ]
    assert json.loads(gateway.calls[0].content) == {
        "model": "bytedance/seedance-2-5",
        "prompt": "a boat",
        "duration": 4,
        "resolution": "480p",
    }


def test_generate_video_reports_a_failed_job(gateway):
    gateway.video_statuses = ["queued", "error"]
    result = tools().generate_video("a boat")
    assert result.content == "Failed to generate video: content policy"
    assert not result.videos


def test_generate_video_gives_up_after_the_timeout(gateway):
    gateway.video_statuses = ["queued"] * 50
    with patch("agno.tools.models.aimlapi.time.monotonic", side_effect=[0, 0, 1000]):
        result = tools(video_timeout=10).generate_video("a boat")
    assert result.content == "Failed to generate video: still queued after 10s."


# --- generate_speech -----------------------------------------------------------


def test_generate_speech_returns_audio(gateway):
    result = tools(speech_voice="nova", speech_speed=1.2).generate_speech("hello")
    assert result.content.startswith("Speech generated successfully with ID: ")
    assert result.audios and result.audios[0].content == b"\x00mp3"
    assert result.audios[0].mime_type == "audio/mpeg"
    assert json.loads(gateway.calls[0].content) == {
        "model": "openai/tts-1",
        "text": "hello",
        "response_format": "mp3",
        "voice": "nova",
        "speed": 1.2,
    }


# --- transcribe_audio ----------------------------------------------------------


def test_transcribe_audio_uploads_a_local_file(gateway, tmp_path):
    audio = tmp_path / "clip.mp3"
    audio.write_bytes(b"\x00mp3")
    assert tools().transcribe_audio(str(audio)) == "hello from agno"
    submit = gateway.calls[0]
    assert submit.url.path == "/v1/stt/create"
    assert submit.headers["content-type"].startswith("multipart/form-data")
    assert b'name="model"' in submit.content and b"deepgram/nova-3" in submit.content
    assert b'filename="clip.mp3"' in submit.content
    assert [c.url.path for c in gateway.calls[1:]] == ["/v1/stt/stt-1"]


def test_transcribe_audio_passes_a_url_through(gateway):
    assert tools(transcription_language="en").transcribe_audio("https://files.example/clip.mp3") == "hello from agno"
    assert json.loads(gateway.calls[0].content) == {
        "model": "deepgram/nova-3",
        "language": "en",
        "url": "https://files.example/clip.mp3",
    }


def test_transcribe_audio_reports_a_missing_file(gateway):
    assert tools().transcribe_audio("/nowhere/clip.mp3").startswith("Failed to transcribe audio: ")
    assert gateway.calls == []
