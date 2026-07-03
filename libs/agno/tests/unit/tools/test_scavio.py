"""Unit tests for ScavioTools class."""

import json
import os
from unittest.mock import Mock, patch

import pytest

from agno.tools.scavio import ScavioTools

TEST_API_KEY = os.environ.get("SCAVIO_API_KEY", "test_api_key")


@pytest.fixture
def mock_scavio_client():
    """Create a mock ScavioClient instance."""
    with patch("agno.tools.scavio.ScavioClient") as mock_client_cls:
        mock_client = Mock()
        mock_client_cls.return_value = mock_client
        return mock_client


@pytest.fixture
def scavio_tools(mock_scavio_client):
    """Create a ScavioTools instance with mocked dependencies."""
    with patch.dict("os.environ", {"SCAVIO_API_KEY": TEST_API_KEY}):
        tools = ScavioTools()
        tools.client = mock_scavio_client
        return tools


def _tool_names(tools: ScavioTools) -> list:
    return [tool.__name__ for tool in tools.tools]


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_with_env_var():
    """Test initialization reads the API key from the environment."""
    with patch("agno.tools.scavio.ScavioClient") as mock_client_cls:
        with patch.dict("os.environ", {"SCAVIO_API_KEY": TEST_API_KEY}, clear=True):
            tools = ScavioTools()
            assert tools.api_key == TEST_API_KEY
            assert tools.client is not None
            mock_client_cls.assert_called_once_with(api_key=TEST_API_KEY)


def test_init_with_param():
    """Test initialization with an explicit API key."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="param_api_key")
        assert tools.api_key == "param_api_key"


def test_all_flag_registers_every_tool():
    """all=True should register all 32 provider tools."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(all=True)
        assert len(tools.tools) == 32


def test_default_registers_every_provider():
    """By default every provider is enabled."""
    with patch("agno.tools.scavio.ScavioClient"):
        names = _tool_names(ScavioTools())
        assert "google_search" in names
        assert "amazon_product" in names
        assert "walmart_product" in names
        assert "youtube_metadata" in names
        assert "reddit_post" in names
        assert "tiktok_profile" in names
        assert "instagram_profile" in names


def test_enable_flags_select_subset():
    """Disabling providers removes their tools."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            enable_google=True,
            enable_amazon=False,
            enable_walmart=False,
            enable_youtube=False,
            enable_reddit=False,
            enable_tiktok=False,
            enable_instagram=False,
        )
        names = _tool_names(tools)
        assert names == ["google_search"]


def test_tool_names_are_unique():
    """Provider-prefixed names must not collide (tiktok/instagram both have search_users)."""
    with patch("agno.tools.scavio.ScavioClient"):
        names = _tool_names(ScavioTools(all=True))
        assert len(names) == len(set(names))


# ============================================================================
# CALL TESTS
# ============================================================================


def test_google_search_returns_json(scavio_tools, mock_scavio_client):
    """google_search returns the SDK response as a JSON string."""
    mock_scavio_client.google.search.return_value = {"results": [{"title": "Result 1"}]}

    result = scavio_tools.google_search("agno framework")

    parsed = json.loads(result)
    assert parsed["results"][0]["title"] == "Result 1"
    mock_scavio_client.google.search.assert_called_once()
    # query is passed positionally; optional params are forwarded as keywords
    call = mock_scavio_client.google.search.call_args
    assert call.args[0] == "agno framework"


def test_amazon_product_passes_asin(scavio_tools, mock_scavio_client):
    """amazon_product forwards the ASIN to the SDK."""
    mock_scavio_client.amazon.product.return_value = {"asin": "B000"}

    result = scavio_tools.amazon_product("B000")

    assert json.loads(result)["asin"] == "B000"
    assert mock_scavio_client.amazon.product.call_args.args[0] == "B000"


def test_error_is_returned_as_json(scavio_tools, mock_scavio_client):
    """Exceptions from the SDK are caught and returned as an error payload."""
    mock_scavio_client.reddit.search.side_effect = Exception("boom")

    result = scavio_tools.reddit_search("test")

    parsed = json.loads(result)
    assert parsed["error"] == "boom"
