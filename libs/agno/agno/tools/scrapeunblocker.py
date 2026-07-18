import json
from os import getenv
from typing import Any, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


class ScrapeUnblockerTools(Toolkit):
    """Tools for scraping web pages through the ScrapeUnblocker API.

    ScrapeUnblocker renders pages in a real browser behind anti-bot protections
    (Cloudflare, DataDome, PerimeterX, Akamai) and returns raw HTML, AI-parsed
    structured JSON, or Google search results.

    Args:
        api_key (Optional[str]): ScrapeUnblocker API key. Falls back to the
            SCRAPEUNBLOCKER_API_KEY environment variable.
        proxy_country (Optional[str]): Two-letter country code for the exit IP,
            for geo-restricted or localised content (e.g. "us", "de").
        parsed_data (bool): Return AI-parsed structured JSON instead of raw HTML.
        max_length (Optional[int]): Truncate returned page content to this many
            characters. Defaults to 20000 to keep responses within model context.
        base_url (str): API base URL. Override to target a different environment.
        timeout (int): HTTP timeout in seconds. Defaults to 180.
        enable_scrape_website (bool): Register the scrape_website tool.
        enable_search_google (bool): Register the search_google tool.
        all (bool): Register every tool regardless of the individual flags.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        proxy_country: Optional[str] = None,
        parsed_data: bool = False,
        max_length: Optional[int] = 20000,
        base_url: str = "https://api.scrapeunblocker.com",
        timeout: int = 180,
        enable_scrape_website: bool = True,
        enable_search_google: bool = True,
        all: bool = False,
        **kwargs: Any,
    ):
        resolved_key = api_key or getenv("SCRAPEUNBLOCKER_API_KEY")
        if not resolved_key:
            log_error("SCRAPEUNBLOCKER_API_KEY not set. Please set the SCRAPEUNBLOCKER_API_KEY environment variable.")
            raise ValueError("SCRAPEUNBLOCKER_API_KEY not set.")
        self.api_key: str = resolved_key

        self.proxy_country = proxy_country
        self.parsed_data = parsed_data
        self.max_length = max_length
        self.base_url = base_url.rstrip("/")

        tools: List[Any] = []
        if all or enable_scrape_website:
            tools.append(self.scrape_website)
        if all or enable_search_google:
            tools.append(self.search_google)

        super().__init__(name="scrapeunblocker_tools", tools=tools, timeout=timeout, **kwargs)

    def _post(self, path: str, params: dict) -> httpx.Response:
        """Call the ScrapeUnblocker API. Empty values are dropped so the API applies its own defaults."""
        response = httpx.post(
            f"{self.base_url}{path}",
            params={k: v for k, v in params.items() if v is not None and v is not False},
            headers={"X-ScrapeUnblocker-Key": self.api_key},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response

    def scrape_website(self, url: str, parsed_data: Optional[bool] = None) -> str:
        """Scrape a web page and return its contents, bypassing anti-bot protection.

        Use this for any page that a plain HTTP request cannot reach, such as
        e-commerce listings, travel sites or marketplaces behind bot detection.

        Args:
            url (str): The full URL of the page to scrape, including the scheme.
            parsed_data (Optional[bool]): Return AI-parsed structured JSON instead
                of raw HTML. Defaults to the value set on the toolkit.

        Returns:
            str: The page HTML, or parsed JSON when parsed_data is enabled.
        """
        if not url:
            return "Error: url is required."

        use_parsed = self.parsed_data if parsed_data is None else parsed_data
        log_debug(f"Scraping {url} (parsed_data={use_parsed})")

        try:
            response = self._post(
                "/getPageSource",
                {"url": url, "parsed_data": use_parsed, "proxy_country": self.proxy_country},
            )
        except Exception as e:
            log_error(f"Failed to scrape {url}: {e}")
            return f"Error scraping {url}: {e}"

        if use_parsed:
            try:
                content = json.dumps(response.json())
            except Exception:
                content = response.text
        else:
            content = response.text

        if self.max_length is not None and len(content) > self.max_length:
            content = content[: self.max_length]
        return content

    def search_google(self, keyword: str, pages_to_check: int = 1) -> str:
        """Search Google for a keyword and return the organic and ad results.

        Args:
            keyword (str): The search term to look up.
            pages_to_check (int): How many result pages to scrape. Defaults to 1.

        Returns:
            str: JSON with the search results, or an error message.
        """
        if not keyword:
            return "Error: keyword is required."

        log_debug(f"Searching Google for '{keyword}' ({pages_to_check} page(s))")

        try:
            response = self._post(
                "/serpApi",
                {
                    "keyword": keyword,
                    "pages_to_check": pages_to_check,
                    "proxy_country": self.proxy_country,
                },
            )
        except Exception as e:
            log_error(f"Failed to search for '{keyword}': {e}")
            return f"Error searching for '{keyword}': {e}"

        try:
            return json.dumps(response.json())
        except Exception:
            return response.text
