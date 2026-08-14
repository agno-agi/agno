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


def test_default_registers_every_tool():
    """By default all 32 provider tools are registered."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="param_api_key")
        assert len(tools.tools) == 32


def test_default_registers_every_provider():
    """By default every provider is enabled."""
    with patch("agno.tools.scavio.ScavioClient"):
        names = _tool_names(ScavioTools(api_key="param_api_key"))
        assert "search_google" in names
        assert "get_amazon_product" in names
        assert "get_walmart_product" in names
        assert "get_youtube_video" in names
        assert "get_reddit_post" in names
        assert "get_tiktok_profile" in names
        assert "get_instagram_profile" in names


def test_include_tools_selects_subset():
    """include_tools registers only the named tools."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(api_key="param_api_key", include_tools=[ScavioTools.SEARCH_GOOGLE])
        assert set(tools.functions.keys()) == {"search_google"}


def test_exclude_tools_removes_subset():
    """exclude_tools removes the named tools from registration."""
    with patch("agno.tools.scavio.ScavioClient"):
        tools = ScavioTools(
            api_key="param_api_key",
            exclude_tools=[ScavioTools.SEARCH_GOOGLE, ScavioTools.SEARCH_AMAZON],
        )
        names = set(tools.functions.keys())
        assert "search_google" not in names
        assert "search_amazon" not in names
        assert "search_walmart" in names


def test_tool_names_are_unique():
    """Tool names must not collide across providers."""
    with patch("agno.tools.scavio.ScavioClient"):
        names = _tool_names(ScavioTools(api_key="param_api_key"))
        assert len(names) == len(set(names))


# ============================================================================
# CALL TESTS
# ============================================================================


def test_search_google_returns_json(scavio_tools, mock_scavio_client):
    """search_google returns the SDK response as a JSON string."""
    mock_scavio_client.google.search.return_value = {"results": [{"title": "Result 1"}]}

    result = scavio_tools.search_google("agno framework")

    parsed = json.loads(result)
    assert parsed["results"][0]["title"] == "Result 1"
    mock_scavio_client.google.search.assert_called_once()
    # query is passed positionally; optional params are forwarded as keywords
    call = mock_scavio_client.google.search.call_args
    assert call.args[0] == "agno framework"


def test_search_google_forwards_params(scavio_tools, mock_scavio_client):
    """search_google forwards every optional param to the SDK as a keyword."""
    mock_scavio_client.google.search.return_value = {"organic_results": []}

    scavio_tools.search_google(
        "agno framework",
        gl="us",
        hl="en",
        start=10,
        device="mobile",
        nfpr=True,
        google_domain="google.de",
        location="Berlin,Germany",
        safe="active",
        time_period="last_week",
    )

    call = mock_scavio_client.google.search.call_args
    assert call.args[0] == "agno framework"
    assert call.kwargs["gl"] == "us"
    assert call.kwargs["hl"] == "en"
    assert call.kwargs["start"] == 10
    assert call.kwargs["device"] == "mobile"
    assert call.kwargs["nfpr"] is True
    assert call.kwargs["google_domain"] == "google.de"
    assert call.kwargs["location"] == "Berlin,Germany"
    assert call.kwargs["safe"] == "active"
    assert call.kwargs["time_period"] == "last_week"


def test_get_amazon_product_passes_asin(scavio_tools, mock_scavio_client):
    """get_amazon_product forwards the ASIN to the SDK."""
    mock_scavio_client.amazon.product.return_value = {"asin": "B000"}

    result = scavio_tools.get_amazon_product("B000")

    assert json.loads(result)["asin"] == "B000"
    assert mock_scavio_client.amazon.product.call_args.args[0] == "B000"


def test_error_is_returned_as_json(scavio_tools, mock_scavio_client):
    """Exceptions from the SDK are caught and returned as an error payload."""
    mock_scavio_client.reddit.search.side_effect = Exception("boom")

    result = scavio_tools.search_reddit("test")

    parsed = json.loads(result)
    assert parsed["error"] == "boom"
