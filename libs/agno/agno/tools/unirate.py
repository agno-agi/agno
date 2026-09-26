import json
from os import getenv
from typing import Any, List, Optional

import httpx
from agno.tools import Toolkit
from agno.utils.log import log_info, logger


class UniRateTools(Toolkit):
    """UniRateTools provides access to currency exchange rates, currency
    conversion, supported currencies, and VAT rates via the UniRate API
    (https://unirateapi.com).

    Args:
        api_key (Optional[str]): UniRate API key. If not provided, will try to get from the UNIRATE_API_KEY env var.
        base_currency (str): Default base (source) currency as an ISO 4217 code. Default is "USD".
        enable_get_exchange_rate (bool): Enable the exchange-rate function. Default is True.
        enable_convert_currency (bool): Enable the currency-conversion function. Default is True.
        enable_list_currencies (bool): Enable the supported-currencies function. Default is True.
        enable_get_vat_rate (bool): Enable the VAT-rate function. Default is True.
        all (bool): Enable all functions. Default is False.
        timeout (int): Per-request HTTP timeout in seconds. Default is 30.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_currency: str = "USD",
        enable_get_exchange_rate: bool = True,
        enable_convert_currency: bool = True,
        enable_list_currencies: bool = True,
        enable_get_vat_rate: bool = True,
        all: bool = False,
        timeout: int = 30,
        **kwargs,
    ):
        self.api_key = api_key or getenv("UNIRATE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "UniRate API key is required. Provide it as an argument or set the UNIRATE_API_KEY environment variable."
            )

        self.base_currency = base_currency
        self.base_url = "https://api.unirateapi.com/api"

        tools: List[Any] = []
        if enable_get_exchange_rate or all:
            tools.append(self.get_exchange_rate)
        if enable_convert_currency or all:
            tools.append(self.convert_currency)
        if enable_list_currencies or all:
            tools.append(self.list_currencies)
        if enable_get_vat_rate or all:
            tools.append(self.get_vat_rate)

        super().__init__(name="unirate_tools", tools=tools, timeout=timeout, **kwargs)

    def _make_request(self, endpoint: str, params: dict) -> Any:
        """Make a request to the UniRate API.

        Args:
            endpoint (str): The API endpoint path (e.g. "rates").
            params (dict): Query parameters for the request.

        Returns:
            Any: The parsed JSON response from the API, or a dict with an "error" key.
        """
        try:
            params["api_key"] = self.api_key
            response = httpx.get(
                f"{self.base_url}/{endpoint}",
                params=params,
                headers={"Accept": "application/json"},
                timeout=self.timeout,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as e:
            logger.exception(f"Error making request to UniRate endpoint '{endpoint}'")
            return {"error": str(e)}

    def get_exchange_rate(self, to_currency: str, from_currency: Optional[str] = None) -> str:
        """Get the current exchange rate between two currencies.

        Args:
            to_currency (str): Target currency code (ISO 4217), e.g. "EUR".
            from_currency (Optional[str]): Source currency code. Defaults to the toolkit base currency (USD).

        Returns:
            str: JSON string containing the exchange rate, e.g. {"rate": "0.92"}.
        """
        try:
            base = (from_currency or self.base_currency).upper()
            target = to_currency.upper()
            log_info(f"Getting exchange rate {base} -> {target}")
            result = self._make_request("rates", {"from": base, "to": target})
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error getting exchange rate")
            return json.dumps({"error": str(e)})

    def convert_currency(self, amount: float, to_currency: str, from_currency: Optional[str] = None) -> str:
        """Convert an amount from one currency to another using current rates.

        Args:
            amount (float): The amount of money to convert.
            to_currency (str): Target currency code (ISO 4217), e.g. "EUR".
            from_currency (Optional[str]): Source currency code. Defaults to the toolkit base currency (USD).

        Returns:
            str: JSON string containing the converted amount, e.g. {"result": "92.50"}.
        """
        try:
            base = (from_currency or self.base_currency).upper()
            target = to_currency.upper()
            log_info(f"Converting {amount} {base} -> {target}")
            result = self._make_request("convert", {"from": base, "to": target, "amount": amount})
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error converting currency")
            return json.dumps({"error": str(e)})

    def list_currencies(self) -> str:
        """List all currency codes supported by the UniRate API.

        Returns:
            str: JSON string containing the list of supported currency codes.
        """
        try:
            log_info("Listing supported currencies")
            result = self._make_request("currencies", {})
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error listing supported currencies")
            return json.dumps({"error": str(e)})

    def get_vat_rate(self, country: Optional[str] = None) -> str:
        """Get value-added-tax (VAT) rates. If a country is provided, returns that
        country's VAT rate; otherwise returns VAT rates for all supported countries.

        Args:
            country (Optional[str]): ISO-3166 alpha-2 country code, e.g. "DE". If omitted, returns all countries.

        Returns:
            str: JSON string containing VAT rate data.
        """
        try:
            params: dict = {}
            if country:
                params["country"] = country.upper()
            log_info(f"Getting VAT rate for {country.upper() if country else 'all countries'}")
            result = self._make_request("vat/rates", params)
            return json.dumps(result, indent=2)
        except Exception as e:
            logger.exception("Error getting VAT rate")
            return json.dumps({"error": str(e)})
