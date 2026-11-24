import os
from unittest.mock import MagicMock, patch

import pytest
import requests

from agno.tools.tradytics import TradyticsTools


@pytest.fixture
def tradytics_tools():
    return TradyticsTools(api_key="tdy_test_key")


def test_init_with_provided_key():
    tools = TradyticsTools(api_key="tdy_explicit")
    assert tools.api_key == "tdy_explicit"
    assert tools.base_url == "https://tradytics.com/api/public/v1"


@patch.dict(os.environ, {"TRADYTICS_API_KEY": "tdy_env"})
def test_init_with_env_key():
    tools = TradyticsTools()
    assert tools.api_key == "tdy_env"


@patch("agno.tools.tradytics.log_error")
def test_init_without_key(mock_log_error):
    with patch.dict(os.environ, {}, clear=True):
        tools = TradyticsTools()
        assert tools.api_key is None
        mock_log_error.assert_called_once()
        assert tools.get_stock_quote("NVDA") == "TRADYTICS_API_KEY not set"


@patch("agno.tools.tradytics.requests.get")
def test_make_request_formats_params_and_booleans(mock_get, tradytics_tools):
    resp = MagicMock()
    resp.text = '{"data": [{"symbol": "NVDA"}]}'
    resp.raise_for_status.return_value = None
    mock_get.return_value = resp

    out = tradytics_tools.get_options_flow(symbol="NVDA", min_premium=500000, opening=True, limit=10)

    assert out == '{"data": [{"symbol": "NVDA"}]}'
    mock_get.assert_called_once_with(
        "https://tradytics.com/api/public/v1/options/flow",
        headers={"Accept": "application/json", "User-Agent": "agno-tradytics-tools"},
        params={"symbol": "NVDA", "min_premium": 500000, "opening": "true", "limit": 10, "apiKey": "tdy_test_key"},
        timeout=30,
    )


@patch("agno.tools.tradytics.log_error")
@patch("agno.tools.tradytics.requests.get")
def test_make_request_hides_api_key_on_error(mock_get, mock_log_error, tradytics_tools):
    err_resp = MagicMock()
    err_resp.status_code = 429
    err = requests.exceptions.HTTPError("429 Too Many Requests", response=err_resp)
    mock_get.side_effect = err

    out = tradytics_tools.get_stock_quote("SPY")

    assert "tdy_test_key" not in out
    assert "status=429" in out
    mock_log_error.assert_called_once()


@patch("agno.tools.tradytics.TradyticsTools._make_request")
def test_stock_and_market_endpoints(mock_req, tradytics_tools):
    mock_req.return_value = '{"data": []}'

    tradytics_tools.get_stock_quote("AAPL")
    mock_req.assert_called_with("stocks/quotes", {"symbol": "AAPL"})

    tradytics_tools.get_stock_bars("SPY", timeframe="5m", start_date="2026-11-01", end_date="2026-11-24", limit=50)
    mock_req.assert_called_with(
        "stocks/bars",
        {"symbol": "SPY", "timeframe": "5m", "from": "2026-11-01", "to": "2026-11-24", "limit": 50},
    )

    tradytics_tools.search_symbols("nvidia", kind="stock", limit=5)
    mock_req.assert_called_with("symbols", {"q": "nvidia", "kind": "stock", "limit": 5})

    tradytics_tools.get_market_news("NVDA", limit=10)
    mock_req.assert_called_with("news", {"symbol": "NVDA", "limit": 10})


@patch("agno.tools.tradytics.TradyticsTools._make_request")
def test_options_and_darkpool_endpoints(mock_req, tradytics_tools):
    mock_req.return_value = '{"data": []}'

    tradytics_tools.get_options_chain("NVDA", expiry="2026-12-18", option_type="call", min_dte=7, max_dte=45, limit=30)
    mock_req.assert_called_with(
        "options/chain",
        {"symbol": "NVDA", "expiry": "2026-12-18", "type": "call", "min_dte": 7, "max_dte": 45, "limit": 30},
    )

    tradytics_tools.get_dealer_exposure("SPY", greek="vanna", by="expiry", dte=30)
    mock_req.assert_called_with(
        "options/exposure",
        {"symbol": "SPY", "greek": "vanna", "by": "expiry", "expiry": None, "dte": 30},
    )

    tradytics_tools.get_darkpool_prints("AAPL", min_notional=1000000, max_rank=10, limit=15)
    mock_req.assert_called_with(
        "darkpool/prints",
        {"symbol": "AAPL", "min_notional": 1000000, "max_rank": 10, "limit": 15},
    )

    tradytics_tools.get_darkpool_levels("SPY", window="3m", limit=10)
    mock_req.assert_called_with("darkpool/levels", {"symbol": "SPY", "window": "3m", "limit": 10})


@patch("agno.tools.tradytics.TradyticsTools._make_request")
def test_fundamentals_filings_disclosures_and_probabilities(mock_req, tradytics_tools):
    mock_req.return_value = '{"data": []}'

    tradytics_tools.get_company_profile("MSFT")
    mock_req.assert_called_with("fundamentals/profile", {"symbol": "MSFT"})

    tradytics_tools.get_income_statement("MSFT", period="annual", limit=3)
    mock_req.assert_called_with("fundamentals/income-statement", {"symbol": "MSFT", "period": "annual", "limit": 3})

    tradytics_tools.get_balance_sheet("MSFT", period="quarter", limit=4)
    mock_req.assert_called_with("fundamentals/balance-sheet", {"symbol": "MSFT", "period": "quarter", "limit": 4})

    tradytics_tools.get_cash_flow("MSFT", period="ttm", limit=1)
    mock_req.assert_called_with("fundamentals/cash-flow", {"symbol": "MSFT", "period": "ttm", "limit": 1})

    tradytics_tools.search_sec_filings("supply chain", symbol="NVDA", form="10-K", limit=5)
    mock_req.assert_called_with("filings/search", {"q": "supply chain", "symbol": "NVDA", "form": "10-K", "limit": 5})

    tradytics_tools.get_earnings_transcript("NVDA", year=2026, quarter=3)
    mock_req.assert_called_with("fundamentals/transcripts", {"symbol": "NVDA", "year": 2026, "quarter": 3})

    tradytics_tools.get_insider_trades("AAPL", trade_type="buy", min_value=100000, limit=10)
    mock_req.assert_called_with(
        "disclosures/insiders",
        {"symbol": "AAPL", "type": "buy", "min_value": 100000, "limit": 10},
    )

    tradytics_tools.get_congress_trades("NVDA", chamber="senate", limit=10)
    mock_req.assert_called_with("disclosures/congress", {"symbol": "NVDA", "chamber": "senate", "limit": 10})

    tradytics_tools.get_institutional_holdings("NVDA", quarter="2026Q3", limit=20)
    mock_req.assert_called_with("disclosures/institutions", {"symbol": "NVDA", "quarter": "2026Q3", "limit": 20})

    tradytics_tools.get_prediction_markets(group="fed", symbol=None, limit=10)
    mock_req.assert_called_with("probabilities", {"group": "fed", "symbol": None, "limit": 10})
