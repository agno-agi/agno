import json
from importlib.metadata import version
from os import getenv
from platform import architecture, python_version
from typing import Optional

from oxylabs import RealtimeClient

from agno.tools import Toolkit
from agno.utils.log import logger


class CustomJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder that handles non-serializable types by converting them to strings."""

    def default(self, obj):
        try:
            return super().default(obj)
        except TypeError:
            return str(obj)


class OxylabsTools(Toolkit):
    """
    Oxylabs integration for Google Search, Amazon Product, and Universal scraping tools.
    Uses OXYLABS_USERNAME and OXYLABS_PASSWORD from environment variables for authentication.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(name="oxylabs_tools", **kwargs)
        self.username = username or getenv("OXYLABS_USERNAME")
        self.password = password or getenv("OXYLABS_PASSWORD")
        if not self.username or not self.password:
            logger.error("OXYLABS_USERNAME and/or OXYLABS_PASSWORD not set. Please set the environment variables.")
        bits, _ = architecture()
        sdk_type = f"oxylabs-agno-sdk-python/{version('agno')} ({python_version()}; {bits})"
        self.client = RealtimeClient(self.username, self.password, sdk_type=sdk_type)
        self.register(self.google_search)
        self.register(self.amazon_product)
        self.register(self.universal)
        self.register(self.amazon_search)

    def google_search(self, **kwargs) -> str:
        """Perform a Google search using Oxylabs SERP API via SDK resource-specific method."""
        response = self.client.google.scrape_search(**kwargs)
        return json.dumps(response.raw, cls=CustomJSONEncoder)

    def amazon_product(self, **kwargs) -> str:
        """Search for an Amazon product using Oxylabs Amazon API via SDK resource-specific method."""
        response = self.client.amazon.scrape_product(**kwargs)
        return json.dumps(response.raw, cls=CustomJSONEncoder)

    def universal(self, **kwargs) -> str:
        """Scrape any website using Oxylabs Universal Scraper API via SDK resource-specific method."""
        response = self.client.universal.scrape_url(**kwargs)
        return json.dumps(response.raw, cls=CustomJSONEncoder)

    def amazon_search(self, **kwargs) -> str:
        """Search Amazon using Oxylabs Amazon Search API via SDK resource-specific method."""
        response = self.client.amazon.scrape_search(**kwargs)
        return json.dumps(response.raw, cls=CustomJSONEncoder)
