"""Nimble Search API toolkit for Agno.

This direct-search surface complements :class:`NimbleAgentTools`, which exposes
the asynchronous Agent API V2 lifecycle. Both use the same official
``nimble-python`` dependency, ``NIMBLE_API_KEY`` credential, and
``X-Client-Source: agno`` attribution.
"""

import json
import os
import re
from typing import Any, Dict, List, Literal, Optional

from agno.tools import Toolkit
from agno.utils.log import log_error

try:
    from nimble_python import AsyncNimble, Nimble
except ImportError:
    raise ImportError("`nimble-python` not installed. Please install using `pip install nimble-python`")

CLIENT_SOURCE = "agno"
_SECRET_PATTERNS = (
    re.compile(r"nvapi-[A-Za-z0-9_-]+"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"\b[0-9a-f]{40,}\b"),
)


def _redact_text(value: str) -> str:
    """Remove common credential shapes and the configured live Nimble key."""
    secret = os.getenv("NIMBLE_API_KEY")
    if secret and len(secret) >= 12:
        value = value.replace(secret, "<redacted>")
    for pattern in _SECRET_PATTERNS:
        value = pattern.sub("<redacted>", value)
    return value


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
        **kwargs: Any,
    ):
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

    @staticmethod
    def _success(response: Any) -> str:
        rendered = _redact_text(json.dumps(_model_to_dict(response), ensure_ascii=False, default=str))
        return rendered

    @staticmethod
    def _error(exc: Exception) -> str:
        return json.dumps(
            {
                "error": _redact_text(str(exc))[:500],
                "error_type": type(exc).__name__,
            }
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
