"""Unit tests for battle.training tools."""

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.battle_training import BattleTrainingTools

TOOL_NAMES = {
    "create_account",
    "create_bot",
    "upload_version",
    "get_me",
    "get_bot",
    "get_ladder",
    "get_matches",
    "get_match",
    "list_ladders",
    "enrol_ladder",
    "scrimmage",
}


def make_response(
    json_data: Any = None,
    status_code: int = 200,
    text: str = "",
) -> MagicMock:
    """Create a mock httpx response."""
    response = MagicMock()
    response.status_code = status_code
    response.is_error = status_code >= 400
    if json_data is None:
        response.json.side_effect = ValueError("no json")
    else:
        response.json.return_value = json_data
    response.text = text
    return response


@pytest.fixture
def mock_client():
    """Patch httpx.Client and hand back the inner request mock."""
    with patch("agno.tools.battle_training.httpx.Client") as mock:
        yield mock.return_value.__enter__.return_value.request


@pytest.fixture
def mock_async_client():
    """Patch httpx.AsyncClient and hand back the inner request mock."""
    with patch("agno.tools.battle_training.httpx.AsyncClient") as mock:
        inner = MagicMock()
        inner.request = AsyncMock()
        mock.return_value.__aenter__ = AsyncMock(return_value=inner)
        mock.return_value.__aexit__ = AsyncMock(return_value=False)
        yield inner.request


@pytest.fixture
def tools_with_key():
    return BattleTrainingTools(api_key="test_key")


@pytest.fixture
def tools_without_key():
    with patch("agno.tools.battle_training.getenv", return_value=None):
        return BattleTrainingTools()


def last_request(mock_request: MagicMock) -> Dict[str, Any]:
    """Describe the most recent mocked HTTP request as a plain dict."""
    args, kwargs = mock_request.call_args
    return {
        "method": args[0],
        "path": args[1],
        "params": kwargs.get("params"),
        "json": kwargs.get("json"),
        "headers": kwargs.get("headers") or {},
    }


# ----------------------------------------------------------------------
# Initialization
# ----------------------------------------------------------------------


def test_init_with_api_key():
    tools = BattleTrainingTools(api_key="test_key")
    assert tools.api_key == "test_key"
    assert tools.base_url == "https://api.battle.training"
    assert tools.timeout == 30.0


def test_init_with_env_var():
    with patch.dict("os.environ", {"BATTLE_TRAINING_API_KEY": "env_key"}):
        tools = BattleTrainingTools()
        assert tools.api_key == "env_key"


def test_init_without_api_key_is_allowed():
    """Read-only use must work without a key, so init must not raise."""
    with patch("agno.tools.battle_training.getenv", return_value=None):
        tools = BattleTrainingTools()
    assert tools.api_key is None


def test_init_strips_base_url_trailing_slash():
    tools = BattleTrainingTools(api_key="test_key", base_url="https://example.com/api/")
    assert tools.base_url == "https://example.com/api"


def test_feature_registration(tools_with_key):
    """All tools register by default, in both sync and async surfaces."""
    assert set(tools_with_key.functions) == TOOL_NAMES
    assert set(tools_with_key.async_functions) == TOOL_NAMES


def test_feature_registration_flags(tools_with_key):
    tools = BattleTrainingTools(api_key="test_key", enable_upload_version=False, enable_scrimmage=False)
    assert "upload_version" not in tools.functions
    assert "upload_version" not in tools.async_functions
    assert "scrimmage" not in tools.functions
    assert len(tools.functions) == len(TOOL_NAMES) - 2


def test_feature_registration_all_overrides_flags():
    tools = BattleTrainingTools(api_key="test_key", enable_get_bot=False, all=True)
    assert set(tools.functions) == TOOL_NAMES


def test_feature_registration_none():
    tools = BattleTrainingTools(
        api_key="test_key",
        enable_create_account=False,
        enable_create_bot=False,
        enable_upload_version=False,
        enable_get_me=False,
        enable_get_bot=False,
        enable_get_ladder=False,
        enable_get_matches=False,
        enable_get_match=False,
        enable_list_ladders=False,
        enable_enrol_ladder=False,
        enable_scrimmage=False,
    )
    assert len(tools.functions) == 0
    assert len(tools.async_functions) == 0


# ----------------------------------------------------------------------
# Public reads
# ----------------------------------------------------------------------


def test_get_bot(tools_without_key, mock_client):
    mock_client.return_value = make_response({"name": "test-bot", "rating": 1200})
    result = tools_without_key.get_bot("test-bot")

    assert result == {"name": "test-bot", "rating": 1200}
    request = last_request(mock_client)
    assert request["method"] == "GET"
    assert request["path"] == "/api/bots/test-bot"
    # Public endpoint: explicit user agent, no Authorization header.
    assert "User-Agent" in request["headers"]
    assert "Authorization" not in request["headers"]


def test_get_bot_empty_name(tools_without_key, mock_client):
    result = tools_without_key.get_bot("  ")
    assert "error" in result
    mock_client.assert_not_called()


def test_get_ladder_wraps_list_response(tools_without_key, mock_client):
    mock_client.return_value = make_response([{"name": "a"}, {"name": "b"}])
    result = tools_without_key.get_ladder()
    assert result == {"result": [{"name": "a"}, {"name": "b"}]}
    assert last_request(mock_client)["path"] == "/api/ladder"


def test_get_matches(tools_without_key, mock_client):
    mock_client.return_value = make_response({"matches": []})
    result = tools_without_key.get_matches("test-bot", limit=5)
    assert result == {"matches": []}
    request = last_request(mock_client)
    assert request["path"] == "/api/matches"
    assert request["params"] == {"bot": "test-bot", "limit": 5}


def test_get_match(tools_without_key, mock_client):
    mock_client.return_value = make_response({"id": "m123", "status": "done"})
    result = tools_without_key.get_match("m123")
    assert result["status"] == "done"
    assert last_request(mock_client)["path"] == "/api/matches/m123"


def test_list_ladders(tools_without_key, mock_client):
    mock_client.return_value = make_response({"ladders": [{"slug": "silent-service"}]})
    result = tools_without_key.list_ladders()
    assert result["ladders"][0]["slug"] == "silent-service"
    assert last_request(mock_client)["path"] == "/api/ladders"


# ----------------------------------------------------------------------
# Authenticated writes
# ----------------------------------------------------------------------


def test_create_account(tools_with_key, mock_client):
    mock_client.return_value = make_response({"handle": "hopper", "key": "shown-once", "claim_url": "https://x"})
    result = tools_with_key.create_account("hopper", "human@example.com")

    assert result["key"] == "shown-once"
    request = last_request(mock_client)
    assert request["method"] == "POST"
    assert request["path"] == "/api/accounts"
    assert request["json"] == {"handle": "hopper", "email": "human@example.com"}
    # Account creation is unauthenticated even when a key is configured.
    assert "Authorization" not in request["headers"]


def test_create_account_empty_fields(tools_with_key, mock_client):
    result = tools_with_key.create_account("", "human@example.com")
    assert "error" in result
    mock_client.assert_not_called()


def test_create_bot(tools_with_key, mock_client):
    mock_client.return_value = make_response({"name": "test-bot"})
    result = tools_with_key.create_bot("test-bot", agent="agno", model="gpt-test", x="@testbot")

    assert result == {"name": "test-bot"}
    request = last_request(mock_client)
    assert request["method"] == "POST"
    assert request["path"] == "/api/bots"
    assert request["json"] == {"name": "test-bot", "agent": "agno", "model": "gpt-test", "x": "@testbot"}
    assert request["headers"]["Authorization"] == "Bearer test_key"


def test_create_bot_without_key(tools_without_key, mock_client):
    result = tools_without_key.create_bot("test-bot", agent="agno", model="gpt-test")
    assert "error" in result
    assert "API key" in result["error"]
    mock_client.assert_not_called()


def test_upload_version(tools_with_key, mock_client):
    mock_client.return_value = make_response({"version": {"label": "v1"}, "smoke": {"passed": True}})
    result = tools_with_key.upload_version("test-bot", "v1", "function tick() {}")

    assert result["smoke"] == {"passed": True}
    request = last_request(mock_client)
    assert request["method"] == "POST"
    assert request["path"] == "/api/bots/test-bot/versions"
    assert request["json"] == {"label": "v1", "source": "function tick() {}"}
    assert request["headers"]["Authorization"] == "Bearer test_key"


def test_upload_version_empty_source(tools_with_key, mock_client):
    result = tools_with_key.upload_version("test-bot", "v1", "   ")
    assert "error" in result
    mock_client.assert_not_called()


def test_upload_version_without_key(tools_without_key, mock_client):
    result = tools_without_key.upload_version("test-bot", "v1", "code")
    assert "error" in result
    mock_client.assert_not_called()


def test_get_me(tools_with_key, mock_client):
    mock_client.return_value = make_response({"bots": [{"name": "test-bot"}]})
    result = tools_with_key.get_me()
    assert result["bots"][0]["name"] == "test-bot"
    request = last_request(mock_client)
    assert request["path"] == "/api/me"
    assert request["headers"]["Authorization"] == "Bearer test_key"


def test_get_me_without_key(tools_without_key, mock_client):
    result = tools_without_key.get_me()
    assert "error" in result
    mock_client.assert_not_called()


def test_scrimmage(tools_with_key, mock_client):
    mock_client.return_value = make_response({"match_id": "m1", "url": "https://battle.training/watch?match=m1"})
    result = tools_with_key.scrimmage("test-bot", "house:hunter")

    assert result["match_id"] == "m1"
    request = last_request(mock_client)
    assert request["path"] == "/api/scrimmage"
    # Seed is omitted unless explicitly requested.
    assert request["json"] == {"bot": "test-bot", "vs": "house:hunter", "theater": "armor"}


def test_scrimmage_with_seed(tools_with_key, mock_client):
    mock_client.return_value = make_response({"match_id": "m2"})
    tools_with_key.scrimmage("test-bot", "other-bot", seed=12345, theater="sub")
    request = last_request(mock_client)
    assert request["json"] == {"bot": "test-bot", "vs": "other-bot", "theater": "sub", "seed": 12345}


def test_enrol_ladder(tools_with_key, mock_client):
    mock_client.return_value = make_response({"enrolled": True})
    result = tools_with_key.enrol_ladder("silent-service", "test-bot")
    assert result == {"enrolled": True}
    request = last_request(mock_client)
    assert request["path"] == "/api/ladders/silent-service/enrol"
    assert request["json"] == {"bot": "test-bot"}


# ----------------------------------------------------------------------
# Error handling
# ----------------------------------------------------------------------


def test_api_error_includes_server_detail(tools_without_key, mock_client):
    mock_client.return_value = make_response({"error": "bot not found"}, status_code=404)
    result = tools_without_key.get_bot("nope")
    assert result["error"] == "battle.training API error: HTTP 404"
    assert result["detail"] == "bot not found"


def test_api_error_with_plain_text_body(tools_without_key, mock_client):
    mock_client.return_value = make_response(None, status_code=500, text="internal error")
    result = tools_without_key.get_ladder()
    assert result["error"] == "battle.training API error: HTTP 500"
    assert result["detail"] == "internal error"


def test_non_json_success_body(tools_without_key, mock_client):
    mock_client.return_value = make_response(None, status_code=200, text="<html></html>")
    result = tools_without_key.get_ladder()
    assert "non-JSON" in result["error"]


def test_request_error(tools_without_key, mock_client):
    mock_client.side_effect = httpx.ConnectError("connection refused", request=MagicMock())
    result = tools_without_key.get_ladder()
    assert result["error"].startswith("Request failed")


# ----------------------------------------------------------------------
# Async variants
# ----------------------------------------------------------------------


async def test_async_get_bot(tools_without_key, mock_async_client):
    mock_async_client.return_value = make_response({"name": "test-bot"})
    result = await tools_without_key.aget_bot("test-bot")
    assert result == {"name": "test-bot"}
    args, kwargs = mock_async_client.call_args
    assert args[0] == "GET"
    assert args[1] == "/api/bots/test-bot"


async def test_async_upload_version(tools_with_key, mock_async_client):
    mock_async_client.return_value = make_response({"version": {"label": "v2"}})
    result = await tools_with_key.aupload_version("test-bot", "v2", "code")
    assert result["version"]["label"] == "v2"
    args, kwargs = mock_async_client.call_args
    assert args[1] == "/api/bots/test-bot/versions"
    assert kwargs["json"] == {"label": "v2", "source": "code"}
    assert kwargs["headers"]["Authorization"] == "Bearer test_key"


async def test_async_create_bot_without_key(tools_without_key, mock_async_client):
    result = await tools_without_key.acreate_bot("test-bot", agent="agno", model="gpt-test")
    assert "error" in result
    mock_async_client.assert_not_called()


async def test_async_scrimmage(tools_with_key, mock_async_client):
    mock_async_client.return_value = make_response({"match_id": "m9"})
    result = await tools_with_key.ascrimmage("test-bot", "house:brawler", seed=7)
    assert result["match_id"] == "m9"
    _, kwargs = mock_async_client.call_args
    assert kwargs["json"]["seed"] == 7
