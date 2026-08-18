"""
FinancialDatasetsProvider — financialdatasets.ai REST API.

Structured, real-time market data built for agents: prices, company facts,
financial statements, metrics, news, insider trades, earnings, SEC filings.
Commercial use is allowed on every plan. Needs `FINANCIAL_DATASETS_API_KEY`
(free keys cover AAPL, GOOGL, NVDA and TSLA). No extra dependency: uses `httpx`.

Not served by this provider (absent from the API): `search_symbols` and
`get_analyst_recommendations` — `FinanceTools` simply does not register those
tools when this provider is selected.

Endpoints follow the OpenAPI spec published at
https://www.financialdatasets.ai/openapi.json (fetched 2026-08-18).
"""

from datetime import date, datetime, timedelta, timezone
from os import getenv
from typing import Any, Dict, List, Optional

import httpx

from agno.tools.finance.base import (
    GET_COMPANY_PROFILE,
    GET_EARNINGS,
    GET_FINANCIALS,
    GET_INSIDER_TRADES,
    GET_KEY_METRICS,
    GET_NEWS,
    GET_PRICE_HISTORY,
    GET_QUOTE,
    GET_SEC_FILINGS,
    INTERVALS,
    PERIODS,
    STATEMENT_PERIODS,
    STATEMENTS,
    CompanyProfile,
    EarningsReport,
    Filing,
    FinanceProvider,
    FinanceProviderError,
    FinancialStatement,
    InsiderTrade,
    KeyMetrics,
    NewsItem,
    PriceBar,
    PriceHistory,
    ProviderStatus,
    Quote,
)
from agno.utils.log import log_error

_ENV_KEY = "FINANCIAL_DATASETS_API_KEY"
_DEFAULT_BASE_URL = "https://api.financialdatasets.ai"
_NEWS_MAX = 10  # API maximum per request

# `get_price_history` period -> look-back window
_PERIOD_DAYS: Dict[str, Optional[int]] = {
    "1d": 1,
    "5d": 7,
    "1mo": 31,
    "3mo": 92,
    "6mo": 183,
    "1y": 366,
    "2y": 731,
    "5y": 1827,
    "ytd": None,  # computed from Jan 1
    "max": 365 * 40,
}
_INTERVAL_MAP: Dict[str, str] = {"1d": "day", "1wk": "week", "1mo": "month"}

_STATEMENT_ENDPOINTS: Dict[str, str] = {
    "income": "financials/income-statements",
    "balance_sheet": "financials/balance-sheets",
    "cash_flow": "financials/cash-flow-statements",
}
_STATEMENT_KEYS: Dict[str, str] = {
    "income": "income_statements",
    "balance_sheet": "balance_sheets",
    "cash_flow": "cash_flow_statements",
}
# Metadata fields on statement records; everything else is a line item.
_STATEMENT_META = frozenset(
    {
        "ticker",
        "report_period",
        "fiscal_period",
        "period",
        "currency",
        "accession_number",
        "form_type",
        "filing_url",
        "filing_date",
        "filing_datetime",
        "cik",
    }
)


class FinancialDatasetsProvider(FinanceProvider):
    """financialdatasets.ai data provider.

    Args:
        api_key: API key. Falls back to the `FINANCIAL_DATASETS_API_KEY` env var.
        base_url: API base URL.
        timeout: Per-request timeout in seconds. Defaults to 30.
    """

    id = "financial_datasets"
    name = "Financial Datasets (financialdatasets.ai)"
    capabilities = frozenset(
        {
            GET_QUOTE,
            GET_PRICE_HISTORY,
            GET_COMPANY_PROFILE,
            GET_KEY_METRICS,
            GET_FINANCIALS,
            GET_NEWS,
            GET_INSIDER_TRADES,
            GET_EARNINGS,
            GET_SEC_FILINGS,
        }
    )

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = _DEFAULT_BASE_URL,
        timeout: Optional[float] = 30.0,
    ) -> None:
        self.api_key: Optional[str] = api_key or getenv(_ENV_KEY)
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout if timeout is not None else 30.0
        if not self.api_key:
            log_error(f"{_ENV_KEY} not set. Please set the {_ENV_KEY} environment variable.")

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def status(self) -> ProviderStatus:
        if not self.api_key:
            return ProviderStatus(ok=False, detail=f"{_ENV_KEY} not set")
        return ProviderStatus(ok=True, detail=self.base_url)

    async def astatus(self) -> ProviderStatus:
        return self.status()

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise FinanceProviderError(f"{_ENV_KEY} not configured")
        return {"X-API-KEY": self.api_key}

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _params(params: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in params.items() if v is not None}

    def _get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        headers = self._headers()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(self._url(path), headers=headers, params=self._params(params))
        except httpx.RequestError as e:
            raise FinanceProviderError(f"Request to financialdatasets.ai failed: {e}") from e
        return self._parse(response, path)

    async def _aget(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        headers = self._headers()
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(self._url(path), headers=headers, params=self._params(params))
        except httpx.RequestError as e:
            raise FinanceProviderError(f"Request to financialdatasets.ai failed: {e}") from e
        return self._parse(response, path)

    @staticmethod
    def _parse(response: httpx.Response, path: str) -> Dict[str, Any]:
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = str(body.get("detail") or body.get("error") or body.get("message") or "")
            except ValueError:
                detail = response.text[:200]
            hint = {
                401: "invalid API key",
                402: "plan does not cover this request (free keys cover AAPL, GOOGL, NVDA, TSLA)",
                404: "no data for this request",
                429: "rate limited",
            }.get(response.status_code, "request failed")
            message = f"financialdatasets.ai {path}: HTTP {response.status_code} ({hint})"
            if detail:
                message = f"{message}: {detail}"
            log_error(message)
            raise FinanceProviderError(message)
        try:
            data = response.json()
        except ValueError as e:
            raise FinanceProviderError(f"financialdatasets.ai {path}: invalid JSON response") from e
        if not isinstance(data, dict):
            raise FinanceProviderError(f"financialdatasets.ai {path}: unexpected response shape")
        return data

    # ------------------------------------------------------------------
    # Capabilities — sync
    # ------------------------------------------------------------------

    def get_quote(self, symbol: str) -> Quote:
        return self._quote(symbol, self._get("prices/snapshot", {"ticker": symbol}))

    def get_price_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> PriceHistory:
        params = self._history_params(symbol, period, interval)
        return self._history(symbol, period, interval, self._get("prices", params))

    def get_company_profile(self, symbol: str) -> CompanyProfile:
        return self._profile(symbol, self._get("company/facts", {"ticker": symbol}))

    def get_key_metrics(self, symbol: str) -> KeyMetrics:
        return self._metrics(symbol, self._get("financial-metrics/snapshot", {"ticker": symbol}))

    def get_financials(
        self, symbol: str, statement: str = "income", period: str = "annual", limit: int = 4
    ) -> List[FinancialStatement]:
        endpoint = self._statement_endpoint(statement, period)
        data = self._get(endpoint, {"ticker": symbol, "period": period, "limit": limit})
        return self._statements(symbol, statement, period, data)

    def get_news(self, symbol: str, limit: int = 10) -> List[NewsItem]:
        data = self._get("news", {"ticker": symbol, "limit": min(max(limit, 1), _NEWS_MAX)})
        return self._news(data)

    def get_insider_trades(self, symbol: str, limit: int = 20) -> List[InsiderTrade]:
        return self._insider_trades(symbol, self._get("insider-trades", {"ticker": symbol, "limit": limit}))

    def get_earnings(self, symbol: str, limit: int = 8) -> List[EarningsReport]:
        return self._earnings(symbol, self._get("earnings", {"ticker": symbol, "limit": limit}))

    def get_sec_filings(self, symbol: str, form_type: Optional[str] = None, limit: int = 10) -> List[Filing]:
        params: Dict[str, Any] = {"ticker": symbol, "limit": limit}
        if form_type:
            params["filing_type"] = form_type
        return self._filings(symbol, self._get("filings", params))

    # ------------------------------------------------------------------
    # Capabilities — async (native httpx)
    # ------------------------------------------------------------------

    async def aget_quote(self, symbol: str) -> Quote:
        return self._quote(symbol, await self._aget("prices/snapshot", {"ticker": symbol}))

    async def aget_price_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> PriceHistory:
        params = self._history_params(symbol, period, interval)
        return self._history(symbol, period, interval, await self._aget("prices", params))

    async def aget_company_profile(self, symbol: str) -> CompanyProfile:
        return self._profile(symbol, await self._aget("company/facts", {"ticker": symbol}))

    async def aget_key_metrics(self, symbol: str) -> KeyMetrics:
        return self._metrics(symbol, await self._aget("financial-metrics/snapshot", {"ticker": symbol}))

    async def aget_financials(
        self, symbol: str, statement: str = "income", period: str = "annual", limit: int = 4
    ) -> List[FinancialStatement]:
        endpoint = self._statement_endpoint(statement, period)
        data = await self._aget(endpoint, {"ticker": symbol, "period": period, "limit": limit})
        return self._statements(symbol, statement, period, data)

    async def aget_news(self, symbol: str, limit: int = 10) -> List[NewsItem]:
        data = await self._aget("news", {"ticker": symbol, "limit": min(max(limit, 1), _NEWS_MAX)})
        return self._news(data)

    async def aget_insider_trades(self, symbol: str, limit: int = 20) -> List[InsiderTrade]:
        return self._insider_trades(symbol, await self._aget("insider-trades", {"ticker": symbol, "limit": limit}))

    async def aget_earnings(self, symbol: str, limit: int = 8) -> List[EarningsReport]:
        return self._earnings(symbol, await self._aget("earnings", {"ticker": symbol, "limit": limit}))

    async def aget_sec_filings(self, symbol: str, form_type: Optional[str] = None, limit: int = 10) -> List[Filing]:
        params: Dict[str, Any] = {"ticker": symbol, "limit": limit}
        if form_type:
            params["filing_type"] = form_type
        return self._filings(symbol, await self._aget("filings", params))

    # ------------------------------------------------------------------
    # Request shaping
    # ------------------------------------------------------------------

    @staticmethod
    def _history_params(symbol: str, period: str, interval: str) -> Dict[str, Any]:
        if period not in PERIODS:
            raise FinanceProviderError(f"period must be one of {', '.join(PERIODS)}")
        if interval not in INTERVALS:
            raise FinanceProviderError(f"interval must be one of {', '.join(INTERVALS)}")
        today = datetime.now(timezone.utc).date()
        days = _PERIOD_DAYS[period]
        start = date(today.year, 1, 1) if days is None else today - timedelta(days=days)
        return {
            "ticker": symbol,
            "interval": _INTERVAL_MAP[interval],
            "interval_multiplier": 1,
            "start_date": start.isoformat(),
            "end_date": today.isoformat(),
        }

    @staticmethod
    def _statement_endpoint(statement: str, period: str) -> str:
        if statement not in STATEMENTS:
            raise FinanceProviderError(f"statement must be one of {', '.join(STATEMENTS)}")
        if period not in STATEMENT_PERIODS:
            raise FinanceProviderError(f"period must be one of {', '.join(STATEMENT_PERIODS)}")
        return _STATEMENT_ENDPOINTS[statement]

    # ------------------------------------------------------------------
    # Normalizers (pure; unit-tested against OpenAPI-shaped fixtures)
    # ------------------------------------------------------------------

    @staticmethod
    def _quote(symbol: str, data: Dict[str, Any]) -> Quote:
        snap = data.get("snapshot")
        if not isinstance(snap, dict) or snap.get("price") is None:
            raise FinanceProviderError(f"No quote data for symbol {symbol}")
        return Quote(
            symbol=str(snap.get("ticker") or symbol),
            price=_num(snap.get("price")),
            currency="USD",
            change=_num(snap.get("day_change")),
            change_percent=_num(snap.get("day_change_percent")),
            as_of=_str(snap.get("time")),
        )

    @staticmethod
    def _history(symbol: str, period: str, interval: str, data: Dict[str, Any]) -> PriceHistory:
        prices = data.get("prices")
        if not isinstance(prices, list) or not prices:
            raise FinanceProviderError(f"No price history for symbol {symbol} (period={period}, interval={interval})")
        bars = [
            PriceBar(
                date=_str(p.get("time")) or "",
                open=_num(p.get("open")),
                high=_num(p.get("high")),
                low=_num(p.get("low")),
                close=_num(p.get("close")),
                volume=_num(p.get("volume")),
            )
            for p in prices
            if isinstance(p, dict)
        ]
        return PriceHistory(symbol=symbol, period=period, interval=interval, currency="USD", bars=bars)

    @staticmethod
    def _profile(symbol: str, data: Dict[str, Any]) -> CompanyProfile:
        facts = data.get("company_facts")
        if not isinstance(facts, dict) or not facts:
            raise FinanceProviderError(f"No company facts for symbol {symbol}")
        return CompanyProfile(
            symbol=str(facts.get("ticker") or symbol),
            name=_str(facts.get("name")),
            sector=_str(facts.get("sector")),
            industry=_str(facts.get("industry")) or _str(facts.get("sic_industry")),
            exchange=_str(facts.get("exchange")),
            location=_str(facts.get("location")),
            website=_str(facts.get("website")),
            employees=_int(facts.get("number_of_employees")),
            market_cap=_num(facts.get("market_cap")),
            cik=_str(facts.get("cik")),
        )

    @staticmethod
    def _metrics(symbol: str, data: Dict[str, Any]) -> KeyMetrics:
        snap = data.get("snapshot")
        if not isinstance(snap, dict) or not snap:
            raise FinanceProviderError(f"No financial metrics for symbol {symbol}")
        return KeyMetrics(
            symbol=str(snap.get("ticker") or symbol),
            currency=_str(snap.get("currency")),
            market_cap=_num(snap.get("market_cap")),
            enterprise_value=_num(snap.get("enterprise_value")),
            pe_ratio=_num(snap.get("price_to_earnings_ratio")),
            peg_ratio=_num(snap.get("peg_ratio")),
            price_to_book=_num(snap.get("price_to_book_ratio")),
            price_to_sales=_num(snap.get("price_to_sales_ratio")),
            ev_to_ebitda=_num(snap.get("enterprise_value_to_ebitda_ratio")),
            eps=_num(snap.get("earnings_per_share")),
            gross_margin=_num(snap.get("gross_margin")),
            operating_margin=_num(snap.get("operating_margin")),
            net_margin=_num(snap.get("net_margin")),
            return_on_equity=_num(snap.get("return_on_equity")),
            return_on_assets=_num(snap.get("return_on_assets")),
            revenue_growth=_num(snap.get("revenue_growth")),
            earnings_growth=_num(snap.get("earnings_growth")),
            debt_to_equity=_num(snap.get("debt_to_equity")),
            current_ratio=_num(snap.get("current_ratio")),
            as_of=_now(),
        )

    @staticmethod
    def _statements(symbol: str, statement: str, period: str, data: Dict[str, Any]) -> List[FinancialStatement]:
        records = data.get(_STATEMENT_KEYS[statement])
        if not isinstance(records, list) or not records:
            raise FinanceProviderError(f"No {period} {statement} statement for symbol {symbol}")
        out: List[FinancialStatement] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            items = {k: v for k, v in rec.items() if k not in _STATEMENT_META and v is not None}
            out.append(
                FinancialStatement(
                    symbol=str(rec.get("ticker") or symbol),
                    statement=statement,
                    period=str(rec.get("period") or period),
                    report_period=_str(rec.get("report_period")),
                    fiscal_period=_str(rec.get("fiscal_period")),
                    currency=_str(rec.get("currency")),
                    items=items,
                )
            )
        return out

    @staticmethod
    def _news(data: Dict[str, Any]) -> List[NewsItem]:
        news = data.get("news")
        if not isinstance(news, list):
            return []
        items: List[NewsItem] = []
        for n in news:
            if not isinstance(n, dict) or not n.get("title"):
                continue
            sentiment = _str(n.get("sentiment"))
            items.append(
                NewsItem(
                    title=_str(n.get("title")),
                    url=_str(n.get("url")),
                    source=_str(n.get("source")),
                    published_at=_str(n.get("date")),
                    summary=f"sentiment: {sentiment}" if sentiment else None,
                )
            )
        return items

    @staticmethod
    def _insider_trades(symbol: str, data: Dict[str, Any]) -> List[InsiderTrade]:
        trades = data.get("insider_trades")
        if not isinstance(trades, list):
            return []
        return [
            InsiderTrade(
                symbol=str(t.get("ticker") or symbol),
                insider=_str(t.get("name")),
                title=_str(t.get("title")),
                transaction_type=_str(t.get("transaction_type")) or _str(t.get("transaction_code")),
                transaction_date=_str(t.get("transaction_date")),
                shares=_num(t.get("transaction_shares")),
                price=_num(t.get("transaction_price_per_share")),
                value=_num(t.get("transaction_value")),
                shares_owned_after=_num(t.get("shares_owned_after_transaction")),
                filing_date=_str(t.get("filing_date")),
            )
            for t in trades
            if isinstance(t, dict)
        ]

    @staticmethod
    def _earnings(symbol: str, data: Dict[str, Any]) -> List[EarningsReport]:
        earnings = data.get("earnings")
        if not isinstance(earnings, list):
            return []
        out: List[EarningsReport] = []
        for e in earnings:
            if not isinstance(e, dict):
                continue
            block = e.get("quarterly") if isinstance(e.get("quarterly"), dict) else e.get("annual")
            block = block if isinstance(block, dict) else {}
            out.append(
                EarningsReport(
                    symbol=str(e.get("ticker") or symbol),
                    report_period=_str(e.get("report_period")),
                    fiscal_period=_str(e.get("fiscal_period")),
                    eps=_num(block.get("earnings_per_share")),
                    revenue=_num(block.get("revenue")),
                    net_income=_num(block.get("net_income")),
                    filing_date=_str(e.get("filing_date")),
                    url=_str(e.get("filing_url")),
                )
            )
        return out

    @staticmethod
    def _filings(symbol: str, data: Dict[str, Any]) -> List[Filing]:
        filings = data.get("filings")
        if not isinstance(filings, list):
            return []
        return [
            Filing(
                symbol=str(f.get("ticker") or symbol),
                form_type=_str(f.get("filing_type")),
                filing_date=_str(f.get("filing_date")),
                report_period=_str(f.get("report_date")),
                url=_str(f.get("url")),
                accession_number=_str(f.get("accession_number")),
            )
            for f in filings
            if isinstance(f, dict)
        ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _num(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.replace(",", ""))
        except ValueError:
            return None
    return None


def _int(value: Any) -> Optional[int]:
    number = _num(value)
    return int(number) if number is not None else None


def _str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = ["FinancialDatasetsProvider"]
