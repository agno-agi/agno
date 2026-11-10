"""Unit tests for CoinGeckoTools class."""

from unittest.mock import Mock, patch

import pytest

from agno.tools.coingecko import CoinGeckoTools


@pytest.fixture
def mock_requests():
    """Mock the requests module."""
    with patch("agno.tools.coingecko.requests") as mock_req:
        yield mock_req


@pytest.fixture
def coingecko_tools():
    """Create a CoinGeckoTools instance."""
    return CoinGeckoTools()


# ============================================================================
# INITIALIZATION TESTS
# ============================================================================


def test_init_defaults():
    """Test default initialization."""
    tools = CoinGeckoTools()
    assert tools.timeout == 30
    assert tools.currency == "usd"
    assert tools.base_url == "https://api.coingecko.com/api/v3"


def test_init_custom_params():
    """Test initialization with custom parameters."""
    tools = CoinGeckoTools(timeout=60, currency="eur")
    assert tools.timeout == 60
    assert tools.currency == "eur"


def test_init_default_tools():
    """Test default tool registration."""
    tools = CoinGeckoTools()
    tool_names = [t.__name__ for t in tools.tools]
    assert "get_coin_price" in tool_names
    assert "search_coins" in tool_names
    assert "get_trending" in tool_names
    assert "get_coin_market_data" not in tool_names


def test_init_all_flag():
    """Test all=True enables all tools."""
    tools = CoinGeckoTools(all=True)
    tool_names = [t.__name__ for t in tools.tools]
    assert "get_coin_price" in tool_names
    assert "search_coins" in tool_names
    assert "get_trending" in tool_names
    assert "get_coin_market_data" in tool_names


def test_init_selective_tools():
    """Test selective tool flags."""
    tools = CoinGeckoTools(enable_price=False, enable_search=False, enable_trending=True)
    tool_names = [t.__name__ for t in tools.tools]
    assert "get_coin_price" not in tool_names
    assert "search_coins" not in tool_names
    assert "get_trending" in tool_names


# ============================================================================
# GET COIN PRICE TESTS
# ============================================================================


def test_get_coin_price(coingecko_tools, mock_requests):
    """Test get_coin_price returns formatted data."""
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "bitcoin": {"usd": 67000, "usd_market_cap": 1300000000000, "usd_24h_change": 2.5},
        "ethereum": {"usd": 3500, "usd_market_cap": 420000000000, "usd_24h_change": -1.2},
    }
    mock_response.raise_for_status = Mock()
    mock_requests.get.return_value = mock_response

    result = coingecko_tools.get_coin_price("bitcoin,ethereum")

    assert "bitcoin" in result
    assert "67000" in result
    assert "ethereum" in result
    mock_requests.get.assert_called_once()
    call_kwargs = mock_requests.get.call_args[1]
    assert call_kwargs["timeout"] == 30


def test_get_coin_price_custom_currency(coingecko_tools, mock_requests):
    """Test get_coin_price with custom currency."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "bitcoin": {"eur": 62000, "eur_market_cap": 1200000000000, "eur_24h_change": 1.0}
    }
    mock_response.raise_for_status = Mock()
    mock_requests.get.return_value = mock_response

    result = coingecko_tools.get_coin_price("bitcoin", currency="eur")

    assert "62000" in result
    call_params = mock_requests.get.call_args[1]["params"]
    assert call_params["vs_currencies"] == "eur"


def test_get_coin_price_error(coingecko_tools, mock_requests):
    """Test get_coin_price handles errors."""
    mock_requests.get.side_effect = Exception("Connection timeout")

    result = coingecko_tools.get_coin_price("bitcoin")

    assert "Error" in result
    assert "Connection timeout" in result


# ============================================================================
# SEARCH COINS TESTS
# ============================================================================


def test_search_coins(coingecko_tools, mock_requests):
    """Test search_coins returns matching results."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "coins": [
            {"id": "bitcoin", "name": "Bitcoin", "symbol": "btc", "market_cap_rank": 1},
            {"id": "bitcoin-cash", "name": "Bitcoin Cash", "symbol": "bch", "market_cap_rank": 20},
        ]
    }
    mock_response.raise_for_status = Mock()
    mock_requests.get.return_value = mock_response

    result = coingecko_tools.search_coins("bitcoin")

    assert "bitcoin" in result
    assert "Bitcoin" in result
    assert "btc" in result
    mock_requests.get.assert_called_once()


def test_search_coins_limits_results(coingecko_tools, mock_requests):
    """Test search_coins limits to 10 results."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "coins": [{"id": f"coin-{i}", "name": f"Coin {i}", "symbol": f"c{i}", "market_cap_rank": i} for i in range(20)]
    }
    mock_response.raise_for_status = Mock()
    mock_requests.get.return_value = mock_response

    result = coingecko_tools.search_coins("coin")

    assert "coin-9" in result
    assert "coin-10" not in result


def test_search_coins_error(coingecko_tools, mock_requests):
    """Test search_coins handles errors."""
    mock_requests.get.side_effect = Exception("Rate limited")

    result = coingecko_tools.search_coins("btc")

    assert "Error" in result


# ============================================================================
# GET TRENDING TESTS
# ============================================================================


def test_get_trending(coingecko_tools, mock_requests):
    """Test get_trending returns trending coins."""
    mock_response = Mock()
    mock_response.json.return_value = {
        "coins": [
            {"item": {"id": "pepe", "name": "Pepe", "symbol": "pepe", "market_cap_rank": 30, "price_btc": 0.0000001}},
            {"item": {"id": "bonk", "name": "Bonk", "symbol": "bonk", "market_cap_rank": 60, "price_btc": 0.0000002}},
        ]
    }
    mock_response.raise_for_status = Mock()
    mock_requests.get.return_value = mock_response

    result = coingecko_tools.get_trending()

    assert "pepe" in result
    assert "Pepe" in result
    assert "bonk" in result
    mock_requests.get.assert_called_once()


def test_get_trending_error(coingecko_tools, mock_requests):
    """Test get_trending handles errors."""
    mock_requests.get.side_effect = Exception("Server error")

    result = coingecko_tools.get_trending()

    assert "Error" in result


# ============================================================================
# GET COIN MARKET DATA TESTS
# ============================================================================


def test_get_coin_market_data(mock_requests):
    """Test get_coin_market_data returns detailed info."""
    tools = CoinGeckoTools(all=True)

    mock_response = Mock()
    mock_response.json.return_value = {
        "id": "bitcoin",
        "name": "Bitcoin",
        "symbol": "btc",
        "market_data": {
            "current_price": {"usd": 67000},
            "market_cap": {"usd": 1300000000000},
            "market_cap_rank": 1,
            "total_volume": {"usd": 30000000000},
            "high_24h": {"usd": 68000},
            "low_24h": {"usd": 66000},
            "price_change_percentage_24h": 2.5,
            "price_change_percentage_7d": 5.0,
            "price_change_percentage_30d": 10.0,
            "circulating_supply": 19500000,
            "total_supply": 21000000,
            "ath": {"usd": 73000},
            "ath_change_percentage": {"usd": -8.2},
        },
    }
    mock_response.raise_for_status = Mock()
    mock_requests.get.return_value = mock_response

    result = tools.get_coin_market_data("bitcoin")

    assert "Bitcoin" in result
    assert "67000" in result
    assert "21000000" in result


def test_get_coin_market_data_custom_currency(mock_requests):
    """Test get_coin_market_data with custom currency."""
    tools = CoinGeckoTools(all=True, currency="eur")

    mock_response = Mock()
    mock_response.json.return_value = {
        "id": "ethereum",
        "name": "Ethereum",
        "symbol": "eth",
        "market_data": {
            "current_price": {"eur": 3200},
            "market_cap": {"eur": 380000000000},
            "market_cap_rank": 2,
            "total_volume": {"eur": 15000000000},
            "high_24h": {"eur": 3300},
            "low_24h": {"eur": 3100},
            "price_change_percentage_24h": -1.5,
            "price_change_percentage_7d": 3.0,
            "price_change_percentage_30d": 8.0,
            "circulating_supply": 120000000,
            "total_supply": None,
            "ath": {"eur": 4500},
            "ath_change_percentage": {"eur": -28.9},
        },
    }
    mock_response.raise_for_status = Mock()
    mock_requests.get.return_value = mock_response

    result = tools.get_coin_market_data("ethereum")

    assert "Ethereum" in result
    assert "3200" in result


def test_get_coin_market_data_error(mock_requests):
    """Test get_coin_market_data handles errors."""
    tools = CoinGeckoTools(all=True)
    mock_requests.get.side_effect = Exception("Not found")

    result = tools.get_coin_market_data("invalid-coin")

    assert "Error" in result


# ============================================================================
# TIMEOUT TESTS
# ============================================================================


def test_timeout_passed_to_requests(mock_requests):
    """Test that timeout is passed to all requests."""
    tools = CoinGeckoTools(timeout=60)

    mock_response = Mock()
    mock_response.json.return_value = {"bitcoin": {"usd": 67000, "usd_market_cap": 0, "usd_24h_change": 0}}
    mock_response.raise_for_status = Mock()
    mock_requests.get.return_value = mock_response

    tools.get_coin_price("bitcoin")

    call_kwargs = mock_requests.get.call_args[1]
    assert call_kwargs["timeout"] == 60
