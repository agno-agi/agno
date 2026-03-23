import os
import time
from unittest.mock import MagicMock, patch

import pytest

from agno.exceptions import ModelAuthenticationError
from agno.models.copilot import CopilotChat


def _mock_token_response(token="copilot-access-token-123", expires_at=None):
    """Return a mock httpx.Response for the Copilot token endpoint."""
    if expires_at is None:
        expires_at = time.time() + 3600
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"token": token, "expires_at": expires_at}
    return resp


def _mock_token_error(status_code=401, text="Unauthorized"):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


# ── Initialization ──────────────────────────────────────────────────────


def test_copilot_default_values():
    model = CopilotChat(github_token="ghp_test")
    assert model.id == "gpt-4.1"
    assert model.name == "CopilotChat"
    assert model.provider == "Copilot"
    assert model.base_url == "https://api.githubcopilot.com/"


def test_copilot_custom_model_id():
    model = CopilotChat(id="o4-mini", github_token="ghp_test")
    assert model.id == "o4-mini"
    assert model.name == "CopilotChat"
    assert model.provider == "Copilot"


def test_copilot_initialization_with_github_token():
    model = CopilotChat(id="gpt-4.1", github_token="ghp_my_token")
    assert model.github_token == "ghp_my_token"


# ── Token resolution ────────────────────────────────────────────────────


def test_copilot_resolve_token_from_env():
    with patch.dict(os.environ, {"GITHUB_COPILOT_TOKEN": "ghp_from_env"}):
        model = CopilotChat()
        token = model._resolve_github_token()
        assert token == "ghp_from_env"
        assert model.github_token == "ghp_from_env"


def test_copilot_resolve_token_prefers_explicit():
    with patch.dict(os.environ, {"GITHUB_COPILOT_TOKEN": "ghp_from_env"}):
        model = CopilotChat(github_token="ghp_explicit")
        token = model._resolve_github_token()
        assert token == "ghp_explicit"


def test_copilot_resolve_token_missing_raises():
    with patch.dict(os.environ, {}, clear=True):
        model = CopilotChat()
        with pytest.raises(ModelAuthenticationError):
            model._resolve_github_token()


# ── Token refresh ───────────────────────────────────────────────────────


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_refresh_token_success(mock_get):
    mock_get.return_value = _mock_token_response(token="fresh-token", expires_at=time.time() + 3600)
    model = CopilotChat(github_token="ghp_test")

    token = model._refresh_copilot_token()

    assert token == "fresh-token"
    assert model._copilot_token == "fresh-token"
    mock_get.assert_called_once()


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_refresh_token_caches(mock_get):
    future = time.time() + 3600
    mock_get.return_value = _mock_token_response(token="cached-token", expires_at=future)
    model = CopilotChat(github_token="ghp_test")

    # First call fetches
    model._refresh_copilot_token()
    assert mock_get.call_count == 1

    # Second call uses cache
    token = model._refresh_copilot_token()
    assert token == "cached-token"
    assert mock_get.call_count == 1


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_refresh_token_re_fetches_when_expired(mock_get):
    past = time.time() - 10
    mock_get.return_value = _mock_token_response(token="old-token", expires_at=past)
    model = CopilotChat(github_token="ghp_test")

    model._refresh_copilot_token()
    assert mock_get.call_count == 1

    # Token is expired, should re-fetch
    mock_get.return_value = _mock_token_response(token="new-token", expires_at=time.time() + 3600)
    token = model._refresh_copilot_token()
    assert token == "new-token"
    assert mock_get.call_count == 2


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_refresh_token_api_error(mock_get):
    mock_get.return_value = _mock_token_error(401, "Bad credentials")
    model = CopilotChat(github_token="ghp_bad")

    with pytest.raises(ModelAuthenticationError, match="Failed to obtain Copilot access token"):
        model._refresh_copilot_token()


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_refresh_token_empty_token(mock_get):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"token": "", "expires_at": 0}
    mock_get.return_value = resp
    model = CopilotChat(github_token="ghp_test")

    with pytest.raises(ModelAuthenticationError, match="did not contain a token"):
        model._refresh_copilot_token()


# ── Client params ───────────────────────────────────────────────────────


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_client_params(mock_get):
    mock_get.return_value = _mock_token_response(token="access-tok")
    model = CopilotChat(github_token="ghp_test")

    params = model._get_client_params()

    assert params["api_key"] == "access-tok"
    assert params["base_url"] == "https://api.githubcopilot.com/"
    # Copilot headers must be in default_headers
    assert model.default_headers is not None
    assert model.default_headers["Copilot-Vision-Request"] == "true"
    assert model.default_headers["editor-version"] == "vscode/1.104.0"


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_client_params_preserves_existing_headers(mock_get):
    mock_get.return_value = _mock_token_response()
    model = CopilotChat(github_token="ghp_test", default_headers={"X-Custom": "value"})

    model._get_client_params()

    assert model.default_headers is not None
    assert model.default_headers["X-Custom"] == "value"
    assert model.default_headers["Copilot-Vision-Request"] == "true"


# ── No token without github_token ───────────────────────────────────────


def test_copilot_get_client_params_without_token_raises():
    with patch.dict(os.environ, {}, clear=True):
        model = CopilotChat()
        with pytest.raises(ModelAuthenticationError):
            model._get_client_params()


# ── get_client invalidates on token change ──────────────────────────────


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_get_client_invalidates_on_new_token(mock_get):
    mock_get.return_value = _mock_token_response(token="tok-1", expires_at=time.time() + 3600)
    model = CopilotChat(github_token="ghp_test")

    # Simulate a cached client with an old api_key
    fake_client = MagicMock()
    fake_client.is_closed.return_value = False
    model.client = fake_client
    model.api_key = "old-tok"

    model.get_client()

    # Old client should have been closed
    fake_client.close.assert_called_once()


@patch("agno.models.copilot.copilot.httpx.get")
def test_copilot_get_async_client_invalidates_on_new_token(mock_get):
    mock_get.return_value = _mock_token_response(token="tok-2", expires_at=time.time() + 3600)
    model = CopilotChat(github_token="ghp_test")

    fake_client = MagicMock()
    fake_client.is_closed.return_value = False
    model.async_client = fake_client
    model.api_key = "old-tok"

    model.get_async_client()

    # Async client should have been set to None and recreated
    assert model.async_client is not fake_client
