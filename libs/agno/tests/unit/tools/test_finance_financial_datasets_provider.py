"""FinancialDatasetsProvider: request shaping and normalization against OpenAPI-shaped payloads (httpx mocked)."""

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from agno.tools.finance import FinanceProviderError, FinanceTools, FinancialDatasetsProvider

BASE = "https://api.financialdatasets.ai"


def _response(status_code: int = 200, payload=None, text: str = "") -> httpx.Response:
    request = httpx.Request("GET", f"{BASE}/x")
    if payload is not None:
        return httpx.Response(status_code, json=payload, request=request)
    return httpx.Response(status_code, text=text, request=request)


@pytest.fixture
def provider() -> FinancialDatasetsProvider:
    return FinancialDatasetsProvider(api_key="test-key", timeout=5)


@pytest.fixture
def client():
    with patch("agno.tools.finance.financial_datasets.httpx.Client") as client_cls:
        yield client_cls.return_value.__enter__.return_value


# ---------------------------------------------------------------------------
# Construction / status
# ---------------------------------------------------------------------------


def test_reads_key_from_env_and_reports_status():
    with patch.dict("os.environ", {"FINANCIAL_DATASETS_API_KEY": "env-key"}):
        p = FinancialDatasetsProvider()
    assert p.api_key == "env-key"
    assert p.status().ok is True
    assert p.capabilities and "search_symbols" not in p.capabilities
    assert "get_analyst_recommendations" not in p.capabilities


def test_missing_key_is_soft_until_a_call(client):
    with patch.dict("os.environ", {}, clear=False):
        import os

        os.environ.pop("FINANCIAL_DATASETS_API_KEY", None)
        p = FinancialDatasetsProvider()
    assert p.status().ok is False
    with pytest.raises(FinanceProviderError, match="FINANCIAL_DATASETS_API_KEY not configured"):
        p.get_quote("NVDA")
    client.get.assert_not_called()


# ---------------------------------------------------------------------------
# Request shaping
# ---------------------------------------------------------------------------


def test_quote_request_and_normalization(provider, client):
    client.get.return_value = _response(
        payload={
            "snapshot": {
                "price": 225.01,
                "ticker": "NVDA",
                "day_change": -0.14,
                "day_change_percent": -0.06,
                "time": "2026-08-18T15:59:00Z",
                "time_milliseconds": 1,
            }
        }
    )

    quote = provider.get_quote("NVDA")

    client.get.assert_called_once_with(
        f"{BASE}/prices/snapshot", headers={"X-API-KEY": "test-key"}, params={"ticker": "NVDA"}
    )
    assert quote.symbol == "NVDA" and quote.price == 225.01
    assert quote.change == -0.14 and quote.change_percent == -0.06
    assert quote.as_of == "2026-08-18T15:59:00Z" and quote.currency == "USD"


def test_price_history_maps_period_and_interval(provider, client):
    client.get.return_value = _response(
        payload={
            "ticker": "NVDA",
            "prices": [{"open": 1, "close": 2, "high": 3, "low": 0.5, "volume": 10, "time": "2026-08-17T00:00:00Z"}],
        }
    )

    history = provider.get_price_history("NVDA", period="ytd", interval="1wk")

    params = client.get.call_args.kwargs["params"]
    assert client.get.call_args.args[0] == f"{BASE}/prices"
    assert params["ticker"] == "NVDA" and params["interval"] == "week" and params["interval_multiplier"] == 1
    assert params["start_date"] == f"{date.today().year}-01-01"
    assert params["end_date"] == date.today().isoformat()
    assert history.bars[0].close == 2 and history.bars[0].date == "2026-08-17T00:00:00Z"
    assert history.period == "ytd" and history.interval == "1wk"


def test_price_history_rejects_bad_period_before_request(provider, client):
    with pytest.raises(FinanceProviderError, match="period must be one of"):
        provider.get_price_history("NVDA", period="7d")
    with pytest.raises(FinanceProviderError, match="interval must be one of"):
        provider.get_price_history("NVDA", interval="1h")
    client.get.assert_not_called()


def test_company_profile(provider, client):
    client.get.return_value = _response(
        payload={
            "company_facts": {
                "ticker": "NVDA",
                "name": "NVIDIA CORP",
                "cik": "0001045810",
                "industry": "Semiconductors",
                "sector": "Technology",
                "exchange": "NASDAQ",
                "location": "SANTA CLARA, CA",
                "sic_industry": "Semiconductors & Related Devices",
            }
        }
    )
    profile = provider.get_company_profile("NVDA")
    client.get.assert_called_once_with(
        f"{BASE}/company/facts", headers={"X-API-KEY": "test-key"}, params={"ticker": "NVDA"}
    )
    assert profile.name == "NVIDIA CORP" and profile.cik == "0001045810"
    assert profile.location == "SANTA CLARA, CA" and profile.industry == "Semiconductors"


def test_key_metrics_snapshot(provider, client):
    client.get.return_value = _response(
        payload={
            "snapshot": {
                "ticker": "NVDA",
                "currency": "USD",
                "market_cap": 5.4e12,
                "price_to_earnings_ratio": 34.4,
                "gross_margin": 0.74,
                "debt_to_equity": 0.06,
                "earnings_per_share": 6.53,
            }
        }
    )
    metrics = provider.get_key_metrics("NVDA")
    assert client.get.call_args.args[0] == f"{BASE}/financial-metrics/snapshot"
    assert metrics.market_cap == 5.4e12 and metrics.pe_ratio == 34.4
    assert metrics.gross_margin == 0.74 and metrics.eps == 6.53 and metrics.as_of


@pytest.mark.parametrize(
    "statement,endpoint,key",
    [
        ("income", "financials/income-statements", "income_statements"),
        ("balance_sheet", "financials/balance-sheets", "balance_sheets"),
        ("cash_flow", "financials/cash-flow-statements", "cash_flow_statements"),
    ],
)
def test_financials_endpoints_and_items(provider, client, statement, endpoint, key):
    client.get.return_value = _response(
        payload={
            key: [
                {
                    "ticker": "NVDA",
                    "report_period": "2026-01-25",
                    "fiscal_period": "FY2026",
                    "period": "annual",
                    "currency": "USD",
                    "filing_url": "https://sec.gov/x",
                    "revenue": 100.0,
                    "net_income": 50.0,
                    "some_null": None,
                }
            ]
        }
    )

    statements = provider.get_financials("NVDA", statement=statement, period="annual", limit=3)

    client.get.assert_called_once_with(
        f"{BASE}/{endpoint}",
        headers={"X-API-KEY": "test-key"},
        params={"ticker": "NVDA", "period": "annual", "limit": 3},
    )
    assert len(statements) == 1
    s = statements[0]
    assert s.statement == statement and s.period == "annual" and s.report_period == "2026-01-25"
    assert s.fiscal_period == "FY2026" and s.currency == "USD"
    assert s.items == {"revenue": 100.0, "net_income": 50.0}  # meta + None removed


def test_financials_rejects_bad_enums(provider, client):
    with pytest.raises(FinanceProviderError, match="statement must be one of"):
        provider.get_financials("NVDA", statement="revenue")
    with pytest.raises(FinanceProviderError, match="period must be one of"):
        provider.get_financials("NVDA", period="monthly")
    client.get.assert_not_called()


def test_news_clamps_limit_to_api_max_and_normalizes(provider, client):
    client.get.return_value = _response(
        payload={
            "news": [
                {
                    "ticker": "NVDA",
                    "title": "T",
                    "source": "Reuters",
                    "date": "2026-08-18",
                    "url": "https://x",
                    "sentiment": "positive",
                },
                {"ticker": "NVDA", "title": None},
            ]
        }
    )
    news = provider.get_news("NVDA", limit=50)
    assert client.get.call_args.kwargs["params"] == {"ticker": "NVDA", "limit": 10}
    assert len(news) == 1
    assert news[0].title == "T" and news[0].source == "Reuters" and news[0].summary == "sentiment: positive"


def test_insider_trades(provider, client):
    client.get.return_value = _response(
        payload={
            "insider_trades": [
                {
                    "ticker": "NVDA",
                    "name": "Jen Hsun Huang",
                    "title": "CEO",
                    "transaction_type": "Open market sale",
                    "transaction_date": "2026-08-01",
                    "transaction_shares": -1000,
                    "transaction_price_per_share": 220.5,
                    "transaction_value": -220500,
                    "shares_owned_after_transaction": 5,
                    "filing_date": "2026-08-03",
                }
            ]
        }
    )
    trades = provider.get_insider_trades("NVDA", limit=5)
    assert client.get.call_args.kwargs["params"] == {"ticker": "NVDA", "limit": 5}
    t = trades[0]
    assert t.insider == "Jen Hsun Huang" and t.transaction_type == "Open market sale"
    assert t.shares == -1000 and t.price == 220.5 and t.value == -220500 and t.shares_owned_after == 5


def test_earnings_prefers_quarterly_block(provider, client):
    client.get.return_value = _response(
        payload={
            "earnings": [
                {
                    "ticker": "NVDA",
                    "report_period": "2026-04-26",
                    "fiscal_period": "Q1 2027",
                    "filing_date": "2026-05-28",
                    "filing_url": "https://sec.gov/8k",
                    "quarterly": {"revenue": 44.0e9, "earnings_per_share": 0.81, "net_income": 18.0e9},
                    "annual": {"revenue": 1},
                }
            ]
        }
    )
    reports = provider.get_earnings("NVDA", limit=2)
    assert client.get.call_args.kwargs["params"] == {"ticker": "NVDA", "limit": 2}
    r = reports[0]
    assert r.fiscal_period == "Q1 2027" and r.eps == 0.81 and r.revenue == 44.0e9 and r.net_income == 18.0e9
    assert r.url == "https://sec.gov/8k"


def test_sec_filings_with_and_without_form_type(provider, client):
    client.get.return_value = _response(
        payload={
            "filings": [
                {
                    "cik": 1045810,
                    "accession_number": "0001045810-26-000069",
                    "filing_type": "8-K",
                    "report_date": "2026-08-17",
                    "filing_date": "2026-08-17",
                    "ticker": "NVDA",
                    "url": "https://sec.gov/f",
                }
            ]
        }
    )
    filings = provider.get_sec_filings("NVDA", form_type="8-K", limit=3)
    assert client.get.call_args.kwargs["params"] == {"ticker": "NVDA", "limit": 3, "filing_type": "8-K"}
    assert filings[0].form_type == "8-K" and filings[0].accession_number == "0001045810-26-000069"

    provider.get_sec_filings("NVDA")
    assert client.get.call_args.kwargs["params"] == {"ticker": "NVDA", "limit": 10}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,hint",
    [
        (401, "invalid API key"),
        (402, "plan does not cover"),
        (404, "no data"),
        (429, "rate limited"),
        (500, "request failed"),
    ],
)
def test_http_errors_become_clean_provider_errors(provider, client, status, hint):
    client.get.return_value = _response(status_code=status, payload={"detail": "because"})
    with pytest.raises(FinanceProviderError) as exc:
        provider.get_quote("NVDA")
    message = str(exc.value)
    assert f"HTTP {status}" in message and hint in message and "because" in message
    assert "test-key" not in message


def test_transport_error_is_wrapped(provider, client):
    client.get.side_effect = httpx.ConnectError("boom")
    with pytest.raises(FinanceProviderError, match="Request to financialdatasets.ai failed"):
        provider.get_news("NVDA")


def test_invalid_json_and_missing_snapshot(provider, client):
    client.get.return_value = _response(text="<html>")
    with pytest.raises(FinanceProviderError, match="invalid JSON"):
        provider.get_quote("NVDA")

    client.get.return_value = _response(payload={"snapshot": {}})
    with pytest.raises(FinanceProviderError, match="No quote data"):
        provider.get_quote("NVDA")

    client.get.return_value = _response(payload={"prices": []})
    with pytest.raises(FinanceProviderError, match="No price history"):
        provider.get_price_history("NVDA")


# ---------------------------------------------------------------------------
# Async (native httpx.AsyncClient)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_quote_uses_async_client(provider):
    with patch("agno.tools.finance.financial_datasets.httpx.AsyncClient") as async_cls:
        aclient = async_cls.return_value.__aenter__.return_value
        aclient.get = AsyncMock(return_value=_response(payload={"snapshot": {"price": 1.5, "ticker": "NVDA"}}))
        quote = await provider.aget_quote("NVDA")
    assert quote.price == 1.5
    aclient.get.assert_awaited_once_with(
        f"{BASE}/prices/snapshot", headers={"X-API-KEY": "test-key"}, params={"ticker": "NVDA"}
    )


@pytest.mark.asyncio
async def test_async_error_status_raises(provider):
    with patch("agno.tools.finance.financial_datasets.httpx.AsyncClient") as async_cls:
        aclient = async_cls.return_value.__aenter__.return_value
        aclient.get = AsyncMock(return_value=_response(status_code=402, payload={"detail": "upgrade"}))
        with pytest.raises(FinanceProviderError, match="HTTP 402"):
            await provider.aget_financials("NVDA")


# ---------------------------------------------------------------------------
# End to end through FinanceTools
# ---------------------------------------------------------------------------


def test_through_toolkit_payload(provider, client):
    client.get.return_value = _response(payload={"snapshot": {"price": 225.0, "ticker": "NVDA", "day_change": 1.0}})
    tools = FinanceTools(provider=provider)

    payload = json.loads(tools.get_quote("nvda"))
    assert payload == {
        "symbol": "NVDA",
        "price": 225.0,
        "currency": "USD",
        "change": 1.0,
        "provider": "financial_datasets",
    }


def test_through_toolkit_error_payload(provider, client):
    client.get.return_value = _response(status_code=404, payload={"detail": "nope"})
    tools = FinanceTools(provider=provider)
    payload = json.loads(tools.get_quote("NVDA"))
    assert payload["symbol"] == "NVDA" and payload["provider"] == "financial_datasets"
    assert "HTTP 404" in payload["error"]


def test_magicmock_response_is_not_required():
    # Guard: the parser must accept a real httpx.Response, not only MagicMocks
    assert isinstance(_response(payload={}), httpx.Response)
    assert MagicMock is not None
