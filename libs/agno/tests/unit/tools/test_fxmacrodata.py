import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from agno.tools.fxmacrodata import FXMacroDataTools


@pytest.fixture
def fxmacrodata_tools():
    """Fixture for FXMacroDataTools instance with an explicit key."""
    return FXMacroDataTools(api_key="test_api_key")


@pytest.fixture
def mock_response():
    """Fixture for a successful mocked API response."""
    response = MagicMock()
    response.text = '{"currency":"USD","data":[]}'
    response.raise_for_status.return_value = None
    return response


# Initialization


def test_init_with_provided_key():
    """Test initialization with an explicitly provided API key."""
    tools = FXMacroDataTools(api_key="explicit_key")
    assert tools.api_key == "explicit_key"


@patch.dict(os.environ, {"FXMACRODATA_API_KEY": "env_key"})
def test_init_with_env_key():
    """Test the API key is read from the environment."""
    tools = FXMacroDataTools()
    assert tools.api_key == "env_key"


@patch.dict(os.environ, {}, clear=True)
def test_init_without_key_is_allowed():
    """USD data is public, so a missing key must not be treated as an error."""
    tools = FXMacroDataTools()
    assert tools.api_key is None


def test_base_url_trailing_slash_is_normalized():
    """A base URL given with a trailing slash must not produce a double slash."""
    tools = FXMacroDataTools(api_key="k", base_url="https://example.test/v1/")
    assert tools.base_url == "https://example.test/v1"


def test_registers_expected_tools(fxmacrodata_tools):
    """Every documented tool should be registered on the toolkit."""
    names = {func.name for func in fxmacrodata_tools.functions.values()}
    assert {
        "search_indicators",
        "get_latest_macro_snapshot",
        "get_indicator_history",
        "get_release_calendar",
        "get_central_bank_headlines",
        "get_fx_rate",
        "get_rate_differential",
        "get_cot_positioning",
        "get_commodity_prices",
        "get_market_sessions",
        "get_risk_sentiment",
    } <= names


# Request construction


def test_api_key_is_sent_as_a_header_not_a_query_parameter(fxmacrodata_tools, mock_response):
    """The key must stay out of the URL so it is not written to access logs."""
    with patch("requests.get", return_value=mock_response) as mock_get:
        fxmacrodata_tools.get_latest_macro_snapshot("USD")

    _, kwargs = mock_get.call_args
    assert kwargs["headers"]["X-API-Key"] == "test_api_key"
    assert "api_key" not in kwargs["params"]


@patch.dict(os.environ, {}, clear=True)
def test_no_auth_header_without_a_key(mock_response):
    """Without a key the public endpoints must still be callable."""
    tools = FXMacroDataTools()
    with patch("requests.get", return_value=mock_response) as mock_get:
        tools.get_release_calendar("USD")

    _, kwargs = mock_get.call_args
    assert "X-API-Key" not in kwargs["headers"]


def test_currency_is_lowercased_in_the_path(fxmacrodata_tools, mock_response):
    """Callers pass 'USD' but the API paths are lowercase."""
    with patch("requests.get", return_value=mock_response) as mock_get:
        fxmacrodata_tools.get_indicator_history(currency="USD", indicator="inflation")

    args, _ = mock_get.call_args
    assert args[0] == "https://api.fxmacrodata.com/v1/announcements/usd/inflation"


def test_none_parameters_are_dropped(fxmacrodata_tools, mock_response):
    """Unset optional dates must not be sent as empty query parameters."""
    with patch("requests.get", return_value=mock_response) as mock_get:
        fxmacrodata_tools.get_indicator_history(currency="USD", indicator="gdp", limit=5)

    _, kwargs = mock_get.call_args
    assert kwargs["params"] == {"limit": 5}


def test_pair_endpoints_build_both_sides(fxmacrodata_tools, mock_response):
    """Base and quote both belong in the path, lowercased."""
    with patch("requests.get", return_value=mock_response) as mock_get:
        fxmacrodata_tools.get_rate_differential(base="USD", quote="JPY")

    args, _ = mock_get.call_args
    assert args[0] == "https://api.fxmacrodata.com/v1/rate_differentials/usd/jpy"


def test_successful_response_returns_body(fxmacrodata_tools, mock_response):
    """A 2xx response should hand back the raw JSON body."""
    with patch("requests.get", return_value=mock_response):
        result = fxmacrodata_tools.get_market_sessions()

    assert result == '{"currency":"USD","data":[]}'


# Error handling


def test_auth_failure_explains_the_key_requirement(fxmacrodata_tools):
    """A 403 should tell the agent a key is needed rather than look like an outage."""
    response = MagicMock()
    response.status_code = 403
    error = requests.exceptions.HTTPError(response=response)
    response.raise_for_status.side_effect = error

    with patch("requests.get", return_value=response):
        result = fxmacrodata_tools.get_cot_positioning("GBP")

    assert "API key" in result
    assert "USD" in result


def test_network_errors_are_returned_not_raised(fxmacrodata_tools):
    """Tool calls should degrade to a message the agent can read."""
    with patch("requests.get", side_effect=requests.exceptions.ConnectionError("boom")):
        result = fxmacrodata_tools.get_risk_sentiment()

    assert "Error making request" in result


def test_server_errors_are_reported(fxmacrodata_tools):
    """A 500 is an upstream failure, not an auth problem."""
    response = MagicMock()
    response.status_code = 500
    response.raise_for_status.side_effect = requests.exceptions.HTTPError(response=response)

    with patch("requests.get", return_value=response):
        result = fxmacrodata_tools.get_commodity_prices()

    assert "Error making request" in result
    assert "API key" not in result
