from os import getenv
from typing import Any, Dict, List, Optional

import requests

from agno.tools import Toolkit
from agno.utils.log import log_error


class FXMacroDataTools(Toolkit):
    """Official-source macroeconomic, FX and central-bank data across 18 currencies.

    FXMacroData aggregates official publishers - statistical agencies, central
    banks and exchanges - behind one contract, so an agent can ask "what did US
    core inflation print at, and when is the next release" without knowing which
    of eighteen publishers to call or how each one formats its data.

    Every observation carries the instant it was published
    (announcement_datetime), which is what makes the data usable for
    point-in-time reasoning rather than only for describing the present.

    USD works without an API key: the catalogue, announcement history, the
    release calendar, central-bank headlines, market sessions and risk sentiment
    are all reachable anonymously, with announcement history limited to the most
    recent 90 days. A key lifts that window and unlocks the other seventeen
    currencies plus FX rates, rate differentials, COT positioning and
    commodities.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.fxmacrodata.com/v1",
        timeout: int = 30,
        **kwargs,
    ):
        """Initialize the FXMacroData Tools.

        Args:
            api_key: FXMacroData API key. Optional - USD data is public. Falls
                back to the FXMACRODATA_API_KEY environment variable.
            base_url: API base URL. Override only to target a different deployment.
            timeout: Per-request HTTP timeout in seconds. Default is 30.
        """

        self.api_key: Optional[str] = api_key or getenv("FXMACRODATA_API_KEY")
        self.base_url: str = base_url.rstrip("/")

        tools: List[Any] = [
            # Discovery
            self.search_indicators,
            # Macro releases
            self.get_latest_macro_snapshot,
            self.get_indicator_history,
            self.get_release_calendar,
            self.get_central_bank_headlines,
            # FX and rates
            self.get_fx_rate,
            self.get_rate_differential,
            # Positioning, commodities and market context
            self.get_cot_positioning,
            self.get_commodity_prices,
            self.get_market_sessions,
            self.get_risk_sentiment,
        ]

        super().__init__(name="fxmacrodata_tools", tools=tools, timeout=timeout, **kwargs)

    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None) -> str:
        """Make a request to the FXMacroData API.

        Args:
            endpoint: API endpoint path, relative to the base URL.
            params: Optional query parameters.

        Returns:
            The raw JSON response body, or an error description.
        """
        headers = {"Accept": "application/json"}
        if self.api_key:
            # Sent as a header rather than a query parameter so the key stays
            # out of proxy and server access logs.
            headers["X-API-Key"] = self.api_key

        clean_params = {key: value for key, value in (params or {}).items() if value is not None}
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        try:
            response = requests.get(url, headers=headers, params=clean_params, timeout=self.timeout)
            response.raise_for_status()
            return response.text
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "unknown"
            if status in (401, 403):
                log_error(
                    f"FXMacroData request to {url} was rejected (HTTP {status}). "
                    "Non-USD currencies and market data require an API key; set FXMACRODATA_API_KEY."
                )
                return (
                    f"FXMacroData denied the request to {endpoint} (HTTP {status}). "
                    "This data requires an API key. USD data is available without one."
                )
            log_error(f"Error making request to {url}: {str(e)}")
            return f"Error making request to {url}: {str(e)}"
        except requests.exceptions.RequestException as e:
            log_error(f"Error making request to {url}: {str(e)}")
            return f"Error making request to {url}: {str(e)}"

    # Discovery

    def search_indicators(self, currency: str = "USD") -> str:
        """List every macroeconomic indicator FXMacroData publishes for a currency.

        Call this first when you do not already know the indicator slug. The
        response gives the slug to pass to get_indicator_history, along with the
        unit, frequency, publisher and how far back the series reaches.

        Args:
            currency: Three-letter currency code, for example 'USD' or 'EUR'.

        Returns:
            JSON mapping each indicator slug to its metadata and coverage.
        """
        return self._make_request(f"data_catalogue/{currency.lower()}")

    # Macro releases

    def get_latest_macro_snapshot(self, currency: str = "USD") -> str:
        """Get the latest value of every indicator for a currency in one call.

        This is the fastest way to understand the current macro picture for an
        economy: one request returns the most recent print for each indicator
        with its publication timestamp, the previous value and the change,
        rather than requiring a request per series.

        Args:
            currency: Three-letter currency code, for example 'USD' or 'JPY'.

        Returns:
            JSON list of indicators with their latest and previous readings.
        """
        return self._make_request(f"announcements/{currency.lower()}/latest")

    def get_indicator_history(
        self,
        currency: str = "USD",
        indicator: str = "inflation",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        limit: int = 20,
    ) -> str:
        """Get the published history of one macroeconomic indicator.

        Each row carries the value, the period it covers and the instant it was
        announced, so a value is never presented as though it were known before
        its release.

        Args:
            currency: Three-letter currency code, for example 'USD'.
            indicator: Indicator slug from search_indicators, for example
                'inflation', 'non_farm_payrolls' or 'policy_rate'.
            start_date: Optional ISO start date, for example '2024-01-01'.
            end_date: Optional ISO end date.
            limit: Maximum rows to return. Caps at 100.

        Returns:
            JSON observations, newest first, with publication timestamps.
        """
        params = {"start_date": start_date, "end_date": end_date, "limit": limit}
        return self._make_request(f"announcements/{currency.lower()}/{indicator}", params)

    def get_release_calendar(self, currency: str = "USD", limit: int = 20) -> str:
        """Get upcoming scheduled macroeconomic releases for a currency.

        Use this to know what is due and when, before it happens - for example
        to avoid acting immediately ahead of a top-tier release, or to schedule
        follow-up work for the moment a figure lands.

        Args:
            currency: Three-letter currency code, for example 'USD'.
            limit: Maximum releases to return. Caps at 100.

        Returns:
            JSON scheduled releases with publication times and importance.
        """
        return self._make_request(f"calendar/{currency.lower()}", {"limit": limit})

    def get_central_bank_headlines(self, currency: str = "USD", limit: int = 10) -> str:
        """Get recent official central-bank press releases for a currency.

        Args:
            currency: Three-letter currency code, for example 'USD' or 'EUR'.
            limit: Maximum headlines to return.

        Returns:
            JSON press releases with titles, timestamps and source links.
        """
        return self._make_request(f"press-releases/{currency.lower()}", {"limit": limit})

    # FX and rates

    def get_fx_rate(self, base: str = "EUR", quote: str = "USD", limit: int = 10) -> str:
        """Get official reference exchange rates for a currency pair.

        Rates come from official publishers such as the ECB and the Federal
        Reserve rather than from a broker feed. Requires an API key.

        Args:
            base: Three-letter base currency code, for example 'EUR'.
            quote: Three-letter quote currency code, for example 'USD'.
            limit: Maximum observations to return, newest first.

        Returns:
            JSON dated reference rates for the pair.
        """
        return self._make_request(f"forex/{base.lower()}/{quote.lower()}", {"limit": limit})

    def get_rate_differential(self, base: str = "USD", quote: str = "JPY", limit: int = 10) -> str:
        """Get the policy rate differential between two currencies.

        The rate differential is the standard first look at carry for a pair.
        Requires an API key.

        Args:
            base: Three-letter base currency code, for example 'USD'.
            quote: Three-letter quote currency code, for example 'JPY'.
            limit: Maximum observations to return, newest first.

        Returns:
            JSON dated policy rate differentials.
        """
        return self._make_request(f"rate_differentials/{base.lower()}/{quote.lower()}", {"limit": limit})

    # Positioning, commodities and market context

    def get_cot_positioning(self, currency: str = "USD", limit: int = 10) -> str:
        """Get CFTC Commitment of Traders positioning for a currency.

        Shows how speculative and commercial participants are positioned, which
        is the usual proxy for crowding in a currency. Requires an API key.

        Args:
            currency: Three-letter currency code, for example 'GBP'.
            limit: Maximum weekly reports to return, newest first.

        Returns:
            JSON COT reports with positioning by participant category.
        """
        return self._make_request(f"cot/{currency.lower()}", {"limit": limit})

    def get_commodity_prices(self) -> str:
        """Get the latest official prices for tracked commodities.

        Requires an API key.

        Returns:
            JSON latest commodity prices with publication timestamps.
        """
        return self._make_request("commodities/latest")

    def get_market_sessions(self) -> str:
        """Get current FX market session status.

        Tells you which of the Sydney, Tokyo, London and New York sessions are
        open right now, which governs when liquidity is available.

        Returns:
            JSON session status with open and close times.
        """
        return self._make_request("market_sessions")

    def get_risk_sentiment(self) -> str:
        """Get the current cross-asset risk sentiment reading.

        Returns:
            JSON risk sentiment score with the inputs behind it.
        """
        return self._make_request("risk_sentiment")
