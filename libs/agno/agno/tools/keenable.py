import ipaddress
import json
from os import getenv
from typing import Any, Dict, List, Literal, Optional
from urllib.parse import urlsplit

import httpx

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error

DEFAULT_BASE_URL = "https://api.keenable.ai"

# Keenable's documented search mode. Kept internal rather than exposed as a
# parameter, since "pro" is the mode this toolkit is built around.
SEARCH_MODE = "pro"


class KeenableTools(Toolkit):
    """Web search and page extraction powered by the Keenable Search API.

    Keenable is a web search API built for agents. It is **keyless by default**:
    with no API key configured the toolkit calls Keenable's public endpoints, so
    an agent has working web search with zero setup and no signup. Setting
    ``KEENABLE_API_KEY`` switches to the authenticated endpoints, which lifts
    rate limits.

    Requests go through ``httpx``, already an Agno dependency, so this toolkit
    needs no additional install.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        enable_search: bool = True,
        enable_fetch: bool = False,
        all: bool = False,
        max_results: int = 5,
        max_snippet_chars: int = 500,
        format: Literal["json", "markdown"] = "markdown",
        timeout: int = 30,
        **kwargs,
    ):
        """Initialize KeenableTools with search and page-fetch capabilities.

        Args:
            api_key: Keenable API key. Optional. Falls back to the KEENABLE_API_KEY env
                var; with neither, the keyless public endpoints are used.
            base_url: Keenable API base URL. Falls back to the KEENABLE_API_URL env var,
                then to https://api.keenable.ai. Must be https (http is allowed only for
                a loopback host, for local development).
            enable_search: Register the web search function. Defaults to True.
            enable_fetch: Register the page-fetch function. Defaults to False.
            all: Register all available functions. Defaults to False.
            max_results: Default maximum number of search results. Defaults to 5.
            max_snippet_chars: Truncate each result's content to this many characters, to keep
                results readable in a prompt. Defaults to 500. Set to 0 for no truncation.
            format: Output format for search results - json or markdown. Defaults to "markdown".
            timeout: Request timeout in seconds. Defaults to 30.
            **kwargs: Additional arguments passed to Toolkit.
        """
        self.api_key: Optional[str] = api_key or getenv("KEENABLE_API_KEY")
        self.base_url: str = (base_url or getenv("KEENABLE_API_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.max_results: int = max_results
        self.max_snippet_chars: int = max_snippet_chars
        self.format: Literal["json", "markdown"] = format
        self.timeout: int = timeout

        tools: List[Any] = []
        if enable_search or all:
            tools.append(self.web_search)
        if enable_fetch or all:
            tools.append(self.fetch_url_content)

        super().__init__(name="keenable_tools", tools=tools, **kwargs)

    def web_search(self, query: str, max_results: Optional[int] = None) -> str:
        """Use this function to search the web for a given query.

        Searches the live web through the Keenable API and returns ranked results.

        Args:
            query (str): Query to search for.
            max_results (Optional[int]): Maximum number of results to return.
                Defaults to the toolkit's max_results.

        Returns:
            str: Search results as markdown or JSON, depending on the toolkit format.
        """
        if not query or not query.strip():
            return "Error: a non-empty search query is required."

        limit = self.max_results if max_results is None else max_results
        if limit < 0:
            return "Error: max_results cannot be negative."

        payload: Dict[str, Any] = {"query": query, "mode": SEARCH_MODE}
        try:
            url = f"{self._resolved_base_url()}{self._path('/v1/search/public', '/v1/search')}"
            log_debug(f"Searching Keenable for: {query}")
            response = httpx.post(url, json=payload, headers=self._headers(), timeout=self.timeout)
        except (httpx.HTTPError, ValueError) as e:
            log_error(f"Keenable search failed: {e}")
            return f"Error performing search: {e}"

        error = self._error_message(response)
        if error:
            log_error(error)
            return error

        try:
            data = response.json()
        except ValueError:
            return "Error performing search: the Keenable API returned a non-JSON response."

        raw_results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(raw_results, list):
            return "Error performing search: unexpected response from the Keenable API."

        results = [
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "content": self._result_content(r),
            }
            for r in raw_results[:limit]
            if isinstance(r, dict) and r.get("url")
        ]
        if not results:
            return "No results found."

        if self.format == "json":
            return json.dumps({"query": query, "results": results}, indent=2)

        markdown = f"# {query}\n\n"
        for result in results:
            markdown += f"### [{result['title']}]({result['url']})\n"
            markdown += f"{result['content']}\n\n"
        return markdown

    def fetch_url_content(self, url: str) -> str:
        """Use this function to read the content of a web page.

        Fetches a URL through the Keenable API and returns the page's main content
        as clean markdown, without boilerplate such as navigation or ads.

        Args:
            url (str): URL of the page to fetch.

        Returns:
            str: The page content as markdown, prefixed with its title.
        """
        if not url.lower().startswith(("http://", "https://")):
            return f"Error: refusing to fetch a non-http(s) URL: {url!r}"

        private_target = self._private_target(url)
        if private_target:
            return f"Error: refusing to fetch a private/internal host: {private_target!r}"

        try:
            endpoint = f"{self._resolved_base_url()}{self._path('/v1/fetch/public', '/v1/fetch')}"
            log_debug(f"Fetching page content from Keenable: {url}")
            response = httpx.get(endpoint, params={"url": url}, headers=self._headers(), timeout=self.timeout)
        except (httpx.HTTPError, ValueError) as e:
            log_error(f"Keenable fetch failed: {e}")
            return f"Error fetching page content: {e}"

        error = self._error_message(response)
        if error:
            log_error(error)
            return error

        try:
            data = response.json()
        except ValueError:
            return "Error fetching page content: the Keenable API returned a non-JSON response."

        if not isinstance(data, dict):
            return "Error fetching page content: unexpected response from the Keenable API."

        content = data.get("content")
        if not content:
            return f"No content could be extracted from {url}."

        title = data.get("title") or data.get("url") or url
        return f"## {title}\n\n{content}"

    def _result_content(self, result: Dict[str, Any]) -> str:
        """Return a result's text, whitespace-collapsed and length-capped.

        The API returns both ``snippet`` and ``description``; ``snippet`` carries the
        page text and ``description`` is often empty, so prefer whichever has content.
        Snippets are raw page text and arrive with newlines, which would break the
        markdown layout, hence the collapse.
        """
        text = " ".join(str(result.get("snippet") or result.get("description") or "").split())
        if 0 < self.max_snippet_chars < len(text):
            return text[: self.max_snippet_chars].rstrip() + "…"
        return text

    def _resolved_base_url(self) -> str:
        """Return the API base URL, enforcing https outside of loopback."""
        base = self.base_url or DEFAULT_BASE_URL
        parsed = urlsplit(base)
        if parsed.hostname:
            if parsed.scheme == "https":
                return base
            # Plain http is permitted only against a loopback host, for local development.
            if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}:
                return base
        raise ValueError(f"Keenable base URL must be an https:// URL with a host, got {base!r}")

    def _path(self, public_path: str, keyed_path: str) -> str:
        """Pick the keyless or authenticated endpoint for the configured key."""
        return keyed_path if (self.api_key or "").strip() else public_path

    def _headers(self) -> Dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "keenable-agno",
            # Attribution header the Keenable backend segments traffic by.
            "X-Keenable-Title": "Agno",
        }
        key = (self.api_key or "").strip()
        if key:
            headers["X-API-Key"] = key
        return headers

    @staticmethod
    def _private_target(url: str) -> Optional[str]:
        """Return the host if it is an obviously private/internal fetch target.

        The Keenable backend enforces this server-side as well; checking here avoids
        sending an internal hostname off the machine in the first place. Hostnames
        that are not IP literals are passed through for the backend to judge.
        """
        host = (urlsplit(url).hostname or "").strip().lower()
        if not host:
            return url
        if host in {"localhost", "metadata.google.internal"}:
            return host
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return None
        if (
            ip.is_loopback
            or ip.is_private
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return host
        return None

    @staticmethod
    def _error_message(response: httpx.Response) -> Optional[str]:
        """Map a non-2xx Keenable response to a message the agent can act on."""
        if response.is_success:
            return None

        detail = ""
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = str(body.get("message") or body.get("error") or body.get("detail") or "")
        except ValueError:
            detail = (response.text or "").strip()

        label = {
            401: "Keenable authentication failed (401)",
            402: "Keenable: insufficient credits (402)",
            429: "Keenable rate limit exceeded (429)",
        }.get(response.status_code, f"Keenable API error ({response.status_code})")
        return f"{label}: {detail}" if detail else label
