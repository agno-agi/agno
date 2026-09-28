import json
from os import getenv
from typing import Any, Dict, List, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error, logger

try:
    import httpx
except ImportError:
    raise ImportError("`httpx` not installed. Please install using `pip install httpx`")


class AnakinTools(Toolkit):
    """
    Anakin (anakin.io) is a managed web scraping and automation API, providing
    single-URL scraping, multi-page crawling, site mapping, and web search.

    Args:
        api_key (Optional[str]): Anakin API key. Retrieved from `ANAKIN_API_KEY` env variable if not provided.
        enable_scrape (bool): Enable single-URL scraping. Default is True.
        enable_crawl (bool): Enable multi-page crawling. Default is False.
        enable_map (bool): Enable site URL discovery/mapping. Default is False.
        enable_search (bool): Enable web search. Default is False.
        all (bool): Enable all tools. Overrides individual flags when True. Default is False.
        country (str): Default two-letter proxy egress country code for scrape/crawl. Default is "us".
        api_base_url (str): Base URL for the Anakin API. Default is "https://api.anakin.io/v1".
        timeout (int): Timeout in seconds for API requests. Default is 60.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_scrape: bool = True,
        enable_crawl: bool = False,
        enable_map: bool = False,
        enable_search: bool = False,
        all: bool = False,
        country: str = "us",
        api_base_url: str = "https://api.anakin.io/v1",
        timeout: int = 60,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("ANAKIN_API_KEY")
        if not self.api_key:
            log_error("ANAKIN_API_KEY not set. Please set the ANAKIN_API_KEY environment variable.")

        self.api_base_url: str = api_base_url
        self.country: str = country
        self.timeout: int = timeout

        tools: List[Any] = []
        if all or enable_scrape:
            tools.append(self.scrape_url)
        if all or enable_crawl:
            tools.append(self.crawl_website)
        if all or enable_map:
            tools.append(self.map_website)
        if all or enable_search:
            tools.append(self.search_web)

        super().__init__(name="anakin_tools", tools=tools, **kwargs)

    def _request(self, method: str, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = {k: v for k, v in payload.items() if v is not None}
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        response = httpx.request(
            method, f"{self.api_base_url}{path}", json=payload, headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        return response.json()

    def scrape_url(
        self,
        url: str,
        generate_json: bool = False,
        use_browser: bool = False,
        force_fresh: bool = False,
        country: Optional[str] = None,
    ) -> str:
        """Use this function to scrape a single URL using Anakin.

        Args:
            url (str): The URL to scrape.
            generate_json (bool): Also extract structured JSON from the page with AI. Defaults to False.
            use_browser (bool): Render with a stealth headless browser, for SPAs and JS-heavy pages. Defaults to False.
            force_fresh (bool): Skip the cache and refetch. Defaults to False.
            country (Optional[str]): Two-letter proxy egress country code. Defaults to the toolkit's country.

        Returns:
            str: JSON string with the scraped markdown (and structured data if requested).
        """
        if not self.api_key:
            return "Error: ANAKIN_API_KEY not set"
        try:
            payload = {
                "url": url,
                "generateJson": generate_json,
                "useBrowser": use_browser,
                "forceFresh": force_fresh,
                "country": country or self.country,
            }
            result = self._request("POST", "/scrape", payload)
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.exception("Anakin scrape request failed")
            return f"Error scraping {url}: {e.response.status_code} {e.response.text}"
        except Exception as e:
            logger.exception("Anakin scrape request failed")
            return f"Error scraping {url}: {e}"

    def crawl_website(
        self,
        url: str,
        max_pages: int = 10,
        depth: int = 1,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
        use_browser: bool = False,
        country: Optional[str] = None,
    ) -> str:
        """Use this function to crawl a website using Anakin, fetching markdown for every page reached.

        Args:
            url (str): The starting URL to crawl from.
            max_pages (int): Maximum number of pages to fetch. Defaults to 10.
            depth (int): Link-hops from the starting URL to follow. Defaults to 1.
            include_patterns (Optional[List[str]]): Only fetch URLs matching one of these glob/regex patterns.
            exclude_patterns (Optional[List[str]]): Skip URLs matching any of these glob/regex patterns.
            use_browser (bool): Render each page with a headless browser, for SPAs. Defaults to False.
            country (Optional[str]): Two-letter proxy egress country code. Defaults to the toolkit's country.

        Returns:
            str: JSON string with the crawled pages.
        """
        if not self.api_key:
            return "Error: ANAKIN_API_KEY not set"
        try:
            payload = {
                "url": url,
                "maxPages": max_pages,
                "depth": depth,
                "includePatterns": include_patterns,
                "excludePatterns": exclude_patterns,
                "useBrowser": use_browser,
                "country": country or self.country,
            }
            result = self._request("POST", "/crawl", payload)
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.exception("Anakin crawl request failed")
            return f"Error crawling {url}: {e.response.status_code} {e.response.text}"
        except Exception as e:
            logger.exception("Anakin crawl request failed")
            return f"Error crawling {url}: {e}"

    def map_website(
        self,
        url: str,
        limit: int = 100,
        depth: int = 2,
        limit_per_level: int = 100,
        include_external_links: bool = False,
        include_subdomains: bool = False,
        search: Optional[str] = None,
        use_browser: bool = False,
    ) -> str:
        """Use this function to discover URLs reachable from a starting URL using Anakin.

        Args:
            url (str): The starting URL for discovery, typically a homepage or section root.
            limit (int): Maximum number of URLs to return overall. Defaults to 100.
            depth (int): Link-hops from the starting URL to follow. Defaults to 2.
            limit_per_level (int): Maximum URLs collected per depth level. Defaults to 100.
            include_external_links (bool): Also collect (but do not follow) external links. Defaults to False.
            include_subdomains (bool): Include URLs on subdomains of the starting host. Defaults to False.
            search (Optional[str]): Only return URLs whose path/title matches this keyword.
            use_browser (bool): Render with a headless browser, for SPAs. Defaults to False.

        Returns:
            str: JSON string with the discovered links.
        """
        if not self.api_key:
            return "Error: ANAKIN_API_KEY not set"
        try:
            payload = {
                "url": url,
                "limit": limit,
                "depth": depth,
                "limitPerLevel": limit_per_level,
                "includeExternalLinks": include_external_links,
                "includeSubdomains": include_subdomains,
                "search": search,
                "useBrowser": use_browser,
            }
            result = self._request("POST", "/map", payload)
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.exception("Anakin map request failed")
            return f"Error mapping {url}: {e.response.status_code} {e.response.text}"
        except Exception as e:
            logger.exception("Anakin map request failed")
            return f"Error mapping {url}: {e}"

    def search_web(self, query: str, limit: int = 5) -> str:
        """Use this function to search the web using Anakin, returning result URLs, titles and snippets.

        Args:
            query (str): The search query, in natural language.
            limit (int): Maximum number of results to return. Defaults to 5.

        Returns:
            str: JSON string with the search results.
        """
        if not self.api_key:
            return "Error: ANAKIN_API_KEY not set"
        try:
            payload = {"prompt": query, "limit": limit}
            result = self._request("POST", "/search", payload)
            return json.dumps(result)
        except httpx.HTTPStatusError as e:
            logger.exception("Anakin search request failed")
            return f"Error searching for {query}: {e.response.status_code} {e.response.text}"
        except Exception as e:
            logger.exception("Anakin search request failed")
            return f"Error searching for {query}: {e}"
