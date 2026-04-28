import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_error, log_info, logger

DEFAULT_BASE_URL = "https://api.you.com"


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
            env var, then defaults to ``https://api.you.com``.
        num_results (int): Default number of search results. Default is 5.
        livecrawl (str): Live-crawl mode for the search API (``"web"``, ``"always"``,
            ``"fallback"``, ``"never"``). Default is ``"web"``.
        livecrawl_formats (str): Comma-separated content formats to request from livecrawl
            (e.g. ``"markdown"``, ``"text"``). Default is ``"markdown"``.
        text_length_limit (int): Max length of text content per result. Default is 1000.
        include_domains (Optional[List[str]]): Restrict results to these domains.
        exclude_domains (Optional[List[str]]): Exclude results from these domains.
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
        livecrawl: Literal["always", "fallback", "never", "web"] = "web",
        livecrawl_formats: str = "markdown",
        text_length_limit: int = 1000,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
        timeout: int = 30,
        format: Literal["json", "markdown"] = "json",
        show_results: bool = False,
        **kwargs: Any,
    ):
        self.api_key = api_key or getenv("YDC_API_KEY")
        if not self.api_key:
            log_error("YDC_API_KEY not set. Please set the YDC_API_KEY environment variable.")

        self.base_url: str = (base_url or getenv("YDC_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.num_results: int = num_results
        self.livecrawl: str = livecrawl
        self.livecrawl_formats: str = livecrawl_formats
        self.text_length_limit: int = text_length_limit
        self.include_domains: Optional[List[str]] = include_domains
        self.exclude_domains: Optional[List[str]] = exclude_domains
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
                "livecrawl": self.livecrawl,
                "livecrawl_formats": self.livecrawl_formats,
            }
            if self.include_domains:
                params["include_domains"] = ",".join(self.include_domains)
            if self.exclude_domains:
                params["exclude_domains"] = ",".join(self.exclude_domains)

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
        raw_results = data.get("results") or data.get("hits") or []
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
            text = r.get("markdown") or r.get("text") or r.get("content")
            if text:
                entry["text"] = self._truncate(text)
            if r.get("published_date"):
                entry["published_date"] = r["published_date"]
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
