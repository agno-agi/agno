"""YFinance normalizers against yfinance-shaped objects (Ticker/Search patched, no network).

Skipped when `yfinance` (and therefore pandas) is not installed; run in `.venvs/demo`.
"""

import json
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

yf = pytest.importorskip("yfinance")
pd = pytest.importorskip("pandas")

from agno.tools.finance import FinanceProviderError, FinanceTools, YFinance  # noqa: E402
from agno.tools.finance.providers.yfinance import _date, _news_item, _num, _snake  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures shaped like yfinance 1.x
# ---------------------------------------------------------------------------

FAST_INFO = {
    "lastPrice": 225.01,
    "previousClose": 225.15,  # last extended-hours print of the previous calendar day
    "regularMarketPreviousClose": 225.16,  # prior regular-session close (what Yahoo shows)
    "open": 226.02,
    "dayHigh": 227.92,
    "dayLow": 224.86,
    "lastVolume": 81442206,
    "marketCap": 5449967210000.0,
    "yearHigh": 236.54,
    "yearLow": 164.07,
    "currency": "USD",
    "exchange": "NMS",
}

INFO = {
    "longName": "NVIDIA Corporation",
    "shortName": "NVIDIA",
    "longBusinessSummary": "NVIDIA builds accelerated computing.",
    "sector": "Technology",
    "industry": "Semiconductors",
    "fullExchangeName": "NasdaqGS",
    "country": "United States",
    "city": "Santa Clara",
    "state": "CA",
    "website": "https://www.nvidia.com",
    "fullTimeEmployees": 42000,
    "currency": "USD",
    "financialCurrency": "USD",
    "marketCap": 5449966944256,
    "enterpriseValue": 5404883943424,
    "trailingPE": 34.457886,
    "forwardPE": 17.532349,
    "trailingPegRatio": 0.6201,
    "priceToBook": 27.88228,
    "priceToSalesTrailing12Months": 21.4996,
    "enterpriseToEbitda": 32.655,
    "trailingEps": 6.53,
    "dividendYield": 0.35,  # Yahoo reports this in percent (0.35 == 0.35%)
    "trailingAnnualDividendYield": 0.0034,  # ...and this one as a fraction
    "beta": 2.215,
    "grossMargins": 0.74144995,
    "operatingMargins": 0.65596,
    "profitMargins": 0.62966,
    "returnOnEquity": 1.14288,
    "returnOnAssets": 0.5273,
    "revenueGrowth": 0.852,
    "earningsGrowth": 2.145,
    "debtToEquity": 78.445,  # percent: 78.445 == 0.78x
    "currentRatio": 3.441,
    "freeCashflow": 46335873024,
    "totalRevenue": 253491003392,
    "ebitda": 165514002432,
    "fiftyTwoWeekHigh": 236.54,
    "fiftyTwoWeekLow": 164.07,
    "recommendationKey": "strong_buy",
    "numberOfAnalystOpinions": 58,
    "targetMeanPrice": 302.82758,
    "targetHighPrice": 500.0,
    "targetLowPrice": 180.0,
    "targetMedianPrice": 300.0,
    "regularMarketPrice": 225.01,
}

NEWS_NEW = [
    {
        "id": "1",
        "content": {
            "title": "Tech stocks today",
            "summary": "Coverage for the week.",
            "pubDate": "2026-08-17T13:29:45Z",
            "provider": {"displayName": "Yahoo Finance"},
            "canonicalUrl": {"url": "https://finance.yahoo.com/a"},
            "clickThroughUrl": {"url": "https://finance.yahoo.com/b"},
        },
    },
    {"id": "2", "content": {"title": ""}},  # dropped: no title
]
NEWS_LEGACY = [
    {"title": "Legacy headline", "link": "https://x/legacy", "publisher": "Wire", "providerPublishTime": 1755000000}
]

SEC_FILINGS = [
    {"date": pd.Timestamp("2026-08-17").date(), "type": "8-K", "title": "Corporate Changes", "edgarUrl": "https://y/1"},
    {"date": pd.Timestamp("2026-05-28").date(), "type": "10-Q", "title": "Quarterly Report", "edgarUrl": "https://y/2"},
]


def _history_frame() -> Any:
    idx = pd.DatetimeIndex(
        [pd.Timestamp("2026-08-11", tz="America/New_York"), pd.Timestamp("2026-08-12", tz="America/New_York")],
        name="Date",
    )
    return pd.DataFrame(
        {
            "Open": [222.17, 221.04],
            "High": [222.2, 225.1],
            "Low": [216.2, 220.2],
            "Close": [217.5, 224.09],
            "Volume": [101273100, 108783600],
            "Dividends": [0.0, 0.0],
            "Stock Splits": [0.0, 0.0],
        },
        index=idx,
    )


def _income_frame() -> Any:
    cols = [pd.Timestamp("2026-01-31"), pd.Timestamp("2025-01-31"), pd.Timestamp("2024-01-31")]
    return pd.DataFrame(
        {
            cols[0]: [253491000000.0, 120067000000.0, float("nan")],
            cols[1]: [130497000000.0, 72880000000.0, 1.0],
            cols[2]: [60922000000.0, 29760000000.0, 2.0],
        },
        index=["Total Revenue", "Net Income", "Tax Effect Of Unusual Items"],
    )


def _tagged_frame(tag: str) -> Any:
    """A one-column statement frame whose only line item names the attribute it came from."""
    return pd.DataFrame({pd.Timestamp("2026-01-31"): [1.0]}, index=[tag])


def _recs_frame() -> Any:
    return pd.DataFrame(
        [
            {"period": "0m", "strongBuy": 10, "buy": 48, "hold": 2, "sell": 1, "strongSell": 0},
            {"period": "-1m", "strongBuy": 9, "buy": 47, "hold": 3, "sell": 1, "strongSell": 0},
        ]
    )


def _insider_frame() -> Any:
    return pd.DataFrame(
        [
            {
                "Shares": 2410,
                "Value": 0,
                "URL": "",
                "Text": "Stock Award(Grant) at price 0.00 per share.",
                "Insider": "NORA JOHNSON SUZANNE M",
                "Position": "Director",
                "Transaction": "",
                "Start Date": pd.Timestamp("2026-08-10"),
                "Ownership": "D",
            },
            {
                "Shares": 500000,
                "Value": 110000000,
                "URL": "https://sec/x",
                "Text": "Sale at price 220.00 per share.",
                "Insider": "COXE TENCH C",
                "Position": "Director",
                "Transaction": "Sale",
                "Start Date": pd.Timestamp("2026-08-05"),
                "Ownership": "I",
            },
        ]
    )


def _earnings_dates_frame() -> Any:
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-08-26 16:00:00", tz="America/New_York"),
            pd.Timestamp("2026-05-20 16:00:00", tz="America/New_York"),
        ],
        name="Earnings Date",
    )
    return pd.DataFrame(
        {"EPS Estimate": [2.08, 1.77], "Reported EPS": [float("nan"), 1.87], "Surprise(%)": [float("nan"), 5.54]},
        index=idx,
    )


def _earnings_history_frame() -> Any:
    idx = pd.DatetimeIndex([pd.Timestamp("2026-01-31"), pd.Timestamp("2026-04-30")], name="quarter")
    return pd.DataFrame(
        {
            "epsActual": [1.62, 1.87],
            "epsEstimate": [1.538, 1.771],
            "epsDifference": [0.08, 0.1],
            "surprisePercent": [0.0532, 0.0554],
        },
        index=idx,
    )


class FakeTicker:
    """Just enough of yfinance.Ticker for the provider."""

    calls: List[tuple] = []

    def __init__(self, symbol: str, session: Any = None, **overrides: Any) -> None:
        FakeTicker.calls.append(("Ticker", symbol, session))
        self.symbol = symbol
        self.session = session
        self.fast_info: Dict[str, Any] = dict(FAST_INFO)
        self.info: Dict[str, Any] = dict(INFO)
        self.news_payload: List[Dict[str, Any]] = NEWS_NEW
        self.recommendations_summary = _recs_frame()
        self.analyst_price_targets = {
            "current": 225.01,
            "high": 500.0,
            "low": 180.0,
            "mean": 302.82758,
            "median": 300.0,
        }
        self.insider_transactions = _insider_frame()
        self.sec_filings = SEC_FILINGS
        self.income_stmt = _income_frame()
        self.quarterly_income_stmt = _tagged_frame("quarterly_income_stmt")
        self.ttm_income_stmt = _tagged_frame("ttm_income_stmt")
        self.balance_sheet = _tagged_frame("balance_sheet")
        self.quarterly_balance_sheet = _tagged_frame("quarterly_balance_sheet")
        self.cash_flow = _tagged_frame("cash_flow")
        self.quarterly_cash_flow = _tagged_frame("quarterly_cash_flow")
        self.ttm_cash_flow = _tagged_frame("ttm_cash_flow")
        self.earnings_history = _earnings_history_frame()
        self._earnings_dates: Optional[Any] = _earnings_dates_frame()
        self.history_frame = _history_frame()
        for key, value in overrides.items():
            setattr(self, key, value)

    def history(self, **kwargs: Any) -> Any:
        FakeTicker.calls.append(("history", self.symbol, kwargs))
        return self.history_frame

    def get_news(self, count: int = 10, tab: str = "news") -> List[Dict[str, Any]]:
        FakeTicker.calls.append(("get_news", self.symbol, count))
        return self.news_payload[:count]

    def get_earnings_dates(self, limit: int = 12) -> Any:
        if self._earnings_dates is None:
            raise RuntimeError("scrape failed")
        return self._earnings_dates


class FakeSearch:
    def __init__(self, query: str, **kwargs: Any) -> None:
        self.query = query
        self.kwargs = kwargs
        self.quotes = [
            {
                "symbol": "NVDA",
                "longname": "NVIDIA Corporation",
                "shortname": "NVIDIA",
                "exchDisp": "NASDAQ",
                "quoteType": "EQUITY",
            },
            {"symbol": "NVD.DE", "shortname": "NVIDIA CORP.", "exchDisp": "XETRA", "quoteType": "EQUITY"},
            {"nosymbol": True},
        ]


@pytest.fixture
def provider() -> YFinance:
    FakeTicker.calls = []
    with patch.object(yf, "Ticker", FakeTicker), patch.object(yf, "Search", FakeSearch):
        yield YFinance()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_status_does_not_hit_network():
    status = YFinance().status()
    assert status.ok is True and "yfinance" in status.detail


def test_search_symbols(provider):
    matches = provider.search_symbols("NVIDIA", limit=2)
    assert [m.symbol for m in matches] == ["NVDA", "NVD.DE"]
    assert matches[0].name == "NVIDIA Corporation" and matches[0].exchange == "NASDAQ" and matches[0].type == "EQUITY"
    assert matches[1].name == "NVIDIA CORP."  # falls back to shortname


def test_quote_from_fast_info(provider):
    quote = provider.get_quote("NVDA")
    assert quote.price == 225.01 and quote.previous_close == 225.16  # regular-session close preferred
    assert quote.change == 225.01 - 225.16
    assert quote.change_percent == (225.01 - 225.16) / 225.16 * 100
    assert quote.market_cap == 5449967210000.0 and quote.fifty_two_week_high == 236.54
    assert quote.currency == "USD" and quote.exchange == "NMS" and quote.as_of


def test_quote_falls_back_to_previous_close(provider):
    fast = {k: v for k, v in FAST_INFO.items() if k != "regularMarketPreviousClose"}
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, fast_info=fast)):
        quote = provider.get_quote("NVDA")
    assert quote.previous_close == 225.15


def test_quote_missing_price_raises(provider):
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, fast_info={"currency": "USD"})):
        with pytest.raises(FinanceProviderError, match="No quote data"):
            provider.get_quote("ZZZZ")


def test_price_history_bars_and_kwargs(provider):
    history = provider.get_price_history("NVDA", period="5d", interval="1d")
    assert history.currency == "USD" and history.period == "5d"
    assert [b.date for b in history.bars] == ["2026-08-11", "2026-08-12"]
    assert history.bars[1].close == 224.09 and history.bars[0].volume == 101273100
    assert ("history", "NVDA", {"period": "5d", "interval": "1d", "auto_adjust": False}) in FakeTicker.calls


def test_price_history_skips_bars_without_a_close(provider):
    frame = _history_frame()
    frame.loc[frame.index[-1], ["Open", "High", "Low", "Close"]] = float("nan")  # Yahoo lag: volume-only latest row
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, history_frame=frame)):
        history = provider.get_price_history("NVDA", period="5d")
    assert [b.date for b in history.bars] == ["2026-08-11"]

    all_nan = _history_frame()
    all_nan[["Open", "High", "Low", "Close"]] = float("nan")
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, history_frame=all_nan)):
        with pytest.raises(FinanceProviderError, match="No price history"):
            provider.get_price_history("NVDA")


def test_price_history_validates_and_handles_empty(provider):
    with pytest.raises(FinanceProviderError, match="period must be one of"):
        provider.get_price_history("NVDA", period="7d")
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, history_frame=pd.DataFrame())):
        with pytest.raises(FinanceProviderError, match="No price history"):
            provider.get_price_history("NVDA")


def test_company_profile(provider):
    profile = provider.get_company_profile("NVDA")
    assert profile.name == "NVIDIA Corporation" and profile.sector == "Technology"
    assert profile.location == "Santa Clara, CA, United States" and profile.country == "United States"
    assert profile.employees == 42000 and profile.exchange == "NasdaqGS" and profile.market_cap == 5449966944256


def test_unknown_symbol_info_raises(provider):
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, info={"trailingPegRatio": None})):
        with pytest.raises(FinanceProviderError, match="No data found for symbol"):
            provider.get_company_profile("ZZZZ")


def test_key_metrics(provider):
    m = provider.get_key_metrics("NVDA")
    assert m.pe_ratio == 34.457886 and m.forward_pe == 17.532349 and m.peg_ratio == 0.6201
    assert m.gross_margin == 0.74144995 and m.free_cash_flow == 46335873024 and m.ebitda == 165514002432
    assert m.fifty_two_week_low == 164.07 and m.currency == "USD" and m.as_of
    # Yahoo's percent-scaled fields are normalized to fractions like the rest of KeyMetrics
    assert m.dividend_yield == 0.0034  # trailingAnnualDividendYield preferred (already a fraction)
    assert m.debt_to_equity == pytest.approx(0.78445)


def test_key_metrics_dividend_yield_falls_back_to_percent_field(provider):
    info = {k: v for k, v in INFO.items() if k != "trailingAnnualDividendYield"}
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, info=info)):
        m = provider.get_key_metrics("NVDA")
    assert m.dividend_yield == pytest.approx(0.0035)  # 0.35% -> 0.0035
    info_none = {k: v for k, v in info.items() if k not in ("dividendYield", "debtToEquity")}
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, info=info_none)):
        m = provider.get_key_metrics("NVDA")
    assert m.dividend_yield is None and m.debt_to_equity is None


def test_financials_snake_case_items_nan_dropped_and_limit(provider):
    statements = provider.get_financials("NVDA", statement="income", period="annual", limit=2)
    assert len(statements) == 2
    first = statements[0]
    assert first.report_period == "2026-01-31" and first.currency == "USD" and first.statement == "income"
    assert first.items == {"total_revenue": 253491000000.0, "net_income": 120067000000.0}  # NaN item dropped
    assert statements[1].items["tax_effect_of_unusual_items"] == 1.0


@pytest.mark.parametrize(
    "statement,period,attr",
    [
        ("income", "quarterly", "quarterly_income_stmt"),
        ("income", "ttm", "ttm_income_stmt"),
        ("balance_sheet", "annual", "balance_sheet"),
        ("balance_sheet", "quarterly", "quarterly_balance_sheet"),
        ("cash_flow", "annual", "cash_flow"),
        ("cash_flow", "quarterly", "quarterly_cash_flow"),
        ("cash_flow", "ttm", "ttm_cash_flow"),
    ],
)
def test_financials_reads_the_right_yfinance_attribute(provider, statement, period, attr):
    statements = provider.get_financials("NVDA", statement=statement, period=period, limit=1)
    assert list(statements[0].items) == [attr]
    assert statements[0].statement == statement and statements[0].period == period


def test_financials_ttm_balance_sheet_not_available(provider):
    with pytest.raises(FinanceProviderError, match="ttm balance_sheet is not available"):
        provider.get_financials("NVDA", statement="balance_sheet", period="ttm")
    with pytest.raises(FinanceProviderError, match="statement must be one of"):
        provider.get_financials("NVDA", statement="revenue")


def test_news_new_shape_and_limit(provider):
    news = provider.get_news("NVDA", limit=5)
    assert len(news) == 1
    n = news[0]
    assert n.title == "Tech stocks today" and n.url == "https://finance.yahoo.com/a"
    assert (
        n.source == "Yahoo Finance"
        and n.published_at == "2026-08-17T13:29:45Z"
        and n.summary == "Coverage for the week."
    )
    assert ("get_news", "NVDA", 5) in FakeTicker.calls


def test_news_legacy_shape():
    item = _news_item(NEWS_LEGACY[0])
    assert item is not None
    assert item.title == "Legacy headline" and item.url == "https://x/legacy" and item.source == "Wire"
    assert item.published_at == "2025-08-12"
    assert _news_item({"content": {"title": None}}) is None
    assert _news_item("junk") is None


def test_analyst_recommendations_merge_sources(provider):
    recs = provider.get_analyst_recommendations("NVDA")
    assert recs.consensus == "strong buy"
    assert (recs.strong_buy, recs.buy, recs.hold, recs.sell, recs.strong_sell) == (10, 48, 2, 1, 0)
    assert recs.num_analysts == 61  # summed from the current-period row
    assert recs.target_mean == 302.82758 and recs.target_high == 500.0 and recs.current_price == 225.01


def test_analyst_recommendations_falls_back_to_info_when_frames_missing(provider):
    with patch.object(
        yf,
        "Ticker",
        lambda s, session=None: FakeTicker(s, recommendations_summary=pd.DataFrame(), analyst_price_targets={}),
    ):
        recs = provider.get_analyst_recommendations("NVDA")
    assert recs.consensus == "strong buy" and recs.num_analysts == 58 and recs.target_mean == 302.82758


def test_analyst_recommendations_none_raises(provider):
    with patch.object(
        yf,
        "Ticker",
        lambda s, session=None: FakeTicker(
            s, recommendations_summary=pd.DataFrame(), analyst_price_targets={}, info={}
        ),
    ):
        with pytest.raises(FinanceProviderError, match="No analyst data"):
            provider.get_analyst_recommendations("NVDA")


def test_insider_trades(provider):
    trades = provider.get_insider_trades("NVDA", limit=1)
    assert len(trades) == 1
    t = trades[0]
    assert t.insider == "NORA JOHNSON SUZANNE M" and t.title == "Director"
    assert t.transaction_type == "Stock Award(Grant) at price 0.00 per share."  # falls back to Text
    assert t.transaction_date == "2026-08-10" and t.shares == 2410 and t.url is None


def test_earnings_prefers_dates_frame_including_upcoming(provider):
    reports = provider.get_earnings("NVDA", limit=2)
    assert len(reports) == 2
    assert reports[0].eps is None and reports[0].eps_estimate == 2.08  # upcoming
    # Yahoo's calendar is keyed by announcement time -> announced_at, not report_period
    assert reports[0].announced_at.startswith("2026-08-26T16:00:00") and reports[0].report_period is None
    assert reports[1].eps == 1.87 and reports[1].surprise_percent == 5.54


def test_earnings_falls_back_to_history_when_scrape_fails(provider):
    with patch.object(yf, "Ticker", lambda s, session=None: FakeTicker(s, _earnings_dates=None)):
        reports = provider.get_earnings("NVDA", limit=5)
    assert [r.report_period for r in reports] == ["2026-04-30", "2026-01-31"]  # fiscal quarter end, most recent first
    assert reports[0].announced_at is None
    assert reports[0].eps == 1.87 and reports[0].surprise_percent == 5.54  # fraction -> percent


def test_sec_filings_filter_and_limit(provider):
    all_filings = provider.get_sec_filings("NVDA", limit=10)
    assert [f.form_type for f in all_filings] == ["8-K", "10-Q"]
    assert all_filings[0].filing_date == "2026-08-17" and all_filings[0].url == "https://y/1"
    only_10q = provider.get_sec_filings("NVDA", form_type="10-q")
    assert [f.form_type for f in only_10q] == ["10-Q"]
    assert len(provider.get_sec_filings("NVDA", limit=1)) == 1


def test_session_and_timeout_are_forwarded():
    sentinel = object()
    seen: Dict[str, Any] = {}

    class RecordingSearch(FakeSearch):
        def __init__(self, query: str, **kwargs: Any) -> None:
            seen.update(kwargs)
            super().__init__(query, **kwargs)

    with patch.object(yf, "Ticker", FakeTicker), patch.object(yf, "Search", RecordingSearch):
        FakeTicker.calls = []
        p = YFinance(session=sentinel, timeout=9)
        p.search_symbols("x")
        assert seen["session"] is sentinel and seen["timeout"] == 9
        p.get_price_history("NVDA")
    assert ("Ticker", "NVDA", sentinel) in FakeTicker.calls  # session reaches yfinance.Ticker
    history_call = next(c for c in FakeTicker.calls if c[0] == "history")
    assert history_call[2]["timeout"] == 9


def test_helpers():
    assert _snake("Total Revenue") == "total_revenue"
    assert _snake("EBITDA") == "ebitda"
    assert _snake("Net Income From Continuing Operation Net Minority Interest") == (
        "net_income_from_continuing_operation_net_minority_interest"
    )
    assert _snake("Tax Effect Of Unusual Items") == "tax_effect_of_unusual_items"
    assert _num("1,234.5") == 1234.5 and _num(True) is None and _num(float("nan")) is None
    assert _num(pd.Series([3.0]).iloc[0]) == 3.0
    assert _date(pd.Timestamp("2026-08-18")) == "2026-08-18"
    assert _date(pd.Timestamp("2026-08-18 16:00", tz="US/Eastern")).startswith("2026-08-18T16:00:00")
    assert _date(1755000000) == "2025-08-12"
    assert _date(None) is None


def test_end_to_end_through_toolkit(provider):
    tools = FinanceTools(provider=provider, all=True)
    quote = json.loads(tools.get_quote("nvda"))
    assert quote["symbol"] == "NVDA" and quote["provider"] == "yfinance" and quote["price"] == 225.01
    fin = json.loads(tools.get_financials("NVDA", limit=1))
    assert fin["results"][0]["items"]["total_revenue"] == 253491000000.0
    assert set(tools.functions) == set(tools.async_functions) and len(tools.functions) == 11
