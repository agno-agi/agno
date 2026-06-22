import json
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`")


class CoinGeckoTools(Toolkit):
    """CoinGecko toolkit for cryptocurrency market data.

    Uses the free CoinGecko public API (no API key required for basic endpoints).

    Args:
        enable_price: Enable coin price lookup. Default is True.
        enable_search: Enable coin search. Default is True.
        enable_trending: Enable trending coins. Default is True.
        enable_market_data: Enable detailed market data. Default is False.
        all: Enable all tools. Default is False.
        timeout: Timeout in seconds for HTTP requests. Default is 30.
        currency: Default fiat currency for prices. Default is 'usd'.
    """

    def __init__(
        self,
        enable_price: bool = True,
        enable_search: bool = True,
        enable_trending: bool = True,
        enable_market_data: bool = False,
        all: bool = False,
        timeout: int = 30,
        currency: str = "usd",
        **kwargs,
    ):
        self.base_url = "https://api.coingecko.com/api/v3"
        self.timeout = timeout
        self.currency = currency

        tools: List[Any] = []
        if all or enable_price:
            tools.append(self.get_coin_price)
        if all or enable_search:
            tools.append(self.search_coins)
        if all or enable_trending:
            tools.append(self.get_trending)
        if all or enable_market_data:
            tools.append(self.get_coin_market_data)

        super().__init__(name="coingecko_tools", tools=tools, **kwargs)

    def _request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a GET request to the CoinGecko API."""
        url = f"{self.base_url}{endpoint}"
        response = requests.get(url, params=params, timeout=self.timeout)
        response.raise_for_status()
        return response.json()

    def get_coin_price(self, coin_ids: str, currency: Optional[str] = None) -> str:
        """Get current price for one or more cryptocurrencies.

        Args:
            coin_ids (str): Comma-separated CoinGecko coin IDs (e.g., 'bitcoin,ethereum,solana').
            currency (Optional[str]): Fiat currency for prices (e.g., 'usd', 'eur'). Defaults to toolkit currency.

        Returns:
            str: JSON with current prices, 24h change, and market cap.
        """
        try:
            vs_currency = currency or self.currency
            data = self._request(
                "/simple/price",
                params={
                    "ids": coin_ids,
                    "vs_currencies": vs_currency,
                    "include_24hr_change": "true",
                    "include_market_cap": "true",
                },
            )

            results = []
            for coin_id, info in data.items():
                results.append(
                    {
                        "coin": coin_id,
                        "price": info.get(vs_currency),
                        "market_cap": info.get(f"{vs_currency}_market_cap"),
                        "24h_change_pct": info.get(f"{vs_currency}_24h_change"),
                    }
                )
            return json.dumps({"prices": results}, indent=2)
        except Exception as e:
            logger.exception(f"Error fetching price for: {coin_ids}")
            return f"Error fetching coin price: {e}"

    def search_coins(self, query: str) -> str:
        """Search for cryptocurrencies by name or symbol.

        Args:
            query (str): Search query (coin name or symbol, e.g., 'bitcoin' or 'btc').

        Returns:
            str: JSON with matching coins (id, name, symbol, market cap rank).
        """
        try:
            data = self._request("/search", params={"query": query})

            coins = data.get("coins", [])[:10]
            results = []
            for coin in coins:
                results.append(
                    {
                        "id": coin.get("id"),
                        "name": coin.get("name"),
                        "symbol": coin.get("symbol"),
                        "market_cap_rank": coin.get("market_cap_rank"),
                    }
                )
            return json.dumps({"coins": results}, indent=2)
        except Exception as e:
            logger.exception(f"Error searching for: {query}")
            return f"Error searching coins: {e}"

    def get_trending(self) -> str:
        """Get trending cryptocurrencies in the last 24 hours.

        Returns:
            str: JSON with trending coins (name, symbol, market cap rank, price info).
        """
        try:
            data = self._request("/search/trending")

            coins = data.get("coins", [])
            results = []
            for item in coins[:10]:
                coin = item.get("item", {})
                results.append(
                    {
                        "id": coin.get("id"),
                        "name": coin.get("name"),
                        "symbol": coin.get("symbol"),
                        "market_cap_rank": coin.get("market_cap_rank"),
                        "price_btc": coin.get("price_btc"),
                    }
                )
            return json.dumps({"trending": results}, indent=2)
        except Exception as e:
            logger.exception("Error fetching trending coins")
            return f"Error fetching trending coins: {e}"

    def get_coin_market_data(self, coin_id: str, currency: Optional[str] = None) -> str:
        """Get detailed market data for a cryptocurrency.

        Args:
            coin_id (str): CoinGecko coin ID (e.g., 'bitcoin', 'ethereum').
            currency (Optional[str]): Fiat currency for prices. Defaults to toolkit currency.

        Returns:
            str: JSON with detailed market data including price, volume, supply, and ATH.
        """
        try:
            vs_currency = currency or self.currency
            data = self._request(
                f"/coins/{coin_id}",
                params={"localization": "false", "tickers": "false", "community_data": "false"},
            )

            market = data.get("market_data", {})
            result = {
                "id": data.get("id"),
                "name": data.get("name"),
                "symbol": data.get("symbol"),
                "current_price": market.get("current_price", {}).get(vs_currency),
                "market_cap": market.get("market_cap", {}).get(vs_currency),
                "market_cap_rank": market.get("market_cap_rank"),
                "total_volume": market.get("total_volume", {}).get(vs_currency),
                "high_24h": market.get("high_24h", {}).get(vs_currency),
                "low_24h": market.get("low_24h", {}).get(vs_currency),
                "price_change_24h_pct": market.get("price_change_percentage_24h"),
                "price_change_7d_pct": market.get("price_change_percentage_7d"),
                "price_change_30d_pct": market.get("price_change_percentage_30d"),
                "circulating_supply": market.get("circulating_supply"),
                "total_supply": market.get("total_supply"),
                "ath": market.get("ath", {}).get(vs_currency),
                "ath_change_pct": market.get("ath_change_percentage", {}).get(vs_currency),
            }
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception(f"Error fetching market data for: {coin_id}")
            return f"Error fetching market data: {e}"
