"""
AnyAPITools - discover and run any API in the AnyAPI catalog.

AnyAPI is a unified marketplace for scraping and data APIs: any API, one wallet, USD, no
subscriptions. Reach hundreds of third-party APIs (social media, search results, web data)
through one key and one normalized interface; pay per request in real dollars; failed calls
are never charged - AnyAPI fails over across providers automatically under one price.

Prerequisites:
- Get an API key at https://getanyapi.com/dashboard. New accounts start with free trial credit.
- Set the API key as an environment variable:
    export ANYAPI_API_KEY=<your-api-key>

Tools:
- search_apis: ranked search over the catalog for an API that returns the data you need
- get_api: one API's normalized input and output JSON Schema, plus its USD price
- run_api: execute one API by slug with a normalized input
- get_balance: remaining USD wallet balance for the key
"""

import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from getanyapi import AnyAPI
except ImportError:
    raise ImportError("`getanyapi` not installed. Please install using `pip install getanyapi`")


class AnyAPITools(Toolkit):
    """
    AnyAPI is a gateway to hundreds of scraping and data APIs behind one key, billed per request
    in USD. An agent finds an API with search_apis, reads its input schema and price with get_api,
    then executes it with run_api.

    Args:
        api_key (Optional[str]): AnyAPI key. Read from the `ANYAPI_API_KEY` env variable if not provided.
        enable_search_apis (bool): Enable catalog search. Default is True.
        enable_get_api (bool): Enable reading one API's schema and price. Default is True.
        enable_run_api (bool): Enable running an API. Default is True.
        enable_get_balance (bool): Enable reading the wallet balance. Default is False.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search_apis: bool = True,
        enable_get_api: bool = True,
        enable_run_api: bool = True,
        enable_get_balance: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("ANYAPI_API_KEY")
        if not self.api_key:
            log_error("ANYAPI_API_KEY not set. Please set the ANYAPI_API_KEY environment variable.")

        self.client: AnyAPI = AnyAPI(api_key=self.api_key, base_url="https://api.getanyapi.com")

        tools: List[Any] = []
        if all or enable_search_apis:
            tools.append(self.search_apis)
        if all or enable_get_api:
            tools.append(self.get_api)
        if all or enable_run_api:
            tools.append(self.run_api)
        if all or enable_get_balance:
            tools.append(self.get_balance)

        super().__init__(name="anyapi_tools", tools=tools, **kwargs)

    def search_apis(
        self,
        query: str,
        category: Optional[str] = None,
        platform: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> str:
        """Use this function to search the AnyAPI catalog for an API that returns the data you need.

        Args:
            query (str): What the API should return, for example "instagram profile" or "google maps reviews".
            category (Optional[str]): Restrict results to one catalog category.
            platform (Optional[str]): Restrict results to one platform, for example "instagram".
            limit (Optional[int]): Maximum number of APIs to return.

        Returns:
            str: JSON string of the matching APIs, each with its slug, description and USD price.
        """
        results = self.client.search(query=query, category=category, platform=platform, limit=limit)
        return json.dumps(results.model_dump(mode="json"), default=str)

    def get_api(self, slug: str) -> str:
        """Use this function to read one API's normalized input and output JSON Schema and its USD price.

        Call this before the first run_api on a slug and build the input from the schema it returns.
        Every input schema is strict, so an invented field name fails the call.

        Args:
            slug (str): The API to describe, as returned by search_apis.

        Returns:
            str: JSON string with the API's input and output schema, USD pricing and latency.
        """
        entry = self.client.describe(slug)
        return json.dumps(entry.model_dump(mode="json"), default=str)

    def run_api(self, slug: str, input: Dict[str, Any]) -> str:
        """Use this function to run one AnyAPI endpoint and get its normalized output.

        The wallet is charged in USD on success only. Read the input schema with get_api first.

        Args:
            slug (str): The API to run, as returned by search_apis.
            input (Dict[str, Any]): The input object, matching the input schema returned by get_api.

        Returns:
            str: JSON string with the output, the USD cost of the call and the number of items returned.
        """
        result = self.client.run(slug, input)
        return json.dumps(result.model_dump(mode="json"), default=str)

    def get_balance(self) -> str:
        """Use this function to read the remaining USD wallet balance for the AnyAPI key.

        Returns:
            str: JSON string with the remaining balance in USD.
        """
        balance = self.client.balance()
        return json.dumps(balance.model_dump(mode="json"), default=str)
