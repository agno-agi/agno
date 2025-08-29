import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit

try:
    from scrapegraph_py import Client
    from scrapegraph_py.logger import sgai_logger
except ImportError:
    raise ImportError("`scrapegraph-py` not installed. Please install using `pip install scrapegraph-py`")

# Set logging level
sgai_logger.set_logging(level="INFO")


class ScrapeGraphTools(Toolkit):
    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_smartscraper: bool = True,
        enable_markdownify: bool = False,
        enable_crawl: bool = False,
        enable_searchscraper: bool = False,
        enable_agentic_crawler: bool = False,
        all: bool = False,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("SGAI_API_KEY")
        self.client = Client(api_key=self.api_key)

        # Start with smartscraper by default
        # Only enable markdownify if smartscraper is False
        if not enable_smartscraper and not all:
            enable_markdownify = True

        tools: List[Any] = []
        if enable_smartscraper or all:
            tools.append(self.smartscraper)
        if enable_markdownify or all:
            tools.append(self.markdownify)
        if enable_crawl or all:
            tools.append(self.crawl)
        if enable_searchscraper or all:
            tools.append(self.searchscraper)
        if enable_agentic_crawler or all:
            tools.append(self.agentic_crawler)

        super().__init__(name="scrapegraph_tools", tools=tools, **kwargs)

    def smartscraper(self, url: str, prompt: str) -> str:
        """Extract structured data from a webpage using LLM.
        Args:
            url (str): The URL to scrape
            prompt (str): Natural language prompt describing what to extract
        Returns:
            The structured data extracted from the webpage
        """
        try:
            response = self.client.smartscraper(website_url=url, user_prompt=prompt)
            return json.dumps(response["result"])
        except Exception as e:
            return json.dumps({"error": str(e)})

    def markdownify(self, url: str) -> str:
        """Convert a webpage to markdown format.
        Args:
            url (str): The URL to convert
        Returns:
            The markdown version of the webpage
        """
        try:
            response = self.client.markdownify(website_url=url)
            return response["result"]
        except Exception as e:
            return f"Error converting to markdown: {str(e)}"

    def crawl(
        self,
        url: str,
        prompt: str,
        schema: dict,
        cache_website: bool = True,
        depth: int = 2,
        max_pages: int = 2,
        same_domain_only: bool = True,
        batch_size: int = 1,
    ) -> str:
        """Crawl a website and extract structured data
        Args:
            url (str): The URL to crawl
            prompt (str): Natural language prompt describing what to extract
            schema (dict): JSON schema for extraction
            cache_website (bool): Whether to cache the website
            depth (int): Crawl depth
            max_pages (int): Max number of pages to crawl
            same_domain_only (bool): Restrict to same domain
            batch_size (int): Batch size for crawling
        Returns:
            The structured data extracted from the website
        """
        try:
            response = self.client.crawl(
                url=url,
                prompt=prompt,
                schema=schema,
                cache_website=cache_website,
                depth=depth,
                max_pages=max_pages,
                same_domain_only=same_domain_only,
                batch_size=batch_size,
            )
            return json.dumps(response, indent=2)
        except Exception as e:
            return json.dumps({"error": str(e)})

    def agentic_crawler(
        self,
        url: str,
        steps: List[str],
        use_session: bool = True,
        user_prompt: Optional[str] = None,
        output_schema: Optional[dict] = None,
        ai_extraction: bool = False,
    ) -> str:
        """Perform agentic crawling with automated browser actions and optional AI extraction.

        This tool can:
        1. Navigate to a website
        2. Perform a series of automated actions (like filling forms, clicking buttons)
        3. Extract the resulting HTML content as markdown
        4. Optionally use AI to extract structured data

        Args:
            url (str): The URL to scrape
            steps (List[str]): List of steps to perform on the webpage (e.g., ["Type email in input box", "click login"])
            use_session (bool): Whether to use session for the scraping (default: True)
            user_prompt (Optional[str]): Prompt for AI extraction (only used when ai_extraction=True)
            output_schema (Optional[dict]): Schema for structured data extraction (only used when ai_extraction=True)
            ai_extraction (bool): Whether to use AI for data extraction from the scraped content (default: False)

        Returns:
            JSON string containing the scraping results, including request_id, status, and extracted data
        """
        try:
            # Validate required parameters for AI extraction
            if ai_extraction and not user_prompt:
                return json.dumps({"error": "user_prompt is required when ai_extraction=True"})

            # Validate URL format
            if not url.strip():
                return json.dumps({"error": "URL cannot be empty"})
            if not (url.startswith("http://") or url.startswith("https://")):
                return json.dumps({"error": "Invalid URL - must start with http:// or https://"})

            # Validate steps
            if not steps:
                return json.dumps({"error": "Steps cannot be empty"})
            if any(not step.strip() for step in steps):
                return json.dumps({"error": "All steps must contain valid instructions"})

            # Prepare parameters for the API call
            params = {"url": url, "steps": steps, "use_session": use_session, "ai_extraction": ai_extraction}

            # Add optional parameters only if they are provided
            if user_prompt:
                params["user_prompt"] = user_prompt
            if output_schema:
                params["output_schema"] = output_schema

            # Call the agentic scraper API
            response = self.client.agenticscraper(**params)

            return json.dumps(response, indent=2)

        except Exception as e:
            return json.dumps({"error": str(e)})

    def searchscraper(self, prompt: str) -> str:
        """Search the web and extract information from the web.
        Args:
            prompt (str): Search query
        Returns:
            JSON of the search results
        """
        try:
            response = self.client.searchscraper(user_prompt=prompt)
            if hasattr(response, "result"):
                return json.dumps(response.result)
            elif isinstance(response, dict) and "result" in response:
                return json.dumps(response["result"])
            else:
                return json.dumps(response)
        except Exception as e:
            return json.dumps({"error": str(e)})
