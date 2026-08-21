import json
from os import getenv
from typing import Callable, List, Optional

from agno.tools import Toolkit

try:
    import agentql
    from playwright.sync_api import sync_playwright
except ImportError:
    raise ImportError("`agentql` not installed. Please install using `pip install agentql`")


class AgentQLTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        agentql_query: str = "",
        scrape_website: bool = True,
        custom_scrape_website: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key = api_key or getenv("AGENTQL_API_KEY")
        if not self.api_key:
            raise ValueError("AGENTQL_API_KEY not set. Please set the AGENTQL_API_KEY environment variable.")

        self.agentql_query = agentql_query

        tools: List[Callable] = []
        if all or scrape_website:
            tools.append(self.agentql_scrape_website)
        if all or custom_scrape_website or agentql_query:
            tools.append(self.agentql_custom_scrape_website)

        super().__init__(name="agentql_tools", tools=tools, **kwargs)

    def agentql_scrape_website(self, url: str) -> str:
        """Scrape all text content from a website using AgentQL.

        Args:
            url: The URL of the website to scrape.

        Returns:
            JSON with text_content array or error.
        """
        if not url:
            return json.dumps({"error": "No URL provided"})

        query = "{ text_content[] }"

        try:
            with sync_playwright() as playwright, playwright.chromium.launch(headless=False) as browser:
                page = agentql.wrap(browser.new_page())
                page.goto(url)

                response = page.query_data(query)

                if isinstance(response, dict) and "text_content" in response:
                    text_items = [item for item in response["text_content"] if item and item.strip()]
                    deduplicated = list(set(text_items))
                    return json.dumps({"text_content": deduplicated})

                return json.dumps({"text_content": []})
        except Exception as e:
            return json.dumps({"error": f"Failed to scrape: {e}"})

    def agentql_custom_scrape_website(self, url: str) -> str:
        """Scrape a website using a custom AgentQL query.

        Args:
            url: The URL of the website to scrape.

        Returns:
            JSON with query results or error.
        """
        if not url:
            return json.dumps({"error": "No URL provided"})

        if not self.agentql_query:
            return json.dumps({"error": "Custom AgentQL query not provided"})

        try:
            with sync_playwright() as playwright, playwright.chromium.launch(headless=False) as browser:
                page = agentql.wrap(browser.new_page())
                page.goto(url)

                response = page.query_data(self.agentql_query)

                if isinstance(response, dict):
                    return json.dumps(response)
                return json.dumps({"result": response})
        except Exception as e:
            return json.dumps({"error": f"Failed to scrape: {e}"})
