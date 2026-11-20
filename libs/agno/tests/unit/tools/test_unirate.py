"""Unit tests for UniRateTools class."""

import json
from unittest.mock import Mock, patch

import httpx
import pytest
from agno.tools.unirate import UniRateTools


@pytest.fixture
def mock_unirate_get():
    """Patch httpx.get inside the unirate module."""
    with patch("agno.tools.unirate.httpx.get") as mock_get:
        yield mock_get


@pytest.fixture
def unirate_tools():
    """Create a UniRateTools instance with a mock API key."""
    with patch.dict("os.environ", {"UNIRATE_API_KEY": "test_api_key"}):
        return UniRateTools()


def _mock_response(payload):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = payload
    return response


def test_initialization_without_api_key():
    """Initialization without an API key raises ValueError."""
    with patch.dict("os.environ", clear=True):
        with pytest.raises(ValueError, match="UniRate API key is required"):
            UniRateTools()


def test_initialization_with_explicit_api_key():
    """API key can be passed explicitly."""
    with patch.dict("os.environ", clear=True):
        tools = UniRateTools(api_key="explicit_key")
        assert tools.api_key == "explicit_key"


def test_default_registers_all_tools(unirate_tools):
    """By default all four functions are registered."""
    names = [func.name for func in unirate_tools.functions.values()]
    assert "get_exchange_rate" in names
    assert "convert_currency" in names
    assert "list_currencies" in names
    assert "get_vat_rate" in names


def test_init_with_selective_tools():
    """Only the enabled functions are registered."""
    with patch.dict("os.environ", {"UNIRATE_API_KEY": "test_api_key"}):
        tools = UniRateTools(
            enable_get_exchange_rate=True,
            enable_convert_currency=False,
            enable_list_currencies=True,
            enable_get_vat_rate=False,
        )
        names = [func.name for func in tools.functions.values()]
        assert "get_exchange_rate" in names
        assert "convert_currency" not in names
        assert "list_currencies" in names
        assert "get_vat_rate" not in names


def test_get_exchange_rate_success(unirate_tools, mock_unirate_get):
    """A single exchange rate is returned."""
    mock_unirate_get.return_value = _mock_response({"rate": "0.92"})

    result = json.loads(unirate_tools.get_exchange_rate("EUR"))

    assert result["rate"] == "0.92"
    # Defaults to the base currency (USD) and uppercases the target.
    _, kwargs = mock_unirate_get.call_args
    assert kwargs["params"]["from"] == "USD"
    assert kwargs["params"]["to"] == "EUR"
    assert kwargs["params"]["api_key"] == "test_api_key"
    assert kwargs["headers"]["Accept"] == "application/json"


def test_get_exchange_rate_uppercases_inputs(unirate_tools, mock_unirate_get):
    """Currency codes are uppercased before the request."""
    mock_unirate_get.return_value = _mock_response({"rate": "1.08"})

    unirate_tools.get_exchange_rate("usd", from_currency="eur")

    _, kwargs = mock_unirate_get.call_args
    assert kwargs["params"]["from"] == "EUR"
    assert kwargs["params"]["to"] == "USD"


def test_convert_currency_success(unirate_tools, mock_unirate_get):
    """An amount is converted between two currencies."""
    mock_unirate_get.return_value = _mock_response({"result": "92.50"})

    result = json.loads(unirate_tools.convert_currency(100, "EUR", from_currency="USD"))

    assert result["result"] == "92.50"
    _, kwargs = mock_unirate_get.call_args
    assert kwargs["params"]["amount"] == 100
    assert kwargs["params"]["from"] == "USD"
    assert kwargs["params"]["to"] == "EUR"


def test_convert_currency_uses_base_currency_default(mock_unirate_get):
    """convert_currency defaults from_currency to the toolkit base_currency."""
    with patch.dict("os.environ", {"UNIRATE_API_KEY": "test_api_key"}):
        tools = UniRateTools(base_currency="GBP")
    mock_unirate_get.return_value = _mock_response({"result": "10.0"})

    tools.convert_currency(10, "USD")

    _, kwargs = mock_unirate_get.call_args
    assert kwargs["params"]["from"] == "GBP"


def test_list_currencies_success(unirate_tools, mock_unirate_get):
    """The supported-currencies list is returned."""
    mock_unirate_get.return_value = _mock_response({"currencies": ["USD", "EUR", "GBP"]})

    result = json.loads(unirate_tools.list_currencies())

    assert result["currencies"] == ["USD", "EUR", "GBP"]
    args, _ = mock_unirate_get.call_args
    assert args[0].endswith("/currencies")


def test_get_vat_rate_for_country(unirate_tools, mock_unirate_get):
    """A single country's VAT rate is returned and the code is uppercased."""
    mock_unirate_get.return_value = _mock_response(
        {"country": "DE", "vat_data": {"country_code": "DE", "vat_rate": 19.0}}
    )

    result = json.loads(unirate_tools.get_vat_rate("de"))

    assert result["vat_data"]["vat_rate"] == 19.0
    _, kwargs = mock_unirate_get.call_args
    assert kwargs["params"]["country"] == "DE"


def test_get_vat_rate_all_countries(unirate_tools, mock_unirate_get):
    """Without a country, VAT rates for all countries are returned and no country param is sent."""
    mock_unirate_get.return_value = _mock_response({"total_countries": 1, "vat_rates": {"DE": {"vat_rate": 19.0}}})

    result = json.loads(unirate_tools.get_vat_rate())

    assert result["total_countries"] == 1
    _, kwargs = mock_unirate_get.call_args
    assert "country" not in kwargs["params"]


def test_request_error_is_wrapped(unirate_tools, mock_unirate_get):
    """Transport/HTTP errors are surfaced as an {"error": ...} payload, not raised."""
    mock_unirate_get.side_effect = httpx.HTTPError("network down")

    result = json.loads(unirate_tools.get_exchange_rate("EUR"))

    assert "error" in result
    assert "network down" in result["error"]


def test_http_status_error_is_wrapped(unirate_tools, mock_unirate_get):
    """A non-2xx response (raise_for_status) is caught and wrapped."""
    response = Mock()
    response.status_code = 403
    response.raise_for_status.side_effect = httpx.HTTPError("403 Forbidden")
    mock_unirate_get.return_value = response

    result = json.loads(unirate_tools.get_exchange_rate("EUR"))

    assert "error" in result
