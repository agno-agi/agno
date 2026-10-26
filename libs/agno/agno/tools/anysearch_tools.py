"""AnySearch tools for Agno.

AnySearch is a search infrastructure built for AI agents. It exposes a
general web search endpoint, vertical-domain search through a ``tag`` plus
``params`` pair, and a page-extraction endpoint. This toolkit wraps all three
as Agno tools.

The API works without credentials: when no API key is configured the client
simply omits the ``Authorization`` header and the request is served
anonymously. Passing a key is optional and only raises the caller's quota.

Two behaviours are verified against the live API and are load-bearing for
this implementation:

* ``max_results`` is clamped client-side. The service may return more rows
  than requested, so results are truncated here rather than trusting it.
* Sending an ``Authorization: Bearer <key>`` header makes the service
  validate the key (a malformed one returns ``401 invalid_api_key``). A key
  is therefore only sent when one is actually configured.

Installation::

    pip install agno

Usage::

    from agno.agent import Agent
    from agno.tools.anysearch import AnySearchTools

    agent = Agent(tools=[AnySearchTools()])
    agent.print_response("Search the web for recent Postgres 19 features.")
"""

import json
from os import getenv
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from agno.tools import Toolkit
from agno.utils.log import log_debug, log_error, logger

DEFAULT_BASE_URL = "https://api.anysearch.com"
DEFAULT_TIMEOUT = 30
MIN_MAX_RESULTS = 1
MAX_MAX_RESULTS = 20
DEFAULT_MAX_RESULTS = 5


class AnySearchTools(Toolkit):
    """Toolkit exposing AnySearch web search and page extraction to an agent.

    Args:
        api_key: AnySearch API key. Falls back to the ``ANYSEARCH_API_KEY``
            environment variable. When absent the API is called anonymously.
        base_url: Override the API base URL.
        enable_search: Register the web search tool. Defaults to True.
        enable_extract: Register the page extraction tool. Defaults to True.
        all: Register every tool. Defaults to False.
        max_results: Default number of results per search, clamped to 1-20.
        format: ``"markdown"`` (default) or ``"json"``.
        timeout: Per-request timeout in seconds.
        tag: Optional vertical domain tag, e.g. ``"code.doc"``.
        params: Optional extra parameters required by ``tag``.
        verify_ssl: Whether to verify TLS certificates.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        enable_search: bool = True,
        enable_extract: bool = True,
        all: bool = False,
        max_results: int = DEFAULT_MAX_RESULTS,
        format: str = "markdown",
        timeout: Optional[int] = DEFAULT_TIMEOUT,
        tag: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        verify_ssl: bool = True,
        **kwargs,
    ):
        self.api_key: Optional[str] = api_key or getenv("ANYSEARCH_API_KEY")
        self.base_url: str = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.max_results: int = self._clamp_max_results(max_results)
        self.format: str = format if format in ("json", "markdown") else "markdown"
        self.timeout: int = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.tag: Optional[str] = tag
        self.params: Optional[Dict[str, Any]] = params
        self.verify_ssl: bool = verify_ssl

        tools: List[Any] = []
        if enable_search or all:
            tools.append(self.web_search_using_anysearch)
        if enable_extract or all:
            tools.append(self.extract_url_content)

        super().__init__(name="anysearch_tools", tools=tools, **kwargs)

    @staticmethod
    def _clamp_max_results(value: Any) -> int:
        """Clamp a requested result count into the supported 1-20 range.

        Args:
            value: Requested count, possibly ``None`` or non-numeric.

        Returns:
            int: A count within 1-20.
        """
        try:
            return max(MIN_MAX_RESULTS, min(MAX_MAX_RESULTS, int(value)))
        except (TypeError, ValueError):
            return DEFAULT_MAX_RESULTS

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """POST a JSON body to the AnySearch API and return the decoded body.

        Args:
            path: Endpoint path, e.g. ``"/v1/search"``.
            payload: JSON-serialisable request body.

        Returns:
            Dict[str, Any]: The decoded response. A failure yields a dict
            carrying an ``error`` key instead of raising, so a tool call
            degrades into text the agent can read.
        """
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        # Only send the header when a key is configured: the service rejects
        # an invalid bearer token with 401 invalid_api_key, and anonymous
        # requests are served normally when the header is absent entirely.
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        request = Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            log_error(f"AnySearch {path} failed with HTTP {e.code}: {detail}")
            return {"error": f"HTTP {e.code}: {detail}"}
        except URLError as e:
            log_error(f"AnySearch {path} unreachable: {e.reason}")
            return {"error": f"Connection failed: {e.reason}"}
        except Exception as e:
            logger.exception(f"AnySearch {path} raised")
            return {"error": str(e)}

        try:
            decoded = json.loads(raw)
        except ValueError:
            log_error(f"AnySearch {path} returned non-JSON payload")
            return {"error": "Response was not valid JSON."}

        if not isinstance(decoded, dict):
            return {"error": "Response was not a JSON object."}
        return decoded

    @staticmethod
    def _data_of(response: Dict[str, Any]) -> Dict[str, Any]:
        """Return the ``data`` object of a response, or ``{}`` when absent.

        Args:
            response: A decoded AnySearch response.

        Returns:
            Dict[str, Any]: The ``data`` mapping.
        """
        data = response.get("data")
        return data if isinstance(data, dict) else {}

    def web_search_using_anysearch(
        self,
        query: str,
        max_results: Optional[int] = None,
        tag: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Search the web with AnySearch and return matching pages.

        Args:
            query: The search query.
            max_results: Maximum results to return, clamped to 1-20. Defaults
                to the toolkit's configured value.
            tag: Optional vertical domain tag, e.g. ``"code.doc"`` for
                documentation search. Defaults to the toolkit's tag.
            params: Optional extra parameters the chosen ``tag`` requires,
                e.g. ``{"library": "golang"}`` for ``"code.doc"``.

        Returns:
            str: Markdown or JSON with the results, or a readable error.
        """
        if not query or not str(query).strip():
            return "Error: No query provided."

        effective_tag = tag or self.tag
        payload: Dict[str, Any] = {
            "query": str(query).strip(),
            "max_results": self._clamp_max_results(
                max_results if max_results is not None else self.max_results
            ),
        }
        if effective_tag:
            payload["tag"] = effective_tag
        merged_params = params or self.params
        if merged_params:
            payload["params"] = merged_params

        response = self._post("/v1/search", payload)
        if "error" in response:
            return f"Error searching AnySearch: {response['error']}"

        code = response.get("code")
        if code not in (0, "0", None):
            message = response.get("message") or "unknown error"
            return f"Error searching AnySearch: {message} (code={code})"

        rows = self._data_of(response).get("results")
        rows = rows if isinstance(rows, list) else []

        # Clamp again: the service can return more rows than requested.
        limit = payload["max_results"]
        results: List[Dict[str, Any]] = []
        for row in rows[:limit]:
            if not isinstance(row, dict):
                continue
            results.append(
                {
                    "title": row.get("title") or "",
                    "url": row.get("url") or "",
                    "content": row.get("content") or row.get("snippet") or "",
                }
            )

        if not results:
            return f"No results found for: {query}"

        if self.format == "json":
            return json.dumps({"query": query, "results": results})

        lines = [f"# {query}", ""]
        for item in results:
            lines.append(f"### [{item['title']}]({item['url']})")
            lines.append(f"{item['content']}")
            lines.append("")
        return "\n".join(lines).strip()

    def extract_url_content(self, url: str) -> str:
        """Extract the main content of one page with AnySearch.

        The extraction endpoint accepts a single URL per call.

        Args:
            url: The page URL to extract.

        Returns:
            str: The extracted content in markdown, or a readable error.
        """
        if not url or not str(url).strip():
            return "Error: No URL provided."

        target = str(url).strip()
        response = self._post("/v1/extract", {"url": target})
        if "error" in response:
            return f"Error extracting {target}: {response['error']}"

        code = response.get("code")
        if code not in (0, "0", None):
            message = response.get("message") or "unknown error"
            return f"Error extracting {target}: {message} (code={code})"

        data = self._data_of(response)
        content = data.get("content") or ""
        title = data.get("title") or target
        if not content:
            return f"No content could be extracted from {target}."

        log_debug(f"AnySearch extracted {len(content)} chars from {target}")
        return f"# {title}\n\n{content}"
