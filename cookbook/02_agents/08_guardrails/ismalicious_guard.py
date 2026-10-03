"""Cookbook-only synchronous tool boundary. No vendor code is added to Agno core."""

import base64
import inspect
from typing import Any, Callable, Dict, FrozenSet, List, Literal, NoReturn, Optional
from urllib.parse import urlsplit

import httpx
from agno.exceptions import StopAgentRun
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_CONTENT_BYTES = 128 * 1024
GATE_BASE_URL = "https://api.ismalicious.com"


class _Decision(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    verdict: Literal["block", "warn", "allow"]
    latency_ms: int = Field(ge=0)


class _URLDecision(_Decision):
    url: str
    entity: str
    sources: int = Field(ge=0)


class _Link(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    url: str
    entity: str
    verdict: Literal["malicious", "suspicious", "clean", "unknown"]
    sources: int = Field(ge=0)


class _Span(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    family: str


class _Injection(BaseModel):
    model_config = ConfigDict(strict=True, extra="allow")
    score: float = Field(ge=0, le=1)
    families: List[str]
    spans: List[_Span]


class _ContentDecision(_Decision):
    injection: _Injection
    links: List[_Link]
    links_truncated: bool
    mode: Literal["fast", "thorough"]
    source: Optional[_Link] = None
    sanitized_content: Optional[str] = None


def _stop(message: str) -> NoReturn:
    # Never include the fetched content, request headers or provider error body.
    raise StopAgentRun(message)


class IsMaliciousGuard:
    """Gate one synchronous public-page tool, with warnings and errors failing closed.

    URL approval is an exact operator-owned allowlist, independent of reputation.
    The HTTP client is injectable only for offline tests, not a model argument.
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        approved_urls: FrozenSet[str],
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        if not api_key or not api_secret:
            raise ValueError("Set ISMALICIOUS_API_KEY and ISMALICIOUS_API_SECRET.")
        if not approved_urls:
            raise ValueError("Approve at least one public HTTPS URL.")
        for url in approved_urls:
            parts = urlsplit(url)
            if (
                parts.scheme != "https"
                or not parts.hostname
                or parts.username
                or parts.password
            ):
                raise ValueError(
                    "Approved pages must be public HTTPS URLs without credentials."
                )
        self.approved_urls = approved_urls
        credential = base64.b64encode(f"{api_key}:{api_secret}".encode()).decode()
        self._headers = {"X-API-KEY": credential}
        self._owns_client = http_client is None
        self._http = http_client or httpx.Client(
            timeout=15.0, follow_redirects=False, trust_env=False
        )

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def _approve_url(self, value: Any) -> str:
        if not isinstance(value, str) or value not in self.approved_urls:
            _stop(
                "Page not fetched: URL is outside the operator's approved public pages."
            )
        return value

    @staticmethod
    def _accept_verdict(response: httpx.Response, stage: str) -> None:
        if response.status_code != 200:
            _stop(
                f"Page withheld: IsMalicious {stage} check failed (HTTP {response.status_code})."
            )
        try:
            body = response.json()
        except ValueError:
            _stop(f"Page withheld: IsMalicious {stage} response was not JSON.")
        try:
            if stage == "content":
                _ContentDecision.model_validate(body)
            else:
                _URLDecision.model_validate(body)
        except ValidationError:
            _stop(f"Page withheld: IsMalicious {stage} response had no valid decision.")
        if stage == "content" and body.get("links_truncated") is not False:
            _stop("Page withheld: embedded-link coverage was incomplete or missing.")
        if body["verdict"] == "warn":
            _stop(
                f"Page withheld: IsMalicious {stage} returned warn. Review outside this run before retrying."
            )
        if body["verdict"] == "block":
            _stop(f"Page withheld: IsMalicious {stage} returned block.")

    def check_url(self, url: str) -> None:
        """Use the endpoint behind MCP check_url, before the fetch executes."""
        try:
            response = self._http.get(
                f"{GATE_BASE_URL}/gate/url",
                params={"u": url},
                headers=self._headers,
                timeout=15.0,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            _stop(
                "Page not fetched: IsMalicious URL check unavailable. No automatic retry."
            )
        self._accept_verdict(response, "URL")

    def scan_before_use(self, content: Any, source_url: str) -> str:
        """Scan the entire returned text before Agno receives any of it."""
        if not isinstance(content, str) or not content.strip():
            _stop("Page withheld: tool must return non-empty text.")
        try:
            content_size = len(content.encode("utf-8"))
        except UnicodeError:
            _stop("Page withheld: tool returned invalid Unicode text.")
        if content_size > MAX_CONTENT_BYTES:
            _stop(
                "Page withheld: text exceeds this example's scan budget. No truncation."
            )
        try:
            response = self._http.post(
                f"{GATE_BASE_URL}/gate/scan",
                json={"content": content, "source_url": source_url, "mode": "fast"},
                headers=self._headers,
                timeout=15.0,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            _stop(
                "Page withheld: IsMalicious content check unavailable. No automatic retry."
            )
        self._accept_verdict(response, "content")
        # An allow decision passes the original text, not a fabricated clean verdict.
        return content

    def hook(
        self, function_name: str, func: Callable[..., Any], args: Dict[str, Any]
    ) -> Any:
        """Synchronous Agent.run hook, deliberately restricted to this one tool."""
        if function_name != "fetch_public_page":
            return func(**args)
        url = self._approve_url(args.get("url"))
        self.check_url(url)
        try:
            result = func(**args)
        except StopAgentRun:
            raise
        except Exception:
            _stop("Page withheld: fetch failed. No unscanned fallback.")
        if inspect.isawaitable(result):
            # Agent.arun uses an async continuation even for a sync entrypoint.
            if inspect.iscoroutine(result):
                result.close()
            _stop("This cookbook requires Agent.run, not Agent.arun. Page not fetched.")
        return self.scan_before_use(result, url)

    def fetch_public_page(self, url: str) -> str:
        """Fetch one operator-approved public HTTPS page as bounded text."""
        url = self._approve_url(url)
        # Gate credentials are never attached to the external page request.
        with self._http.stream(
            "GET", url, timeout=15.0, follow_redirects=False
        ) as response:
            if response.status_code != 200:
                _stop(
                    f"Page withheld: external page returned HTTP {response.status_code}; redirects are not followed."
                )
            media_type = (
                response.headers.get("content-type", "")
                .split(";", 1)[0]
                .strip()
                .lower()
            )
            if media_type not in {"text/plain", "text/html", "application/xhtml+xml"}:
                _stop("Page withheld: this example accepts text pages only.")
            data = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                data.extend(chunk)
                if len(data) > MAX_CONTENT_BYTES:
                    _stop(
                        "Page withheld: response exceeds the text budget. No partial result."
                    )
            try:
                return bytes(data).decode(response.encoding or "utf-8", errors="strict")
            except (LookupError, UnicodeError):
                _stop("Page withheld: text could not be decoded without loss.")
        return ""  # Unreachable; helps static checking on Python 3.9.
