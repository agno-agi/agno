"""Unit tests for ClickUpTools class."""

from unittest.mock import MagicMock, patch

import pytest

from agno.tools.clickup import ClickUpTools


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("CLICKUP_API_KEY", "test_api_key")
    monkeypatch.setenv("MASTER_SPACE_ID", "test_space_id")


@pytest.fixture
def clickup_tools(mock_env):
    return ClickUpTools()


@pytest.fixture
def mock_requests():
    with patch("agno.tools.clickup.requests") as m:
        yield m


def _ok_response(json_data):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = json_data
    return resp


class TestClickUpToolsInit:
    def test_init_with_explicit_credentials(self):
        tools = ClickUpTools(api_key="key", master_space_id="space")
        assert tools.api_key == "key"
        assert tools.master_space_id == "space"

    def test_init_missing_api_key(self, monkeypatch):
        monkeypatch.delenv("CLICKUP_API_KEY", raising=False)
        monkeypatch.setenv("MASTER_SPACE_ID", "space")
        with pytest.raises(ValueError, match="CLICKUP_API_KEY"):
            ClickUpTools()

    def test_init_missing_space_id(self, monkeypatch):
        monkeypatch.setenv("CLICKUP_API_KEY", "key")
        monkeypatch.delenv("MASTER_SPACE_ID", raising=False)
        with pytest.raises(ValueError, match="MASTER_SPACE_ID"):
            ClickUpTools()


class TestClickUpMakeRequest:
    def test_make_request_includes_timeout(self, clickup_tools, mock_requests):
        """_make_request must pass timeout=30 to requests.request."""
        mock_requests.request.return_value = _ok_response({"ok": True})

        clickup_tools._make_request("GET", "team/space/123/space")

        _, kwargs = mock_requests.request.call_args
        assert kwargs.get("timeout") == 30

    def test_make_request_returns_json(self, clickup_tools, mock_requests):
        mock_requests.request.return_value = _ok_response({"spaces": []})

        result = clickup_tools._make_request("GET", "team/space/123/space")

        assert result == {"spaces": []}

    def test_make_request_handles_error(self, clickup_tools, mock_requests):
        import requests as req_lib

        mock_requests.request.side_effect = req_lib.exceptions.ConnectionError("refused")
        mock_requests.exceptions.RequestException = req_lib.exceptions.RequestException

        result = clickup_tools._make_request("GET", "team/space/123/space")

        assert "error" in result


class TestClickUpListSpaces:
    def test_list_spaces_uses_timeout(self, clickup_tools, mock_requests):
        """list_spaces must route through _make_request, which uses timeout=30."""
        mock_requests.request.return_value = _ok_response({"spaces": [{"id": "1", "name": "Dev"}]})

        clickup_tools.list_spaces()

        _, kwargs = mock_requests.request.call_args
        assert kwargs.get("timeout") == 30
