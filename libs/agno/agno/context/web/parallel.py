"""ParallelBackend — web research via Parallel (`parallel-web` SDK).

Exposes two tools:

- `web_search(objective)` — natural-language search; returns URL +
  excerpt pairs.
- `web_extract(url)` — full-content extraction.

Requires `PARALLEL_API_KEY`.
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


class ParallelBackend(ContextBackend):
    """Backend for `WebContextProvider` backed by Parallel's beta API."""

    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key: str = api_key if api_key else getenv("PARALLEL_API_KEY", "")
        self._client: Any = None

    def status(self) -> Status:
        if not self.api_key:
            return Status(ok=False, detail="PARALLEL_API_KEY not set")
        return Status(ok=True, detail="parallel.ai")

    async def astatus(self) -> Status:
        return self.status()

    def _get_client(self) -> Any:
        if self._client is None:
            from parallel import AsyncParallel  # type: ignore[import-not-found]

            self._client = AsyncParallel(api_key=self.api_key)
        return self._client

    def get_tools(self) -> list:
        backend = self

        @tool(name="web_search")
        async def web_search(objective: str, max_results: int = 8) -> str:
            """Search the web with a natural-language objective.

            Args:
                objective: What you're trying to find.
                max_results: Upper bound on results (default 8).

            Returns:
                JSON with `results: [{url, title, excerpts: [...]}, ...]`.
            """
            if not backend.api_key:
                return json.dumps({"error": "PARALLEL_API_KEY not configured"})
            try:
                out = await backend._get_client().beta.search(
                    objective=objective, max_results=max_results, mode="agentic"
                )
            except Exception as exc:
                log_error(f"web_search failed: {exc}")
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            results = []
            for r in (out.results or [])[:max_results]:
                results.append(
                    {
                        "url": getattr(r, "url", None),
                        "title": getattr(r, "title", None),
                        "excerpts": [e for e in (getattr(r, "excerpts", None) or [])][:5],
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
                return json.dumps({"error": "PARALLEL_API_KEY not configured"})
            try:
                result = await backend._get_client().beta.extract(urls=[url], full_content=True)
            except Exception as exc:
                log_error(f"web_extract failed for {url}: {exc}")
                return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
            if not result or not result.results:
                return json.dumps({"url": url, "content": ""})
            body = result.results[0].full_content or ""
            return json.dumps({"url": url, "content": body[:_MAX_EXTRACT_CHARS]})

        return [web_search, web_extract]
