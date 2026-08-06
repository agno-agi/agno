"""Nimble Search API toolkit for Agno.

This direct-search surface complements :class:`NimbleAgentTools`, which exposes
the asynchronous Agent API V2 lifecycle. Both use the same official
``nimble-python`` dependency, ``NIMBLE_API_KEY`` credential, and
``X-Client-Source: agno`` attribution.
"""

import json
import os
import re
from math import isfinite
from typing import Any, Dict, Iterator, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from nimble_python import AsyncNimble, Nimble
except ImportError:
    raise ImportError("`nimble-python` not installed. Please install using `pip install nimble-python`")

CLIENT_SOURCE = "agno"
# A deep search returns full page content per result, so an unbounded response can
# be far larger than the model's context. Cap the rendered payload by default.
DEFAULT_MAX_CONTENT_CHARS = 8000
MIN_MAX_CONTENT_CHARS = 500
_SECRET_PATTERNS = (
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"nvapi-[A-Za-z0-9_-]+"),
    re.compile(r"(?<![0-9a-f])[0-9a-f]{40,}(?![0-9a-f])"),
)


def _redact_text(value: str) -> str:
    """Remove common credential shapes and the configured live Nimble key."""
    secret = os.getenv("NIMBLE_API_KEY")
    if secret and len(secret) >= 12:
        value = value.replace(secret, "<redacted>")
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("<redacted>", value)
    return value


def _sanitize_json(value: Any) -> Any:
    """Convert a value to JSON-safe data and scrub every emitted string.

    SDK extension dictionaries can contain arbitrary keys and values, including
    objects that ``json.dumps(default=str)`` would stringify without redaction.
    Sanitizing the complete structure before it is bounded keeps the output
    parseable and prevents a credential from surviving in a key, fallback
    stringification, or content beyond the truncation point.
    """
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, dict):
        sanitized: Dict[str, Any] = {}
        for key, item in value.items():
            base_key = _redact_text(str(key))
            safe_key = base_key
            suffix = 2
            while safe_key in sanitized:
                safe_key = f"{base_key}#{suffix}"
                suffix += 1
            sanitized[safe_key] = _sanitize_json(item)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_json(item) for item in value]
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if isfinite(value) else _redact_text(str(value))
    return _redact_text(str(value))


def _truncate_strings(value: Any, cap: int) -> Any:
    """Copy ``value`` with every string leaf truncated to ``cap`` characters."""
    if isinstance(value, str):
        return value if len(value) <= cap else value[:cap]
    if isinstance(value, dict):
        return {key: _truncate_strings(item, cap) for key, item in value.items()}
    if isinstance(value, list):
        return [_truncate_strings(item, cap) for item in value]
    return value


def _render(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, allow_nan=False)


def _iter_strings(value: Any) -> Iterator[str]:
    """Yield every string leaf, used to size the binary search upper bound."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)


def _bounded_render(payload: Dict[str, Any], limit: int) -> str:
    """Render ``payload`` as JSON no longer than ``limit`` characters.

    Slicing the serialized JSON would hand the model an unparseable string, so the
    bound is applied to the structure instead: string leaves are shortened until
    the rendered form fits. The per-field cap is found by binary search because
    rendered length grows monotonically with it, which keeps the result as full as
    the budget allows rather than truncating to an arbitrary depth.
    """
    rendered = _render(payload)
    if len(rendered) <= limit:
        return rendered

    original_characters = len(rendered)
    meta_key = "truncation"

    longest = max((len(text) for text in _iter_strings(payload)), default=0)
    low, high, best = 0, longest, 0
    while low <= high:
        cap = (low + high) // 2
        candidate = _truncate_strings(payload, cap)
        if isinstance(candidate, dict):
            candidate[meta_key] = {
                "truncated": True,
                "original_characters": original_characters,
                "field_characters": cap,
            }
        if len(_render(candidate)) <= limit:
            best, low = cap, cap + 1
        else:
            high = cap - 1

    bounded = _truncate_strings(payload, best)
    if isinstance(bounded, dict):
        bounded[meta_key] = {
            "truncated": True,
            "original_characters": original_characters,
            "field_characters": best,
        }
    rendered = _render(bounded)
    if len(rendered) <= limit:
        return rendered
    # Structural overhead alone exceeds the budget (very many fields). Fall back to
    # a small, valid envelope rather than returning something oversized or invalid.
    return _render(
        {
            "results": [],
            meta_key: {
                "truncated": True,
                "original_characters": original_characters,
                "field_characters": 0,
                "note": "Response omitted: its structure exceeds max_content_chars. Retry with fewer max_results.",
            },
        }
    )


def _model_to_dict(model: Any) -> Dict[str, Any]:
    """Convert the released SDK response model to a JSON-safe dictionary."""
    if hasattr(model, "to_dict"):
        value = model.to_dict()
    elif hasattr(model, "model_dump"):
        value = model.model_dump(mode="json")
    elif hasattr(model, "dict"):
        value = model.dict()
    else:
        raise TypeError("Nimble SDK response does not expose a supported dict conversion")
    if not isinstance(value, dict):
        raise TypeError("Nimble SDK response conversion did not return a dict")
    return value


class NimbleTools(Toolkit):
    """Provide direct, real-time web search through Nimble's Search API.

    Use :class:`NimbleTools` for one-shot search. Use
    :class:`agno.tools.nimble_agent.NimbleAgentTools` when a task needs a
    resumable Agent API V2 start/status/result lifecycle.

    Args:
        api_key: Nimble API key. Falls back to ``NIMBLE_API_KEY``.
        enable_search: Register the direct-search tool. Defaults to ``True``.
        all: Enable all tools exposed by this toolkit.
        locale: Default result locale.
        country: Default result country.
        output_format: Default page-content format.
        timeout: Per-request timeout in seconds.
        max_retries: Bounded SDK retry budget. Search is read-only.
        max_content_chars: Upper bound on the characters of JSON returned to the
            model. A deep search carries full page content, so this keeps one call
            from flooding the context. The result stays valid JSON and reports what
            was truncated. Minimum 500.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search: bool = True,
        all: bool = False,
        locale: str = "en",
        country: str = "US",
        output_format: Literal["markdown", "plain_text", "simplified_html"] = "markdown",
        timeout: int = 30,
        max_retries: int = 2,
        max_content_chars: int = DEFAULT_MAX_CONTENT_CHARS,
        **kwargs: Any,
    ):
        if isinstance(max_content_chars, bool) or not isinstance(max_content_chars, int):
            raise ValueError("max_content_chars must be an integer")
        if max_content_chars < MIN_MAX_CONTENT_CHARS:
            raise ValueError(f"max_content_chars must be at least {MIN_MAX_CONTENT_CHARS}")
        self.max_content_chars = int(max_content_chars)
        self.api_key = api_key or os.getenv("NIMBLE_API_KEY")
        if not self.api_key:
            log_error("NIMBLE_API_KEY not set. Set NIMBLE_API_KEY or pass api_key.")

        self.locale = locale
        self.country = country
        self.output_format = output_format
        self.timeout = timeout
        self.max_retries = max_retries
        self._sync_client = self._build_sync_client() if self.api_key else None
        self._async_client: Optional[AsyncNimble] = None

        tools: List[Any] = []
        async_tools: List[Any] = []
        if enable_search or all:
            tools.append(self.web_search_using_nimble)
            async_tools.append((self.aweb_search_using_nimble, "web_search_using_nimble"))

        super().__init__(
            name="nimble_tools",
            tools=tools,
            async_tools=async_tools,
            timeout=timeout,
            **kwargs,
        )

    def _build_sync_client(self) -> Nimble:
        return Nimble(
            api_key=self.api_key,
            client_source=CLIENT_SOURCE,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    def _get_async_client(self) -> AsyncNimble:
        if self._async_client is None:
            self._async_client = AsyncNimble(
                api_key=self.api_key,
                client_source=CLIENT_SOURCE,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._async_client

    def _search_options(
        self,
        *,
        query: str,
        max_results: int,
        deep_search: bool,
        include_answer: bool,
        time_range: Optional[Literal["hour", "day", "week", "month", "year"]],
        include_domains: Optional[List[str]],
        exclude_domains: Optional[List[str]],
    ) -> Dict[str, Any]:
        prompt = (query or "").strip()
        if not prompt:
            raise ValueError("query is required")
        if not 1 <= max_results <= 100:
            raise ValueError("max_results must be between 1 and 100")

        options: Dict[str, Any] = {
            "query": prompt,
            "max_results": max_results,
            "deep_search": deep_search,
            "include_answer": include_answer,
            "locale": self.locale,
            "country": self.country,
            "output_format": self.output_format,
        }
        if time_range is not None:
            options["time_range"] = time_range
        if include_domains:
            options["include_domains"] = include_domains
        if exclude_domains:
            options["exclude_domains"] = exclude_domains
        return options

    def _success(self, response: Any) -> str:
        """Shared success path for the sync and async search tools.

        Sanitization runs on every emitted string before bounding, so a
        credential cannot survive in a key, fallback stringification, or content
        past the truncation point.
        """
        return _bounded_render(_sanitize_json(_model_to_dict(response)), self.max_content_chars)

    def _error(self, exc: Exception) -> str:
        return _bounded_render(
            _sanitize_json(
                {
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                }
            ),
            self.max_content_chars,
        )

    def web_search_using_nimble(
        self,
        query: str,
        max_results: int = 3,
        deep_search: bool = False,
        include_answer: bool = False,
        time_range: Optional[Literal["hour", "day", "week", "month", "year"]] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> str:
        """Search the web for real-time information using Nimble.

        Fast mode is the token-efficient default for URL discovery and quick
        answers. Set ``deep_search=True`` when the agent needs full-page content
        for detailed analysis.
        """
        if self._sync_client is None:
            return json.dumps({"error": "Nimble API key not configured.", "error_type": "configuration_error"})
        try:
            options = self._search_options(
                query=query,
                max_results=max_results,
                deep_search=deep_search,
                include_answer=include_answer,
                time_range=time_range,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )
            return self._success(self._sync_client.search(**options))
        except Exception as exc:
            log_error(f"Nimble web search failed: {type(exc).__name__}")
            return self._error(exc)

    async def aweb_search_using_nimble(
        self,
        query: str,
        max_results: int = 3,
        deep_search: bool = False,
        include_answer: bool = False,
        time_range: Optional[Literal["hour", "day", "week", "month", "year"]] = None,
        include_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> str:
        """Async variant of :meth:`web_search_using_nimble`."""
        if not self.api_key:
            return json.dumps({"error": "Nimble API key not configured.", "error_type": "configuration_error"})
        try:
            options = self._search_options(
                query=query,
                max_results=max_results,
                deep_search=deep_search,
                include_answer=include_answer,
                time_range=time_range,
                include_domains=include_domains,
                exclude_domains=exclude_domains,
            )
            return self._success(await self._get_async_client().search(**options))
        except Exception as exc:
            log_error(f"Nimble async web search failed: {type(exc).__name__}")
            return self._error(exc)
