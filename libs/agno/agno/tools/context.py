from os import getenv
from typing import Any, Dict, List, Literal, Optional, Tuple

from agno.tools import Toolkit
from agno.tools.context_client import ContextClient
from agno.utils.log import log_error


class ContextTools(Toolkit):
    """Toolkit for live web data and brand intelligence from Context.dev.

    Args:
        api_key: Context.dev API key. Falls back to CONTEXT_API_KEY.
        base_url: Context.dev API base URL.
        timeout: HTTP timeout in seconds.
        enable_search: Enable live web search. Default is True.
        enable_scrape: Enable single-page Markdown scraping. Default is True.
        enable_crawl: Enable multi-page website crawling. Default is False.
        enable_sitemap: Enable website URL discovery. Default is False.
        enable_extract: Enable structured website extraction. Default is False.
        enable_brand: Enable brand profile retrieval. Default is False.
        all: Enable every Context.dev tool. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "https://api.context.dev/v1",
        timeout: int = 120,
        enable_search: bool = True,
        enable_scrape: bool = True,
        enable_crawl: bool = False,
        enable_sitemap: bool = False,
        enable_extract: bool = False,
        enable_brand: bool = False,
        all: bool = False,
        **kwargs: Any,
    ) -> None:
        self.api_key = api_key or getenv("CONTEXT_API_KEY")
        if not self.api_key:
            log_error("CONTEXT_API_KEY not set. Please set the CONTEXT_API_KEY environment variable.")

        self.client = ContextClient(
            api_key=self.api_key,
            base_url=base_url,
            timeout=timeout,
        )

        available_tools = [
            (enable_search, self.search_web, self.asearch_web, "search_web"),
            (enable_scrape, self.scrape_url, self.ascrape_url, "scrape_url"),
            (enable_crawl, self.crawl_website, self.acrawl_website, "crawl_website"),
            (enable_sitemap, self.find_website_pages, self.afind_website_pages, "find_website_pages"),
            (enable_extract, self.extract_structured_data, self.aextract_structured_data, "extract_structured_data"),
            (enable_brand, self.get_brand_profile, self.aget_brand_profile, "get_brand_profile"),
        ]
        tools: List[Any] = [sync_tool for enabled, sync_tool, _, _ in available_tools if all or enabled]
        async_tools: List[Tuple[Any, str]] = [
            (async_tool, name) for enabled, _, async_tool, name in available_tools if all or enabled
        ]

        super().__init__(
            name="context_tools",
            tools=tools,
            async_tools=async_tools,
            timeout=timeout,
            **kwargs,
        )

    def search_web(
        self,
        query: str,
        num_results: int = 10,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        freshness: Optional[Literal["last_24_hours", "last_week", "last_month", "last_year"]] = None,
        country: Optional[str] = None,
        include_markdown: bool = False,
    ) -> str:
        """Search the live web and return ranked results.

        Args:
            query: Natural-language search query.
            num_results: Number of results to return, from 10 to 100.
            include_domains: Optional domains to restrict the search to.
            exclude_domains: Optional domains to exclude from the search.
            freshness: Optional result recency filter.
            country: Optional two-letter country code for regional results.
            include_markdown: Include page Markdown with each result.

        Returns:
            JSON string containing ranked search results.
        """
        return self.client.post(
            "/web/search",
            _search_payload(
                query=query,
                num_results=num_results,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                freshness=freshness,
                country=country,
                include_markdown=include_markdown,
            ),
        )

    async def asearch_web(
        self,
        query: str,
        num_results: int = 10,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        freshness: Optional[Literal["last_24_hours", "last_week", "last_month", "last_year"]] = None,
        country: Optional[str] = None,
        include_markdown: bool = False,
    ) -> str:
        """Search the live web asynchronously and return ranked results.

        Args:
            query: Natural-language search query.
            num_results: Number of results to return, from 10 to 100.
            include_domains: Optional domains to restrict the search to.
            exclude_domains: Optional domains to exclude from the search.
            freshness: Optional result recency filter.
            country: Optional two-letter country code for regional results.
            include_markdown: Include page Markdown with each result.

        Returns:
            JSON string containing ranked search results.
        """
        return await self.client.apost(
            "/web/search",
            _search_payload(
                query=query,
                num_results=num_results,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
                freshness=freshness,
                country=country,
                include_markdown=include_markdown,
            ),
        )

    def scrape_url(
        self,
        url: str,
        use_main_content_only: bool = True,
        include_links: bool = True,
        include_images: bool = False,
        max_age_ms: int = 86400000,
    ) -> str:
        """Scrape one webpage and return clean Markdown.

        Args:
            url: Full HTTP or HTTPS URL to scrape.
            use_main_content_only: Remove navigation, headers, footers, and sidebars.
            include_links: Keep hyperlinks in the Markdown output.
            include_images: Keep image references in the Markdown output.
            max_age_ms: Maximum cache age in milliseconds. Use 0 for a fresh fetch.

        Returns:
            JSON string containing Markdown and page metadata.
        """
        return self.client.get(
            "/web/scrape/markdown",
            _scrape_params(
                url=url,
                use_main_content_only=use_main_content_only,
                include_links=include_links,
                include_images=include_images,
                max_age_ms=max_age_ms,
            ),
        )

    async def ascrape_url(
        self,
        url: str,
        use_main_content_only: bool = True,
        include_links: bool = True,
        include_images: bool = False,
        max_age_ms: int = 86400000,
    ) -> str:
        """Scrape one webpage asynchronously and return clean Markdown.

        Args:
            url: Full HTTP or HTTPS URL to scrape.
            use_main_content_only: Remove navigation, headers, footers, and sidebars.
            include_links: Keep hyperlinks in the Markdown output.
            include_images: Keep image references in the Markdown output.
            max_age_ms: Maximum cache age in milliseconds. Use 0 for a fresh fetch.

        Returns:
            JSON string containing Markdown and page metadata.
        """
        return await self.client.aget(
            "/web/scrape/markdown",
            _scrape_params(
                url=url,
                use_main_content_only=use_main_content_only,
                include_links=include_links,
                include_images=include_images,
                max_age_ms=max_age_ms,
            ),
        )

    def crawl_website(
        self,
        url: str,
        max_pages: int = 25,
        max_depth: Optional[int] = None,
        url_regex: Optional[str] = None,
        follow_subdomains: bool = False,
    ) -> str:
        """Crawl linked pages from a website and return their Markdown.

        Args:
            url: Full HTTP or HTTPS URL where the crawl should begin.
            max_pages: Maximum number of pages to crawl, from 1 to 500.
            max_depth: Optional maximum link depth from the starting URL.
            url_regex: Optional RE2-compatible pattern used to keep matching URLs.
            follow_subdomains: Allow the crawler to follow subdomains.

        Returns:
            JSON string containing crawled pages and crawl metadata.
        """
        return self.client.post(
            "/web/crawl",
            _crawl_payload(
                url=url,
                max_pages=max_pages,
                max_depth=max_depth,
                url_regex=url_regex,
                follow_subdomains=follow_subdomains,
            ),
        )

    async def acrawl_website(
        self,
        url: str,
        max_pages: int = 25,
        max_depth: Optional[int] = None,
        url_regex: Optional[str] = None,
        follow_subdomains: bool = False,
    ) -> str:
        """Crawl linked pages asynchronously and return their Markdown.

        Args:
            url: Full HTTP or HTTPS URL where the crawl should begin.
            max_pages: Maximum number of pages to crawl, from 1 to 500.
            max_depth: Optional maximum link depth from the starting URL.
            url_regex: Optional RE2-compatible pattern used to keep matching URLs.
            follow_subdomains: Allow the crawler to follow subdomains.

        Returns:
            JSON string containing crawled pages and crawl metadata.
        """
        return await self.client.apost(
            "/web/crawl",
            _crawl_payload(
                url=url,
                max_pages=max_pages,
                max_depth=max_depth,
                url_regex=url_regex,
                follow_subdomains=follow_subdomains,
            ),
        )

    def find_website_pages(
        self,
        domain: str,
        search: Optional[str] = None,
        max_links: int = 100,
        sitemap_url: Optional[str] = None,
        url_regex: Optional[str] = None,
    ) -> str:
        """Discover URLs from a website sitemap without downloading content.

        Args:
            domain: Website domain to inspect, such as context.dev.
            search: Optional topic used to rank relevant URLs.
            max_links: Maximum number of URLs to return.
            sitemap_url: Optional sitemap URL to use instead of discovery.
            url_regex: Optional RE2-compatible pattern used to keep matching URLs.

        Returns:
            JSON string containing discovered page URLs.
        """
        return self.client.get(
            "/web/scrape/sitemap",
            _sitemap_params(
                domain=domain,
                search=search,
                max_links=max_links,
                sitemap_url=sitemap_url,
                url_regex=url_regex,
            ),
        )

    async def afind_website_pages(
        self,
        domain: str,
        search: Optional[str] = None,
        max_links: int = 100,
        sitemap_url: Optional[str] = None,
        url_regex: Optional[str] = None,
    ) -> str:
        """Discover website URLs asynchronously without downloading content.

        Args:
            domain: Website domain to inspect, such as context.dev.
            search: Optional topic used to rank relevant URLs.
            max_links: Maximum number of URLs to return.
            sitemap_url: Optional sitemap URL to use instead of discovery.
            url_regex: Optional RE2-compatible pattern used to keep matching URLs.

        Returns:
            JSON string containing discovered page URLs.
        """
        return await self.client.aget(
            "/web/scrape/sitemap",
            _sitemap_params(
                domain=domain,
                search=search,
                max_links=max_links,
                sitemap_url=sitemap_url,
                url_regex=url_regex,
            ),
        )

    def extract_structured_data(
        self,
        url: str,
        schema: Dict[str, Any],
        instructions: Optional[str] = None,
        max_pages: int = 5,
        max_depth: Optional[int] = None,
        follow_subdomains: bool = False,
        fact_check: bool = False,
    ) -> str:
        """Extract website data into a caller-provided JSON Schema.

        Args:
            url: Full HTTP or HTTPS URL where extraction should begin.
            schema: JSON Schema describing the data to return.
            instructions: Optional extraction guidance in plain language.
            max_pages: Maximum number of pages to analyze, from 1 to 50.
            max_depth: Optional maximum link depth from the starting URL.
            follow_subdomains: Allow extraction to follow subdomains.
            fact_check: Validate extracted values against analyzed pages.

        Returns:
            JSON string containing structured data and source metadata.
        """
        return self.client.post(
            "/web/extract",
            _extract_payload(
                url=url,
                schema=schema,
                instructions=instructions,
                max_pages=max_pages,
                max_depth=max_depth,
                follow_subdomains=follow_subdomains,
                fact_check=fact_check,
            ),
        )

    async def aextract_structured_data(
        self,
        url: str,
        schema: Dict[str, Any],
        instructions: Optional[str] = None,
        max_pages: int = 5,
        max_depth: Optional[int] = None,
        follow_subdomains: bool = False,
        fact_check: bool = False,
    ) -> str:
        """Extract website data asynchronously into a JSON Schema.

        Args:
            url: Full HTTP or HTTPS URL where extraction should begin.
            schema: JSON Schema describing the data to return.
            instructions: Optional extraction guidance in plain language.
            max_pages: Maximum number of pages to analyze, from 1 to 50.
            max_depth: Optional maximum link depth from the starting URL.
            follow_subdomains: Allow extraction to follow subdomains.
            fact_check: Validate extracted values against analyzed pages.

        Returns:
            JSON string containing structured data and source metadata.
        """
        return await self.client.apost(
            "/web/extract",
            _extract_payload(
                url=url,
                schema=schema,
                instructions=instructions,
                max_pages=max_pages,
                max_depth=max_depth,
                follow_subdomains=follow_subdomains,
                fact_check=fact_check,
            ),
        )

    def get_brand_profile(
        self,
        domain: str,
        maximum_speed: bool = False,
        max_age_ms: int = 7776000000,
    ) -> str:
        """Retrieve a company profile with logos, colors, and business details.

        Args:
            domain: Company website domain, such as stripe.com.
            maximum_speed: Skip slower enrichment for a faster response.
            max_age_ms: Maximum cache age in milliseconds.

        Returns:
            JSON string containing the company's brand profile.
        """
        return self.client.post(
            "/brand/retrieve",
            _brand_payload(
                domain=domain,
                maximum_speed=maximum_speed,
                max_age_ms=max_age_ms,
            ),
        )

    async def aget_brand_profile(
        self,
        domain: str,
        maximum_speed: bool = False,
        max_age_ms: int = 7776000000,
    ) -> str:
        """Retrieve a company brand profile asynchronously.

        Args:
            domain: Company website domain, such as stripe.com.
            maximum_speed: Skip slower enrichment for a faster response.
            max_age_ms: Maximum cache age in milliseconds.

        Returns:
            JSON string containing the company's brand profile.
        """
        return await self.client.apost(
            "/brand/retrieve",
            _brand_payload(
                domain=domain,
                maximum_speed=maximum_speed,
                max_age_ms=max_age_ms,
            ),
        )


def _search_payload(
    query: str,
    num_results: int,
    include_domains: Optional[List[str]],
    exclude_domains: Optional[List[str]],
    freshness: Optional[str],
    country: Optional[str],
    include_markdown: bool,
) -> Dict[str, Any]:
    return _without_none(
        {
            "query": query,
            "numResults": num_results,
            "includeDomains": include_domains,
            "excludeDomains": exclude_domains,
            "freshness": freshness,
            "country": country,
            "markdownOptions": {
                "enabled": include_markdown,
                "useMainContentOnly": True,
                "includeLinks": True,
                "includeImages": False,
            },
        }
    )


def _scrape_params(
    url: str,
    use_main_content_only: bool,
    include_links: bool,
    include_images: bool,
    max_age_ms: int,
) -> Dict[str, Any]:
    return {
        "url": url,
        "useMainContentOnly": use_main_content_only,
        "includeLinks": include_links,
        "includeImages": include_images,
        "maxAgeMs": max_age_ms,
    }


def _crawl_payload(
    url: str,
    max_pages: int,
    max_depth: Optional[int],
    url_regex: Optional[str],
    follow_subdomains: bool,
) -> Dict[str, Any]:
    return _without_none(
        {
            "url": url,
            "maxPages": max_pages,
            "maxDepth": max_depth,
            "urlRegex": url_regex,
            "followSubdomains": follow_subdomains,
            "useMainContentOnly": True,
            "includeLinks": True,
            "includeImages": False,
        }
    )


def _sitemap_params(
    domain: str,
    search: Optional[str],
    max_links: int,
    sitemap_url: Optional[str],
    url_regex: Optional[str],
) -> Dict[str, Any]:
    return _without_none(
        {
            "domain": domain,
            "search": search,
            "maxLinks": max_links,
            "sitemapUrl": sitemap_url,
            "urlRegex": url_regex,
        }
    )


def _extract_payload(
    url: str,
    schema: Dict[str, Any],
    instructions: Optional[str],
    max_pages: int,
    max_depth: Optional[int],
    follow_subdomains: bool,
    fact_check: bool,
) -> Dict[str, Any]:
    return _without_none(
        {
            "url": url,
            "schema": schema,
            "instructions": instructions,
            "maxPages": max_pages,
            "maxDepth": max_depth,
            "followSubdomains": follow_subdomains,
            "factCheck": fact_check,
        }
    )


def _brand_payload(domain: str, maximum_speed: bool, max_age_ms: int) -> Dict[str, Any]:
    return {
        "type": "by_domain",
        "domain": domain,
        "maxSpeed": maximum_speed,
        "maxAgeMs": max_age_ms,
    }


def _without_none(values: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
