"""AnySearchBackend -- web research via AnySearch's REST API.

Exposes four tools to the calling agent:

- `web_search(query, max_results)` -- URL + title + snippet/content per result.
- `web_search_batch(queries)` -- up to five independent searches in one call.
- `web_extract(url)` -- fetches a URL's full content as text.
- `web_sub_domains(domains)` -- the vertical sub-domains a search `tag` may target.

`web_search` and `web_extract` keep the names the other web backends expose,
so swapping backends does not change the calling agent's prompt.

No API key is required: anonymous traffic is rate-limited per client IP and metered
against the daily free quota. `ANYSEARCH_API_KEY` (or `api_key`) bills against
the paid quota, which comes with higher concurrency limits.
"""

from __future__ import annotations

import asyncio
import json
import re
from os import getenv
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union, get_args
from urllib.parse import urlparse

import httpx

from agno import __version__
from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.tools import tool
from agno.utils.log import log_debug, log_error

# Capability domains `web_sub_domains` accepts, per https://www.anysearch.com/docs -- the same
# set AnySearch's own MCP server and CLI carry. Extend this Literal when AnySearch adds a domain.
Domain = Literal[
    "general",
    "resource",
    "social_media",
    "finance",
    "academic",
    "legal",
    "health",
    "business",
    "security",
    "ip",
    "code",
    "energy",
    "environment",
    "agriculture",
    "travel",
    "film",
    "gaming",
]
ANYSEARCH_DOMAINS: Tuple[str, ...] = get_args(Domain)

_DEFAULT_BASE_URL = "https://api.anysearch.com"
_MAX_EXTRACT_CHARS = 50_000
_MAX_RESULTS_CAP = 10
_MAX_BATCH_QUERIES = 5
_MAX_DOMAINS = 5

# A quota response can embed auto-generated credentials. Matching on the text keeps the
# redaction in force under any status code, not just 402 (see `_failure`).
_CREDENTIAL_MARKERS = re.compile(
    r"['\"]?(?:password|passwd|secret|api[_\s-]?key|username)['\"]?\s*[:=]|automatically generated",
    re.IGNORECASE,
)

# How the API's HTTP statuses are reported back to the model. 402 is deliberately absent: its
# body can carry auto-generated credentials (see `_failure`).
_STATUS_MESSAGES: Dict[int, str] = {
    400: "invalid request (HTTP 400)",
    401: "invalid API key (HTTP 401)",
    403: "expired API key or disabled account (HTTP 403)",
    415: "unsupported content type (HTTP 415)",
    422: "unable to extract content from the URL (HTTP 422)",
    429: "rate limit exceeded (HTTP 429)",
    502: "search service unavailable (HTTP 502)",
}


def _clamp_max_results(value: Optional[int]) -> int:
    """The API accepts 1-10 results per query; anything else falls back to the cap."""
    if value is None:
        return _MAX_RESULTS_CAP
    try:
        return max(1, min(int(value), _MAX_RESULTS_CAP))
    except (TypeError, ValueError, OverflowError):
        return _MAX_RESULTS_CAP


def _normalize_length_limit(value: Optional[int]) -> Optional[int]:
    """A non-positive limit keeps the whole field, matching the toolkit."""
    if value is None:
        return None
    try:
        limit = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return limit if limit > 0 else None


def _normalize_base_url(configured: Optional[str]) -> str:
    """A base URL without an http(s) scheme would raise deep inside httpx; fall back instead."""
    candidate = (configured or _DEFAULT_BASE_URL).rstrip("/")
    if urlparse(candidate).scheme not in ("http", "https"):
        log_error(f"AnySearch base URL {candidate!r} is not an http(s) URL; using {_DEFAULT_BASE_URL}.")
        return _DEFAULT_BASE_URL
    return candidate


def _looks_like_credentials(message: Any) -> bool:
    """True when a message carries credential-shaped text, whatever the status code."""
    return isinstance(message, str) and bool(_CREDENTIAL_MARKERS.search(message))


class AnySearchBackend(ContextBackend):
    """Backend for `WebContextProvider` using AnySearch's search and extract APIs.

    Args:
        api_key (Optional[str]): AnySearch API key. Uses `ANYSEARCH_API_KEY` when omitted.
            Without a key the backend works on AnySearch's anonymous free quota.
        base_url (Optional[str]): API base URL. Uses `ANYSEARCH_API_BASE_URL` when omitted,
            defaulting to `https://api.anysearch.com`.
        timeout (int): Per-request timeout in seconds. Default is 30.
        max_results (int): Default number of search results, clamped to 1-10. Default is 10.
        content_length_limit (Optional[int]): Characters of `content` kept per search result.
            `None`, or any non-positive value, keeps the whole field. Default is 2000.
        zone (Optional[str]): Region preference, `cn` or `intl`. Sends nothing when omitted.
        language (Optional[str]): Preferred result language, e.g. `en` or `zh-CN`.
        format (Literal["json", "markdown"]): Format of each result's `content` field.
            Default is `json`.
    """

    extractor_id = "anysearch"
    # /v1/extract takes one URL per request.
    fetch_batch_limit = 1

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
        max_results: int = 10,
        content_length_limit: Optional[int] = 2000,
        zone: Optional[str] = None,
        language: Optional[str] = None,
        format: Literal["json", "markdown"] = "json",
    ) -> None:
        self.api_key: Optional[str] = api_key if api_key is not None else getenv("ANYSEARCH_API_KEY")
        configured_base_url = base_url if base_url is not None else getenv("ANYSEARCH_API_BASE_URL")
        self.base_url: str = _normalize_base_url(configured_base_url)
        self.timeout: int = timeout
        self.max_results: int = _clamp_max_results(max_results)
        self.content_length_limit: Optional[int] = _normalize_length_limit(content_length_limit)
        self.zone: Optional[str] = zone
        self.language: Optional[str] = language
        self.format: Literal["json", "markdown"] = format

        if not self.api_key:
            log_debug("ANYSEARCH_API_KEY not set: using AnySearch's anonymous quota.")

    def status(self) -> Status:
        host = urlparse(self.base_url).netloc or self.base_url
        return Status(ok=True, detail=f"{host} ({'keyed' if self.api_key else 'keyless'})")

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    # ------------------------------------------------------------------
    # Agent-facing tools
    # ------------------------------------------------------------------

    def get_tools(self) -> list:
        backend = self

        @tool(name="web_search")
        async def web_search(
            query: str,
            max_results: Optional[int] = None,
            tag: Optional[str] = None,
            params: Optional[Dict[str, Any]] = None,
        ) -> str:
            """Search the web for URLs, titles, and excerpts.

            Args:
                query: The search query.
                max_results: Upper bound on results, clamped to 1-10. Defaults to the backend default.
                tag: Vertical capability tag from `web_sub_domains`, e.g. `"finance.quote"`.
                params: Structured params for `tag`, exactly the names `web_sub_domains` lists
                    for it. A tag missing one of its required params comes back as an HTTP 400
                    naming the param.

            Returns:
                JSON with `results: [{title, url, snippet, content}, ...]`.
            """
            item = backend._item(query=query, max_results=max_results, tag=tag, params=params)
            async with httpx.AsyncClient(timeout=backend.timeout) as client:
                return json.dumps(await backend._asearch_one(client, item))

        @tool(name="web_search_batch")
        async def web_search_batch(queries: List[Union[str, Dict[str, Any]]]) -> str:
            """Run up to five independent searches in one call.

            Args:
                queries: Between one and five queries, each a query string or an object with
                    `query` plus optional `tag`, `params`, `zone`, `language`, and
                    `max_results`. Each item's `params` must be the set `web_sub_domains`
                    lists for that item's `tag`.

            Returns:
                JSON with `searches`, one entry per query in input order.
            """
            try:
                items = backend._prepare_batch(queries)
            except ValueError as error:
                return json.dumps({"error": str(error)})
            async with httpx.AsyncClient(timeout=backend.timeout) as client:
                searches = list(
                    await asyncio.gather(
                        *(backend._asearch_entry(client, item) for item in items), return_exceptions=True
                    )
                )
            return json.dumps(
                {
                    "searches": [
                        backend._batch_entry(item, backend._batch_result(entry)) for item, entry in zip(items, searches)
                    ]
                }
            )

        @tool(name="web_extract")
        async def web_extract(url: str) -> str:
            """Fetch a URL's full content as text.

            Args:
                url: The URL to fetch.

            Returns:
                JSON with `{url, title, content}` or `{error}`.
            """
            async with httpx.AsyncClient(timeout=backend.timeout) as client:
                return json.dumps(await backend._aextract_one(client, url.strip()))

        @tool(name="web_sub_domains")
        async def web_sub_domains(domains: List[Domain]) -> str:
            """List the vertical sub-domains, and their params, for the given capability domains.

            Args:
                domains: Between one and five of: general, resource, social_media, finance,
                    academic, legal, health, business, security, ip, code, energy, environment,
                    agriculture, travel, film, gaming.

            Returns:
                JSON with `domains`, each carrying its `sub_domains`.
            """
            error = backend._validate_domains(domains)
            if error is not None:
                return json.dumps(error)
            async with httpx.AsyncClient(timeout=backend.timeout) as client:
                return json.dumps(await backend._asub_domains_one(client, domains))

        return [web_search, web_search_batch, web_extract, web_sub_domains]

    # ------------------------------------------------------------------
    # Page fetching (knowledge readers fetch through this)
    # ------------------------------------------------------------------

    def fetch_many(self, urls: List[str], *, max_chars: int = _MAX_EXTRACT_CHARS) -> list:
        with httpx.Client(timeout=self.timeout) as client:
            return [self._page_from_extract(client, url, max_chars) for url in urls]

    async def afetch_many(self, urls: List[str], *, max_chars: int = _MAX_EXTRACT_CHARS) -> list:
        pages = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for url in urls:
                pages.append(await self._apage_from_extract(client, url, max_chars))
        return pages

    def _page_from_extract(self, client: httpx.Client, url: str, max_chars: int) -> Any:
        try:
            response = client.post(f"{self.base_url}/v1/extract", headers=self._headers(), json={"url": url})
        except Exception as error:  # noqa: BLE001 - any failure reaches the model, never raises
            return self._error_page(url, f"{type(error).__name__}: {error}"[:300])
        return self._page_from_response(response, url, max_chars)

    async def _apage_from_extract(self, client: httpx.AsyncClient, url: str, max_chars: int) -> Any:
        try:
            response = await client.post(f"{self.base_url}/v1/extract", headers=self._headers(), json={"url": url})
        except Exception as error:  # noqa: BLE001 - any failure reaches the model, never raises
            return self._error_page(url, f"{type(error).__name__}: {error}"[:300])
        return self._page_from_response(response, url, max_chars)

    @classmethod
    def _error_page(cls, url: str, error: str) -> Any:
        from agno.knowledge.reader.page_fetcher import FetchedPage

        return FetchedPage(url=url, error=error, extractor=cls.extractor_id)

    @classmethod
    def _page_from_response(cls, response: httpx.Response, url: str, max_chars: int) -> Any:
        """One extract response as a page, raising `RateLimited` when the provider says to slow down."""
        from agno.knowledge.reader.page_fetcher import FetchedPage, RateLimited, rate_limit_from_text

        body = cls._json(response)
        message = cls._message(body)
        if response.status_code == 402 or _looks_like_credentials(message):
            # A quota wall is not a rate limit: retrying it only hammers the quota, and `_failure`
            # keeps the credentials such a body can carry out of the page error.
            return cls._error_page(url, cls._page_failure(response, body))
        if response.status_code == 429 or rate_limit_from_text(message or ""):
            raise RateLimited(cls._rate_limit_message(response), retry_after=cls._retry_after(response))
        if not isinstance(body, dict) or body.get("code") != 0:
            return cls._error_page(url, cls._page_failure(response, body))
        data = body.get("data")
        if not isinstance(data, dict):
            return cls._error_page(url, cls._envelope_error(response, body))
        content = data.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        if not content:
            return FetchedPage(url=url, error="empty", extractor=cls.extractor_id)
        limit = _normalize_length_limit(max_chars)
        if limit:
            content = content[:limit]
        return FetchedPage(
            url=url,
            content=content,
            title=data.get("title"),
            extractor=cls.extractor_id,
        )

    @classmethod
    def _page_failure(cls, response: httpx.Response, body: Any) -> str:
        """A failed page's error: `_failure`'s wording plus the API's own message when it is safe."""
        failure = cls._failure(response, body)
        error = str(failure.get("error"))
        detail = failure.get("detail")
        if detail:
            error = f"{error}: {detail}"
        return error[:300]

    @classmethod
    def _envelope_error(cls, response: httpx.Response, body: Any) -> str:
        return str(cls._envelope_failure(response, body)["error"])[:300]

    @staticmethod
    def _retry_after(response: httpx.Response) -> Optional[float]:
        try:
            return float(response.headers.get("retry-after") or "")
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _rate_limit_message(response: httpx.Response) -> str:
        return f"AnySearch rate limit exceeded (HTTP {response.status_code})"

    # ------------------------------------------------------------------
    # Single-request helpers
    # ------------------------------------------------------------------

    async def _asearch_one(self, client: httpx.AsyncClient, item: Dict[str, Any]) -> Dict[str, Any]:
        try:
            response = await client.post(
                f"{self.base_url}/v1/search", headers=self._headers(), json=self._search_body(item)
            )
        except Exception as error:  # noqa: BLE001 - any failure reaches the model, never raises
            return self._transport_failure("search", error)
        return self._search_result(response, item["query"])

    async def _asearch_entry(self, client: httpx.AsyncClient, item: Dict[str, Any]) -> Dict[str, Any]:
        """One batch entry never takes the batch down: anything unexpected becomes its own error."""
        try:
            return await self._asearch_one(client, item)
        except Exception as error:  # noqa: BLE001 - the batch contract is per-item errors
            return self._transport_failure("search", error)

    async def _aextract_one(self, client: httpx.AsyncClient, url: str) -> Dict[str, Any]:
        if not url:
            return {"error": "url is required"}
        try:
            # /v1/extract takes a strict body: one url field, no others.
            response = await client.post(f"{self.base_url}/v1/extract", headers=self._headers(), json={"url": url})
        except Exception as error:  # noqa: BLE001 - any failure reaches the model, never raises
            return self._transport_failure("extract", error)
        return self._extract_result(response, url)

    async def _asub_domains_one(self, client: httpx.AsyncClient, domains: Sequence[str]) -> Dict[str, Any]:
        try:
            response = await client.get(
                f"{self.base_url}/v1/sub-domains",
                headers=self._headers(),
                params=[("domain", domain) for domain in domains],
            )
        except Exception as error:  # noqa: BLE001 - any failure reaches the model, never raises
            return self._transport_failure("sub-domains", error)
        return self._sub_domains_result(response)

    # ------------------------------------------------------------------
    # Request building
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        client_header = f"agno/{__version__}"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-Anysearch-Client": client_header,
            "User-Agent": client_header,
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _search_body(self, item: Dict[str, Any]) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "query": item["query"],
            "max_results": _clamp_max_results(item.get("max_results", self.max_results)),
            "format": self.format,
        }
        if item.get("tag"):
            body["tag"] = item["tag"]
        if item.get("params"):
            body["params"] = item["params"]
        zone = item.get("zone", self.zone)
        if zone:
            body["zone"] = zone
        language = item.get("language", self.language)
        if language:
            body["language"] = language
        return body

    @staticmethod
    def _item(
        query: str,
        max_results: Optional[int] = None,
        tag: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        item: Dict[str, Any] = {"query": query}
        for key, value in (("max_results", max_results), ("tag", tag), ("params", params)):
            if value is not None:
                item[key] = value
        return item

    @staticmethod
    def _normalize_item(entry: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """One batch entry as a query item, raising ValueError on a malformed shape."""
        if isinstance(entry, str):
            if not entry.strip():
                raise ValueError("each query item needs a non-empty query")
            return {"query": entry.strip()}
        if not isinstance(entry, dict):
            raise ValueError("each query item must be a query string or an object with a query field")
        query = entry.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("each query item needs a non-empty query")
        item: Dict[str, Any] = {"query": query}
        for key in ("tag", "params", "zone", "language"):
            if entry.get(key):
                item[key] = entry[key]
        if entry.get("max_results") is not None:
            item["max_results"] = entry["max_results"]
        return item

    @classmethod
    def _prepare_batch(cls, queries: List[Union[str, Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if not isinstance(queries, list) or not queries:
            raise ValueError("queries must be a non-empty list of one to five queries")
        if len(queries) > _MAX_BATCH_QUERIES:
            raise ValueError(f"queries takes at most {_MAX_BATCH_QUERIES} items per call")
        return [cls._normalize_item(entry) for entry in queries]

    @staticmethod
    def _batch_entry(item: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        """Every batch entry names its own query, failures included."""
        if "query" in result:
            return result
        return {"query": item["query"], **result}

    @staticmethod
    def _batch_result(entry: Any) -> Dict[str, Any]:
        """`asyncio.gather(return_exceptions=True)` hands back whatever escaped one entry."""
        if isinstance(entry, BaseException):
            return AnySearchBackend._transport_failure("search", entry)
        return entry if isinstance(entry, dict) else {"error": "search returned no result"}

    @staticmethod
    def _validate_domains(domains: List[Domain]) -> Optional[Dict[str, Any]]:
        if not isinstance(domains, list) or not domains:
            return {"error": "domains must be a non-empty list of one to five domains"}
        if len(domains) > _MAX_DOMAINS:
            return {"error": f"web_sub_domains takes at most {_MAX_DOMAINS} domains per call"}
        unknown = [domain for domain in domains if domain not in ANYSEARCH_DOMAINS]
        if unknown:
            return {"error": f"unknown domain(s): {', '.join(str(domain) for domain in unknown)}"}
        return None

    # ------------------------------------------------------------------
    # Response parsing
    # ------------------------------------------------------------------

    def _search_result(self, response: httpx.Response, query: str) -> Dict[str, Any]:
        body = self._json(response)
        if not isinstance(body, dict) or body.get("code") != 0:
            return self._failure(response, body)
        data = body.get("data")
        if not isinstance(data, dict):
            return self._envelope_failure(response, body)
        entries = data.get("results")
        if not isinstance(entries, list):
            # A renamed field lands here too: an empty list would read as "nothing found".
            return self._envelope_failure(response, body)
        results: List[Dict[str, Any]] = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            result: Dict[str, Any] = {"title": entry.get("title", ""), "url": entry.get("url")}
            if entry.get("snippet"):
                result["snippet"] = entry["snippet"]
            content = entry.get("content")
            if content:
                result["content"] = self._truncate(content)
            results.append(result)
        out: Dict[str, Any] = {"query": query, "results": results}
        metadata = data.get("metadata")
        if isinstance(metadata, dict):
            if metadata.get("total_results") is not None:
                out["total_results"] = metadata["total_results"]
            if metadata.get("search_time_ms") is not None:
                out["search_time_ms"] = metadata["search_time_ms"]
        request_id = body.get("request_id")
        if request_id:
            out["request_id"] = request_id
        return out

    def _extract_result(self, response: httpx.Response, url: str) -> Dict[str, Any]:
        body = self._json(response)
        if not isinstance(body, dict) or body.get("code") != 0:
            return self._failure(response, body)
        data = body.get("data")
        if not isinstance(data, dict):
            return self._envelope_failure(response, body)
        content = data.get("content") or ""
        if not isinstance(content, str):
            content = str(content)
        out: Dict[str, Any] = {
            "url": data.get("url") or url,
            "title": data.get("title", ""),
            "content": content[:_MAX_EXTRACT_CHARS],
        }
        request_id = body.get("request_id")
        if request_id:
            out["request_id"] = request_id
        return out

    def _sub_domains_result(self, response: httpx.Response) -> Dict[str, Any]:
        body = self._json(response)
        if not isinstance(body, dict) or body.get("code") != 0:
            return self._failure(response, body)
        data = body.get("data")
        if not isinstance(data, dict):
            return self._envelope_failure(response, body)
        domains = data.get("domains")
        if not isinstance(domains, list):
            return self._envelope_failure(response, body)
        out: Dict[str, Any] = {"domains": domains}
        request_id = body.get("request_id")
        if request_id:
            out["request_id"] = request_id
        return out

    @staticmethod
    def _failure(response: httpx.Response, body: Any) -> Dict[str, Any]:
        request_id = body.get("request_id") if isinstance(body, dict) else None
        status = response.status_code
        message = AnySearchBackend._message(body)
        out: Dict[str, Any] = {}
        if status == 402 or _looks_like_credentials(message):
            # The quota body can embed auto-generated credentials, so it reaches neither the tool
            # result nor the logs - whatever status code it arrives with.
            log_debug(f"AnySearch quota response withheld (HTTP {status}).")
            if status == 402:
                out["error"] = "quota exhausted (HTTP 402); set ANYSEARCH_API_KEY or check the dashboard"
            else:
                out["error"] = "quota response withheld; set ANYSEARCH_API_KEY or check the dashboard"
        else:
            if status in _STATUS_MESSAGES:
                out["error"] = _STATUS_MESSAGES[status]
            elif 200 <= status < 300:
                out["error"] = (
                    "AnySearch returned an error response (code != 0)"
                    if isinstance(body, dict)
                    else "unexpected response envelope from AnySearch"
                )
            else:
                out["error"] = f"AnySearch request failed (HTTP {status})"
            if message:
                out["detail"] = message[:300]
            log_error(f"AnySearch request failed: {out['error']} (request_id={request_id})")
        if request_id:
            out["request_id"] = request_id
        return out

    @staticmethod
    def _envelope_failure(response: httpx.Response, body: Any) -> Dict[str, Any]:
        """A 2xx body that is not the documented envelope: say so instead of returning an
        empty result set, which the model would read as "nothing found"."""
        log_error(f"AnySearch response did not match the documented envelope (HTTP {response.status_code}).")
        out: Dict[str, Any] = {"error": "unexpected response envelope from AnySearch"}
        request_id = body.get("request_id") if isinstance(body, dict) else None
        if request_id:
            out["request_id"] = request_id
        return out

    @staticmethod
    def _message(body: Any) -> Optional[str]:
        if not isinstance(body, dict):
            return None
        message = body.get("message")
        return str(message) if message else None

    @staticmethod
    def _transport_failure(operation: str, error: BaseException) -> Dict[str, Any]:
        detail = f"{type(error).__name__}: {error}"
        log_error(f"AnySearch {operation} request failed: {detail}")
        return {"error": f"{operation} request failed", "detail": detail[:300]}

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return None

    def _truncate(self, content: Any) -> str:
        text = content if isinstance(content, str) else str(content)
        if self.content_length_limit is None:
            return text
        return text[: self.content_length_limit]


__all__ = ["ANYSEARCH_DOMAINS", "AnySearchBackend", "Domain"]
