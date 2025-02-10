import json
import re
from os import getenv
from typing import Optional

from agno.tools import Toolkit
from agno.utils.log import logger

try:
    import requests
except ImportError:
    raise ImportError("`requests` not installed. Please install using `pip install requests`.")


class ZendeskTools(Toolkit):
    """
    A toolkit class for interacting with the Zendesk API to search articles.
    It requires authentication details and the company name to configure the API access.
    """

    def __init__(
        self,
        username: Optional[str] = None,
        password: Optional[str] = None,
        company_name: Optional[str] = None,
    ):
        """
        Initializes the ZendeskTools class with necessary authentication details
        and registers the search_zendesk method.

        Parameters:
        username (str): The username for Zendesk API authentication.
        password (str): The password for Zendesk API authentication.
        company_name (str): The company name to form the base URL for API requests.
        """
        super().__init__(name="zendesk_tools")
        self.username = username or getenv("ZENDESK_USERNAME")
        self.password = password or getenv("ZENDESK_PW")
        self.company_name = company_name or getenv("ZENDESK_COMPANY_NAME")

        if not self.username or not self.password or not self.company_name:
            logger.error("Username, password, or company name not provided.")

        self.register(self.search_zendesk)

    def search_zendesk(self, search_string: str) -> str:
        """
        Searches for articles in Zendesk Help Center that match the given search string.

        Parameters:
        search_string (str): The search query to look for in Zendesk articles.

        Returns:
        str: A JSON-formatted string containing the list of articles without HTML tags.

        Raises:
        ConnectionError: If the API request fails due to connection-related issues.
        """

        if not self.username or not self.password or not self.company_name:
            return "Username, password, or company name not provided."

        logger.debug(f"Searching Zendesk for: {search_string}")

        auth = (self.username, self.password)
        url = f"https://{self.company_name}.zendesk.com/api/v2/help_center/articles/search.json?query={search_string}"
        try:
            response = requests.get(url, auth=auth)
            response.raise_for_status()
            clean = re.compile("<.*?>")
            articles = [re.sub(clean, "", article["body"]) for article in response.json()["results"]]
            return json.dumps(articles)
        except requests.RequestException as e:
            raise ConnectionError(f"API request failed: {e}")
