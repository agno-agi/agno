"""
Finance providers
=================

`FinanceTools` owns the agent-facing tool schema (`get_quote`, `get_news`, ...)
and the JSON shape every tool returns. A `FinanceProvider` is the data adapter
behind it: it talks to one data source (Yahoo Finance, financialdatasets.ai, ...)
and returns the normalized dataclasses defined here. Swapping providers never
changes what the agent sees.

Contract for a provider:

- declare `id`, `name` and `capabilities` (a subset of `ALL_CAPABILITIES`,
  which are exactly the tool names)
- implement the sync method for every capability it declares; the async
  variant defaults to running the sync one in a thread, override it when the
  provider has a native async client
- raise `FinanceProviderError` with an agent-safe message on failure — the
  toolkit turns it into `{"error": ...}`; never let a traceback reach the model
- `status()` must not hit the network
"""

import asyncio
from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional

# ---------------------------------------------------------------------------
# Capabilities == tool names. A provider declares which of these it serves and
# FinanceTools registers only those tools.
# ---------------------------------------------------------------------------

SEARCH_SYMBOLS = "search_symbols"
GET_QUOTE = "get_quote"
GET_PRICE_HISTORY = "get_price_history"
GET_COMPANY_PROFILE = "get_company_profile"
GET_KEY_METRICS = "get_key_metrics"
GET_FINANCIALS = "get_financials"
GET_NEWS = "get_news"
GET_ANALYST_RECOMMENDATIONS = "get_analyst_recommendations"
GET_INSIDER_TRADES = "get_insider_trades"
GET_EARNINGS = "get_earnings"
GET_SEC_FILINGS = "get_sec_filings"

ALL_CAPABILITIES: FrozenSet[str] = frozenset(
    {
        SEARCH_SYMBOLS,
        GET_QUOTE,
        GET_PRICE_HISTORY,
        GET_COMPANY_PROFILE,
        GET_KEY_METRICS,
        GET_FINANCIALS,
        GET_NEWS,
        GET_ANALYST_RECOMMENDATIONS,
        GET_INSIDER_TRADES,
        GET_EARNINGS,
        GET_SEC_FILINGS,
    }
)

# Enum-style parameters. Validated by the toolkit before a provider is called so
# the model gets one stable error message regardless of provider.
PERIODS = ("1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "ytd", "max")
INTERVALS = ("1d", "1wk", "1mo")
STATEMENTS = ("income", "balance_sheet", "cash_flow")
STATEMENT_PERIODS = ("annual", "quarterly", "ttm")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class FinanceProviderError(Exception):
    """A provider call failed. The message is shown to the agent verbatim, so
    keep it short and free of secrets and tracebacks."""


class NotSupportedError(FinanceProviderError):
    """The provider does not serve this capability."""


# ---------------------------------------------------------------------------
# Normalized types. Every provider returns these; the toolkit serializes them.
# ---------------------------------------------------------------------------


@dataclass
class ProviderStatus:
    """Health of a provider. Programmatic only (not surfaced to the model)."""

    ok: bool
    detail: str = ""


@dataclass
class SymbolMatch:
    symbol: str
    name: Optional[str] = None
    exchange: Optional[str] = None
    type: Optional[str] = None


@dataclass
class Quote:
    symbol: str
    price: Optional[float] = None
    currency: Optional[str] = None
    name: Optional[str] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    previous_close: Optional[float] = None
    volume: Optional[float] = None
    market_cap: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    exchange: Optional[str] = None
    as_of: Optional[str] = None


@dataclass
class PriceBar:
    date: str
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None


@dataclass
class PriceHistory:
    symbol: str
    period: str
    interval: str
    currency: Optional[str] = None
    bars: List[PriceBar] = field(default_factory=list)


@dataclass
class CompanyProfile:
    symbol: str
    name: Optional[str] = None
    description: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    exchange: Optional[str] = None
    country: Optional[str] = None
    location: Optional[str] = None
    website: Optional[str] = None
    employees: Optional[int] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    cik: Optional[str] = None


@dataclass
class KeyMetrics:
    """Ratios, margins, growth rates and yields are fractions (0.05 == 5%); money in the
    reporting currency."""

    symbol: str
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    enterprise_value: Optional[float] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    peg_ratio: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    eps: Optional[float] = None
    dividend_yield: Optional[float] = None
    beta: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    return_on_equity: Optional[float] = None
    return_on_assets: Optional[float] = None
    revenue_growth: Optional[float] = None
    earnings_growth: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    free_cash_flow: Optional[float] = None
    revenue: Optional[float] = None
    ebitda: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    as_of: Optional[str] = None


@dataclass
class FinancialStatement:
    """One statement for one period. `items` keeps the provider's line items as
    snake_case keys; the record shape is normalized, the item vocabulary is not."""

    symbol: str
    statement: str
    period: str
    report_period: Optional[str] = None
    fiscal_period: Optional[str] = None
    currency: Optional[str] = None
    items: Dict[str, Any] = field(default_factory=dict)


@dataclass
class NewsItem:
    title: Optional[str] = None
    url: Optional[str] = None
    source: Optional[str] = None
    published_at: Optional[str] = None
    summary: Optional[str] = None


@dataclass
class AnalystRecommendations:
    symbol: str
    consensus: Optional[str] = None
    strong_buy: Optional[int] = None
    buy: Optional[int] = None
    hold: Optional[int] = None
    sell: Optional[int] = None
    strong_sell: Optional[int] = None
    num_analysts: Optional[int] = None
    target_mean: Optional[float] = None
    target_high: Optional[float] = None
    target_low: Optional[float] = None
    target_median: Optional[float] = None
    current_price: Optional[float] = None
    as_of: Optional[str] = None


@dataclass
class InsiderTrade:
    symbol: str
    insider: Optional[str] = None
    title: Optional[str] = None
    transaction_type: Optional[str] = None
    transaction_date: Optional[str] = None
    shares: Optional[float] = None
    price: Optional[float] = None
    value: Optional[float] = None
    shares_owned_after: Optional[float] = None
    filing_date: Optional[str] = None
    url: Optional[str] = None


@dataclass
class EarningsReport:
    """`report_period` is the fiscal period end the numbers cover; `announced_at`
    is when results were (or will be) reported; `filing_date` is the SEC filing date."""

    symbol: str
    report_period: Optional[str] = None
    fiscal_period: Optional[str] = None
    announced_at: Optional[str] = None
    eps: Optional[float] = None
    eps_estimate: Optional[float] = None
    surprise_percent: Optional[float] = None
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    filing_date: Optional[str] = None
    url: Optional[str] = None


@dataclass
class Filing:
    symbol: str
    form_type: Optional[str] = None
    filing_date: Optional[str] = None
    report_period: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    accession_number: Optional[str] = None


# ---------------------------------------------------------------------------
# Provider ABC
# ---------------------------------------------------------------------------


class FinanceProvider(ABC):
    """Base class for finance data providers.

    Subclasses set `id`, `name`, `capabilities` and implement the sync method
    for each declared capability. Async variants default to running the sync
    method in a thread; override them for providers with a native async client.
    """

    id: str = "finance"
    name: str = "Finance provider"
    capabilities: FrozenSet[str] = frozenset()

    # -- health -----------------------------------------------------------

    def status(self) -> ProviderStatus:
        """Whether the provider is usable. Must not hit the network."""
        return ProviderStatus(ok=True, detail=self.name)

    async def astatus(self) -> ProviderStatus:
        return await asyncio.to_thread(self.status)

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    # -- sync data methods (one per capability) ---------------------------

    def _not_supported(self, capability: str) -> NotSupportedError:
        return NotSupportedError(f"{self.name} does not support {capability}")

    def search_symbols(self, query: str, limit: int = 5) -> List[SymbolMatch]:
        raise self._not_supported(SEARCH_SYMBOLS)

    def get_quote(self, symbol: str) -> Quote:
        raise self._not_supported(GET_QUOTE)

    def get_price_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> PriceHistory:
        raise self._not_supported(GET_PRICE_HISTORY)

    def get_company_profile(self, symbol: str) -> CompanyProfile:
        raise self._not_supported(GET_COMPANY_PROFILE)

    def get_key_metrics(self, symbol: str) -> KeyMetrics:
        raise self._not_supported(GET_KEY_METRICS)

    def get_financials(
        self, symbol: str, statement: str = "income", period: str = "annual", limit: int = 4
    ) -> List[FinancialStatement]:
        raise self._not_supported(GET_FINANCIALS)

    def get_news(self, symbol: str, limit: int = 10) -> List[NewsItem]:
        raise self._not_supported(GET_NEWS)

    def get_analyst_recommendations(self, symbol: str) -> AnalystRecommendations:
        raise self._not_supported(GET_ANALYST_RECOMMENDATIONS)

    def get_insider_trades(self, symbol: str, limit: int = 20) -> List[InsiderTrade]:
        raise self._not_supported(GET_INSIDER_TRADES)

    def get_earnings(self, symbol: str, limit: int = 8) -> List[EarningsReport]:
        raise self._not_supported(GET_EARNINGS)

    def get_sec_filings(self, symbol: str, form_type: Optional[str] = None, limit: int = 10) -> List[Filing]:
        raise self._not_supported(GET_SEC_FILINGS)

    # -- async variants (default: sync method in a thread) ----------------

    async def asearch_symbols(self, query: str, limit: int = 5) -> List[SymbolMatch]:
        return await asyncio.to_thread(self.search_symbols, query, limit)

    async def aget_quote(self, symbol: str) -> Quote:
        return await asyncio.to_thread(self.get_quote, symbol)

    async def aget_price_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> PriceHistory:
        return await asyncio.to_thread(self.get_price_history, symbol, period, interval)

    async def aget_company_profile(self, symbol: str) -> CompanyProfile:
        return await asyncio.to_thread(self.get_company_profile, symbol)

    async def aget_key_metrics(self, symbol: str) -> KeyMetrics:
        return await asyncio.to_thread(self.get_key_metrics, symbol)

    async def aget_financials(
        self, symbol: str, statement: str = "income", period: str = "annual", limit: int = 4
    ) -> List[FinancialStatement]:
        return await asyncio.to_thread(self.get_financials, symbol, statement, period, limit)

    async def aget_news(self, symbol: str, limit: int = 10) -> List[NewsItem]:
        return await asyncio.to_thread(self.get_news, symbol, limit)

    async def aget_analyst_recommendations(self, symbol: str) -> AnalystRecommendations:
        return await asyncio.to_thread(self.get_analyst_recommendations, symbol)

    async def aget_insider_trades(self, symbol: str, limit: int = 20) -> List[InsiderTrade]:
        return await asyncio.to_thread(self.get_insider_trades, symbol, limit)

    async def aget_earnings(self, symbol: str, limit: int = 8) -> List[EarningsReport]:
        return await asyncio.to_thread(self.get_earnings, symbol, limit)

    async def aget_sec_filings(self, symbol: str, form_type: Optional[str] = None, limit: int = 10) -> List[Filing]:
        return await asyncio.to_thread(self.get_sec_filings, symbol, form_type, limit)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} id={self.id} capabilities={sorted(self.capabilities)}>"


# ---------------------------------------------------------------------------
# Registry: lets `FinanceTools(provider="<id>")` resolve a name to a class.
# Built-in providers register lazily in `agno.tools.finance.toolkit` so importing
# the package never imports an optional provider SDK.
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: Dict[str, Any] = {}


def register_provider(provider_id: str, provider: Any) -> None:
    """Register a provider under an id for `FinanceTools(provider="<id>")`.

    `provider` is a `FinanceProvider` subclass, or a zero/keyword-argument
    callable that returns one (use a callable to defer optional imports).
    """
    if not provider_id or not isinstance(provider_id, str):
        raise ValueError("provider_id must be a non-empty string")
    _PROVIDER_REGISTRY[provider_id] = provider


def registered_providers() -> List[str]:
    return sorted(_PROVIDER_REGISTRY)


def _get_registered_provider(provider_id: str) -> Optional[Any]:
    return _PROVIDER_REGISTRY.get(provider_id)


__all__ = [
    "ALL_CAPABILITIES",
    "AnalystRecommendations",
    "ProviderStatus",
    "CompanyProfile",
    "EarningsReport",
    "Filing",
    "FinanceProvider",
    "FinanceProviderError",
    "FinancialStatement",
    "GET_ANALYST_RECOMMENDATIONS",
    "GET_COMPANY_PROFILE",
    "GET_EARNINGS",
    "GET_FINANCIALS",
    "GET_INSIDER_TRADES",
    "GET_KEY_METRICS",
    "GET_NEWS",
    "GET_PRICE_HISTORY",
    "GET_QUOTE",
    "GET_SEC_FILINGS",
    "INTERVALS",
    "InsiderTrade",
    "KeyMetrics",
    "NewsItem",
    "NotSupportedError",
    "PERIODS",
    "PriceBar",
    "PriceHistory",
    "Quote",
    "SEARCH_SYMBOLS",
    "STATEMENTS",
    "STATEMENT_PERIODS",
    "SymbolMatch",
    "register_provider",
    "registered_providers",
]
