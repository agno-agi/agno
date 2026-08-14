import json
import re
import warnings
from os import getenv
from typing import Callable, List, Optional
from urllib.parse import quote_plus

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`.")


class ZendeskTools(Toolkit):
    """Toolkit for searching Zendesk Help Center articles.

    Args:
        username: Zendesk username. Falls back to ZENDESK_USERNAME env var.
        password: Zendesk password. Falls back to ZENDESK_PASSWORD env var.
        company_name: Company subdomain. Falls back to ZENDESK_COMPANY_NAME env var.
        search_zendesk: Enable search_zendesk tool. Defaults to True.
        timeout: Request timeout in seconds. Defaults to 30.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        company_name: Optional[str] = None,
        search_zendesk: bool = True,
        timeout: int = 30,
        **kwargs,
    ):
        # Backwards compat for old param names
        if "enable_search_zendesk" in kwargs:
            warnings.warn("enable_search_zendesk is deprecated, use search_zendesk", DeprecationWarning, stacklevel=2)
            search_zendesk = kwargs.pop("enable_search_zendesk")

        self.username = username or getenv("ZENDESK_USERNAME")
        self.password = password or getenv("ZENDESK_PASSWORD")
        self.company_name = company_name or getenv("ZENDESK_COMPANY_NAME")

        if not self.username or not self.password or not self.company_name:
            log_error("Username, password, or company name not provided.")

        tools: List[Callable] = []
        if search_zendesk:
            tools.append(self.search_zendesk)

        super().__init__(name="zendesk_tools", tools=tools, timeout=timeout, **kwargs)

    def search_zendesk(self, search_string: str) -> str:
        """Search Zendesk Help Center articles.

        Args:
            search_string: The search query.

        Returns:
            JSON with matching articles.
        """

        if not self.username or not self.password or not self.company_name:
            return json.dumps({"error": "Username, password, or company name not provided."})

        log_debug(f"Searching Zendesk for: {search_string}")

        auth = (self.username, self.password)
        url = f"https://{self.company_name}.zendesk.com/api/v2/help_center/articles/search.json?query={quote_plus(search_string)}"
        try:
            response = requests.get(url, auth=auth, timeout=self.timeout)
            response.raise_for_status()
            clean = re.compile("<.*?>")
            articles = [re.sub(clean, "", article["body"]) for article in response.json()["results"]]
            return json.dumps({"articles": articles})
        except requests.RequestException as e:
            return json.dumps({"error": f"API request failed: {e}"})
