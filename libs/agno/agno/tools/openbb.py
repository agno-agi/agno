import json
from os import getenv
from typing import Any, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, logger

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
        stock_price: bool = True,
        search_symbols: bool = False,
        company_news: bool = False,
        company_profile: bool = False,
        price_targets: bool = False,
        **kwargs,
    ):
        super().__init__(name="yfinance_tools", **kwargs)

        self.obb = obb or openbb_app
        try:
            if openbb_pat or getenv("OPENBB_PAT"):
                self.obb.account.login(pat=openbb_pat or getenv("OPENBB_PAT"))  # type: ignore
        except Exception as e:
            logger.error(f"Error logging into OpenBB: {e}")

        self.provider: Literal["benzinga", "fmp", "intrinio", "polygon", "tiingo", "tmx", "yfinance"] = provider

        if stock_price:
            self.register(self.get_stock_price)
        if search_symbols:
            self.register(self.search_company_symbol)
        if company_news:
            self.register(self.get_company_news)
        if company_profile:
            self.register(self.get_company_profile)
        if price_targets:
            self.register(self.get_price_targets)

    def get_stock_price(self, symbol: str) -> str:
        """Use this function to get the current stock price for a stock symbol or list of symbols.

        Args:
            symbol (str): The stock symbol or list of stock symbols.
                Eg: "AAPL" or "AAPL,MSFT,GOOGL"

        Returns:
          str: The current stock prices or error message.
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
            return f"Error fetching current price for {symbol}: {e}"

    def search_company_symbol(self, company_name: str) -> str:
        """Use this function to get a list of ticker symbols for a company.

        Args:
            company_name (str): The name of the company.

        Returns:
            str: A JSON string containing the ticker symbols.
        """

        log_debug(f"Search ticker for {company_name}")
        result = self.obb.equity.search(company_name).to_polars()  # type: ignore
        clean_results = []
        if len(result) > 0:
            for row in result.to_dicts():
                clean_results.append({"symbol": row.get("symbol"), "name": row.get("name")})

        return json.dumps(clean_results, indent=2, default=str)

    def get_price_targets(self, symbol: str) -> str:
        """Use this function to get consensus price target and recommendations for a stock symbol or list of symbols.

        Args:
            symbol (str): The stock symbol or list of stock symbols.
                Eg: "AAPL" or "AAPL,MSFT,GOOGL"

        Returns:
            str: JSON containing consensus price target and recommendations.
        """
        try:
            log_debug(f"Fetching price targets for {symbol}")
            result = self.obb.equity.estimates.consensus(symbol=symbol, provider=self.provider).to_polars()  # type: ignore
            return json.dumps(result.to_dicts(), indent=2, default=str)
        except Exception as e:
            return f"Error fetching company news for {symbol}: {e}"

    def get_company_news(self, symbol: str, num_stories: int = 10) -> str:
        """Use this function to get company news for a stock symbol or list of symbols.

        Args:
            symbol (str): The stock symbol or list of stock symbols.
                Eg: "AAPL" or "AAPL,MSFT,GOOGL"
            num_stories (int): The number of news stories to return. Defaults to 10.

        Returns:
            str: JSON containing company news and press releases.
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
            return f"Error fetching company news for {symbol}: {e}"

    def get_company_profile(self, symbol: str) -> str:
        """Use this function to get company profile and overview for a stock symbol or list of symbols.

        Args:
            symbol (str): The stock symbol or list of stock symbols.
                Eg: "AAPL" or "AAPL,MSFT,GOOGL"

        Returns:
            str: JSON containing company profile and overview.
        """
        try:
            log_debug(f"Fetching company profile for {symbol}")
            result = self.obb.equity.profile(symbol=symbol, provider=self.provider).to_polars()  # type: ignore
            return json.dumps(result.to_dicts(), indent=2, default=str)
        except Exception as e:
            return f"Error fetching company profile for {symbol}: {e}"
