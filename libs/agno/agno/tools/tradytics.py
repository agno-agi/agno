from os import getenv
from typing import Any, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_error


class TradyticsTools(Toolkit):
    """Toolkit for querying US market data from the Tradytics Public API.

    Covers stock quotes and bars, stitched OPRA options flow, options chains,
    dealer exposure (gamma, delta, vanna, charm), ranked dark pool prints and
    levels, fundamentals, SEC filing semantic search, earnings transcripts,
    insider/Congress/13F disclosures, news, and prediction markets.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://tradytics.com/api/public/v1",
        timeout: int = 30,
        **kwargs,
    ):
        """Initialize the Tradytics Tools.

        Args:
            api_key: Tradytics API key. Falls back to the TRADYTICS_API_KEY environment variable.
            base_url: Base URL for the Tradytics Public API.
            timeout: Per-request HTTP timeout in seconds. Defaults to 30.
        """
        self.api_key: Optional[str] = api_key or getenv("TRADYTICS_API_KEY")
        if not self.api_key:
            log_error(
                "TRADYTICS_API_KEY not set. Create a free key at https://tradytics.com/developer/keys "
                "and set TRADYTICS_API_KEY."
            )

        self.base_url = base_url.rstrip("/")

        tools: List[Any] = [
            # Equities
            self.get_stock_quote,
            self.get_stock_bars,
            self.search_symbols,
            self.get_market_news,
            # Options & dealer positioning
            self.get_options_flow,
            self.get_options_chain,
            self.get_dealer_exposure,
            # Dark pool
            self.get_darkpool_prints,
            self.get_darkpool_levels,
            # Fundamentals, SEC filings & transcripts
            self.get_company_profile,
            self.get_income_statement,
            self.get_balance_sheet,
            self.get_cash_flow,
            self.search_sec_filings,
            self.get_earnings_transcript,
            # Disclosures & prediction markets
            self.get_insider_trades,
            self.get_congress_trades,
            self.get_institutional_holdings,
            self.get_prediction_markets,
        ]

        super().__init__(name="tradytics_tools", tools=tools, timeout=timeout, **kwargs)

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Make a GET request to the Tradytics Public API.

        Args:
            endpoint: API path relative to base_url (e.g. 'options/flow').
            params: Query parameters for the request.

        Returns:
            Raw JSON response string from the API, or an error string.
        """
        if not self.api_key:
            log_error("No Tradytics API key provided. Cannot make request.")
            return "TRADYTICS_API_KEY not set"

        query: Dict[str, Any] = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            query[key] = ("true" if value else "false") if isinstance(value, bool) else value
        query["apiKey"] = self.api_key

        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        headers = {"Accept": "application/json", "User-Agent": "agno-tradytics-tools"}

        try:
            response = requests.get(url, headers=headers, params=query, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            msg = f"Error calling Tradytics {url} (status={status})" if status else f"Error calling Tradytics {url}"
            log_error(msg)
            return msg

    # Equities

    def get_stock_quote(self, symbol: str) -> str:
        """Get the latest quote and session stats for one or more US stock symbols.

        Args:
            symbol: Ticker symbol or comma-separated symbols (e.g. 'NVDA' or 'AAPL,MSFT').
        """
        return self._make_request("stocks/quotes", {"symbol": symbol})

    def get_stock_bars(
        self,
        symbol: str,
        timeframe: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 100,
    ) -> str:
        """Get split-adjusted OHLCV bars with VWAP for a stock or index.

        Args:
            symbol: Ticker symbol (e.g. 'SPY', 'NVDA').
            timeframe: Bar interval ('1s', '1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w').
            start_date: Optional start date (YYYY-MM-DD or RFC 3339).
            end_date: Optional end date (YYYY-MM-DD or RFC 3339).
            limit: Maximum number of bars to return (up to 5000).
        """
        return self._make_request(
            "stocks/bars",
            {"symbol": symbol, "timeframe": timeframe, "from": start_date, "to": end_date, "limit": limit},
        )

    def search_symbols(self, query: str, kind: Optional[str] = None, limit: int = 10) -> str:
        """Search Tradytics symbols by ticker or company name.

        Args:
            query: Search string (e.g. 'nvidia', 'SPY').
            kind: Optional asset kind filter (e.g. 'stock', 'etf', 'index').
            limit: Maximum results to return.
        """
        return self._make_request("symbols", {"q": query, "kind": kind, "limit": limit})

    def get_market_news(self, symbol: Optional[str] = None, limit: int = 20) -> str:
        """Get market news headlines, optionally filtered by ticker symbol.

        Args:
            symbol: Optional ticker symbol (e.g. 'NVDA').
            limit: Maximum news items to return.
        """
        return self._make_request("news", {"symbol": symbol, "limit": limit})

    # Options & dealer positioning

    def get_options_flow(
        self,
        symbol: Optional[str] = None,
        min_premium: Optional[float] = None,
        option_type: Optional[str] = None,
        opening: Optional[bool] = None,
        limit: int = 25,
    ) -> str:
        """Get stitched OPRA options flow orders (sweeps, blocks, splits) with inferred side.

        Args:
            symbol: Optional ticker symbol (e.g. 'NVDA'). Omit for market-wide flow.
            min_premium: Optional minimum order premium in USD (e.g. 250000).
            option_type: Optional filter: 'call' or 'put'.
            opening: Optional filter for opening orders (True/False).
            limit: Maximum orders to return.
        """
        return self._make_request(
            "options/flow",
            {"symbol": symbol, "min_premium": min_premium, "type": option_type, "opening": opening, "limit": limit},
        )

    def get_options_chain(
        self,
        symbol: str,
        expiry: Optional[str] = None,
        option_type: Optional[str] = None,
        min_dte: Optional[int] = None,
        max_dte: Optional[int] = None,
        limit: int = 50,
    ) -> str:
        """Get options chain contracts with Greeks, IV, volume, and open interest.

        Args:
            symbol: Ticker symbol (e.g. 'SPY', 'AAPL').
            expiry: Optional expiration date (YYYY-MM-DD).
            option_type: Optional filter: 'call' or 'put'.
            min_dte: Optional minimum days to expiration.
            max_dte: Optional maximum days to expiration.
            limit: Maximum contracts to return.
        """
        return self._make_request(
            "options/chain",
            {
                "symbol": symbol,
                "expiry": expiry,
                "type": option_type,
                "min_dte": min_dte,
                "max_dte": max_dte,
                "limit": limit,
            },
        )

    def get_dealer_exposure(
        self,
        symbol: str,
        greek: str = "gamma",
        by: str = "strike",
        expiry: Optional[str] = None,
        dte: Optional[int] = None,
    ) -> str:
        """Get dealer exposure profile (gamma/GEX, delta, vanna, or charm) by strike or expiry.

        Args:
            symbol: Ticker symbol (e.g. 'SPY', 'NVDA').
            greek: Exposure Greek ('gamma', 'delta', 'vanna', 'charm').
            by: Grouping axis ('strike' or 'expiry').
            expiry: Optional expiration date (YYYY-MM-DD).
            dte: Optional max days to expiration.
        """
        return self._make_request(
            "options/exposure",
            {"symbol": symbol, "greek": greek, "by": by, "expiry": expiry, "dte": dte},
        )

    # Dark pool

    def get_darkpool_prints(
        self,
        symbol: Optional[str] = None,
        min_notional: Optional[float] = None,
        max_rank: Optional[int] = None,
        limit: int = 25,
    ) -> str:
        """Get off-exchange dark pool prints ranked against each symbol's rolling 12-month history.

        Args:
            symbol: Optional ticker symbol.
            min_notional: Optional minimum trade notional value in USD.
            max_rank: Optional maximum 12-month rank (e.g. 10 for top-10 largest prints).
            limit: Maximum prints to return.
        """
        return self._make_request(
            "darkpool/prints",
            {"symbol": symbol, "min_notional": min_notional, "max_rank": max_rank, "limit": limit},
        )

    def get_darkpool_levels(self, symbol: str, window: str = "1m", limit: int = 20) -> str:
        """Get aggregated dark pool support/resistance price levels for a stock.

        Args:
            symbol: Ticker symbol (e.g. 'SPY', 'AAPL').
            window: Lookback window (e.g. '1w', '1m', '3m').
            limit: Maximum price levels to return.
        """
        return self._make_request("darkpool/levels", {"symbol": symbol, "window": window, "limit": limit})

    # Fundamentals, SEC filings & transcripts

    def get_company_profile(self, symbol: str) -> str:
        """Get company profile, sector, industry, market cap, and metadata.

        Args:
            symbol: Ticker symbol (e.g. 'NVDA').
        """
        return self._make_request("fundamentals/profile", {"symbol": symbol})

    def get_income_statement(self, symbol: str, period: str = "quarter", limit: int = 4) -> str:
        """Get normalized income statements for a US company.

        Args:
            symbol: Ticker symbol.
            period: 'quarter', 'annual', or 'ttm'.
            limit: Number of periods to return.
        """
        return self._make_request("fundamentals/income-statement", {"symbol": symbol, "period": period, "limit": limit})

    def get_balance_sheet(self, symbol: str, period: str = "quarter", limit: int = 4) -> str:
        """Get normalized balance sheets for a US company.

        Args:
            symbol: Ticker symbol.
            period: 'quarter' or 'annual'.
            limit: Number of periods to return.
        """
        return self._make_request("fundamentals/balance-sheet", {"symbol": symbol, "period": period, "limit": limit})

    def get_cash_flow(self, symbol: str, period: str = "quarter", limit: int = 4) -> str:
        """Get normalized cash flow statements for a US company.

        Args:
            symbol: Ticker symbol.
            period: 'quarter', 'annual', or 'ttm'.
            limit: Number of periods to return.
        """
        return self._make_request("fundamentals/cash-flow", {"symbol": symbol, "period": period, "limit": limit})

    def search_sec_filings(
        self,
        query: str,
        symbol: Optional[str] = None,
        form: Optional[str] = None,
        limit: int = 10,
    ) -> str:
        """Run semantic search across SEC filings (10-K, 10-Q, 8-K, DEF 14A).

        Args:
            query: Natural-language search query (e.g. 'supply chain concentration').
            symbol: Optional ticker symbol filter.
            form: Optional SEC form filter (e.g. '10-K', '10-Q', '8-K').
            limit: Maximum matching passages to return.
        """
        return self._make_request("filings/search", {"q": query, "symbol": symbol, "form": form, "limit": limit})

    def get_earnings_transcript(
        self,
        symbol: str,
        year: Optional[int] = None,
        quarter: Optional[int] = None,
    ) -> str:
        """Get earnings call transcripts for a company.

        Args:
            symbol: Ticker symbol.
            year: Optional fiscal year (e.g. 2026).
            quarter: Optional fiscal quarter (1-4).
        """
        return self._make_request("fundamentals/transcripts", {"symbol": symbol, "year": year, "quarter": quarter})

    # Disclosures & prediction markets

    def get_insider_trades(
        self,
        symbol: Optional[str] = None,
        trade_type: Optional[str] = None,
        min_value: Optional[float] = None,
        limit: int = 25,
    ) -> str:
        """Get SEC Form 4 insider buys and sells.

        Args:
            symbol: Optional ticker symbol.
            trade_type: Optional transaction type filter (e.g. 'buy', 'sell').
            min_value: Optional minimum transaction value in USD.
            limit: Maximum transactions to return.
        """
        return self._make_request(
            "disclosures/insiders",
            {"symbol": symbol, "type": trade_type, "min_value": min_value, "limit": limit},
        )

    def get_congress_trades(
        self,
        symbol: Optional[str] = None,
        chamber: Optional[str] = None,
        limit: int = 25,
    ) -> str:
        """Get disclosed US Congressional stock trades.

        Args:
            symbol: Optional ticker symbol.
            chamber: Optional chamber filter ('senate' or 'house').
            limit: Maximum trades to return.
        """
        return self._make_request("disclosures/congress", {"symbol": symbol, "chamber": chamber, "limit": limit})

    def get_institutional_holdings(
        self,
        symbol: str,
        quarter: Optional[str] = None,
        limit: int = 25,
    ) -> str:
        """Get SEC Form 13F institutional holdings for a ticker.

        Args:
            symbol: Ticker symbol.
            quarter: Optional filing quarter (e.g. '2026Q3').
            limit: Maximum holders to return.
        """
        return self._make_request(
            "disclosures/institutions",
            {"symbol": symbol, "quarter": quarter, "limit": limit},
        )

    def get_prediction_markets(
        self,
        group: Optional[str] = None,
        symbol: Optional[str] = None,
        limit: int = 25,
    ) -> str:
        """Get live prediction market probabilities from Kalshi and Polymarket.

        Args:
            group: Optional topic group filter (e.g. 'fed', 'macro', 'earnings').
            symbol: Optional related ticker symbol.
            limit: Maximum markets to return.
        """
        return self._make_request("probabilities", {"group": group, "symbol": symbol, "limit": limit})
