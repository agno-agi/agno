from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.adanos import AdanosTools


def test_initialization_registers_sync_and_async_tools():
    tools = AdanosTools(api_key="test-key")

    assert tools.name == "adanos_tools"
    assert set(tools.functions) == {
        "get_stock_sentiment",
        "get_crypto_sentiment",
        "get_trending",
        "get_market_sentiment",
    }
    assert set(tools.async_functions) == set(tools.functions)


def test_initialization_reads_api_key_from_environment():
    with patch.dict("os.environ", {"ADANOS_API_KEY": "env-key"}):
        tools = AdanosTools()

    assert tools.api_key == "env-key"


def test_disabled_tool_is_not_registered():
    tools = AdanosTools(api_key="test-key", enable_crypto_sentiment=False)

    assert "get_crypto_sentiment" not in tools.functions
    assert "get_stock_sentiment" in tools.functions


@patch("agno.tools.adanos.httpx.Client")
def test_get_stock_sentiment_maps_source_dates_and_auth(mock_client_class):
    response = MagicMock()
    response.json.return_value = {"ticker": "AAPL", "found": True}
    response.raise_for_status.return_value = None
    client = mock_client_class.return_value.__enter__.return_value
    client.get.return_value = response
    tools = AdanosTools(api_key="test-key", base_url="https://example.test/")

    result = tools.get_stock_sentiment("$aapl", source="news", start_date="2026-07-01", end_date="2026-07-07")

    assert result == {"ticker": "AAPL", "found": True}
    client.get.assert_called_once_with(
        "https://example.test/news/stocks/v1/stock/AAPL",
        headers={"X-API-Key": "test-key"},
        params={"from": "2026-07-01", "to": "2026-07-07"},
    )


@patch("agno.tools.adanos.httpx.Client")
def test_get_crypto_sentiment_uses_reddit_crypto_endpoint(mock_client_class):
    response = MagicMock()
    response.json.return_value = {"symbol": "BTC", "found": True}
    response.raise_for_status.return_value = None
    client = mock_client_class.return_value.__enter__.return_value
    client.get.return_value = response
    tools = AdanosTools(api_key="test-key")

    result = tools.get_crypto_sentiment("btc")

    assert result["symbol"] == "BTC"
    assert client.get.call_args.args[0] == "https://api.adanos.org/reddit/crypto/v1/token/BTC"


@patch("agno.tools.adanos.httpx.Client")
def test_get_trending_clamps_limit_to_api_maximum(mock_client_class):
    response = MagicMock()
    response.json.return_value = {"results": []}
    response.raise_for_status.return_value = None
    client = mock_client_class.return_value.__enter__.return_value
    client.get.return_value = response
    tools = AdanosTools(api_key="test-key")

    tools.get_trending(source="x", limit=500)

    assert client.get.call_args.kwargs["params"] == {"limit": 100}
    assert client.get.call_args.args[0] == "https://api.adanos.org/x/stocks/v1/trending"


@patch("agno.tools.adanos.httpx.Client")
def test_crypto_rejects_non_reddit_source_without_request(mock_client_class):
    tools = AdanosTools(api_key="test-key")

    result = tools.get_market_sentiment(asset_type="crypto", source="news")

    assert result == {"error": "crypto sentiment is currently available from reddit only"}
    mock_client_class.assert_not_called()


@patch("agno.tools.adanos.httpx.Client")
def test_missing_api_key_returns_actionable_error(mock_client_class):
    with patch.dict("os.environ", {}, clear=True):
        tools = AdanosTools()

    result = tools.get_stock_sentiment("AAPL")

    assert result == {"error": "Adanos API key is required. Set ADANOS_API_KEY or pass api_key."}
    mock_client_class.return_value.__enter__.return_value.get.assert_not_called()


@patch("agno.tools.adanos.httpx.Client")
def test_http_error_preserves_status_and_api_detail(mock_client_class):
    request = httpx.Request("GET", "https://api.adanos.org/reddit/stocks/v1/stock/AAPL")
    response = MagicMock(spec=httpx.Response)
    response.status_code = 429
    response.json.return_value = {"detail": {"error": "Rate limit exceeded"}}
    client = mock_client_class.return_value.__enter__.return_value
    client.get.return_value = response
    response.raise_for_status.side_effect = httpx.HTTPStatusError("rate limited", request=request, response=response)
    tools = AdanosTools(api_key="test-key")

    result = tools.get_stock_sentiment("AAPL")

    assert result == {
        "error": "Adanos API request failed",
        "status_code": 429,
        "detail": {"error": "Rate limit exceeded"},
    }


@pytest.mark.asyncio
@patch("agno.tools.adanos.httpx.AsyncClient")
async def test_async_tool_uses_same_endpoint_contract(mock_client_class):
    response = MagicMock()
    response.json.return_value = {"market_sentiment": "bullish"}
    response.raise_for_status.return_value = None
    client = mock_client_class.return_value.__aenter__.return_value
    client.get = AsyncMock(return_value=response)
    tools = AdanosTools(api_key="test-key")

    result = await tools.aget_market_sentiment(source="polymarket")

    assert result == {"market_sentiment": "bullish"}
    client.get.assert_awaited_once_with(
        "https://api.adanos.org/polymarket/stocks/v1/market-sentiment",
        headers={"X-API-Key": "test-key"},
        params={},
    )
