"""ParallelMCPBackend — keyless (or keyed) web search via Parallel's MCP server.

Exposes Parallel's `web_search` + `web_fetch` tools to the calling
agent. The default endpoint is keyless; passing `api_key` (or setting
`PARALLEL_API_KEY`) authenticates via Bearer token and raises the
rate ceiling.

Two endpoints are supported:
- `search.parallel.ai/mcp` (default): allows anonymous use, Bearer token
  optional. Good for prototyping and single-user dev.
- `search.parallel.ai/mcp-oauth` (`authenticated=True`): authenticated-only,
  rejects anonymous requests with 401. Use for org-wide deployments, ZDR
  contexts, or MCP clients that negotiate auth via OAuth2.

Pairs with `ParallelBackend` (direct SDK) — the two are not equivalent:
the SDK exposes `web_search` + `web_extract`, whereas the MCP server
exposes `web_search` + `web_fetch` (token-efficient markdown). Pick
MCP when you want the compressed markdown output, SDK when you need
the raw extraction payload.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from os import getenv
from typing import Any, Optional

from agno import __version__ as _AGNO_VERSION
from agno.context.backend import ContextBackend
from agno.context.provider import Status
from agno.utils.log import log_info, log_warning

_BASE_URL = "https://search.parallel.ai/mcp"
_OAUTH_BASE_URL = "https://search.parallel.ai/mcp-oauth"
_DEFAULT_TOOLS: Sequence[str] = ("web_search", "web_fetch")


class ParallelMCPBackend(ContextBackend):
    """Backend for `WebContextProvider` that speaks to Parallel's MCP server."""

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        authenticated: bool = False,
        timeout_seconds: int = 60,
        include_tools: Sequence[str] | None = _DEFAULT_TOOLS,
        exclude_tools: Sequence[str] | None = None,
        tool_name_prefix: str | None = None,
    ) -> None:
        self.api_key = api_key if api_key is not None else (getenv("PARALLEL_API_KEY", "") or None)
        self.url = _OAUTH_BASE_URL if authenticated else _BASE_URL
        self.include_tools = list(include_tools) if include_tools is not None else None
        self.exclude_tools = list(exclude_tools) if exclude_tools is not None else None
        self.tool_name_prefix = tool_name_prefix
        # /mcp-oauth rejects anonymous requests with 401 (unlike /mcp), so
        # the endpoint is unusable without a key — fail fast instead of
        # surfacing a runtime 401 during asetup().
        if self.url == _OAUTH_BASE_URL and not self.api_key:
            raise ValueError("authenticated=True requires api_key (or PARALLEL_API_KEY env var).")
        # web_fetch returns server-compressed markdown for long pages and
        # regularly exceeds MCPTools' 10s default.
        self.timeout_seconds = timeout_seconds
        self._mcp_tools: Any = None
        # The keyless tier meters by session_id (per the web_fetch schema); one per backend
        # keeps this instance's fetches on one meter and correlates them in Parallel's logs.
        from uuid import uuid4

        self._fetch_session_id = uuid4().hex

    def status(self) -> Status:
        endpoint = self.url.rsplit("/", 1)[-1]
        return Status(ok=True, detail=f"search.parallel.ai/{endpoint} ({'keyed' if self.api_key else 'keyless'})")

    async def astatus(self) -> Status:
        return await asyncio.to_thread(self.status)

    def get_tools(self) -> list:
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        return [self._mcp_tools]

    def _headers(self) -> dict:
        headers: dict[str, Any] = {"User-Agent": f"agno/{_AGNO_VERSION}"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_tools(self) -> Any:
        from datetime import timedelta

        from agno.tools.mcp import MCPTools
        from agno.tools.mcp.params import StreamableHTTPClientParams

        headers = self._headers()

        server_params = StreamableHTTPClientParams(
            url=self.url,
            headers=headers,
            timeout=timedelta(seconds=self.timeout_seconds),
        )
        return MCPTools(
            server_params=server_params,
            transport="streamable-http",
            include_tools=self.include_tools,
            exclude_tools=self.exclude_tools,
            tool_name_prefix=self.tool_name_prefix,
            timeout_seconds=self.timeout_seconds,
        )

    async def asetup(self) -> None:
        """Connect to the Parallel MCP server.

        On failure, logs a warning; the web backend will be
        unavailable until the next restart.
        """
        if self._mcp_tools is None:
            self._mcp_tools = self._build_tools()
        if getattr(self._mcp_tools, "initialized", False):
            return
        log_info(f"ParallelMCPBackend: connecting to {self.url} ({'keyed' if self.api_key else 'keyless'})")
        try:
            await self._mcp_tools._connect()
        except Exception as exc:
            log_warning(f"ParallelMCPBackend setup failed — {type(exc).__name__}: {exc}.")
            self._mcp_tools = None

    async def aclose(self) -> None:
        """Close the MCP session and clear the cached tool handle."""
        tools = self._mcp_tools
        self._mcp_tools = None
        if tools is None:
            return
        try:
            await tools.close()
        except Exception as exc:
            log_warning(f"ParallelMCPBackend close raised {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # Page fetching (knowledge readers fetch through this)
    # ------------------------------------------------------------------

    extractor_id = "parallel_mcp"
    fetch_batch_limit = 20  # web_fetch takes up to 20 URLs per request

    def _pages_from_fetch_payload(self, urls: list, payload: dict, max_chars: int = 50_000) -> list:
        from agno.knowledge.reader.page_fetcher import FetchedPage

        by_url: dict = {}
        for entry in payload.get("results") or []:
            if isinstance(entry, dict) and entry.get("url"):
                by_url[entry["url"]] = entry
        errors_by_url: dict = {}
        for entry in payload.get("errors") or []:
            if isinstance(entry, dict) and entry.get("url"):
                errors_by_url[entry["url"]] = str(entry.get("error") or entry.get("message") or "fetch error")

        pages = []
        for url in urls:
            entry = by_url.get(url)
            content = None
            title = None
            if entry is not None:
                content = entry.get("full_content") or "\n".join(entry.get("excerpts") or [])
                title = entry.get("title")
            if content:
                # The MCP tool has no per-page size parameter, so the cap is applied here
                pages.append(
                    FetchedPage(url=url, content=content[:max_chars], title=title, extractor=self.extractor_id)
                )
            else:
                pages.append(FetchedPage(url=url, error=errors_by_url.get(url, "empty"), extractor=self.extractor_id))
        return pages

    async def afetch_many(self, urls: list, *, max_chars: int = 50_000) -> list:
        """Fetch up to ``fetch_batch_limit`` pages with one ``web_fetch`` call.

        Opens and closes its own MCP session on the calling task — the HTTP transport keeps
        anyio cancel scopes that must be entered and exited on one task, so a fetch never
        reuses the provider-side session ``get_tools()`` manages.
        """
        import json
        from datetime import timedelta

        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        from agno.knowledge.reader.page_fetcher import FetchedPage, RateLimited, rate_limit_from_text

        arguments: dict[str, Any] = {"urls": list(urls), "full_content": True}
        if not self.api_key:
            arguments["session_id"] = self._fetch_session_id

        try:
            async with streamablehttp_client(
                url=self.url, headers=self._headers(), timeout=timedelta(seconds=self.timeout_seconds)
            ) as (read, write, _):
                async with ClientSession(
                    read, write, read_timeout_seconds=timedelta(seconds=self.timeout_seconds)
                ) as session:
                    await session.initialize()
                    result = await session.call_tool("web_fetch", arguments)
        except Exception as e:
            message = str(e)
            if rate_limit_from_text(message):
                raise RateLimited(message) from e
            return [
                FetchedPage(url=url, error=f"{type(e).__name__}: {message}"[:300], extractor=self.extractor_id)
                for url in urls
            ]

        text = "".join(getattr(block, "text", "") or "" for block in result.content or [])
        if result.isError:
            if rate_limit_from_text(text):
                raise RateLimited(text[:300])
            return [
                FetchedPage(url=url, error=(text or "tool error")[:300], extractor=self.extractor_id) for url in urls
            ]

        try:
            payload = json.loads(text) if text else {}
        except ValueError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return self._pages_from_fetch_payload(list(urls), payload, max_chars=max_chars)

    def fetch_many(self, urls: list, *, max_chars: int = 50_000) -> list:
        """Sync variant: runs :meth:`afetch_many` on a private event loop in a worker thread.

        The MCP client is async-only, so the sync path pays one thread per call. Works from
        inside a running event loop too, because the loop lives on its own thread.
        """
        import threading

        outcome: dict[str, Any] = {}

        def runner() -> None:
            loop = asyncio.new_event_loop()
            try:
                outcome["pages"] = loop.run_until_complete(self.afetch_many(list(urls), max_chars=max_chars))
            except BaseException as e:  # noqa: BLE001 - re-raised on the calling thread
                outcome["error"] = e
            finally:
                try:
                    loop.run_until_complete(loop.shutdown_asyncgens())
                except Exception:
                    pass
                loop.close()

        thread = threading.Thread(target=runner, name="parallel-mcp-fetch", daemon=True)
        thread.start()
        thread.join()
        if "error" in outcome:
            raise outcome["error"]
        return outcome["pages"]
