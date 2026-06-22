"""Unit tests for ClickUpTools class."""

from unittest.mock import Mock, patch

from agno.tools.clickup import ClickUpTools


def test_make_request_uses_configured_timeout():
    """Test _make_request passes the configured timeout to requests."""
    tools = ClickUpTools(api_key="test_key", master_space_id="space_id", timeout=17)
    mock_response = Mock()
    mock_response.json.return_value = {"ok": True}

    with patch("agno.tools.clickup.requests.request", return_value=mock_response) as mock_request:
        result = tools._make_request("GET", "task/task_id", params={"include_subtasks": "true"})

    assert result == {"ok": True}
    mock_response.raise_for_status.assert_called_once_with()
    mock_request.assert_called_once_with(
        method="GET",
        url="https://api.clickup.com/api/v2/task/task_id",
        headers=tools.headers,
        params={"include_subtasks": "true"},
        json=None,
        timeout=17,
    )
