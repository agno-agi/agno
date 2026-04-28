"""ExaBackend — web research via Exa's SDK (`exa-py`).

Exposes two tools:

- `web_search(query)` — returns URL + title + excerpt for each result.
- `web_extract(url)` — fetches a URL's full content as text.

Requires `EXA_API_KEY`.
"""

from __future__ import annotations

import json
from os import getenv
from typing import Any

from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.tools import tool
from agno.utils.log import log_error

_MAX_EXTRACT_CHARS = 50_000


class ExaBackend(ContextBackend):
    """Backend for `WebContextProvider` using Exa's search + contents APIs."""

    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key: str = api_key if api_key else getenv("EXA_API_KEY", "")
        self._client: Any = None

    def status(self) -> Status:
        if not self.api_key:
            return Status(ok=False, detail="EXA_API_KEY not set")
        return Status(ok=True, detail="exa.ai")

    async def astatus(self) -> Status:
        return self.status()

    def _get_client(self) -> Any:
        if self._client is None:
            from exa_py import AsyncExa  # type: ignore[import-not-found]

            self._client = AsyncExa(api_key=self.api_key)
        return self._client

    def get_tools(self) -> list:
        backend = self

        @tool(name="web_search")
        async def web_search(query: str, max_results: int = 8) -> str:
            """Search the web; returns URL + title + excerpt for each result.

            Args:
                query: The search query.
                max_results: Upper bound on results (default 8).

            Returns:
                JSON with `results: [{url, title, excerpt}, ...]`.
            """
            if not backend.api_key:
                return json.dumps({"error": "EXA_API_KEY not configured"})
            try:
                out = await backend._get_client().search_and_contents(query, num_results=max_results, text=True)
            except Exception as exc:
                log_error(f"web_search failed: {exc}")
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            results = []
            for r in (getattr(out, "results", None) or [])[:max_results]:
                results.append(
                    {
                        "url": getattr(r, "url", None),
                        "title": getattr(r, "title", None),
                        "excerpt": (getattr(r, "text", "") or "")[:500],
                    }
                )
            return json.dumps({"results": results})

        @tool(name="web_extract")
        async def web_extract(url: str) -> str:
            """Fetch a URL's full content as text.

            Args:
                url: The URL to fetch.

            Returns:
                JSON with `{url, content}` or `{error}`.
            """
            if not backend.api_key:
                return json.dumps({"error": "EXA_API_KEY not configured"})
            try:
                out = await backend._get_client().get_contents([url], text=True)
            except Exception as exc:
                log_error(f"web_extract failed for {url}: {exc}")
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            results = getattr(out, "results", None) or []
            if not results:
                return json.dumps({"url": url, "content": ""})
            body = getattr(results[0], "text", "") or ""
            return json.dumps({"url": url, "content": body[:_MAX_EXTRACT_CHARS]})

        return [web_search, web_extract]
