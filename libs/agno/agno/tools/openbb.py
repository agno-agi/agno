import json
from os import getenv
from typing import Any, Callable, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_exception

try:
    from openbb import obb as openbb_app
except ImportError:
    raise ImportError("`openbb` not installed. Please install using `pip install 'openbb'`.")


class OpenBBTools(Toolkit):
    def __init__(
        self,
        obb: Optional[Any] = None,
        openbb_pat: Optional[str] = None,
        provider: Literal["benzinga", "fmp", "intrinio", "polygon", "tiingo", "tmx", "yfinance"] = "yfinance",
        get_stock_price: bool = True,
        search_company_symbol: bool = False,
        get_company_news: bool = False,
        get_company_profile: bool = False,
        get_price_targets: bool = False,
        all: bool = False,
        **kwargs,
    ):
        """OpenBB financial data tools for stock prices, company info, and news.

        Requires `pip install openbb`. For premium data providers, authenticate with
        an OpenBB PAT via the openbb_pat parameter or OPENBB_PAT env var.

        Args:
            obb: Custom OpenBB instance. Defaults to the global obb app.
            openbb_pat: OpenBB Personal Access Token. Falls back to OPENBB_PAT env var.
            provider: Data provider to use for API calls.
            get_stock_price: Enable stock price lookup tool.
            search_company_symbol: Enable company symbol search tool.
            get_company_news: Enable company news tool.
            get_company_profile: Enable company profile tool.
            get_price_targets: Enable price targets tool.
            all: Enable all tools regardless of individual flags.
        """
        self.obb = obb or openbb_app

        try:
            pat = openbb_pat or getenv("OPENBB_PAT")
            if pat:
                self.obb.account.login(pat=pat)  # type: ignore
        except Exception:
            log_exception("Error logging into OpenBB")

        self.provider: Literal["benzinga", "fmp", "intrinio", "polygon", "tiingo", "tmx", "yfinance"] = provider

        tools: List[Callable] = []
        if all or get_stock_price:
            tools.append(self.get_stock_price)
        if all or search_company_symbol:
            tools.append(self.search_company_symbol)
        if all or get_company_news:
            tools.append(self.openbb_get_company_news)
        if all or get_company_profile:
            tools.append(self.get_company_profile)
        if all or get_price_targets:
            tools.append(self.get_price_targets)

        super().__init__(name="openbb_tools", tools=tools, **kwargs)

    def get_stock_price(self, symbol: str) -> str:
        """Get the current stock price for a stock symbol or list of symbols.

        Args:
            symbol: The stock symbol or comma-separated list. E.g. "AAPL" or "AAPL,MSFT,GOOGL".

        Returns:
            JSON array of price data including last_price, high, low, open, close, volume.
        """
        try:
            log_debug(f"Fetching current price for {symbol}")
            result = self.obb.equity.price.quote(symbol=symbol, provider=self.provider).to_polars()  # type: ignore
            clean_results = []
            for row in result.to_dicts():
                clean_results.append(
                    {
                        "symbol": row.get("symbol"),
                        "last_price": row.get("last_price"),
                        "currency": row.get("currency"),
                        "name": row.get("name"),
                        "high": row.get("high"),
                        "low": row.get("low"),
                        "open": row.get("open"),
                        "close": row.get("close"),
                        "prev_close": row.get("prev_close"),
                        "volume": row.get("volume"),
                        "ma_50d": row.get("ma_50d"),
                        "ma_200d": row.get("ma_200d"),
                    }
                )
            return json.dumps(clean_results, indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": f"Error fetching current price for {symbol}: {e}"})

    def search_company_symbol(self, company_name: str) -> str:
        """Search for ticker symbols by company name.

        Args:
            company_name: The name of the company to search for.

        Returns:
            JSON array of matches with symbol and name fields.
        """

        log_debug(f"Search ticker for {company_name}")
        result = self.obb.equity.search(company_name).to_polars()  # type: ignore
        clean_results = []
        if len(result) > 0:
            for row in result.to_dicts():
                clean_results.append({"symbol": row.get("symbol"), "name": row.get("name")})

        return json.dumps(clean_results, indent=2, default=str)

    def get_price_targets(self, symbol: str) -> str:
        """Get consensus price target and recommendations for a stock symbol.

        Args:
            symbol: The stock symbol or comma-separated list. E.g. "AAPL" or "AAPL,MSFT,GOOGL".

        Returns:
            JSON array with consensus price targets and analyst recommendations.
        """
        try:
            log_debug(f"Fetching price targets for {symbol}")
            result = self.obb.equity.estimates.consensus(symbol=symbol, provider=self.provider).to_polars()  # type: ignore
            return json.dumps(result.to_dicts(), indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": f"Error fetching company news for {symbol}: {e}"})

    def openbb_get_company_news(self, symbol: str, num_stories: int = 10) -> str:
        """Get company news for a stock symbol.

        Args:
            symbol: The stock symbol or comma-separated list. E.g. "AAPL" or "AAPL,MSFT,GOOGL".
            num_stories: Maximum number of news stories to return.

        Returns:
            JSON array of news articles with title, date, text, and URL.
        """
        try:
            log_debug(f"Fetching news for {symbol}")
            result = self.obb.news.company(symbol=symbol, provider=self.provider, limit=num_stories).to_polars()  # type: ignore
            clean_results = []
            if len(result) > 0:
                for row in result.to_dicts():
                    row.pop("images")
                    clean_results.append(row)
            return json.dumps(clean_results[:num_stories], indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": f"Error fetching company news for {symbol}: {e}"})

    def get_company_profile(self, symbol: str) -> str:
        """Get company profile and overview for a stock symbol.

        Args:
            symbol: The stock symbol or comma-separated list. E.g. "AAPL" or "AAPL,MSFT,GOOGL".

        Returns:
            JSON array with company profile including sector, industry, description.
        """
        try:
            log_debug(f"Fetching company profile for {symbol}")
            result = self.obb.equity.profile(symbol=symbol, provider=self.provider).to_polars()  # type: ignore
            return json.dumps(result.to_dicts(), indent=2, default=str)
        except Exception as e:
            return json.dumps({"error": f"Error fetching company profile for {symbol}: {e}"})
