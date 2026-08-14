"""
Brandfetch API toolkit for retrieving brand data and searching brands.
"""

import json
import warnings
from os import getenv
from typing import Callable, List, Optional

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed.")

from agno.tools import Toolkit


class BrandfetchTools(Toolkit):
    """
    Brandfetch API toolkit for retrieving brand data and searching brands.

    Supports both Brand API (retrieve comprehensive brand data) and
    Brand Search API (find and search brands by name).

    -- Brand API

    api_key: str - your Brandfetch API key

    -- Brand Search API

    client_id: str - your Brandfetch Client ID

    all: bool - if True, will use all tools
    search_by_identifier: bool - if True, will use search by identifier
    search_by_brand: bool - if True, will use search by brand
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        base_url: str = "https://api.brandfetch.io/v2",
        timeout: Optional[float] = 20.0,
        search_by_identifier: bool = True,
        search_by_brand: bool = False,
        all: bool = False,
        **kwargs,
    ):
        # Backwards compat for old param names
        if "enable_search_by_identifier" in kwargs:
            warnings.warn(
                "enable_search_by_identifier is deprecated, use search_by_identifier", DeprecationWarning, stacklevel=2
            )
            search_by_identifier = kwargs.pop("enable_search_by_identifier")
        if "enable_search_by_brand" in kwargs:
            warnings.warn("enable_search_by_brand is deprecated, use search_by_brand", DeprecationWarning, stacklevel=2)
            search_by_brand = kwargs.pop("enable_search_by_brand")

        self.api_key = api_key or getenv("BRANDFETCH_API_KEY")
        self.client_id = client_id or getenv("BRANDFETCH_CLIENT_ID")
        self.base_url = base_url
        self.timeout = httpx.Timeout(timeout)
        self.search_url = f"{self.base_url}/search"
        self.brand_url = f"{self.base_url}/brands"

        # Build tools lists
        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Callable] = []
        async_tools_list: List[tuple] = []

        if all or search_by_identifier:
            tools.append(self.search_by_identifier)
            async_tools_list.append((self.asearch_by_identifier, "search_by_identifier"))
        if all or search_by_brand:
            tools.append(self.search_by_brand)
            async_tools_list.append((self.asearch_by_brand, "search_by_brand"))

        name = kwargs.pop("name", "brandfetch_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools_list, **kwargs)

    async def asearch_by_identifier(self, identifier: str) -> str:
        """Search for brand data by identifier (domain, brand id, isin, stock ticker).

        Args:
            identifier: Domain (nike.com), Brand ID (id_0dwKPKT), ISIN (US6541061031), or Stock Ticker (NKE).

        Returns:
            JSON with brand data including logos, colors, fonts, and other brand assets.
        """
        if not self.api_key:
            return json.dumps({"error": "API key is required for brand search by identifier"})

        url = f"{self.brand_url}/{identifier}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return json.dumps(response.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return json.dumps({"error": f"Brand not found for identifier: {identifier}"})
            elif e.response.status_code == 401:
                return json.dumps({"error": "Invalid API key"})
            elif e.response.status_code == 429:
                return json.dumps({"error": "Rate limit exceeded"})
            else:
                return json.dumps({"error": f"API error: {e.response.status_code}"})
        except httpx.RequestError as e:
            return json.dumps({"error": f"Request failed: {e}"})

    def search_by_identifier(self, identifier: str) -> str:
        """Search for brand data by identifier (domain, brand id, isin, stock ticker).

        Args:
            identifier: Domain (nike.com), Brand ID (id_0dwKPKT), ISIN (US6541061031), or Stock Ticker (NKE).

        Returns:
            JSON with brand data including logos, colors, fonts, and other brand assets.
        """
        if not self.api_key:
            return json.dumps({"error": "API key is required for brand search by identifier"})

        url = f"{self.brand_url}/{identifier}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                return json.dumps(response.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return json.dumps({"error": f"Brand not found for identifier: {identifier}"})
            elif e.response.status_code == 401:
                return json.dumps({"error": "Invalid API key"})
            elif e.response.status_code == 429:
                return json.dumps({"error": "Rate limit exceeded"})
            else:
                return json.dumps({"error": f"API error: {e.response.status_code}"})
        except httpx.RequestError as e:
            return json.dumps({"error": f"Request failed: {e}"})

    async def asearch_by_brand(self, name: str) -> str:
        """Search for brands by name using the Brand Search API.

        Args:
            name: Brand name to search for (e.g., 'Google', 'Apple').

        Returns:
            JSON with search results containing brand matches.
        """
        if not self.client_id:
            return json.dumps({"error": "Client ID is required for brand search by name"})

        url = f"{self.search_url}/{name}"
        params = {"c": self.client_id}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return json.dumps(response.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return json.dumps({"error": f"No brands found for name: {name}"})
            elif e.response.status_code == 401:
                return json.dumps({"error": "Invalid client ID"})
            elif e.response.status_code == 429:
                return json.dumps({"error": "Rate limit exceeded"})
            else:
                return json.dumps({"error": f"API error: {e.response.status_code}"})
        except httpx.RequestError as e:
            return json.dumps({"error": f"Request failed: {e}"})

    def search_by_brand(self, name: str) -> str:
        """Search for brands by name using the Brand Search API.

        Args:
            name: Brand name to search for (e.g., 'Google', 'Apple').

        Returns:
            JSON with search results containing brand matches.
        """
        if not self.client_id:
            return json.dumps({"error": "Client ID is required for brand search by name"})

        url = f"{self.search_url}/{name}"
        params = {"c": self.client_id}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return json.dumps(response.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return json.dumps({"error": f"No brands found for name: {name}"})
            elif e.response.status_code == 401:
                return json.dumps({"error": "Invalid client ID"})
            elif e.response.status_code == 429:
                return json.dumps({"error": "Rate limit exceeded"})
            else:
                return json.dumps({"error": f"API error: {e.response.status_code}"})
        except httpx.RequestError as e:
            return json.dumps({"error": f"Request failed: {e}"})
