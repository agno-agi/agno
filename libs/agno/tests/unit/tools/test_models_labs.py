"""Unit tests for ModelsLabTools class."""

from unittest.mock import patch

import pytest
from requests.exceptions import RequestException

from agno.tools.models_labs import ModelsLabTools


@pytest.fixture
def mock_requests_post():
    """Mock requests.post to return a canned generation response."""
    with patch("agno.tools.models_labs.requests.post") as mock_post:
        mock_post.return_value.json.return_value = {"status": "success", "eta": 10}
        yield mock_post


def test_generate_media_passes_default_timeout(mock_requests_post):
    """Test that the generation request receives the default HTTP timeout."""
    tools = ModelsLabTools(api_key="test-key")
    tools.generate_media("a sunset over the ocean")

    assert mock_requests_post.call_args[1]["timeout"] == 120


def test_generate_media_passes_configured_timeout(mock_requests_post):
    """Test that the generation request receives the configured HTTP timeout."""
    tools = ModelsLabTools(api_key="test-key", timeout=12)
    tools.generate_media("a sunset over the ocean")

    assert mock_requests_post.call_args[1]["timeout"] == 12


def test_wait_for_media_passes_configured_timeout(mock_requests_post):
    """Test that the fetch request receives the configured HTTP timeout."""
    tools = ModelsLabTools(api_key="test-key", timeout=12)
    tools._wait_for_media("media-id-123", eta=1)

    assert mock_requests_post.call_args[1]["timeout"] == 12


def test_wait_for_media_stops_at_max_wait_time(mock_requests_post):
    """Test that polling gives up once max_wait_time has passed."""
    mock_requests_post.side_effect = RequestException("Read timed out")

    tools = ModelsLabTools(api_key="test-key", max_wait_time=10)
    with patch("agno.tools.models_labs.time.monotonic", side_effect=[0, 0, 1000]):
        success = tools._wait_for_media("media-id-123", eta=1)

    assert success is False
    mock_requests_post.assert_called_once()
