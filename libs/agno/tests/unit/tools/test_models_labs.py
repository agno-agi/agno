"""Unit tests for ModelsLabTools."""

from unittest.mock import Mock, patch

from agno.tools.models_labs import ModelsLabTools


def test_models_labs_default_timeout():
    """Test default timeout is 30 seconds."""
    tools = ModelsLabTools(api_key="test-key")
    assert tools.timeout == 30


def test_models_labs_custom_timeout():
    """Test custom timeout is respected."""
    tools = ModelsLabTools(api_key="test-key", timeout=45)
    assert tools.timeout == 45


@patch("agno.tools.models_labs.requests.post")
def test_models_labs_generate_media_timeout(mock_post):
    """Test generate_media passes timeout to requests.post."""
    mock_response = Mock()
    mock_response.json.return_value = {"status": "success", "id": 12345, "eta": 10}
    mock_post.return_value = mock_response

    tools = ModelsLabTools(api_key="test-key", timeout=25)
    tools.generate_media("a sunset over the ocean")

    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["timeout"] == 25


@patch("agno.tools.models_labs.requests.post")
def test_models_labs_wait_for_media_timeout(mock_post):
    """Test _wait_for_media passes timeout to requests.post."""
    mock_response = Mock()
    mock_response.json.return_value = {"status": "success"}
    mock_post.return_value = mock_response

    tools = ModelsLabTools(api_key="test-key", timeout=12)
    success = tools._wait_for_media("media-id-123", eta=1)

    assert success is True
    mock_post.assert_called_once()
    assert mock_post.call_args.kwargs["timeout"] == 12
