"""
Brandfetch API toolkit for retrieving brand data and searching brands.
"""

import warnings
from os import getenv
from typing import Any, List, Optional

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
    enable_search_by_identifier: bool - if True, will use search by identifier
    enable_search_by_brand: bool - if True, will use search by brand
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        client_id: Optional[str] = None,
        base_url: str = "https://api.brandfetch.io/v2",
        timeout: Optional[float] = 20.0,
        enable_search_by_identifier: bool = True,
        enable_search_by_brand: bool = False,
        all: bool = False,
        async_tools: bool = False,  # Deprecated
        **kwargs,
    ):
        # Handle deprecated async_tools parameter
        if async_tools:
            warnings.warn(
                "The 'async_tools' parameter is deprecated and will be removed in a future version. "
                "Async tools are now automatically used when calling agent.arun() or agent.aprint_response().",
                DeprecationWarning,
                stacklevel=2,
            )

        self.api_key = api_key or getenv("BRANDFETCH_API_KEY")
        self.client_id = client_id or getenv("BRANDFETCH_CLIENT_ID")
        self.base_url = base_url
        self.timeout = httpx.Timeout(timeout)
        self.search_url = f"{self.base_url}/search"
        self.brand_url = f"{self.base_url}/brands"

        # Build tools lists
        # sync tools: used by agent.run() and agent.print_response()
        # async tools: used by agent.arun() and agent.aprint_response()
        tools: List[Any] = []
        async_tools_list: List[tuple] = []

        if all or enable_search_by_identifier:
            tools.append(self.search_by_identifier)
            async_tools_list.append((self.asearch_by_identifier, "search_by_identifier"))
        if all or enable_search_by_brand:
            tools.append(self.search_by_brand)
            async_tools_list.append((self.asearch_by_brand, "search_by_brand"))

        name = kwargs.pop("name", "brandfetch_tools")
        super().__init__(name=name, tools=tools, async_tools=async_tools_list, **kwargs)

    async def asearch_by_identifier(self, identifier: str) -> dict[str, Any]:
        """
        Search for brand data by identifier (domain, brand id, isin, stock ticker).

        Args:
            identifier: Options are you can use: Domain (nike.com), Brand ID (id_0dwKPKT), ISIN (US6541061031), Stock Ticker (NKE)
        Returns:
            Dict containing brand data including logos, colors, fonts, and other brand assets

        Raises:
            ValueError: If no API key is provided
        """
        if not self.api_key:
            raise ValueError("API key is required for brand search by identifier")

        url = f"{self.brand_url}/{identifier}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"error": f"Brand not found for identifier: {identifier}"}
            elif e.response.status_code == 401:
                return {"error": "Invalid API key"}
            elif e.response.status_code == 429:
                return {"error": "Rate limit exceeded"}
            else:
                return {"error": f"API error: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}

    def search_by_identifier(self, identifier: str) -> dict[str, Any]:
        """
        Search for brand data by identifier (domain, brand id, isin, stock ticker).

        Args:
            identifier: Options are you can use: Domain (nike.com), Brand ID (id_0dwKPKT), ISIN (US6541061031), Stock Ticker (NKE)

        Returns:
            Dict containing brand data including logos, colors, fonts, and other brand assets

        Raises:
            ValueError: If no API key is provided
        """
        if not self.api_key:
            raise ValueError("API key is required for brand search by identifier")

        url = f"{self.brand_url}/{identifier}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, headers=headers)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"error": f"Brand not found for identifier: {identifier}"}
            elif e.response.status_code == 401:
                return {"error": "Invalid API key"}
            elif e.response.status_code == 429:
                return {"error": "Rate limit exceeded"}
            else:
                return {"error": f"API error: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}

    async def asearch_by_brand(self, name: str) -> dict[str, Any]:
        """
        Search for brands by name using the Brand Search API - can give you the right brand id to use for the brand api.

        Args:
            name: Brand name to search for (e.g., 'Google', 'Apple')

        Returns:
            Dict containing search results with brand matches

        Raises:
            ValueError: If no client ID is provided
        """
        if not self.client_id:
            raise ValueError("Client ID is required for brand search by name")

        url = f"{self.search_url}/{name}"
        params = {"c": self.client_id}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"error": f"No brands found for name: {name}"}
            elif e.response.status_code == 401:
                return {"error": "Invalid client ID"}
            elif e.response.status_code == 429:
                return {"error": "Rate limit exceeded"}
            else:
                return {"error": f"API error: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}

    def search_by_brand(self, name: str) -> dict[str, Any]:
        """
        Search for brands by name using the Brand Search API - can give you the right brand id to use for the brand api.

        Args:
            name: Brand name to search for (e.g., 'Google', 'Apple')

        Returns:
            Dict containing search results with brand matches

        Raises:
            ValueError: If no client ID is provided
        """
        if not self.client_id:
            raise ValueError("Client ID is required for brand search by name")

        url = f"{self.search_url}/{name}"
        params = {"c": self.client_id}

        try:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return {"error": f"No brands found for name: {name}"}
            elif e.response.status_code == 401:
                return {"error": "Invalid client ID"}
            elif e.response.status_code == 429:
                return {"error": "Rate limit exceeded"}
            else:
                return {"error": f"API error: {e.response.status_code}"}
        except httpx.RequestError as e:
            return {"error": f"Request failed: {str(e)}"}
