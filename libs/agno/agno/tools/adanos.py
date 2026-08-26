from os import getenv
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import quote

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error

StockSource = Literal["reddit", "x", "news", "polymarket"]
AssetType = Literal["stocks", "crypto"]


class AdanosTools(Toolkit):
    """Tools for retrieving stock and crypto market sentiment from Adanos."""

    _STOCK_PATHS: Dict[str, str] = {
        "reddit": "reddit/stocks/v1",
        "x": "x/stocks/v1",
        "news": "news/stocks/v1",
        "polymarket": "polymarket/stocks/v1",
    }
    _CRYPTO_PATH = "reddit/crypto/v1"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.adanos.org",
        timeout: float = 20.0,
        enable_stock_sentiment: bool = True,
        enable_crypto_sentiment: bool = True,
        enable_trending: bool = True,
        enable_market_sentiment: bool = True,
        all: bool = False,
        **kwargs,
    ):
        """Initialize the Adanos market sentiment toolkit.

        Args:
            api_key: Adanos API key. Uses ``ADANOS_API_KEY`` when omitted.
            base_url: Adanos API base URL.
            timeout: Per-request timeout in seconds.
            enable_stock_sentiment: Register the stock sentiment tool.
            enable_crypto_sentiment: Register the crypto sentiment tool.
            enable_trending: Register the trending assets tool.
            enable_market_sentiment: Register the aggregate market sentiment tool.
            all: Register all tools regardless of individual flags.
        """
        self.api_key = api_key or getenv("ADANOS_API_KEY")
        self.base_url = base_url.rstrip("/")
        self.timeout = httpx.Timeout(timeout)

        if not self.api_key:
            log_error("ADANOS_API_KEY not set. Please set the ADANOS_API_KEY environment variable.")

        tools: List[Any] = []
        async_tools: List[tuple] = []
        if all or enable_stock_sentiment:
            tools.append(self.get_stock_sentiment)
            async_tools.append((self.aget_stock_sentiment, "get_stock_sentiment"))
        if all or enable_crypto_sentiment:
            tools.append(self.get_crypto_sentiment)
            async_tools.append((self.aget_crypto_sentiment, "get_crypto_sentiment"))
        if all or enable_trending:
            tools.append(self.get_trending)
            async_tools.append((self.aget_trending, "get_trending"))
        if all or enable_market_sentiment:
            tools.append(self.get_market_sentiment)
            async_tools.append((self.aget_market_sentiment, "get_market_sentiment"))

        name = kwargs.pop("name", "adanos_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools, **kwargs)

    def _headers(self) -> Dict[str, str]:
        if not self.api_key:
            raise ValueError("Adanos API key is required. Set ADANOS_API_KEY or pass api_key.")
        return {"X-API-Key": self.api_key}

    @staticmethod
    def _params(start_date: Optional[str] = None, end_date: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
        params: Dict[str, Any] = {"from": start_date, "to": end_date, **kwargs}
        return {key: value for key, value in params.items() if value is not None}

    @staticmethod
    def _error(response: httpx.Response) -> Dict[str, Any]:
        try:
            detail = response.json().get("detail", response.text)
        except ValueError:
            detail = response.text
        return {"error": "Adanos API request failed", "status_code": response.status_code, "detail": detail}

    def _request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/{path}", headers=self._headers(), params=params)
                response.raise_for_status()
                return response.json()
        except ValueError as error:
            return {"error": str(error)}
        except httpx.HTTPStatusError as error:
            return self._error(error.response)
        except httpx.RequestError as error:
            return {"error": "Adanos API request failed", "detail": str(error)}

    async def _arequest(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/{path}", headers=self._headers(), params=params)
                response.raise_for_status()
                return response.json()
        except ValueError as error:
            return {"error": str(error)}
        except httpx.HTTPStatusError as error:
            return self._error(error.response)
        except httpx.RequestError as error:
            return {"error": "Adanos API request failed", "detail": str(error)}

    def get_stock_sentiment(
        self,
        ticker: str,
        source: StockSource = "reddit",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get sentiment for a stock from one Adanos data source.

        Args:
            ticker: Stock ticker, for example ``AAPL`` or ``TSLA``.
            source: Sentiment source: reddit, x, news, or polymarket.
            start_date: Inclusive UTC start date in YYYY-MM-DD format.
            end_date: Inclusive UTC end date in YYYY-MM-DD format.
        """
        path = self._STOCK_PATHS.get(source)
        if path is None:
            return {"error": "source must be one of: reddit, x, news, polymarket"}
        symbol = quote(ticker.strip().lstrip("$").upper(), safe=".-")
        return self._request(f"{path}/stock/{symbol}", self._params(start_date, end_date))

    async def aget_stock_sentiment(
        self,
        ticker: str,
        source: StockSource = "reddit",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Asynchronously get sentiment for a stock from one Adanos data source."""
        path = self._STOCK_PATHS.get(source)
        if path is None:
            return {"error": "source must be one of: reddit, x, news, polymarket"}
        symbol = quote(ticker.strip().lstrip("$").upper(), safe=".-")
        return await self._arequest(f"{path}/stock/{symbol}", self._params(start_date, end_date))

    def get_crypto_sentiment(
        self, symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get Reddit sentiment for a cryptocurrency.

        Args:
            symbol: Cryptocurrency symbol, for example ``BTC`` or ``ETH``.
            start_date: Inclusive UTC start date in YYYY-MM-DD format.
            end_date: Inclusive UTC end date in YYYY-MM-DD format.
        """
        normalized_symbol = quote(symbol.strip().upper(), safe=".-")
        return self._request(f"{self._CRYPTO_PATH}/token/{normalized_symbol}", self._params(start_date, end_date))

    async def aget_crypto_sentiment(
        self, symbol: str, start_date: Optional[str] = None, end_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """Asynchronously get Reddit sentiment for a cryptocurrency."""
        normalized_symbol = quote(symbol.strip().upper(), safe=".-")
        return await self._arequest(
            f"{self._CRYPTO_PATH}/token/{normalized_symbol}", self._params(start_date, end_date)
        )

    def get_trending(
        self,
        asset_type: AssetType = "stocks",
        source: StockSource = "reddit",
        limit: int = 10,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get trending stocks or cryptocurrencies ranked by buzz score with sentiment data.

        Args:
            asset_type: Asset universe: stocks or crypto.
            source: For stocks, reddit, x, news, or polymarket. Crypto uses reddit.
            limit: Maximum number of results, from 1 to 100.
            start_date: Inclusive UTC start date in YYYY-MM-DD format.
            end_date: Inclusive UTC end date in YYYY-MM-DD format.
        """
        path = self._asset_path(asset_type, source)
        if isinstance(path, dict):
            return path
        params = self._params(start_date, end_date, limit=max(1, min(limit, 100)))
        return self._request(f"{path}/trending", params)

    async def aget_trending(
        self,
        asset_type: AssetType = "stocks",
        source: StockSource = "reddit",
        limit: int = 10,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Asynchronously get trending stocks or cryptocurrencies ranked by buzz score with sentiment data."""
        path = self._asset_path(asset_type, source)
        if isinstance(path, dict):
            return path
        params = self._params(start_date, end_date, limit=max(1, min(limit, 100)))
        return await self._arequest(f"{path}/trending", params)

    def get_market_sentiment(
        self,
        asset_type: AssetType = "stocks",
        source: StockSource = "reddit",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get aggregate market sentiment for stocks or cryptocurrencies.

        Args:
            asset_type: Asset universe: stocks or crypto.
            source: For stocks, reddit, x, news, or polymarket. Crypto uses reddit.
            start_date: Inclusive UTC start date in YYYY-MM-DD format.
            end_date: Inclusive UTC end date in YYYY-MM-DD format.
        """
        path = self._asset_path(asset_type, source)
        if isinstance(path, dict):
            return path
        return self._request(f"{path}/market-sentiment", self._params(start_date, end_date))

    async def aget_market_sentiment(
        self,
        asset_type: AssetType = "stocks",
        source: StockSource = "reddit",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Asynchronously get aggregate market sentiment for stocks or cryptocurrencies."""
        path = self._asset_path(asset_type, source)
        if isinstance(path, dict):
            return path
        return await self._arequest(f"{path}/market-sentiment", self._params(start_date, end_date))

    def _asset_path(self, asset_type: str, source: str) -> Any:
        if asset_type == "crypto":
            if source != "reddit":
                return {"error": "crypto sentiment is currently available from reddit only"}
            return self._CRYPTO_PATH
        if asset_type != "stocks":
            return {"error": "asset_type must be one of: stocks, crypto"}
        return self._STOCK_PATHS.get(source) or {"error": "source must be one of: reddit, x, news, polymarket"}
