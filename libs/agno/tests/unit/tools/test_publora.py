import json
from unittest.mock import Mock, patch

import pytest
import requests

from agno.tools.publora import PubloraTools


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    """Ensure PUBLORA_API_KEY is unset unless explicitly needed."""
    monkeypatch.delenv("PUBLORA_API_KEY", raising=False)


@pytest.fixture
def api_tools():
    """PubloraTools with a known API key for testing."""
    return PubloraTools(api_key="test_key", all=True)


def _mock_response(payload):
    mock = Mock(spec=requests.Response)
    mock.json.return_value = payload
    mock.raise_for_status.return_value = None
    return mock


def test_toolkit_registers_default_tools():
    tools = PubloraTools(api_key="test_key")
    names = [t.name for t in tools.functions.values()]
    assert "list_connections" in names
    assert "create_post" in names
    assert "delete_post" not in names


def test_toolkit_all_flag_registers_every_tool():
    tools = PubloraTools(api_key="test_key", all=True)
    names = [t.name for t in tools.functions.values()]
    assert {"list_connections", "create_post", "get_post", "list_posts", "update_post", "delete_post"} <= set(names)


def test_missing_api_key_returns_error():
    tools = PubloraTools()
    result = json.loads(tools.list_connections())
    assert "API key" in result["error"]


def test_list_connections(api_tools):
    payload = {
        "success": True,
        "connections": [
            {
                "platformId": "linkedin-n20H8w1Omj",
                "platform": "linkedin",
                "username": "Jane Ivanova",
                "tokenStatus": "valid",
                "lastError": None,
            }
        ],
    }
    with patch("requests.request", return_value=_mock_response(payload)) as mock_request:
        result = json.loads(api_tools.list_connections())

    assert result["connections"][0]["platform_id"] == "linkedin-n20H8w1Omj"
    assert result["connections"][0]["token_status"] == "valid"
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert kwargs["headers"]["x-publora-key"] == "test_key"


def test_create_post_schedules_when_time_given(api_tools):
    payload = {"success": True, "postGroupId": "abc123", "scheduledTime": "2026-10-20T09:00:00.000Z"}
    with patch("requests.request", return_value=_mock_response(payload)) as mock_request:
        result = json.loads(
            api_tools.create_post(
                content="Hello",
                platform_ids=["mastodon-117189156651500869"],
                scheduled_time="2026-10-20T09:00:00Z",
                media_urls=["https://example.com/image.png"],
            )
        )

    assert result == {
        "post_group_id": "abc123",
        "scheduled_time": "2026-10-20T09:00:00.000Z",
        "status": "scheduled",
    }
    sent = mock_request.call_args.kwargs["json"]
    assert sent["platforms"] == ["mastodon-117189156651500869"]
    assert sent["scheduledTime"] == "2026-10-20T09:00:00Z"
    assert sent["mediaUrls"] == ["https://example.com/image.png"]


def test_create_post_without_time_is_a_draft(api_tools):
    payload = {"success": True, "postGroupId": "draft1", "scheduledTime": None}
    with patch("requests.request", return_value=_mock_response(payload)) as mock_request:
        result = json.loads(api_tools.create_post(content="Hello", platform_ids=["bluesky-did:plc:xyz"]))

    assert result["status"] == "draft"
    assert "scheduledTime" not in mock_request.call_args.kwargs["json"]


def test_create_post_requires_content_and_platforms(api_tools):
    assert "text" in json.loads(api_tools.create_post(content="", platform_ids=["x"]))["error"]
    assert "platform id" in json.loads(api_tools.create_post(content="Hello", platform_ids=[]))["error"]


def test_get_post(api_tools):
    payload = {
        "success": True,
        "postGroupId": "abc123",
        "status": "published",
        "scheduledTime": "2026-10-20T09:00:00.000Z",
        "posts": [
            {
                "platform": "mastodon",
                "platformId": "117189156651500869",
                "status": "published",
                "permalink": "https://mastodon.social/@jane/1",
            }
        ],
    }
    with patch("requests.request", return_value=_mock_response(payload)):
        result = json.loads(api_tools.get_post("abc123"))

    assert result["status"] == "published"
    assert result["posts"][0]["permalink"] == "https://mastodon.social/@jane/1"


def test_list_posts_passes_filters(api_tools):
    payload = {
        "success": True,
        "posts": [
            {
                "postGroupId": "abc123",
                "status": "scheduled",
                "scheduledTime": "2026-10-20T09:00:00.000Z",
                "content": "Hello",
                "platforms": [{"platform": "mastodon"}],
            }
        ],
    }
    with patch("requests.request", return_value=_mock_response(payload)) as mock_request:
        result = json.loads(api_tools.list_posts(status="scheduled", limit=5))

    assert result["posts"][0]["platforms"] == ["mastodon"]
    assert mock_request.call_args.kwargs["params"] == {"limit": 5, "status": "scheduled"}


def test_update_post_requires_a_change(api_tools):
    result = json.loads(api_tools.update_post("abc123"))
    assert "something to change" in result["error"]


def test_update_post(api_tools):
    payload = {"success": True, "postGroup": {"_id": "abc123", "status": "draft"}}
    with patch("requests.request", return_value=_mock_response(payload)) as mock_request:
        result = json.loads(api_tools.update_post("abc123", status="draft"))

    assert result["post_group_id"] == "abc123"
    assert mock_request.call_args.args[0] == "PUT"


def test_delete_post(api_tools):
    with patch("requests.request", return_value=_mock_response({"success": True})) as mock_request:
        result = json.loads(api_tools.delete_post("abc123"))

    assert result == {"deleted": True, "post_group_id": "abc123"}
    assert mock_request.call_args.args[0] == "DELETE"


def test_http_error_is_reported(api_tools):
    with patch("requests.request", side_effect=requests.exceptions.HTTPError("401 Client Error")):
        result = json.loads(api_tools.list_connections())

    assert "HTTP error" in result["error"]
