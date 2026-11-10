"""
FinanceTools
============

One finance toolkit, swappable data providers. The toolkit owns the tool
names, parameters and JSON shapes; a `FinanceProvider` supplies the data.

```python
from agno.agent import Agent
from agno.tools.finance import FinanceTools

agent = Agent(model="openai:gpt-5.6", tools=[FinanceTools()])
agent.print_response("Give me a market brief on NVIDIA", stream=True)
```

Swap the provider without touching the agent:

```python
from agno.tools.finance.providers import FinancialDatasets, YFinance

FinanceTools(provider=FinancialDatasets())                # financialdatasets.ai, FINANCIAL_DATASETS_API_KEY
FinanceTools(provider=YFinance(session=session))          # a configured provider instance
FinanceTools(provider="financial_datasets")               # registered id (shorthand)
```
"""

import json
import math
from dataclasses import asdict, is_dataclass
from os import getenv
from pathlib import Path
from tempfile import gettempdir
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from agno.tools.finance.base import (
    ALL_CAPABILITIES,
    GET_ANALYST_RECOMMENDATIONS,
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
    SEARCH_SYMBOLS,
    STATEMENT_PERIODS,
    STATEMENTS,
    FinanceProvider,
    FinanceProviderError,
    ProviderStatus,
    _get_registered_provider,
    register_provider,
    registered_providers,
)
from agno.tools.toolkit import Toolkit
from agno.utils.log import log_debug, log_error, log_warning

# Upper bounds on list sizes so a single tool call cannot flood the context.
_MAX_SEARCH_RESULTS = 25
_MAX_STATEMENTS = 20
_MAX_NEWS = 50
_MAX_INSIDER_TRADES = 100
_MAX_EARNINGS = 40
_MAX_FILINGS = 100

# Short, model-facing description per tool. Used to build the toolkit
# instructions from whatever subset of tools ends up registered.
_TOOL_HINTS: Dict[str, str] = {
    SEARCH_SYMBOLS: "company name -> ticker symbol",
    GET_QUOTE: "current price and day change",
    GET_PRICE_HISTORY: "OHLCV bars over a period, for trends and performance",
    GET_COMPANY_PROFILE: "what the company does, sector, industry",
    GET_KEY_METRICS: "valuation, margins, growth, balance-sheet ratios",
    GET_FINANCIALS: "income statement, balance sheet or cash flow by period",
    GET_NEWS: "recent headlines",
    GET_ANALYST_RECOMMENDATIONS: "analyst consensus and price targets",
    GET_INSIDER_TRADES: "recent insider buys and sells",
    GET_EARNINGS: "reported vs estimated earnings by period",
    GET_SEC_FILINGS: "recent SEC filings",
}

# Registration order == the order tools appear in the model's tool list.
_TOOL_ORDER: Tuple[str, ...] = (
    SEARCH_SYMBOLS,
    GET_QUOTE,
    GET_PRICE_HISTORY,
    GET_COMPANY_PROFILE,
    GET_KEY_METRICS,
    GET_NEWS,
    GET_ANALYST_RECOMMENDATIONS,
    GET_FINANCIALS,
    GET_INSIDER_TRADES,
    GET_EARNINGS,
    GET_SEC_FILINGS,
)


def _register_builtin_providers() -> None:
    """Register the built-in provider ids lazily so importing this module never
    imports an optional provider SDK (yfinance)."""
    if _get_registered_provider("yfinance") is None:

        def _yfinance(**kwargs: Any) -> FinanceProvider:
            from agno.tools.finance.providers.yfinance import YFinance

            return YFinance(**kwargs)

        register_provider("yfinance", _yfinance)

    if _get_registered_provider("financial_datasets") is None:

        def _financial_datasets(**kwargs: Any) -> FinanceProvider:
            from agno.tools.finance.providers.financial_datasets import FinancialDatasets

            return FinancialDatasets(**kwargs)

        register_provider("financial_datasets", _financial_datasets)


def _yfinance_importable() -> bool:
    try:
        import yfinance  # noqa: F401
    except ImportError:
        return False
    return True


class FinanceTools(Toolkit):
    """Market data tools with a swappable provider.

    Args:
        provider: A `FinanceProvider` instance, a registered provider id
            (`"yfinance"`, `"financial_datasets"`), or None. None resolves to
            `"yfinance"` when the `yfinance` package is installed, otherwise to
            `"financial_datasets"` when `FINANCIAL_DATASETS_API_KEY` is set.
        search_symbols: Register `search_symbols` (company name -> ticker). Default True.
        quote: Register `get_quote`. Default True.
        price_history: Register `get_price_history`. Default True.
        company_profile: Register `get_company_profile`. Default True.
        key_metrics: Register `get_key_metrics`. Default True.
        news: Register `get_news`. Default True.
        analyst_recommendations: Register `get_analyst_recommendations`. Default True.
        financials: Register `get_financials` (statements; large payloads). Default False.
        insider_trades: Register `get_insider_trades`. Default False.
        earnings: Register `get_earnings`. Default False.
        sec_filings: Register `get_sec_filings`. Default False.
        all: Register every tool the provider supports. Default False.
        instructions: Override the generated toolkit instructions.
        add_instructions: Add the toolkit instructions to the agent. Default True.
        timeout: Request timeout in seconds, forwarded when the provider is built
            from an id / None. Ignored (with a warning) for a provider instance.
        **kwargs: Passed to `Toolkit` (include_tools, exclude_tools, cache_results, ...).

    A tool is registered only when its toggle is on *and* the provider declares
    the capability, so the model never sees a tool the provider cannot serve.
    """

    def __init__(
        self,
        provider: Union[FinanceProvider, str, None] = None,
        search_symbols: bool = True,
        quote: bool = True,
        price_history: bool = True,
        company_profile: bool = True,
        key_metrics: bool = True,
        news: bool = True,
        analyst_recommendations: bool = True,
        financials: bool = False,
        insider_trades: bool = False,
        earnings: bool = False,
        sec_filings: bool = False,
        all: bool = False,
        instructions: Optional[str] = None,
        add_instructions: bool = True,
        timeout: Optional[float] = None,
        **kwargs,
    ):
        self.provider: FinanceProvider = self._resolve_provider(provider, timeout=timeout)

        wanted: Dict[str, bool] = {
            SEARCH_SYMBOLS: search_symbols,
            GET_QUOTE: quote,
            GET_PRICE_HISTORY: price_history,
            GET_COMPANY_PROFILE: company_profile,
            GET_KEY_METRICS: key_metrics,
            GET_NEWS: news,
            GET_ANALYST_RECOMMENDATIONS: analyst_recommendations,
            GET_FINANCIALS: financials,
            GET_INSIDER_TRADES: insider_trades,
            GET_EARNINGS: earnings,
            GET_SEC_FILINGS: sec_filings,
        }
        # `include_tools=[...]` names a tool explicitly, so it should not also
        # need its toggle flipped: FinanceTools(include_tools=["get_financials"])
        # just works. Names the provider cannot serve still fail the Toolkit
        # include/exclude check below with a clear message.
        for tool_name in kwargs.get("include_tools") or []:
            if tool_name in wanted:
                wanted[tool_name] = True

        tools: List[Callable] = []
        async_tools: List[Tuple[Callable, str]] = []
        registered: List[str] = []
        for tool_name in _TOOL_ORDER:
            if not (all or wanted[tool_name]):
                continue
            if not self.provider.supports(tool_name):
                log_debug(f"FinanceTools: {self.provider.id} does not support {tool_name}, skipping")
                continue
            tools.append(getattr(self, tool_name))
            async_tools.append((getattr(self, f"a{tool_name}"), tool_name))
            registered.append(tool_name)

        # cache_results: Function cache keys are `<tool name>:<args>` in a
        # process-wide directory, and every provider serves the same tool names.
        # Scope the cache to the provider so two toolkits with different
        # providers never hand each other's payloads back.
        if kwargs.get("cache_results") and not kwargs.get("cache_dir"):
            kwargs["cache_dir"] = str(Path(gettempdir()) / "agno_cache" / "finance" / self.provider.id)

        name = kwargs.pop("name", "finance_tools")
        super().__init__(
            name=name,
            tools=tools,
            async_tools=async_tools,
            instructions=instructions,
            add_instructions=add_instructions,
            **kwargs,
        )

        # What actually got registered, after the Toolkit include/exclude
        # filters. Instructions are built from this list so the model is never
        # told about a tool it does not have.
        self._registered_tools: List[str] = [name for name in _TOOL_ORDER if name in self.functions]
        if instructions is None:
            self.instructions = self._build_instructions(self._registered_tools) or None

        if not self._registered_tools:
            log_warning(
                f"FinanceTools: no tools registered for provider '{self.provider.id}' "
                f"(supports: {sorted(self.provider.capabilities)})"
            )

    # ------------------------------------------------------------------
    # Provider resolution
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_provider(
        provider: Union[FinanceProvider, str, None], timeout: Optional[float] = None
    ) -> FinanceProvider:
        if isinstance(provider, FinanceProvider):
            if timeout is not None:
                log_warning(
                    "FinanceTools: `timeout` is ignored when a provider instance is passed; set it on the provider"
                )
            return provider

        _register_builtin_providers()

        if provider is None:
            if _yfinance_importable():
                provider = "yfinance"
            elif getenv("FINANCIAL_DATASETS_API_KEY"):
                provider = "financial_datasets"
            else:
                raise ImportError(
                    "FinanceTools needs a data provider. Install the default one with `pip install yfinance`, "
                    "or set FINANCIAL_DATASETS_API_KEY and use FinanceTools(provider='financial_datasets')."
                )
            log_debug(f"FinanceTools: using '{provider}' provider")

        if not isinstance(provider, str):
            raise TypeError(
                f"provider must be a FinanceProvider, a provider id string, or None; got {type(provider).__name__}"
            )

        factory = _get_registered_provider(provider)
        if factory is None:
            raise ValueError(f"Unknown finance provider '{provider}'. Registered providers: {registered_providers()}")

        kwargs: Dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = timeout
        instance = factory(**kwargs)
        if not isinstance(instance, FinanceProvider):
            raise TypeError(
                f"Provider factory for '{provider}' returned {type(instance).__name__}, expected FinanceProvider"
            )
        return instance

    # ------------------------------------------------------------------
    # Instructions
    # ------------------------------------------------------------------

    def _build_instructions(self, registered: List[str]) -> str:
        if not registered:
            return ""
        tool_lines = "\n".join(f"- `{name}`: {_TOOL_HINTS[name]}" for name in registered)
        lines = [
            f"Market data comes from {self.provider.name} through these tools:",
            tool_lines,
            "",
            "Guidelines:",
        ]
        if SEARCH_SYMBOLS in registered:
            lines.append("- Work with ticker symbols. If you only have a company name, call `search_symbols` first.")
        else:
            lines.append("- Work with ticker symbols (e.g. NVIDIA -> NVDA).")
        lines.extend(
            [
                "- Every result includes `provider` and, where available, `as_of`. State the ticker, currency and as-of time.",
                '- If a field is missing from a result, say "N/A". Never invent a number.',
                "- This is market data, not personalized investment advice.",
            ]
        )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Health (programmatic; not exposed to the model)
    # ------------------------------------------------------------------

    def status(self) -> ProviderStatus:
        return self.provider.status()

    async def astatus(self) -> ProviderStatus:
        return await self.provider.astatus()

    @property
    def registered_tools(self) -> List[str]:
        return list(self._registered_tools)

    # ------------------------------------------------------------------
    # Dispatch + serialization
    # ------------------------------------------------------------------

    def _call(self, capability: str, symbol: Optional[str] = None, **kwargs: Any) -> str:
        context = self._context(symbol, kwargs)
        try:
            result = getattr(self.provider, capability)(**self._args(symbol, kwargs))
        except Exception as e:
            return self._error(capability, context, e)
        return self._ok(result, context)

    async def _acall(self, capability: str, symbol: Optional[str] = None, **kwargs: Any) -> str:
        context = self._context(symbol, kwargs)
        try:
            result = await getattr(self.provider, f"a{capability}")(**self._args(symbol, kwargs))
        except Exception as e:
            return self._error(capability, context, e)
        return self._ok(result, context)

    @staticmethod
    def _args(symbol: Optional[str], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        args = dict(kwargs)
        if symbol is not None:
            args["symbol"] = symbol
        return args

    def _context(self, symbol: Optional[str], kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Fields echoed on every response so the model can tie results to a request."""
        context: Dict[str, Any] = {}
        if symbol is not None:
            context["symbol"] = symbol
        for key in ("query", "statement", "period", "interval", "form_type"):
            if kwargs.get(key) is not None:
                context[key] = kwargs[key]
        return context

    def _ok(self, result: Any, context: Dict[str, Any]) -> str:
        if isinstance(result, list):
            payload: Dict[str, Any] = dict(context)
            payload["results"] = result
        elif is_dataclass(result) and not isinstance(result, type):
            payload = asdict(result)
        elif isinstance(result, dict):
            payload = dict(result)
        else:
            payload = dict(context)
            payload["result"] = result
        payload["provider"] = self.provider.id
        return json.dumps(_clean(payload), default=str)

    def _error(self, capability: str, context: Dict[str, Any], e: Exception) -> str:
        if isinstance(e, FinanceProviderError):
            message = str(e) or type(e).__name__
        else:
            message = f"{type(e).__name__}: {e}" if str(e) else type(e).__name__
        log_error(f"FinanceTools.{capability} failed ({self.provider.id}): {message}")
        payload = dict(context)
        payload["error"] = message
        payload["provider"] = self.provider.id
        return json.dumps(payload, default=str)

    @staticmethod
    def _invalid(context: Dict[str, Any], message: str, provider_id: str) -> str:
        payload = dict(context)
        payload["error"] = message
        payload["provider"] = provider_id
        return json.dumps(payload, default=str)

    @staticmethod
    def _symbol(symbol: str) -> str:
        return (symbol or "").strip().upper()

    @staticmethod
    def _limit(limit: Any, cap: int, default: int) -> int:
        try:
            value = int(limit)
        except (TypeError, ValueError):
            value = default
        return max(1, min(value, cap))

    def _validate(self, symbol: str, **choices: Tuple[Any, Tuple[str, ...]]) -> Optional[str]:
        """Return an error payload when `symbol` is empty or an enum-style
        argument is out of range, else None."""
        if not symbol:
            return self._invalid({}, "symbol is required", self.provider.id)
        for name, (value, allowed) in choices.items():
            if value not in allowed:
                return self._invalid(
                    {"symbol": symbol}, f"{name} must be one of {', '.join(allowed)} (got {value!r})", self.provider.id
                )
        return None

    # ------------------------------------------------------------------
    # Tools. Each has a sync and an async variant registered under the same
    # name; the async variant reuses the sync docstring.
    # ------------------------------------------------------------------

    def search_symbols(self, query: str, limit: int = 5) -> str:
        """Search for ticker symbols by company name or keyword.

        Use this when you have a company name but not its ticker (e.g. "NVIDIA" -> NVDA).

        Args:
            query (str): Company name or keyword.
            limit (int): Maximum number of matches to return. Defaults to 5.

        Returns:
            str: JSON with `results` (symbol, name, exchange, type) and `provider`.
        """
        query = (query or "").strip()
        if not query:
            return self._invalid({}, "query is required", self.provider.id)
        return self._call(SEARCH_SYMBOLS, query=query, limit=self._limit(limit, _MAX_SEARCH_RESULTS, 5))

    async def asearch_symbols(self, query: str, limit: int = 5) -> str:
        query = (query or "").strip()
        if not query:
            return self._invalid({}, "query is required", self.provider.id)
        return await self._acall(SEARCH_SYMBOLS, query=query, limit=self._limit(limit, _MAX_SEARCH_RESULTS, 5))

    asearch_symbols.__doc__ = search_symbols.__doc__

    def get_quote(self, symbol: str) -> str:
        """Get the current price and day change for a ticker symbol.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".

        Returns:
            str: JSON with price, currency, change, change_percent, open/high/low, previous_close,
                volume, market_cap, 52-week range, exchange, as_of and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(symbol) or self._call(GET_QUOTE, symbol=symbol)

    async def aget_quote(self, symbol: str) -> str:
        symbol = self._symbol(symbol)
        return self._validate(symbol) or await self._acall(GET_QUOTE, symbol=symbol)

    aget_quote.__doc__ = get_quote.__doc__

    def get_price_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> str:
        """Get historical OHLCV price bars for a ticker symbol.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".
            period (str): Look-back window. One of 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, ytd, max. Defaults to "1mo".
            interval (str): Bar size. One of 1d, 1wk, 1mo. Defaults to "1d".

        Returns:
            str: JSON with symbol, period, interval, currency, `bars` (date, open, high, low, close, volume) and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(symbol, period=(period, PERIODS), interval=(interval, INTERVALS)) or self._call(
            GET_PRICE_HISTORY, symbol=symbol, period=period, interval=interval
        )

    async def aget_price_history(self, symbol: str, period: str = "1mo", interval: str = "1d") -> str:
        symbol = self._symbol(symbol)
        return self._validate(symbol, period=(period, PERIODS), interval=(interval, INTERVALS)) or await self._acall(
            GET_PRICE_HISTORY, symbol=symbol, period=period, interval=interval
        )

    aget_price_history.__doc__ = get_price_history.__doc__

    def get_company_profile(self, symbol: str) -> str:
        """Get the company profile for a ticker symbol: name, description, sector, industry, exchange, location, website, employees.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".

        Returns:
            str: JSON company profile and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(symbol) or self._call(GET_COMPANY_PROFILE, symbol=symbol)

    async def aget_company_profile(self, symbol: str) -> str:
        symbol = self._symbol(symbol)
        return self._validate(symbol) or await self._acall(GET_COMPANY_PROFILE, symbol=symbol)

    aget_company_profile.__doc__ = get_company_profile.__doc__

    def get_key_metrics(self, symbol: str) -> str:
        """Get key financial metrics for a ticker symbol: market cap, P/E, PEG, P/B, P/S, EV/EBITDA, EPS,
        dividend yield, beta, margins, ROE/ROA, growth, debt-to-equity, current ratio, free cash flow, revenue, EBITDA.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".

        Returns:
            str: JSON metrics (missing metrics are omitted) and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(symbol) or self._call(GET_KEY_METRICS, symbol=symbol)

    async def aget_key_metrics(self, symbol: str) -> str:
        symbol = self._symbol(symbol)
        return self._validate(symbol) or await self._acall(GET_KEY_METRICS, symbol=symbol)

    aget_key_metrics.__doc__ = get_key_metrics.__doc__

    def get_financials(self, symbol: str, statement: str = "income", period: str = "annual", limit: int = 4) -> str:
        """Get financial statements for a ticker symbol, most recent period first.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".
            statement (str): One of income, balance_sheet, cash_flow. Defaults to "income".
            period (str): One of annual, quarterly, ttm. Defaults to "annual".
            limit (int): Number of periods to return. Defaults to 4.

        Returns:
            str: JSON with `results`, one record per period (report_period, fiscal_period, currency,
                `items` = line items as snake_case keys) and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(
            symbol, statement=(statement, STATEMENTS), period=(period, STATEMENT_PERIODS)
        ) or self._call(
            GET_FINANCIALS,
            symbol=symbol,
            statement=statement,
            period=period,
            limit=self._limit(limit, _MAX_STATEMENTS, 4),
        )

    async def aget_financials(
        self, symbol: str, statement: str = "income", period: str = "annual", limit: int = 4
    ) -> str:
        symbol = self._symbol(symbol)
        return self._validate(
            symbol, statement=(statement, STATEMENTS), period=(period, STATEMENT_PERIODS)
        ) or await self._acall(
            GET_FINANCIALS,
            symbol=symbol,
            statement=statement,
            period=period,
            limit=self._limit(limit, _MAX_STATEMENTS, 4),
        )

    aget_financials.__doc__ = get_financials.__doc__

    def get_news(self, symbol: str, limit: int = 10) -> str:
        """Get recent news headlines for a ticker symbol.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".
            limit (int): Maximum number of articles. Defaults to 10.

        Returns:
            str: JSON with `results` (title, url, source, published_at, summary) and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(symbol) or self._call(GET_NEWS, symbol=symbol, limit=self._limit(limit, _MAX_NEWS, 10))

    async def aget_news(self, symbol: str, limit: int = 10) -> str:
        symbol = self._symbol(symbol)
        return self._validate(symbol) or await self._acall(
            GET_NEWS, symbol=symbol, limit=self._limit(limit, _MAX_NEWS, 10)
        )

    aget_news.__doc__ = get_news.__doc__

    def get_analyst_recommendations(self, symbol: str) -> str:
        """Get analyst consensus and price targets for a ticker symbol.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".

        Returns:
            str: JSON with consensus, strong_buy/buy/hold/sell/strong_sell counts, num_analysts,
                target_mean/high/low/median, current_price, as_of and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(symbol) or self._call(GET_ANALYST_RECOMMENDATIONS, symbol=symbol)

    async def aget_analyst_recommendations(self, symbol: str) -> str:
        symbol = self._symbol(symbol)
        return self._validate(symbol) or await self._acall(GET_ANALYST_RECOMMENDATIONS, symbol=symbol)

    aget_analyst_recommendations.__doc__ = get_analyst_recommendations.__doc__

    def get_insider_trades(self, symbol: str, limit: int = 20) -> str:
        """Get recent insider transactions (buys, sells, grants) for a ticker symbol.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".
            limit (int): Maximum number of transactions. Defaults to 20.

        Returns:
            str: JSON with `results` (insider, title, transaction_type, transaction_date, shares, price,
                value, shares_owned_after, filing_date, url) and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(symbol) or self._call(
            GET_INSIDER_TRADES, symbol=symbol, limit=self._limit(limit, _MAX_INSIDER_TRADES, 20)
        )

    async def aget_insider_trades(self, symbol: str, limit: int = 20) -> str:
        symbol = self._symbol(symbol)
        return self._validate(symbol) or await self._acall(
            GET_INSIDER_TRADES, symbol=symbol, limit=self._limit(limit, _MAX_INSIDER_TRADES, 20)
        )

    aget_insider_trades.__doc__ = get_insider_trades.__doc__

    def get_earnings(self, symbol: str, limit: int = 8) -> str:
        """Get reported and estimated earnings by period for a ticker symbol (may include upcoming dates).

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".
            limit (int): Maximum number of periods. Defaults to 8.

        Returns:
            str: JSON with `results` (report_period, fiscal_period, eps, eps_estimate, surprise_percent,
                revenue, net_income, filing_date, url) and provider.
        """
        symbol = self._symbol(symbol)
        return self._validate(symbol) or self._call(
            GET_EARNINGS, symbol=symbol, limit=self._limit(limit, _MAX_EARNINGS, 8)
        )

    async def aget_earnings(self, symbol: str, limit: int = 8) -> str:
        symbol = self._symbol(symbol)
        return self._validate(symbol) or await self._acall(
            GET_EARNINGS, symbol=symbol, limit=self._limit(limit, _MAX_EARNINGS, 8)
        )

    aget_earnings.__doc__ = get_earnings.__doc__

    def get_sec_filings(self, symbol: str, form_type: Optional[str] = None, limit: int = 10) -> str:
        """Get recent SEC filings for a ticker symbol.

        Args:
            symbol (str): Ticker symbol, e.g. "NVDA".
            form_type (str, optional): Filter by form type, e.g. "10-K", "10-Q", "8-K". Defaults to all.
            limit (int): Maximum number of filings. Defaults to 10.

        Returns:
            str: JSON with `results` (form_type, filing_date, report_period, title, url, accession_number) and provider.
        """
        symbol = self._symbol(symbol)
        form_type = form_type.strip().upper() if isinstance(form_type, str) and form_type.strip() else None
        return self._validate(symbol) or self._call(
            GET_SEC_FILINGS, symbol=symbol, form_type=form_type, limit=self._limit(limit, _MAX_FILINGS, 10)
        )

    async def aget_sec_filings(self, symbol: str, form_type: Optional[str] = None, limit: int = 10) -> str:
        symbol = self._symbol(symbol)
        form_type = form_type.strip().upper() if isinstance(form_type, str) and form_type.strip() else None
        return self._validate(symbol) or await self._acall(
            GET_SEC_FILINGS, symbol=symbol, form_type=form_type, limit=self._limit(limit, _MAX_FILINGS, 10)
        )

    aget_sec_filings.__doc__ = get_sec_filings.__doc__

    def __repr__(self) -> str:
        return f"<FinanceTools provider={self.provider.id} tools={self._registered_tools}>"


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _round(value: float) -> float:
    """Round for token economy without destroying small numbers: 4 decimals for
    ordinary magnitudes, 4 significant digits below 0.01 (sub-penny prices,
    tiny ratios) so 4.44e-06 does not become 0.0."""
    if abs(value) >= 0.01:
        return round(value, 4)
    return float(f"{value:.4g}")


def _clean(value: Any) -> Any:
    """Make a payload compact and JSON-safe: drop None, round floats, NaN -> None,
    numpy scalars -> Python, timestamps -> ISO strings."""
    if is_dataclass(value) and not isinstance(value, type):
        return _clean(asdict(value))
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for key, item in value.items():
            cleaned = _clean(item)
            if cleaned is not None:
                out[str(key)] = cleaned
        return out
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return _round(value)
    if isinstance(value, (int, str)) or value is None:
        return value
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if hasattr(value, "item"):
        # numpy / pandas scalars
        try:
            return _clean(value.item())
        except Exception:
            return str(value)
    return value


__all__ = ["FinanceTools", "ALL_CAPABILITIES"]
