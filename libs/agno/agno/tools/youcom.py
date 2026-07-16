import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Union

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

DEFAULT_BASE_URL = "https://ydc-index.io"


class YouTools(Toolkit):
    """
    YouTools exposes the You.com Search API as a first-class Agno tool.

    Get an API key at https://you.com/platform/api-keys and set ``YDC_API_KEY``.

    Tip: You.com also hosts a free MCP profile at
    ``https://api.you.com/mcp?profile=free`` (``you-search`` with 100 queries/day,
    no API key required). To use it instead, point Agno's ``MCPTools`` at that URL.

    Args:
        api_key (Optional[str]): You.com API key. Falls back to the ``YDC_API_KEY`` env var.
        base_url (Optional[str]): Override the API base URL. Falls back to the ``YDC_BASE_URL``
            env var, then defaults to ``https://ydc-index.io``.
        num_results (int): Default number of search results. Default is 5.
        livecrawl (Optional[str]): Live-crawl mode for the search API (``"web"``, ``"news"``,
            ``"all"``). Default is ``None`` (off).
        livecrawl_formats (Union[str, List[str]]): Content formats to request from livecrawl
            (e.g. ``"markdown"``, ``"html"``, or ``["markdown", "html"]``). Default is ``"markdown"``.
        text_length_limit (int): Max length of text content per result. Default is 1000.
        include_domains (Optional[List[str]]): Restrict results to these domains. Cannot be combined
            with exclude_domains or boost_domains.
        exclude_domains (Optional[List[str]]): Exclude results from these domains.
        country (Optional[str]): The country code that determines the geographical focus of the web results.
        freshness (Optional[str]): Specifies the freshness of the results to return (e.g. ``"day"``, ``"week"``, ``"month"``, ``"year"``).
        language (Optional[str]): The language of the web results that will be returned (BCP 47 format).
        safesearch (Optional[str]): Configures the safesearch filter for content moderation (``"off"``, ``"moderate"``, ``"strict"``).
        offset (Optional[int]): Indicates the offset for pagination, in multiples of the result count.
            Must be between 0 and 9.
        boost_domains (Optional[List[str]]): Domains to boost in search ranking (results are not limited
            to them). Cannot be combined with include_domains.
        crawl_timeout (int): Maximum time in seconds to wait for page content when livecrawl is set.
            Must be between 1 and 60 seconds. Default is 10.
        search_params (Optional[Dict[str, Any]]): Additional query parameters merged into the search
            request, overriding the arguments above. Lets you pass You.com params not exposed here.
        timeout (int): Maximum time in seconds to wait for API responses. Default is 30.
        format (str): Output format for search results (``"json"`` or ``"markdown"``).
            Default is ``"json"``.
        show_results (bool): Log responses for debugging. Default is False.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        num_results: int = 5,
        livecrawl: Optional[Literal["web", "news", "all"]] = None,
        livecrawl_formats: Union[str, List[str]] = "markdown",
        text_length_limit: int = 1000,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        country: Optional[str] = None,
        freshness: Optional[str] = None,
        language: Optional[str] = None,
        safesearch: Optional[str] = None,
        offset: Optional[int] = None,
        boost_domains: Optional[List[str]] = None,
        crawl_timeout: int = 10,
        search_params: Optional[Dict[str, Any]] = None,
        timeout: int = 30,
        format: Literal["json", "markdown"] = "json",
        show_results: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or getenv("YDC_API_KEY")
        if not self.api_key:
            log_error("YDC_API_KEY not set. Please set the YDC_API_KEY environment variable.")

        if not (1 <= crawl_timeout <= 60):
            raise ValueError("crawl_timeout must be between 1 and 60 seconds")

        if offset is not None and not (0 <= offset <= 9):
            raise ValueError("offset must be between 0 and 9")

        # You.com 422s include+exclude, and accepts include+boost only intermittently; reject both up front.
        if include_domains and (exclude_domains or boost_domains):
            raise ValueError("include_domains cannot be combined with exclude_domains or boost_domains")

        self.base_url: str = (base_url or getenv("YDC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.num_results: int = num_results
        self.livecrawl: Optional[str] = livecrawl
        self.livecrawl_formats: Union[str, List[str]] = livecrawl_formats
        self.text_length_limit: int = text_length_limit
        self.include_domains: Optional[List[str]] = include_domains
        self.exclude_domains: Optional[List[str]] = exclude_domains
        self.country: Optional[str] = country
        self.freshness: Optional[str] = freshness
        self.language: Optional[str] = language
        self.safesearch: Optional[str] = safesearch
        self.offset: Optional[int] = offset
        self.boost_domains: Optional[List[str]] = boost_domains
        self.crawl_timeout: int = crawl_timeout
        self.search_params: Optional[Dict[str, Any]] = search_params
        self.timeout: int = timeout
        self.format: Literal["json", "markdown"] = format
        self.show_results: bool = show_results

        super().__init__(name="youcom", tools=[self.you_search], **kwargs)

    def _headers(self) -> Dict[str, str]:
        return {"X-API-Key": self.api_key or "", "Accept": "application/json"}

    def _truncate(self, text: Optional[str]) -> Optional[str]:
        if text is None:
            return None
        if self.text_length_limit and len(text) > self.text_length_limit:
            return text[: self.text_length_limit]
        return text

    def you_search(self, query: str, num_results: Optional[int] = None) -> str:
        """Search the web using the You.com Search API.

        Args:
            query (str): The search query.
            num_results (Optional[int]): Override the configured result count.

        Returns:
            str: Search results formatted as JSON or markdown.
        """
        try:
            if self.show_results:
                log_info(f"Searching You.com for: {query}")

            params: Dict[str, Any] = {
                "query": query,
                "count": num_results or self.num_results,
            }
            # livecrawl is off unless set; its formats/timeout only apply when it is on.
            if self.livecrawl:
                params["livecrawl"] = self.livecrawl
                params["crawl_timeout"] = self.crawl_timeout
                if isinstance(self.livecrawl_formats, str):
                    params["livecrawl_formats"] = [f.strip() for f in self.livecrawl_formats.split(",") if f.strip()]
                else:
                    params["livecrawl_formats"] = self.livecrawl_formats

            if self.include_domains:
                params["include_domains"] = ",".join(self.include_domains)
            if self.exclude_domains:
                params["exclude_domains"] = ",".join(self.exclude_domains)
            if self.country:
                params["country"] = self.country
            if self.freshness:
                params["freshness"] = self.freshness
            if self.language:
                params["language"] = self.language
            if self.safesearch:
                params["safesearch"] = self.safesearch
            if self.offset is not None:
                params["offset"] = self.offset
            if self.boost_domains:
                params["boost_domains"] = ",".join(self.boost_domains)
            if self.search_params:
                params.update(self.search_params)

            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(f"{self.base_url}/v1/search", headers=self._headers(), params=params)
            response.raise_for_status()
            data = response.json()
            return self._format_results(query, data)
        except httpx.HTTPError as e:
            log_error(f"You.com search request failed: {e}")
            return f"Error: {e}"
        except Exception as e:
            logger.exception("Failed to run You.com search")
            return f"Error: {e}"

    def _format_results(self, query: str, data: Dict[str, Any]) -> str:
        results = data.get("results")
        # Results are grouped by source (web/news); flatten them into a single list.
        if isinstance(results, dict):
            raw_results = [r for section in results.values() if isinstance(section, list) for r in section]
        else:
            raw_results = results or data.get("hits") or []
        cleaned: List[Dict[str, Any]] = []
        for r in raw_results:
            if not isinstance(r, dict):
                continue
            entry: Dict[str, Any] = {}
            if r.get("url"):
                entry["url"] = r["url"]
            if r.get("title"):
                entry["title"] = r["title"]
            snippet = r.get("description") or r.get("snippet")
            if snippet:
                entry["snippet"] = snippet
            # Body text comes from livecrawled "contents", else the "snippets" list.
            contents = r.get("contents")
            if not isinstance(contents, dict):
                contents = r
            text = contents.get("markdown") or contents.get("text") or contents.get("html") or contents.get("content")
            if not text and isinstance(r.get("snippets"), list):
                text = "\n".join(s for s in r["snippets"] if isinstance(s, str)) or None
            if text:
                entry["text"] = self._truncate(text)
            published_date = r.get("published_date") or r.get("page_age")
            if published_date:
                entry["published_date"] = published_date
            cleaned.append(entry)

        if self.format == "markdown":
            lines = [f"# Results for: {query}\n"]
            for r in cleaned:
                title = r.get("title") or r.get("url") or "Untitled"
                url = r.get("url", "")
                lines.append(f"## [{title}]({url})")
                if r.get("snippet"):
                    lines.append(r["snippet"])
                if r.get("text"):
                    lines.append(r["text"])
                lines.append("")
            output = "\n".join(lines)
            if self.show_results:
                log_info(output)
            return output

        output = json.dumps(cleaned, indent=4, ensure_ascii=False)
        if self.show_results:
            log_info(output)
        return output
