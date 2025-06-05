from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_info

try:
    import agentql
    from playwright.sync_api import sync_playwright
except ImportError:
    raise ImportError("`agentql` not installed. Please install using `pip install agentql`")


class AgentQLTools(Toolkit):
    def __init__(self, api_key: Optional[str] = None, scrape: bool = True, agentql_query: str = "", **kwargs):
        self.api_key = api_key or getenv("AGENTQL_API_KEY")
        if not self.api_key:
            raise ValueError("AGENTQL_API_KEY not set. Please set the AGENTQL_API_KEY environment variable.")

        self.agentql_query = agentql_query

        tools: List[Any] = []
        if scrape:
            tools.append(self.scrape_website)
        if agentql_query:
            log_info("Custom AgentQL query provided. Registering custom scrape function.")
            tools.append(self.custom_scrape_website)

        super().__init__(name="agentql_tools", tools=tools, **kwargs)

    def scrape_website(self, url: str) -> str:
        """
        Scrape all text content from a website using AgentQL.

        Args:
            url (str): The URL of the website to scrape

        Returns:
            str: Extracted text content or error message
        """
        if not url:
            return "No URL provided"

        TEXT_SEARCH_QUERY = """
        {
            text_content[]
        }
        """

        try:
            with sync_playwright() as playwright, playwright.chromium.launch(headless=False) as browser:
                page = agentql.wrap(browser.new_page())
                page.goto(url)

                try:
                    # Get response from AgentQL query
                    response = page.query_data(TEXT_SEARCH_QUERY)

                    # Extract text based on response format
                    if isinstance(response, dict) and "text_content" in response:
                        text_items = [item for item in response["text_content"] if item and item.strip()]

                        deduplicated = list(set(text_items))
                        return " ".join(deduplicated)

                except Exception as e:
                    return f"Error extracting text: {e}"
        except Exception as e:
            return f"Error launching browser: {e}"

        return "No text content found"

    def custom_scrape_website(self, url: str) -> str:
        """
        Scrape a website using a custom AgentQL query.

        Args:
            url (str): The URL of the website to scrape

        Returns:
            str: Extracted text content or error message
        """
        if not url:
            return "No URL provided"

        if self.agentql_query == "":
            return "Custom AgentQL query not provided. Please provide a custom AgentQL query."

        try:
            with sync_playwright() as playwright, playwright.chromium.launch(headless=False) as browser:
                page = agentql.wrap(browser.new_page())
                page.goto(url)

                try:
                    # Get response from AgentQL query
                    response = page.query_data(self.agentql_query)

                    # Extract text based on response format
                    if isinstance(response, dict):
                        items = [item for item in response]
                        text_items = [text_item for text_item in items if text_item]

                        deduplicated = list(set(text_items))
                        return " ".join(deduplicated)

                except Exception as e:
                    return f"Error extracting text: {e}"
        except Exception as e:
            return f"Error launching browser: {e}"

        return "No text content found"
