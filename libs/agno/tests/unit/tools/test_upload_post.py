"""Unit tests for UploadPostTools. All HTTP goes through httpx.MockTransport, no network."""

import json
from typing import Callable, Dict, List
from urllib.parse import parse_qs

import httpx
import pytest

from agno.tools import upload_post as upload_post_module
from agno.tools.upload_post import UploadPostTools

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv("UPLOAD_POST_API_KEY", raising=False)
    monkeypatch.delenv("UPLOAD_POST_USER", raising=False)


class Recorder:
    """Routes requests to per-path handlers and records every call."""

    def __init__(self, routes: Dict[str, List[httpx.Response]]):
        self.routes = routes
        self.calls: List[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        queue = self.routes.get(request.url.path)
        if not queue:
            raise AssertionError(f"Unexpected request to {request.url.path}")
        response = queue[0] if len(queue) == 1 else queue.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def calls_to(self, path: str) -> List[httpx.Request]:
        return [c for c in self.calls if c.url.path == path]


@pytest.fixture
def mock_http(monkeypatch):
    """Install a recorder behind both httpx.Client and httpx.AsyncClient."""

    def install(routes: Dict[str, list]) -> Recorder:
        recorder = Recorder(routes)
        real_client, real_async_client = httpx.Client, httpx.AsyncClient
        transport = httpx.MockTransport(recorder)
        monkeypatch.setattr(upload_post_module.httpx, "Client", lambda **kw: real_client(transport=transport, **kw))
        monkeypatch.setattr(
            upload_post_module.httpx, "AsyncClient", lambda **kw: real_async_client(transport=transport, **kw)
        )
        return recorder

    return install


def make_tools(**kwargs) -> UploadPostTools:
    kwargs.setdefault("api_key", "test_key")
    kwargs.setdefault("user", "creator")
    kwargs.setdefault("poll_interval", 0)
    kwargs.setdefault("max_wait", 1)
    return UploadPostTools(**kwargs)


@pytest.fixture
def video_file(tmp_path):
    path = tmp_path / "short.mp4"
    path.write_bytes(b"fake-mp4-bytes")
    return str(path)


COMPLETED = {
    "status": "completed",
    "results": [
        {
            "platform": "youtube",
            "success": True,
            "platform_post_id": "abc123",
            "post_url": "Post uploaded as Private. No public URL available.",
        },
        {"platform": "tiktok", "success": True, "post_url": "https://www.tiktok.com/@a/video/1"},
        {"platform": "linkedin", "success": False, "skipped": True, "error_message": "No account"},
    ],
}


# ============================================================================
# INITIALIZATION
# ============================================================================


def test_init_reads_env(monkeypatch):
    monkeypatch.setenv("UPLOAD_POST_API_KEY", "env_key")
    monkeypatch.setenv("UPLOAD_POST_USER", "env_user")
    tools = UploadPostTools()
    assert tools.api_key == "env_key"
    assert tools.user == "env_user"


def test_publishing_tools_require_confirmation_by_default():
    tools = make_tools()
    assert set(tools.requires_confirmation_tools) == {"upload_video", "upload_photos", "upload_text"}
    assert tools.functions["upload_video"].requires_confirmation is True
    assert tools.functions["get_upload_status"].requires_confirmation is not True


def test_confirmation_can_be_disabled():
    tools = make_tools(requires_confirmation_tools=[])
    assert tools.requires_confirmation_tools == []


def test_tool_flags_register_sync_and_async():
    tools = make_tools(enable_upload_photos=False, enable_upload_text=False)
    assert set(tools.functions) == {"upload_video", "get_upload_status", "list_profiles"}
    assert set(tools.async_functions) == {"upload_video", "get_upload_status", "list_profiles"}
    assert tools.requires_confirmation_tools == ["upload_video"]


def test_missing_api_key_or_user_is_rejected_without_network(mock_http, video_file):
    recorder = mock_http({})
    no_key = json.loads(UploadPostTools(user="creator").upload_video(video_file, "t", ["tiktok"]))
    no_user = json.loads(UploadPostTools(api_key="k").upload_video(video_file, "t", ["tiktok"]))
    assert no_key["status"] == "rejected" and "UPLOAD_POST_API_KEY" in no_key["error"]
    assert no_user["status"] == "rejected" and "UPLOAD_POST_USER" in no_user["error"]
    assert recorder.calls == []


# ============================================================================
# REQUEST SHAPE
# ============================================================================


def test_video_request_shape(mock_http, video_file):
    recorder = mock_http(
        {
            "/api/upload": [httpx.Response(200, json={"success": True})],
            "/api/uploadposts/status": [httpx.Response(200, json=COMPLETED)],
        }
    )
    make_tools().upload_video(video_file, "My short", ["TikTok", "youtube"], tiktok_privacy="SELF_ONLY")

    post = recorder.calls_to("/api/upload")[0]
    body = post.content.decode(errors="ignore")
    assert post.headers["Authorization"] == "Apikey test_key"
    request_id = post.headers["Idempotency-Key"]
    assert f'name="request_id"\r\n\r\n{request_id}' in body
    assert body.count('name="platform[]"') == 2
    assert 'name="privacyStatus"\r\n\r\nprivate' in body
    assert 'name="privacy_level"\r\n\r\nSELF_ONLY' in body
    assert 'name="async_upload"\r\n\r\ntrue' in body
    assert 'filename="short.mp4"' in body
    # the status poll uses the same id
    status = recorder.calls_to("/api/uploadposts/status")[0]
    assert status.url.params["request_id"] == request_id


def test_video_url_is_sent_as_a_field(mock_http):
    recorder = mock_http(
        {
            "/api/upload": [httpx.Response(200, json={"success": True})],
            "/api/uploadposts/status": [httpx.Response(200, json=COMPLETED)],
        }
    )
    make_tools().upload_video("https://cdn.example.com/v.mp4", "t", ["x"])
    post = recorder.calls_to("/api/upload")[0]
    # no file to send, so the form goes urlencoded
    assert post.headers["Content-Type"] == "application/x-www-form-urlencoded"
    form = parse_qs(post.content.decode())
    assert form["video"] == ["https://cdn.example.com/v.mp4"]
    assert "privacyStatus" not in form  # only sent when YouTube is a target


def test_missing_local_file_is_rejected_without_network(mock_http):
    recorder = mock_http({})
    result = json.loads(make_tools().upload_video("/nope/missing.mp4", "t", ["tiktok"]))
    assert result["status"] == "rejected"
    assert recorder.calls == []


def test_photos_and_text_use_their_endpoints(mock_http, tmp_path):
    img = tmp_path / "a.jpg"
    img.write_bytes(b"jpg")
    recorder = mock_http(
        {
            "/api/upload_photos": [httpx.Response(200, json={"success": True})],
            "/api/upload_text": [httpx.Response(200, json={"success": True})],
            "/api/uploadposts/status": [httpx.Response(200, json=COMPLETED)],
        }
    )
    tools = make_tools()
    tools.upload_photos([str(img), "https://cdn.example.com/b.jpg"], "Carousel", ["instagram"])
    tools.upload_text("Hello", ["bluesky", "x"])

    photos_body = recorder.calls_to("/api/upload_photos")[0].content.decode(errors="ignore")
    assert 'filename="a.jpg"' in photos_body
    assert 'name="photos[]"\r\n\r\nhttps://cdn.example.com/b.jpg' in photos_body
    text_form = parse_qs(recorder.calls_to("/api/upload_text")[0].content.decode())
    assert text_form["title"] == ["Hello"]
    assert text_form["platform[]"] == ["bluesky", "x"]


# ============================================================================
# OUTCOMES
# ============================================================================


def test_success_summarizes_each_platform(mock_http, video_file):
    mock_http(
        {
            "/api/upload": [httpx.Response(200, json={"success": True})],
            "/api/uploadposts/status": [
                httpx.Response(200, json={"status": "processing", "results": []}),
                httpx.Response(200, json=COMPLETED),
            ],
        }
    )
    result = json.loads(make_tools(max_wait=5).upload_video(video_file, "t", ["youtube", "tiktok", "linkedin"]))
    assert result["status"] == "completed"
    assert result["summary"] == {"completed": 2, "skipped": 1}
    by_platform = {r["platform"]: r for r in result["results"]}
    assert by_platform["youtube"]["url"] is None
    assert by_platform["youtube"]["post_id"] == "abc123"
    assert "Private" in by_platform["youtube"]["note"]
    assert by_platform["tiktok"]["url"] == "https://www.tiktok.com/@a/video/1"
    assert by_platform["linkedin"]["status"] == "skipped"


@pytest.mark.parametrize("code", [400, 401, 403, 422])
def test_definitive_rejections_do_not_poll(mock_http, video_file, code):
    recorder = mock_http({"/api/upload": [httpx.Response(code, json={"message": "bad input"})]})
    result = json.loads(make_tools().upload_video(video_file, "t", ["tiktok"]))
    assert result["status"] == "rejected"
    assert result["http_status"] == code
    assert result["error"] == "bad input"
    assert recorder.calls_to("/api/uploadposts/status") == []


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(502, text="Bad Gateway"),
        httpx.Response(200, text=""),
        httpx.Response(200, text="<html>proxy page</html>"),
        httpx.ReadTimeout("timed out"),
        httpx.ConnectError("connection reset"),
    ],
    ids=["5xx", "empty-2xx", "non-json-2xx", "timeout", "transport-error"],
)
def test_ambiguous_failures_poll_the_same_id_and_never_resend(mock_http, video_file, response):
    recorder = mock_http(
        {
            "/api/upload": [response],
            "/api/uploadposts/status": [httpx.Response(200, json=COMPLETED)],
        }
    )
    result = json.loads(make_tools().upload_video(video_file, "t", ["tiktok"]))
    assert result["status"] == "completed"
    assert len(recorder.calls_to("/api/upload")) == 1
    sent_id = recorder.calls_to("/api/upload")[0].headers["Idempotency-Key"]
    assert recorder.calls_to("/api/uploadposts/status")[0].url.params["request_id"] == sent_id


def test_ambiguous_failure_with_no_trace_returns_unknown(mock_http, video_file):
    recorder = mock_http(
        {
            "/api/upload": [httpx.ReadTimeout("timed out")],
            "/api/uploadposts/status": [httpx.Response(404, json={"status": "not_found"})],
        }
    )
    result = json.loads(make_tools().upload_video(video_file, "t", ["tiktok"]))
    assert result["status"] == "unknown"
    assert result["request_id"] == recorder.calls_to("/api/upload")[0].headers["Idempotency-Key"]
    assert "Do NOT publish again" in result["message"]
    assert len(recorder.calls_to("/api/upload")) == 1


def test_status_endpoint_down_after_ambiguous_failure_returns_unknown(mock_http, video_file):
    mock_http(
        {
            "/api/upload": [httpx.Response(503, text="")],
            "/api/uploadposts/status": [httpx.ConnectError("down")],
        }
    )
    result = json.loads(make_tools().upload_video(video_file, "t", ["tiktok"]))
    assert result["status"] == "unknown"


def test_scheduled_upload_returns_job_without_polling(mock_http, video_file):
    recorder = mock_http(
        {
            "/api/upload": [
                httpx.Response(202, json={"success": True, "job_id": "job-1", "scheduled_date": "2026-10-01"})
            ]
        }
    )
    result = json.loads(make_tools().upload_video(video_file, "t", ["x"], scheduled_date="2026-10-01T09:00:00Z"))
    assert result["status"] == "scheduled"
    assert result["job_id"] == "job-1"
    assert recorder.calls_to("/api/uploadposts/status") == []


def test_wait_timeout_says_not_to_publish_again(mock_http, video_file):
    mock_http(
        {
            "/api/upload": [httpx.Response(200, json={"success": True})],
            "/api/uploadposts/status": [httpx.Response(200, json={"status": "processing", "results": []})],
        }
    )
    result = json.loads(make_tools(max_wait=0).upload_video(video_file, "t", ["tiktok"]))
    assert result["status"] == "processing"
    assert "do NOT publish again" in result["message"]


def test_wait_for_result_false_returns_request_id(mock_http, video_file):
    recorder = mock_http({"/api/upload": [httpx.Response(200, json={"success": True})]})
    result = json.loads(make_tools(wait_for_result=False).upload_video(video_file, "t", ["tiktok"]))
    assert result["status"] == "submitted"
    assert result["request_id"] == recorder.calls[0].headers["Idempotency-Key"]


# ============================================================================
# STATUS AND PROFILES
# ============================================================================


def test_get_upload_status(mock_http):
    recorder = mock_http({"/api/uploadposts/status": [httpx.Response(200, json=COMPLETED)]})
    tools = make_tools()
    result = json.loads(tools.get_upload_status(request_id="r1"))
    assert result["status"] == "completed"
    tools.get_upload_status(job_id="j1")
    assert recorder.calls[1].url.params["job_id"] == "j1"
    assert json.loads(tools.get_upload_status())["error"]


def test_get_upload_status_not_found(mock_http):
    mock_http({"/api/uploadposts/status": [httpx.Response(404, json={"status": "not_found"})]})
    assert json.loads(make_tools().get_upload_status(request_id="nope"))["status"] == "not_found"


def test_list_profiles(mock_http):
    mock_http(
        {
            "/api/uploadposts/users": [
                httpx.Response(
                    200,
                    json={
                        "profiles": [
                            {"username": "creator", "social_accounts": {"tiktok": {"handle": "a"}, "x": ""}},
                        ]
                    },
                )
            ]
        }
    )
    result = json.loads(make_tools().list_profiles())
    assert result["profiles"] == [{"user": "creator", "connected_platforms": ["tiktok"]}]


# ============================================================================
# ASYNC
# ============================================================================


@pytest.mark.asyncio
async def test_async_success(mock_http, video_file):
    recorder = mock_http(
        {
            "/api/upload": [httpx.Response(200, json={"success": True})],
            "/api/uploadposts/status": [httpx.Response(200, json=COMPLETED)],
        }
    )
    result = json.loads(await make_tools().aupload_video(video_file, "t", ["youtube"]))
    assert result["status"] == "completed"
    assert 'filename="short.mp4"' in recorder.calls_to("/api/upload")[0].content.decode(errors="ignore")


@pytest.mark.asyncio
async def test_async_ambiguous_failure_is_unknown_and_not_resent(mock_http, video_file):
    recorder = mock_http(
        {
            "/api/upload": [httpx.ReadTimeout("timed out")],
            "/api/uploadposts/status": [httpx.Response(404, json={"status": "not_found"})],
        }
    )
    result = json.loads(await make_tools().aupload_video(video_file, "t", ["tiktok"]))
    assert result["status"] == "unknown"
    assert len(recorder.calls_to("/api/upload")) == 1


@pytest.mark.asyncio
async def test_async_rejection_text_status_and_profiles(mock_http):
    mock_http(
        {
            "/api/upload_text": [httpx.Response(401, json={"message": "Invalid API key"})],
            "/api/uploadposts/status": [httpx.Response(200, json=COMPLETED)],
            "/api/uploadposts/users": [httpx.Response(200, json={"profiles": []})],
        }
    )
    tools = make_tools()
    rejected = json.loads(await tools.aupload_text("Hello", ["bluesky"]))
    assert rejected["status"] == "rejected" and rejected["http_status"] == 401
    assert json.loads(await tools.aget_upload_status(request_id="r1"))["status"] == "completed"
    assert json.loads(await tools.alist_profiles()) == {"profiles": []}
