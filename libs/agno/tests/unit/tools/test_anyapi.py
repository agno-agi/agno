import json
import os
from unittest.mock import Mock, patch

import pytest
from getanyapi import AnyAPI  # noqa

from agno.tools.anyapi import AnyAPITools

TEST_API_KEY = os.environ.get("ANYAPI_API_KEY", "test_api_key")
TEST_BASE_URL = "https://api.getanyapi.com"


@pytest.fixture
def mock_anyapi():
    """Create a mock AnyAPI client instance."""
    with patch("agno.tools.anyapi.AnyAPI") as mock_anyapi_cls:
        mock_client = Mock()
        mock_anyapi_cls.return_value = mock_client
        return mock_client


@pytest.fixture
def anyapi_tools(mock_anyapi):
    """Create an AnyAPITools instance with mocked dependencies."""
    with patch.dict("os.environ", {"ANYAPI_API_KEY": TEST_API_KEY}):
        tools = AnyAPITools()
        # Directly set the client to our mock to avoid initialization issues
        tools.client = mock_anyapi
        return tools


def _mock_response(payload):
    """Build a mock that serializes to the given payload."""
    response = Mock(spec=["model_dump"])
    response.model_dump.return_value = payload
    return response


def test_init_with_env_vars():
    """Test initialization with environment variables."""
    with patch("agno.tools.anyapi.AnyAPI") as mock_anyapi_cls:
        with patch.dict("os.environ", {"ANYAPI_API_KEY": TEST_API_KEY}, clear=True):
            tools = AnyAPITools()
            assert tools.api_key == TEST_API_KEY
            assert tools.client is not None
            mock_anyapi_cls.assert_called_once_with(api_key=TEST_API_KEY, base_url=TEST_BASE_URL)


def test_init_with_params():
    """Test initialization with parameters."""
    with patch("agno.tools.anyapi.AnyAPI") as mock_anyapi_cls:
        tools = AnyAPITools(api_key="param_api_key")
        assert tools.api_key == "param_api_key"
        assert tools.client is not None
        mock_anyapi_cls.assert_called_once_with(api_key="param_api_key", base_url=TEST_BASE_URL)


def test_default_tools_registered():
    """Test that the default flags register discovery and execution but not the balance tool."""
    with patch("agno.tools.anyapi.AnyAPI"):
        tools = AnyAPITools(api_key=TEST_API_KEY)
        registered = [func.name for func in tools.functions.values()]
        assert "search_apis" in registered
        assert "get_api" in registered
        assert "run_api" in registered
        assert "get_balance" not in registered


def test_all_flag_registers_every_tool():
    """Test that `all=True` registers every tool."""
    with patch("agno.tools.anyapi.AnyAPI"):
        tools = AnyAPITools(api_key=TEST_API_KEY, all=True)
        registered = [func.name for func in tools.functions.values()]
        assert registered == ["search_apis", "get_api", "run_api", "get_balance"]


def test_individual_flags_registered():
    """Test that individual flags select the tools."""
    with patch("agno.tools.anyapi.AnyAPI"):
        tools = AnyAPITools(
            api_key=TEST_API_KEY,
            enable_search_apis=False,
            enable_get_api=False,
            enable_run_api=False,
            enable_get_balance=True,
        )
        registered = [func.name for func in tools.functions.values()]
        assert registered == ["get_balance"]


def test_search_apis(anyapi_tools, mock_anyapi):
    """Test search_apis method."""
    mock_anyapi.search.return_value = _mock_response(
        {
            "results": [{"slug": "instagram.profile", "provider": "AnyAPI"}],
            "total": 1,
            "ranking": "semantic",
        }
    )

    result = anyapi_tools.search_apis("instagram profile")
    result_data = json.loads(result)

    assert result_data["results"][0]["slug"] == "instagram.profile"
    assert result_data["total"] == 1
    mock_anyapi.search.assert_called_once_with(query="instagram profile", category=None, platform=None, limit=None)


def test_search_apis_with_filters(anyapi_tools, mock_anyapi):
    """Test that search_apis forwards every filter to the client."""
    mock_anyapi.search.return_value = _mock_response({"results": [], "total": 0, "ranking": "keyword"})

    anyapi_tools.search_apis("reviews", category="maps", platform="google", limit=5)

    mock_anyapi.search.assert_called_once_with(query="reviews", category="maps", platform="google", limit=5)


def test_get_api(anyapi_tools, mock_anyapi):
    """Test get_api method."""
    mock_anyapi.describe.return_value = _mock_response(
        {
            "slug": "instagram.profile",
            "input_schema": {"type": "object", "properties": {"username": {"type": "string"}}},
            "pricing": {"maxUsd": 0.002},
        }
    )

    result = anyapi_tools.get_api("instagram.profile")
    result_data = json.loads(result)

    assert result_data["slug"] == "instagram.profile"
    assert result_data["input_schema"]["properties"]["username"]["type"] == "string"
    mock_anyapi.describe.assert_called_once_with("instagram.profile")


def test_run_api(anyapi_tools, mock_anyapi):
    """Test run_api method."""
    mock_anyapi.run.return_value = _mock_response(
        {
            "output": {"found": True, "data": {"username": "agno"}},
            "provider": "AnyAPI",
            "cost_usd": 0.002,
            "items": 1,
        }
    )

    result = anyapi_tools.run_api("instagram.profile", {"username": "agno"})
    result_data = json.loads(result)

    assert result_data["output"]["data"]["username"] == "agno"
    assert result_data["cost_usd"] == 0.002
    assert result_data["items"] == 1
    mock_anyapi.run.assert_called_once_with("instagram.profile", {"username": "agno"})


def test_get_balance(anyapi_tools, mock_anyapi):
    """Test get_balance method."""
    mock_anyapi.balance.return_value = _mock_response({"usd": 4.21})

    result = anyapi_tools.get_balance()
    result_data = json.loads(result)

    assert result_data["usd"] == 4.21
    mock_anyapi.balance.assert_called_once_with()


def test_results_are_json_serializable(anyapi_tools, mock_anyapi):
    """Test that a value the JSON encoder cannot handle is stringified rather than raising."""
    mock_anyapi.describe.return_value = _mock_response({"slug": "web.scrape", "latency": object()})

    result = anyapi_tools.get_api("web.scrape")
    result_data = json.loads(result)

    assert result_data["slug"] == "web.scrape"
    assert isinstance(result_data["latency"], str)
