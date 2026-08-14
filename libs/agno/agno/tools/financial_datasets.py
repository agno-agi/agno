import json
from os import getenv
from typing import Any, Callable, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_error


class FinancialDatasetsTools(Toolkit):
    """Financial market data toolkit for stocks, crypto, and SEC filings.

    Args:
        api_key: API key for Financial Datasets API. Falls back to FINANCIAL_DATASETS_API_KEY env var.
        timeout: Per-request HTTP timeout in seconds. Defaults to 30.
        search_tickers: Enable search_tickers tool. Defaults to True.
        get_company_info: Enable get_company_info tool. Defaults to True.
        get_stock_prices: Enable get_stock_prices tool. Defaults to True.
        get_news: Enable get_news tool. Defaults to True.
        get_income_statements: Enable get_income_statements tool. Defaults to True.
        get_balance_sheets: Enable get_balance_sheets tool. Defaults to True.
        get_cash_flow_statements: Enable get_cash_flow_statements tool. Defaults to True.
        get_segmented_financials: Enable get_segmented_financials tool. Defaults to True.
        get_financial_metrics: Enable get_financial_metrics tool. Defaults to True.
        get_earnings: Enable get_earnings tool. Defaults to True.
        get_insider_trades: Enable get_insider_trades tool. Defaults to True.
        get_institutional_ownership: Enable get_institutional_ownership tool. Defaults to True.
        get_sec_filings: Enable get_sec_filings tool. Defaults to True.
        get_crypto_prices: Enable get_crypto_prices tool. Defaults to True.
        all: Enable all tools. Defaults to False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        timeout: int = 30,
        search_tickers: bool = True,
        get_company_info: bool = True,
        get_stock_prices: bool = True,
        get_news: bool = True,
        get_income_statements: bool = True,
        get_balance_sheets: bool = True,
        get_cash_flow_statements: bool = True,
        get_segmented_financials: bool = True,
        get_financial_metrics: bool = True,
        get_earnings: bool = True,
        get_insider_trades: bool = True,
        get_institutional_ownership: bool = True,
        get_sec_filings: bool = True,
        get_crypto_prices: bool = True,
        all: bool = False,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("FINANCIAL_DATASETS_API_KEY")
        if not self.api_key:
            log_error(
                "FINANCIAL_DATASETS_API_KEY not set. Please set the FINANCIAL_DATASETS_API_KEY environment variable."
            )

        self.base_url = "https://api.financialdatasets.ai"
        self.timeout = timeout

        tools: List[Callable] = []
        if all or get_income_statements:
            tools.append(self.get_income_statements)
        if all or get_balance_sheets:
            tools.append(self.get_balance_sheets)
        if all or get_cash_flow_statements:
            tools.append(self.get_cash_flow_statements)
        if all or get_segmented_financials:
            tools.append(self.get_segmented_financials)
        if all or get_financial_metrics:
            tools.append(self.get_financial_metrics)
        if all or get_company_info:
            tools.append(self.get_company_info)
        if all or get_stock_prices:
            tools.append(self.get_stock_prices)
        if all or get_earnings:
            tools.append(self.get_earnings)
        if all or get_insider_trades:
            tools.append(self.get_insider_trades)
        if all or get_institutional_ownership:
            tools.append(self.get_institutional_ownership)
        if all or get_news:
            tools.append(self.get_news)
        if all or get_sec_filings:
            tools.append(self.get_sec_filings)
        if all or get_crypto_prices:
            tools.append(self.get_crypto_prices)
        if all or search_tickers:
            tools.append(self.search_tickers)

        super().__init__(name="financial_datasets_tools", tools=tools, **kwargs)

    def _make_request(self, endpoint: str, params: Dict[str, Any]) -> str:
        """
        Makes a request to the Financial Datasets API.

        Args:
            endpoint: API endpoint to call
            params: Query parameters for the request

        Returns:
            JSON response from the API
        """
        if not self.api_key:
            log_error("No API key provided. Cannot make request.")
            return "API key not set"

        headers = {"X-API-KEY": self.api_key}
        url = f"{self.base_url}/{endpoint}"

        try:
            response = requests.get(url, headers=headers, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            log_error(f"Error making request to {url}: {str(e)}")
            return json.dumps({"error": f"Error making request to {url}: {str(e)}"})

    # Financial Statements
    def get_income_statements(self, ticker: str, period: str = "annual", limit: int = 10) -> str:
        """
        Get income statements for a ticker.

        Args:
            ticker: Stock ticker symbol
            period: 'annual', 'quarterly', or 'ttm'
            limit: Number of statements to return

        Returns:
            Dictionary containing income statements
        """
        params = {"ticker": ticker, "period": period, "limit": limit}
        return self._make_request("financials/income-statements", params)

    def get_balance_sheets(self, ticker: str, period: str = "annual", limit: int = 10) -> str:
        """
        Get balance sheets for a ticker.

        Args:
            ticker: Stock ticker symbol
            period: 'annual', 'quarterly', or 'ttm'
            limit: Number of statements to return

        Returns:
            Dictionary containing balance sheets
        """
        params = {"ticker": ticker, "period": period, "limit": limit}
        return self._make_request("financials/balance-sheets", params)

    def get_cash_flow_statements(self, ticker: str, period: str = "annual", limit: int = 10) -> str:
        """
        Get cash flow statements for a ticker.

        Args:
            ticker: Stock ticker symbol
            period: 'annual', 'quarterly', or 'ttm'
            limit: Number of statements to return

        Returns:
            Dictionary containing cash flow statements
        """
        params = {"ticker": ticker, "period": period, "limit": limit}
        return self._make_request("financials/cash-flow-statements", params)

    # Other API endpoints from the documentation

    def get_company_info(self, ticker: str) -> str:
        """
        Get company information for a ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dictionary containing company information
        """
        params = {"ticker": ticker}
        return self._make_request("company", params)

    def get_crypto_prices(self, symbol: str, interval: str = "1d", limit: int = 100) -> str:
        """
        Get cryptocurrency prices.

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTC')
            interval: Price interval (e.g., '1d', '1h')
            limit: Number of price points to return

        Returns:
            Dictionary containing crypto prices
        """
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        return self._make_request("crypto/prices", params)

    def get_earnings(self, ticker: str, limit: int = 10) -> str:
        """
        Get earnings data for a ticker.

        Args:
            ticker: Stock ticker symbol
            limit: Number of earnings reports to return

        Returns:
            Dictionary containing earnings data
        """
        params = {"ticker": ticker, "limit": limit}
        return self._make_request("earnings", params)

    def get_financial_metrics(self, ticker: str) -> str:
        """
        Get financial metrics for a ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dictionary containing financial metrics
        """
        params = {"ticker": ticker}
        return self._make_request("financials/metrics", params)

    def get_insider_trades(self, ticker: str, limit: int = 50) -> str:
        """
        Get insider trades for a ticker.

        Args:
            ticker: Stock ticker symbol
            limit: Number of trades to return

        Returns:
            Dictionary containing insider trades
        """
        params = {"ticker": ticker, "limit": limit}
        return self._make_request("insider-trades", params)

    def get_institutional_ownership(self, ticker: str) -> str:
        """
        Get institutional ownership data for a ticker.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dictionary containing institutional ownership data
        """
        params = {"ticker": ticker}
        return self._make_request("institutional-ownership", params)

    def get_news(self, ticker: Optional[str] = None, limit: int = 50) -> str:
        """
        Get market news, optionally filtered by ticker.

        Args:
            ticker: Stock ticker symbol (optional)
            limit: Number of news items to return

        Returns:
            Dictionary containing news items
        """
        params: Dict[str, Any] = {"limit": limit}
        if ticker:
            params["ticker"] = ticker
        return self._make_request("news", params)

    def get_stock_prices(self, ticker: str, interval: str = "1d", limit: int = 100) -> str:
        """
        Get stock prices for a ticker.

        Args:
            ticker: Stock ticker symbol
            interval: Price interval (e.g., '1d', '1h')
            limit: Number of price points to return

        Returns:
            Dictionary containing stock prices
        """
        params = {"ticker": ticker, "interval": interval, "limit": limit}
        return self._make_request("prices", params)

    def search_tickers(self, query: str, limit: int = 10) -> str:
        """
        Search for tickers based on a query.

        Args:
            query: Search query
            limit: Maximum number of results to return

        Returns:
            Dictionary containing search results
        """
        params = {"query": query, "limit": limit}
        return self._make_request("search", params)

    def get_sec_filings(self, ticker: str, form_type: Optional[str] = None, limit: int = 50) -> str:
        """
        Get SEC filings for a ticker.

        Args:
            ticker: Stock ticker symbol
            form_type: Type of SEC form (e.g., '10-K', '10-Q')
            limit: Number of filings to return

        Returns:
            Dictionary containing SEC filings
        """
        params: Dict[str, Any] = {"ticker": ticker, "limit": limit}
        if form_type:
            params["form_type"] = form_type
        return self._make_request("sec-filings", params)

    def get_segmented_financials(self, ticker: str, period: str = "annual", limit: int = 10) -> str:
        """
        Get segmented financials for a ticker.

        Args:
            ticker: Stock ticker symbol
            period: 'annual' or 'quarterly'
            limit: Number of reports to return

        Returns:
            Dictionary containing segmented financials
        """
        params = {"ticker": ticker, "period": period, "limit": limit}
        return self._make_request("financials/segmented", params)
