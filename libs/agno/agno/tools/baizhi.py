import asyncio
import json
import logging
import re
from contextvars import ContextVar
from ipaddress import ip_address
from os import getenv
from typing import Any, Callable, Coroutine, Dict, List, Literal, Optional
from urllib.parse import urlsplit

from pydantic import SecretStr

from agno.tools import Toolkit

try:
    import anyio
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
except ImportError:
    raise ImportError("BaizhiTools requires MCP. Install it with `pip install 'agno[mcp]'`.")


_BAIZHI_MCP_URL = "https://agent-toolkit.app.baizhi.cloud/mcp"
_ACTIVE_KEY: ContextVar[Optional[str]] = ContextVar("agno_baizhi_active_key", default=None)


class _SDKLogFilter(logging.Filter):
    """Redact SDK diagnostics only while this toolkit owns the calling context."""

    def filter(self, record: logging.LogRecord) -> bool:
        key = _ACTIVE_KEY.get()
        if key:
            record.msg = record.getMessage().replace(key, "[REDACTED]")
            record.args = ()
            # SDK parse exceptions include raw provider bodies. Keep the error
            # message, but do not forward those bodies through a traceback.
            record.exc_info = None
            record.exc_text = None
            record.stack_info = None
        return True


# Filters attach to the SDK emitters, not the root logger. Outside a Baizhi call
# their messages, arguments, levels and tracebacks remain unchanged. ContextVar
# also keeps concurrent calls and unrelated tasks isolated.
for _logger_name in (
    "mcp.client.streamable_http",
    "client",
    "mcp.shared.jsonrpc_dispatcher",
    "mcp.shared.dispatcher",
):
    logging.getLogger(_logger_name).addFilter(_SDKLogFilter())


class BaizhiTools(Toolkit):
    """Search, read, and extract web pages through Baizhi's hosted MCP service.

    Only the three explicitly enabled tools are exposed, even when the remote
    catalog grows. The backend is hosted and closed source. Calls may consume
    paid credits; supply your own key and keep Agno's tool approval controls.

    Args:
        api_key: Raw API key; defaults to BAIZHI_API_KEY only when omitted.
        enable_search: Expose websearch_search. Defaults to True.
        enable_scrape: Expose web_scrape. Defaults to True.
        enable_extract: Expose web_extract. Defaults to True.
        all: Enable all three supported tools, not the entire remote catalog.
        timeout: Total seconds for one MCP session, including initialization.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        enable_search: bool = True,
        enable_scrape: bool = True,
        enable_extract: bool = True,
        all: bool = False,
        timeout: int = 60,
        **kwargs: Any,
    ):
        key = getenv("BAIZHI_API_KEY") if api_key is None else api_key
        if not key or not key.strip():
            raise ValueError("Set BAIZHI_API_KEY or pass api_key before using BaizhiTools.")
        if any(char.isspace() for char in key):
            raise ValueError("Baizhi api_key must be the raw key without whitespace or the Bearer prefix.")
        if timeout <= 0:
            raise ValueError("timeout must be positive.")
        self._api_key = SecretStr(key)
        self._enabled_tools = set()
        tools: List[Any] = []
        async_tools = []
        for enabled, sync_method, async_method in (
            (enable_search, self.websearch_search, self.awebsearch_search),
            (enable_scrape, self.web_scrape, self.aweb_scrape),
            (enable_extract, self.web_extract, self.aweb_extract),
        ):
            if enabled or all:
                self._enabled_tools.add(sync_method.__name__)
                tools.append(sync_method)
                async_tools.append((async_method, sync_method.__name__))
        super().__init__(name="baizhi_tools", tools=tools, async_tools=async_tools, timeout=timeout, **kwargs)

    @staticmethod
    def _error(message: str) -> str:
        return json.dumps({"isError": True, "content": [{"type": "text", "text": message}]})

    def _run_sync(self, method: Callable[..., Coroutine[Any, Any, str]], **arguments: Any) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(method(**arguments))
        return self._error("Use the async BaizhiTools method inside a running event loop.")

    def _redact(self, value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(self._api_key.get_secret_value(), "[REDACTED]")
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, dict):
            return {self._redact(key): self._redact(item) for key, item in value.items()}
        return value

    @staticmethod
    async def _check_request(request: httpx2.Request) -> None:
        # The MCP SDK manages redirects independently of the HTTP client setting.
        # Enforce the fixed endpoint before every request, including SDK redirects.
        if str(request.url) != _BAIZHI_MCP_URL:
            raise ValueError("Baizhi MCP requests must use the configured endpoint without redirects.")

    @staticmethod
    def _valid_domain(value: str) -> bool:
        if not isinstance(value, str) or not value or any(char.isspace() for char in value):
            return False
        try:
            ip_address(value)
            return True
        except ValueError:
            pass
        try:
            domain = value.encode("idna").decode("ascii")
        except UnicodeError:
            return False
        return (
            len(domain) <= 253
            and "." in domain
            and all(re.fullmatch(r"(?!-)[a-zA-Z0-9-]{1,63}(?<!-)", label) for label in domain.split("."))
        )

    async def _call(self, name: str, arguments: Dict[str, Any]) -> str:
        if name not in self._enabled_tools:
            return self._error("This Baizhi tool is disabled.")
        # Each operation owns its session, so sync calls never reuse resources
        # from a closed event loop and concurrent async calls cannot share state.
        # No application retry: a timeout can occur after a billable call began.
        log_context = _ACTIVE_KEY.set(self._api_key.get_secret_value())
        try:
            with anyio.fail_after(self.timeout):
                async with httpx2.AsyncClient(
                    headers={"Authorization": f"Bearer {self._api_key.get_secret_value()}"},
                    timeout=self.timeout,
                    follow_redirects=False,
                    trust_env=False,
                    event_hooks={"request": [self._check_request]},
                ) as client:
                    async with streamable_http_client(_BAIZHI_MCP_URL, http_client=client) as (read, write):
                        async with ClientSession(read, write) as session:
                            await session.initialize()
                            result = await session.call_tool(name, arguments=arguments)
                            return json.dumps(
                                self._redact(result.model_dump(mode="json", by_alias=True, exclude_none=True))
                            )
        except TimeoutError:
            return self._error("Baizhi MCP request timed out; check its status before retrying a billable call.")
        except Exception:
            # Transport exceptions may contain request headers or response bodies.
            return self._error("Baizhi MCP request failed. Check your key, account quota, and service availability.")
        finally:
            _ACTIVE_KEY.reset(log_context)

    def websearch_search(
        self,
        query: str,
        count: int = 10,
        time_range: Literal["day", "week", "month", "year"] = "month",
        need_summary: bool = False,
        domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> str:
        """Search public web pages. This call may consume paid credits.

        Args:
            query: Search terms; put site restrictions in domains, not in query.
            count: Maximum results, from 1 to 50.
            time_range: Result freshness: day, week, month, or year.
            need_summary: Request summaries for individual results.
            domains: Restrict results to these bare domains or IPs, without URL paths.
            exclude_domains: Exclude these bare domains or IPs.

        Returns:
            JSON containing MCP content, structuredContent when provided, and isError.
        """
        return self._run_sync(
            self.awebsearch_search,
            query=query,
            count=count,
            time_range=time_range,
            need_summary=need_summary,
            domains=domains,
            exclude_domains=exclude_domains,
        )

    async def awebsearch_search(
        self,
        query: str,
        count: int = 10,
        time_range: Literal["day", "week", "month", "year"] = "month",
        need_summary: bool = False,
        domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> str:
        """Search public web pages asynchronously. Calls may consume paid credits.

        Args:
            query: Search terms; put site restrictions in domains, not in query.
            count: Maximum results, from 1 to 50.
            time_range: Result freshness: day, week, month, or year.
            need_summary: Request summaries for individual results.
            domains: Restrict results to these bare domains or IPs, without URL paths.
            exclude_domains: Exclude these bare domains or IPs.
        """
        if not query.strip() or not 1 <= count <= 50 or time_range not in ("day", "week", "month", "year"):
            return self._error("Provide nonempty query, count from 1 to 50, and a valid time_range.")
        for values in (domains, exclude_domains):
            if values is not None and (not isinstance(values, list) or any(not self._valid_domain(v) for v in values)):
                return self._error("Search domains must be bare domains or IPs, without URL paths or credentials.")
        arguments: Dict[str, Any] = dict(query=query, count=count, time_range=time_range, need_summary=need_summary)
        filters = {key: value for key, value in (("domains", domains), ("exclude_domains", exclude_domains)) if value}
        if filters:
            arguments["filter"] = filters
        return await self._call("websearch_search", arguments)

    @staticmethod
    def _valid_url(url: str) -> bool:
        try:
            parsed = urlsplit(url)
            return (
                parsed.scheme in ("http", "https")
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
            )
        except ValueError:
            return False

    def web_scrape(
        self,
        url: str,
        return_format: Literal["markdown", "json"] = "markdown",
        accept_language: Optional[str] = None,
    ) -> str:
        """Read a public web page without requesting a downloadable export. May consume credits.

        Args:
            url: Absolute HTTP or HTTPS page URL.
            return_format: Page text format: markdown or json.
            accept_language: Preferred page language, for example zh-CN.
        """
        return self._run_sync(self.aweb_scrape, url=url, return_format=return_format, accept_language=accept_language)

    async def aweb_scrape(
        self,
        url: str,
        return_format: Literal["markdown", "json"] = "markdown",
        accept_language: Optional[str] = None,
    ) -> str:
        """Read a public web page asynchronously without requesting an export. May consume credits.

        Args:
            url: Absolute HTTP or HTTPS page URL.
            return_format: Page text format: markdown or json.
            accept_language: Preferred page language, for example zh-CN.
        """
        if not self._valid_url(url) or return_format not in ("markdown", "json"):
            return self._error("Provide an HTTP(S) URL and return_format markdown or json.")
        arguments: Dict[str, Any] = dict(url=url, return_format=return_format, download=False)
        if accept_language is not None:
            arguments["accept_language"] = accept_language
        return await self._call("web_scrape", arguments)

    def web_extract(
        self,
        url: str,
        fields: Optional[Dict[str, str]] = None,
        instruction: Optional[str] = None,
        accept_language: Optional[str] = None,
    ) -> str:
        """Extract specified information from a public page. May consume paid credits.

        Args:
            url: Absolute HTTP or HTTPS page URL.
            fields: Map field names to string, number, boolean, or array. Supply fields or instruction.
            instruction: Natural language extraction request; required when fields is empty.
            accept_language: Preferred page language, for example zh-CN.
        """
        return self._run_sync(
            self.aweb_extract, url=url, fields=fields, instruction=instruction, accept_language=accept_language
        )

    async def aweb_extract(
        self,
        url: str,
        fields: Optional[Dict[str, str]] = None,
        instruction: Optional[str] = None,
        accept_language: Optional[str] = None,
    ) -> str:
        """Extract information asynchronously without requesting an export. May consume credits.

        Args:
            url: Absolute HTTP or HTTPS page URL.
            fields: Map field names to string, number, boolean, or array. Supply fields or instruction.
            instruction: Natural language extraction request; required when fields is empty.
            accept_language: Preferred page language, for example zh-CN.
        """
        if not self._valid_url(url) or not (fields or (instruction and instruction.strip())):
            return self._error("Provide an HTTP(S) URL and at least one of fields or instruction.")
        if fields and any(value not in ("string", "number", "boolean", "array") for value in fields.values()):
            return self._error("Field types must be string, number, boolean, or array.")
        arguments: Dict[str, Any] = dict(url=url, download=False)
        if fields:
            arguments["fields"] = fields
        if instruction:
            arguments["instruction"] = instruction
        if accept_language is not None:
            arguments["accept_language"] = accept_language
        return await self._call("web_extract", arguments)
