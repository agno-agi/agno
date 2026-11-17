"""Unit tests for LinearTools class."""

from unittest.mock import patch

import pytest

from agno.tools.linear import LinearTools


@pytest.fixture
def mock_requests_post():
    """Mock requests.post to return a canned viewer response."""
    with patch("agno.tools.linear.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {
            "data": {"viewer": {"id": "1", "name": "Test", "email": "test@example.com"}}
        }
        yield mock_post


def test_get_user_details_passes_default_timeout(mock_requests_post):
    """Test that the Linear request receives the default HTTP timeout."""
    tools = LinearTools(api_key="test-api-key")
    tools.get_user_details()

    assert mock_requests_post.call_args[1]["timeout"] == 30


def test_get_user_details_passes_configured_timeout(mock_requests_post):
    """Test that the Linear request receives the configured HTTP timeout."""
    tools = LinearTools(api_key="test-api-key", timeout=12)
    tools.get_user_details()

    assert mock_requests_post.call_args[1]["timeout"] == 12
