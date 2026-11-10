import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.getyoutubetranscript import GetYouTubeTranscriptTools

BASE = "https://getyoutubetranscript.com/api/v1"


def _response(payload, status_code=200):
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = payload
    response.text = json.dumps(payload)
    return response


def _sync_client(mock_client_class, response):
    client = mock_client_class.return_value.__enter__.return_value
    client.get.return_value = response
    return client


def test_default_registers_only_transcript_tool():
    tools = GetYouTubeTranscriptTools(api_key="test-key")

    assert tools.name == "getyoutubetranscript_tools"
    assert set(tools.functions) == {"get_youtube_transcript"}
    assert set(tools.async_functions) == {"get_youtube_transcript"}


def test_all_registers_every_tool():
    tools = GetYouTubeTranscriptTools(api_key="test-key", all=True)

    assert set(tools.functions) == {"get_youtube_transcript", "search_youtube", "list_channel_videos"}
    assert set(tools.async_functions) == set(tools.functions)


def test_individual_flags():
    tools = GetYouTubeTranscriptTools(
        api_key="test-key", enable_get_transcript=False, enable_search=True, enable_list_channel_videos=True
    )

    assert set(tools.functions) == {"search_youtube", "list_channel_videos"}


def test_api_key_falls_back_to_environment():
    with patch.dict("os.environ", {"GETYOUTUBETRANSCRIPT_API_KEY": "env-key"}):
        tools = GetYouTubeTranscriptTools()

    assert tools.api_key == "env-key"


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_missing_api_key_returns_error_without_request(mock_client_class):
    with patch.dict("os.environ", {}, clear=True):
        tools = GetYouTubeTranscriptTools()

    result = json.loads(tools.get_youtube_transcript("5e37ZT3SQbk"))

    assert "GETYOUTUBETRANSCRIPT_API_KEY" in result["error"]
    mock_client_class.assert_not_called()


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_get_transcript_sends_auth_and_params_and_unwraps_data(mock_client_class):
    data = {"video_id": "5e37ZT3SQbk", "title": "T", "transcript": "hello", "language_code": "en"}
    client = _sync_client(mock_client_class, _response({"success": True, "data": data}))
    tools = GetYouTubeTranscriptTools(api_key="test-key", base_url=f"{BASE}/")

    result = tools.get_youtube_transcript(" https://youtu.be/5e37ZT3SQbk ", language="es", timestamps=True)

    assert json.loads(result) == data
    client.get.assert_called_once_with(
        f"{BASE}/transcript",
        headers={"Authorization": "Bearer test-key", "Accept": "application/json"},
        params={"v": "https://youtu.be/5e37ZT3SQbk", "language": "es", "timestamps": "true"},
    )


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_get_transcript_omits_optional_params_by_default(mock_client_class):
    client = _sync_client(mock_client_class, _response({"success": True, "data": {"transcript": "x"}}))
    tools = GetYouTubeTranscriptTools(api_key="test-key")

    tools.get_youtube_transcript("5e37ZT3SQbk")

    assert client.get.call_args.kwargs["params"] == {"v": "5e37ZT3SQbk"}


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_get_transcript_rejects_empty_video(mock_client_class):
    tools = GetYouTubeTranscriptTools(api_key="test-key")

    result = json.loads(tools.get_youtube_transcript("  "))

    assert "video" in result["error"].lower()
    mock_client_class.assert_not_called()


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_search_defaults_to_video_type(mock_client_class):
    data = {"video_results": [{"video_id": "abc"}], "continuation_token": "tok"}
    client = _sync_client(mock_client_class, _response({"success": True, "data": data}))
    tools = GetYouTubeTranscriptTools(api_key="test-key", enable_search=True)

    result = tools.search_youtube("agno agents")

    assert json.loads(result) == data
    assert client.get.call_args.args[0] == f"{BASE}/search"
    assert client.get.call_args.kwargs["params"] == {"q": "agno agents", "type": "video"}


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_search_page_token_replaces_query(mock_client_class):
    client = _sync_client(mock_client_class, _response({"success": True, "data": {"video_results": []}}))
    tools = GetYouTubeTranscriptTools(api_key="test-key", enable_search=True)

    tools.search_youtube("ignored", type="channel", page_token="tok")

    assert client.get.call_args.kwargs["params"] == {"page_token": "tok"}


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_search_validates_input_without_request(mock_client_class):
    tools = GetYouTubeTranscriptTools(api_key="test-key", enable_search=True)

    assert "error" in json.loads(tools.search_youtube(None))
    assert "error" in json.loads(tools.search_youtube("a"))
    assert "type" in json.loads(tools.search_youtube("agno", type="playlist"))["error"]  # type: ignore[arg-type]
    mock_client_class.assert_not_called()


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_list_channel_videos_by_channel_then_continuation(mock_client_class):
    data = {"videos": [{"video_id": "abc"}], "has_more": True, "continuation_token": "tok"}
    client = _sync_client(mock_client_class, _response({"success": True, "data": data}))
    tools = GetYouTubeTranscriptTools(api_key="test-key", enable_list_channel_videos=True)

    assert json.loads(tools.list_channel_videos("@mkbhd")) == data
    assert client.get.call_args.args[0] == f"{BASE}/channel/videos"
    assert client.get.call_args.kwargs["params"] == {"channel": "@mkbhd"}

    tools.list_channel_videos(continuation="tok")
    assert client.get.call_args.kwargs["params"] == {"continuation": "tok"}


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_list_channel_videos_requires_channel_or_continuation(mock_client_class):
    tools = GetYouTubeTranscriptTools(api_key="test-key", enable_list_channel_videos=True)

    assert "error" in json.loads(tools.list_channel_videos())
    mock_client_class.assert_not_called()


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_api_error_keeps_status_code_and_message(mock_client_class):
    body = {"success": False, "code": "INVALID_API_KEY", "message": "This API key is invalid or has been revoked."}
    _sync_client(mock_client_class, _response(body, status_code=401))
    tools = GetYouTubeTranscriptTools(api_key="bad")

    result = json.loads(tools.get_youtube_transcript("5e37ZT3SQbk"))

    assert result == {
        "error": "This API key is invalid or has been revoked.",
        "status_code": 401,
        "code": "INVALID_API_KEY",
    }


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_non_json_response_returns_error(mock_client_class):
    response = _response({})
    response.json.side_effect = ValueError("not json")
    response.text = "<html>Bad gateway</html>"
    response.status_code = 502
    _sync_client(mock_client_class, response)
    tools = GetYouTubeTranscriptTools(api_key="test-key")

    result = json.loads(tools.get_youtube_transcript("5e37ZT3SQbk"))

    assert result["status_code"] == 502
    assert "Invalid JSON" in result["error"]


@patch("agno.tools.getyoutubetranscript.httpx.Client")
def test_network_failure_returns_error(mock_client_class):
    client = mock_client_class.return_value.__enter__.return_value
    client.get.side_effect = httpx.ConnectTimeout("timed out")
    tools = GetYouTubeTranscriptTools(api_key="test-key")

    result = json.loads(tools.get_youtube_transcript("5e37ZT3SQbk"))

    assert "Request failed" in result["error"]


@pytest.mark.asyncio
@patch("agno.tools.getyoutubetranscript.httpx.AsyncClient")
async def test_async_transcript_uses_same_request_contract(mock_client_class):
    data = {"video_id": "5e37ZT3SQbk", "transcript": "hello"}
    client = mock_client_class.return_value.__aenter__.return_value
    client.get = AsyncMock(return_value=_response({"success": True, "data": data}))
    tools = GetYouTubeTranscriptTools(api_key="test-key")

    result = await tools.aget_youtube_transcript("5e37ZT3SQbk", timestamps=True)

    assert json.loads(result) == data
    client.get.assert_awaited_once_with(
        f"{BASE}/transcript",
        headers={"Authorization": "Bearer test-key", "Accept": "application/json"},
        params={"v": "5e37ZT3SQbk", "timestamps": "true"},
    )


@pytest.mark.asyncio
@patch("agno.tools.getyoutubetranscript.httpx.AsyncClient")
async def test_async_search_and_channel_videos(mock_client_class):
    client = mock_client_class.return_value.__aenter__.return_value
    client.get = AsyncMock(return_value=_response({"success": True, "data": {"ok": True}}))
    tools = GetYouTubeTranscriptTools(api_key="test-key", all=True)

    assert json.loads(await tools.asearch_youtube("agno", type="channel")) == {"ok": True}
    assert client.get.await_args.kwargs["params"] == {"q": "agno", "type": "channel"}

    assert json.loads(await tools.alist_channel_videos("@mkbhd")) == {"ok": True}
    assert client.get.await_args.args[0] == f"{BASE}/channel/videos"

    assert "error" in json.loads(await tools.alist_channel_videos())
