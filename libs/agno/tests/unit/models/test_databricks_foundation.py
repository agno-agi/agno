import json
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from agno.databricks.async_client import AsyncDatabricksClient
from agno.databricks.auth import DEFAULT_DATABRICKS_USER_AGENT, build_databricks_headers
from agno.databricks.client import DatabricksClient
from agno.databricks.errors import raise_for_databricks_response
from agno.databricks.settings import DatabricksSettings
from agno.exceptions import ModelAuthenticationError, ModelRateLimitError, RemoteServerUnavailableError


def _make_response(status_code: int, payload=None, url: str = "https://example.cloud.databricks.com/api/2.0/test"):
    request = httpx.Request("GET", url)
    content = b""
    if payload is not None:
        content = json.dumps(payload).encode("utf-8")
    return httpx.Response(status_code=status_code, request=request, content=content)


def test_databricks_settings_normalize_host():
    settings = DatabricksSettings(host="example.cloud.databricks.com/", token="token")

    assert settings.host == "https://example.cloud.databricks.com"
    assert settings.workspace_url == "https://example.cloud.databricks.com"
    assert settings.base_url == "https://example.cloud.databricks.com"
    assert settings.has_pat_auth is True


def test_databricks_settings_resolve_workspace_url():
    settings = DatabricksSettings(workspace_url="https://workspace.cloud.databricks.com/")

    assert settings.host == "https://workspace.cloud.databricks.com"
    assert settings.workspace_url == "https://workspace.cloud.databricks.com"


def test_databricks_settings_from_values_prefers_explicit_values_over_env(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://env.cloud.databricks.com")
    monkeypatch.setenv("DATABRICKS_TOKEN", "env-token")

    settings = DatabricksSettings.from_values(
        host="https://explicit.cloud.databricks.com",
        token="explicit-token",
        default_headers={"X-Test": "1"},
    )

    assert settings.host == "https://explicit.cloud.databricks.com"
    assert settings.workspace_url == "https://explicit.cloud.databricks.com"
    assert settings.token == "explicit-token"
    assert settings.default_headers["X-Test"] == "1"


def test_databricks_settings_with_overrides_revalidates_values():
    settings = DatabricksSettings(host="https://env.cloud.databricks.com", token="token")

    updated = settings.with_overrides(
        host="explicit.cloud.databricks.com/",
        timeout=30,
        default_headers={"X-Test": "1"},
    )

    assert updated.host == "https://explicit.cloud.databricks.com"
    assert updated.workspace_url == "https://explicit.cloud.databricks.com"
    assert updated.timeout == 30
    assert updated.default_headers["X-Test"] == "1"


def test_databricks_settings_with_overrides_rejects_invalid_timeout():
    settings = DatabricksSettings(host="https://env.cloud.databricks.com", token="token")

    with pytest.raises(ValueError):
        settings.with_overrides(timeout=0)


def test_build_databricks_headers():
    headers = build_databricks_headers(token="secret", headers={"X-Test": "1"})

    assert headers["Authorization"] == "Bearer secret"
    assert headers["User-Agent"] == DEFAULT_DATABRICKS_USER_AGENT
    assert headers["X-Test"] == "1"


def test_raise_for_databricks_response_maps_auth_error():
    response = _make_response(401, {"error_code": "UNAUTHENTICATED", "message": "Token expired"})

    with pytest.raises(ModelAuthenticationError) as exc:
        raise_for_databricks_response(response, operation="POST /serving-endpoints", model_name="Databricks")

    assert exc.value.status_code == 401
    assert exc.value.model_name == "Databricks"
    assert "Token expired" in exc.value.message


def test_raise_for_databricks_response_maps_rate_limit_error():
    response = _make_response(429, {"error_code": "RATE_LIMITED", "message": "Too many requests"})

    with pytest.raises(ModelRateLimitError) as exc:
        raise_for_databricks_response(
            response,
            operation="POST /serving-endpoints/query",
            model_name="Databricks",
            model_id="endpoint-name",
        )

    assert exc.value.status_code == 429
    assert exc.value.model_id == "endpoint-name"
    assert "Too many requests" in exc.value.message


def test_databricks_client_builds_url_and_merges_headers():
    mock_client = Mock()
    mock_client.request.return_value = _make_response(200, {"ok": True})

    client = DatabricksClient(
        host="https://example.cloud.databricks.com",
        token="secret",
        default_headers={"X-Default": "1"},
        http_client=mock_client,
    )

    result = client.request_json("GET", "/api/2.0/test", headers={"X-Request": "2"})

    assert result == {"ok": True}
    mock_client.request.assert_called_once()
    call_kwargs = mock_client.request.call_args.kwargs
    assert call_kwargs["url"] == "https://example.cloud.databricks.com/api/2.0/test"
    assert call_kwargs["headers"]["Authorization"] == "Bearer secret"
    assert call_kwargs["headers"]["X-Default"] == "1"
    assert call_kwargs["headers"]["X-Request"] == "2"


def test_databricks_client_retries_request_errors():
    mock_client = Mock()
    mock_client.request.side_effect = [
        httpx.ConnectError("boom"),
        _make_response(200, {"ok": True}),
    ]

    client = DatabricksClient(
        host="https://example.cloud.databricks.com",
        token="secret",
        max_retries=1,
        http_client=mock_client,
    )

    with patch("agno.databricks.client.sleep", return_value=None):
        result = client.request_json("GET", "/api/2.0/test")

    assert result == {"ok": True}
    assert mock_client.request.call_count == 2


@pytest.mark.asyncio
async def test_async_databricks_client_builds_url_and_merges_headers():
    mock_client = Mock()
    mock_client.request = AsyncMock(return_value=_make_response(200, {"ok": True}))

    client = AsyncDatabricksClient(
        host="https://example.cloud.databricks.com",
        token="secret",
        default_headers={"X-Default": "1"},
        http_client=mock_client,
    )

    result = await client.request_json("GET", "/api/2.0/test", headers={"X-Request": "2"})

    assert result == {"ok": True}
    mock_client.request.assert_awaited_once()
    call_kwargs = mock_client.request.call_args.kwargs
    assert call_kwargs["url"] == "https://example.cloud.databricks.com/api/2.0/test"
    assert call_kwargs["headers"]["Authorization"] == "Bearer secret"
    assert call_kwargs["headers"]["X-Default"] == "1"
    assert call_kwargs["headers"]["X-Request"] == "2"


@pytest.mark.asyncio
async def test_async_databricks_client_maps_request_errors():
    mock_client = Mock()
    mock_client.request = AsyncMock(side_effect=httpx.ConnectTimeout("timeout"))

    client = AsyncDatabricksClient(
        host="https://example.cloud.databricks.com",
        token="secret",
        max_retries=0,
        http_client=mock_client,
    )

    with pytest.raises(RemoteServerUnavailableError):
        await client.request_json("GET", "/api/2.0/test")
