import asyncio
import inspect
import time
import weakref
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable, Literal, Optional, Tuple, Union

from agno.tools import Toolkit
from agno.tools.function import Function
from agno.tools.mcp.params import SSEClientParams, StreamableHTTPClientParams
from agno.utils.log import log_debug, log_error, log_warning
from agno.utils.mcp import MCPSession, get_default_toolkit_name, get_entrypoint_for_tool, ping_session, prepare_command

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run import RunContext
    from agno.team.team import Team

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import get_default_environment
except ModuleNotFoundError:
    raise ImportError("`mcp` not installed. Please install using `pip install 'mcp>=2.1.0,<3.0.0'`")


_FASTMCP_INSTALL_HINT = (
    "`fastmcp` not installed. MCPTools builds its connections with it. "
    "Please install using `pip install 'fastmcp>=4.0.0,<5'`"
)


def _import_fastmcp() -> Any:
    """Import fastmcp, raising the same shape of error the ``mcp`` guard above does.

    fastmcp is imported lazily because it is only needed when the toolkit builds its own
    connection, but a missing install must still say so: connect() swallows exceptions,
    so an unguarded ModuleNotFoundError surfaces only as an agent running with no tools.
    """
    try:
        import fastmcp
    except ModuleNotFoundError:
        raise ImportError(_FASTMCP_INSTALL_HINT)
    return fastmcp


def _retain_session_transport_class() -> Any:
    """A transport that keeps the server session alive when the client closes.

    fastmcp's StreamableHttpTransport calls the SDK's ``streamable_http_client`` without
    ``terminate_on_close``, so the SDK default (send DELETE on close) always wins and a
    caller asking to retain the session silently loses it.

    This subclasses fastmcp's public ``ClientTransport`` base and drives the MCP SDK
    directly, which is the layer that owns the flag. Nothing is copied from fastmcp's
    own transport internals, so a 4.x upgrade cannot silently change what this does --
    it depends only on ``ClientTransport``'s documented contract and the SDK signature.

    Used only when the caller asks to retain the session; every other connection stays
    on fastmcp's stock transport.
    """
    import contextlib

    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    _import_fastmcp()
    from fastmcp.client.transports import ClientTransport

    class _RetainSessionTransport(ClientTransport):
        def __init__(
            self,
            url: str,
            *,
            headers: Optional[dict] = None,
            httpx_client_factory: Any = None,
            terminate_on_close: Any = False,
        ) -> None:
            super().__init__()
            self.url = url
            self.headers = headers or {}
            self.httpx_client_factory = httpx_client_factory
            self._terminate_on_close = bool(terminate_on_close)
            self._session_id: Optional[str] = None

        async def _capture_session_id(self, response: Any) -> None:
            """httpx response hook: record the server's ``mcp-session-id``.

            The SDK's client no longer surfaces the id, so it is read off the response
            headers the way fastmcp's own transport does. Without this
            ``get_session_id()`` stays None here and the tool-call trace spans lose it.
            """
            sid = response.headers.get("mcp-session-id")
            if sid:
                self._session_id = sid

        def get_session_id(self) -> Optional[str]:
            return self._session_id

        @contextlib.asynccontextmanager
        async def connect_session(self, *, transport_options: Any = None, **session_kwargs: Any) -> Any:
            from mcp.shared._httpx_utils import create_mcp_http_client

            factory = self.httpx_client_factory or create_mcp_http_client
            http_client = factory(headers=dict(self.headers), auth=None)
            self._session_id = None
            http_client.event_hooks.setdefault("response", []).append(self._capture_session_id)

            session_class = getattr(transport_options, "session_class", None) or ClientSession
            async with (
                http_client,
                streamable_http_client(
                    self.url,
                    http_client=http_client,
                    terminate_on_close=self._terminate_on_close,
                ) as (read_stream, write_stream),
                session_class(read_stream, write_stream, **session_kwargs) as session,
            ):
                yield session

    return _RetainSessionTransport


def _http_client_factory(timeout: Any, sse_read_timeout: Any) -> Any:
    """Build the httpx client factory that keeps operation and stream timeouts distinct.

    ``timeout`` covers connect/write/pool; ``sse_read_timeout`` bounds the long-lived
    stream read. Either knob left unset keeps the SDK default (30s ops, 300s read)
    rather than going unbounded -- ``read=None`` means no read limit at all.
    """
    import httpx2
    from mcp.shared._httpx_utils import create_mcp_http_client

    # A timedelta may arrive from an older config; normalize to seconds.
    if timeout is not None and hasattr(timeout, "total_seconds"):
        timeout = timeout.total_seconds()
    if sse_read_timeout is not None and hasattr(sse_read_timeout, "total_seconds"):
        sse_read_timeout = sse_read_timeout.total_seconds()

    op_timeout = float(timeout) if timeout is not None else 30.0
    read_timeout = float(sse_read_timeout) if sse_read_timeout is not None else 300.0

    def factory(*, headers: Any = None, auth: Any = None, **_: Any) -> Any:
        return create_mcp_http_client(
            headers=headers,
            auth=auth,
            timeout=httpx2.Timeout(op_timeout, read=read_timeout),
        )

    return factory


def _is_fastmcp_client(session: Any) -> bool:
    """True when the session is a fastmcp Client (which handshakes on its own)."""
    try:
        from fastmcp import Client
    except ModuleNotFoundError:
        return False
    return isinstance(session, Client)


def _build_fastmcp_client(
    transport: str,
    params: dict,
    server_params: Any,
    timeout_seconds: float,
    protocol_mode: str,
) -> Any:
    """Build a ``fastmcp.Client`` for one connection.

    fastmcp's transports take ``headers`` directly, so the httpx client no longer has
    to be assembled by hand, and the client drives its own connect/initialize/close --
    ``async with`` is the whole lifecycle. ``protocol_mode`` selects the protocol era:
    "legacy" keeps the session-based behaviour this toolkit has always had, "auto"
    negotiates the newest era both sides support.
    """
    _import_fastmcp()
    from fastmcp import Client
    from fastmcp.client.transports import SSETransport, StdioTransport, StreamableHttpTransport

    if transport == "streamable-http":
        # fastmcp derives the HTTP read timeout from the session timeout, which would
        # cut long-lived streams down to it. Build the httpx client here instead so
        # ``sse_read_timeout`` keeps bounding the stream read, as params.py documents.
        transport_kwargs: dict = {
            "headers": params.get("headers") or None,
            "httpx_client_factory": _http_client_factory(params.get("timeout"), params.get("sse_read_timeout")),
        }
        # fastmcp's transport drops terminate_on_close, which would tear down a session
        # the caller asked to keep. Swap in the subclass that forwards it, and only then
        # -- the default path stays on the stock transport.
        #
        # Falsy, not just False: StreamableHTTPClientParams defaults the field to None,
        # and the SDK gates the DELETE on `session_id and terminate_on_close`, so None
        # has always meant "keep the session". Treating it as True here would silently
        # start terminating sessions for every caller using the dataclass default.
        terminate_on_close = params.get("terminate_on_close", True)
        if terminate_on_close:
            transport_cls: Any = StreamableHttpTransport
        else:
            transport_cls = _retain_session_transport_class()
            transport_kwargs["terminate_on_close"] = terminate_on_close
        fastmcp_transport: Any = transport_cls(params["url"], **transport_kwargs)
        timeout = params.get("timeout")
    elif transport == "sse":
        # Same split as streamable-http: without the factory, fastmcp derives the whole
        # httpx timeout from the session read timeout and the caller's connect/write
        # timeout is lost. SSETransport keeps its own sse_read_timeout for the stream.
        fastmcp_transport = SSETransport(
            params["url"],
            headers=params.get("headers") or None,
            sse_read_timeout=params.get("sse_read_timeout"),
            httpx_client_factory=_http_client_factory(params.get("timeout"), params.get("sse_read_timeout")),
        )
        timeout = params.get("timeout")
    else:
        # stdio carries no headers: the server is a subprocess, not an HTTP endpoint.
        # keep_alive=False because close() must stop that subprocess. fastmcp defaults it
        # on, which would leave one orphaned child per connect/close cycle -- and a
        # non-AgentOS agent run does one cycle per run.
        fastmcp_transport = StdioTransport(
            command=server_params.command,
            args=list(server_params.args or []),
            env=dict(server_params.env) if server_params.env else None,
            cwd=getattr(server_params, "cwd", None),
            keep_alive=False,
        )
        timeout = None

    # A timedelta may arrive from an older config; normalize to seconds.
    if timeout is not None and hasattr(timeout, "total_seconds"):
        timeout = timeout.total_seconds()
    client_timeout = min(timeout_seconds, float(timeout)) if timeout is not None else float(timeout_seconds)

    return Client(fastmcp_transport, timeout=client_timeout, mode=protocol_mode)


class MCPTools(Toolkit):
    """
    A toolkit for integrating Model Context Protocol (MCP) servers with Agno agents.
    This allows agents to access tools, resources, and prompts exposed by MCP servers.

    Can be used in three ways:
    1. Direct initialization with a ClientSession
    2. As an async context manager with StdioServerParameters
    3. As an async context manager with SSE or Streamable HTTP client parameters
    """

    def __init__(
        self,
        command: Optional[str] = None,
        *,
        name: Optional[str] = None,
        url: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        transport: Optional[Literal["stdio", "sse", "streamable-http"]] = None,
        server_params: Optional[Union[StdioServerParameters, SSEClientParams, StreamableHTTPClientParams]] = None,
        session: Optional[ClientSession] = None,
        timeout_seconds: int = 10,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        refresh_connection: bool = False,
        tool_name_prefix: Optional[str] = None,
        headers: Optional[dict[str, Any]] = None,
        header_provider: Optional[Callable[..., dict[str, Any]]] = None,
        protocol_mode: Literal["legacy", "auto"] = "legacy",
        **kwargs,
    ):
        """
        Initialize the MCP toolkit.

        Args:
            name: The toolkit name. Defaults to a stable name derived from the connection
                parameters (URL or command), so multiple MCP toolkits in one registry stay
                distinguishable and selectable by name. Falls back to "MCPTools" when only
                a session is provided.
            session: An initialized MCP ClientSession connected to an MCP server. When
                omitted, the toolkit builds its own connection and ``self.session`` holds
                a ``fastmcp.Client`` instead.
            server_params: Parameters for creating a new session
            command: The command to run to start the server. Should be used in conjunction with env.
            url: The URL endpoint for SSE or Streamable HTTP connection when transport is "sse" or "streamable-http".
            env: The environment variables to pass to the server. Should be used in conjunction with command.
            client: The underlying MCP client (optional, used to prevent garbage collection)
            timeout_seconds: Read timeout in seconds for the MCP client
            include_tools: Optional list of tool names to include (if None, includes all)
            exclude_tools: Optional list of tool names to exclude (if None, excludes none)
            transport: The transport protocol to use, either "stdio" or "sse" or "streamable-http".
                       Defaults to "streamable-http" when url is provided, otherwise defaults to "stdio".
            refresh_connection: If True, the connection and tools will be refreshed on each run
            headers: Optional static HTTP headers applied when establishing the MCP session
                (connect/handshake) and merged into per-run sessions. Only relevant with
                HTTP transports (Streamable HTTP or SSE). Prefer this for connect-time auth
                tokens; use header_provider for per-run dynamic values.
            header_provider: Optional function to generate dynamic HTTP headers.
                Only relevant with HTTP transports (Streamable HTTP or SSE).
                Invoked during connect() so secured servers receive auth on the handshake,
                and again per agent run when run context is available.
            protocol_mode: Which MCP protocol era to negotiate. "legacy" (the default)
                keeps the session-based era (<= 2025-11-25), where the connection is
                long-lived and liveness checks work. "auto" negotiates the newest era both
                sides support; the 2026-07-28 era is sessionless, so a server that gates on
                initialize, keeps per-session state, or elicits mid-tool needs "legacy".
        """
        # Extract these before super().__init__() to bypass early validation
        # (tools aren't available until build_tools() is called)
        requires_confirmation_tools = kwargs.pop("requires_confirmation_tools", None)
        external_execution_required_tools = kwargs.pop("external_execution_required_tools", None)
        stop_after_tool_call_tools = kwargs.pop("stop_after_tool_call_tools", None)
        show_result_tools = kwargs.pop("show_result_tools", None)

        super().__init__(
            name=name or get_default_toolkit_name(url=url, command=command, server_params=server_params),
            **kwargs,
        )

        if url is not None:
            if transport is None:
                transport = "streamable-http"
            elif transport == "stdio":
                log_warning(
                    "Transport cannot be 'stdio' when url is provided. Setting transport to 'streamable-http' instead."
                )
                transport = "streamable-http"

        if transport == "sse":
            log_warning(
                "SSE as a standalone transport is deprecated and will be removed in a future release. "
                "Please use Streamable HTTP instead."
            )

        # Set these after `__init__` to bypass the `_check_tools_filters`
        # because tools are not available until `initialize()` is called.
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools
        self.requires_confirmation_tools = requires_confirmation_tools or []
        self.external_execution_required_tools = external_execution_required_tools or []
        self.stop_after_tool_call_tools = stop_after_tool_call_tools or []
        self.show_result_tools = show_result_tools or []
        self.refresh_connection = refresh_connection
        self.tool_name_prefix = tool_name_prefix
        self.protocol_mode = protocol_mode

        if session is None and server_params is None:
            if transport == "sse" and url is None:
                raise ValueError("One of 'url' or 'server_params' parameters must be provided when using SSE transport")
            if transport == "stdio" and command is None:
                raise ValueError(
                    "One of 'command' or 'server_params' parameters must be provided when using stdio transport"
                )
            if transport == "streamable-http" and url is None:
                raise ValueError(
                    "One of 'url' or 'server_params' parameters must be provided when using Streamable HTTP transport"
                )

        # Ensure the received server_params are valid for the given transport
        if server_params is not None:
            if transport == "sse":
                if not isinstance(server_params, SSEClientParams):
                    raise ValueError(
                        "If using the SSE transport, server_params must be an instance of SSEClientParams."
                    )
            elif transport == "stdio":
                if not isinstance(server_params, StdioServerParameters):
                    raise ValueError(
                        "If using the stdio transport, server_params must be an instance of StdioServerParameters."
                    )
            elif transport == "streamable-http":
                if not isinstance(server_params, StreamableHTTPClientParams):
                    raise ValueError(
                        "If using the streamable-http transport, server_params must be an instance of StreamableHTTPClientParams."
                    )

        self.transport = transport

        # Stored separately from any subclass attribute named `headers`
        # (e.g. MCPToolbox uses `self.headers` for toolbox-core credentials).
        self._mcp_headers: Optional[dict[str, Any]] = None
        if headers is not None:
            if self.transport not in ["sse", "streamable-http"]:
                raise ValueError(
                    f"headers is not supported with '{self.transport}' transport. "
                    "Use 'sse' or 'streamable-http' transport instead."
                )
            self._mcp_headers = headers

        self.header_provider = None
        if header_provider is not None:
            if self.transport not in ["sse", "streamable-http"]:
                raise ValueError(
                    f"header_provider is not supported with '{self.transport}' transport. "
                    "Use 'sse' or 'streamable-http' transport instead."
                )
            log_debug("Dynamic header support enabled for MCP tools")
            self.header_provider = header_provider

        self.timeout_seconds = timeout_seconds
        # Either a caller-supplied ClientSession or the fastmcp Client built for an
        # internally-created connection; MCPSession is the surface both satisfy.
        self.session: Optional[MCPSession] = session
        self.server_params: Optional[Union[StdioServerParameters, SSEClientParams, StreamableHTTPClientParams]] = (
            server_params
        )
        self.url = url

        # Merge provided env with system env
        if env is not None:
            env = {
                **get_default_environment(),
                **env,
            }
        else:
            env = get_default_environment()

        if command is not None and transport not in ["sse", "streamable-http"]:
            parts = prepare_command(command)
            cmd = parts[0]
            arguments = parts[1:] if len(parts) > 1 else []
            self.server_params = StdioServerParameters(command=cmd, args=arguments, env=env)

        self._client = client

        self._initialized = False
        self._connection_task = None
        self._active_contexts: list[Any] = []
        self._context = None
        self._session_context = None

        # Session management for per-agent-run sessions with dynamic headers
        # Maps run_id to (session, timestamp) for TTL-based cleanup
        self._run_sessions: dict[str, Tuple[MCPSession, float]] = {}
        self._run_session_contexts: dict[str, Any] = {}  # Maps run_id to its connection context
        self._session_ttl_seconds: float = 300.0  # 5 minutes TTL for MCP sessions
        self._session_lock: Optional[asyncio.Lock] = None  # Lazily created lock for session creation

        def cleanup():
            """Cancel active connections"""
            if self._connection_task and not self._connection_task.done():
                self._connection_task.cancel()

        # Setup cleanup logic before the instance is garbage collected
        self._cleanup_finalizer = weakref.finalize(self, cleanup)

    @property
    def initialized(self) -> bool:
        return self._initialized

    @property
    def _session_creation_lock(self) -> asyncio.Lock:
        """Lazily create an asyncio lock for serializing session creation."""
        if self._session_lock is None:
            self._session_lock = asyncio.Lock()
        return self._session_lock

    def _call_header_provider(
        self,
        run_context: Optional["RunContext"] = None,
        agent: Optional["Agent"] = None,
        team: Optional["Team"] = None,
    ) -> dict[str, Any]:
        """Call the header_provider with run_context, agent, and/or team based on its signature.

        Args:
            run_context: The RunContext for the current agent run
            agent: The Agent instance (if running within an agent)
            team: The Team instance (if running within a team)

        Returns:
            dict[str, Any]: The headers returned by the header_provider
        """
        header_provider = getattr(self, "header_provider", None)
        if header_provider is None:
            return {}

        try:
            sig = inspect.signature(header_provider)
            param_names = set(sig.parameters.keys())

            # Build kwargs based on what the function accepts
            call_kwargs: dict[str, Any] = {}

            if "run_context" in param_names:
                call_kwargs["run_context"] = run_context
            if "agent" in param_names:
                call_kwargs["agent"] = agent
            if "team" in param_names:
                call_kwargs["team"] = team

            # Check if function accepts **kwargs (VAR_KEYWORD)
            has_var_keyword = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())

            if has_var_keyword:
                # Pass all available context to **kwargs
                call_kwargs = {"run_context": run_context, "agent": agent, "team": team}
                return header_provider(**call_kwargs)
            elif call_kwargs:
                return header_provider(**call_kwargs)
            else:
                # Function takes no recognized parameters - check for positional
                positional_params = [
                    p
                    for p in sig.parameters.values()
                    if p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
                ]
                if positional_params:
                    # Legacy support: pass run_context as first positional arg
                    return header_provider(run_context)
                else:
                    # Function takes no parameters
                    return header_provider()
        except Exception as e:
            log_warning(f"Error calling header_provider: {str(e)}")
            return {}

    def _merge_http_headers(
        self,
        base_headers: Optional[dict[str, Any]] = None,
        run_context: Optional["RunContext"] = None,
        agent: Optional["Agent"] = None,
        team: Optional["Team"] = None,
    ) -> dict[str, Any]:
        """Merge server_params headers, static MCP headers, and header_provider output."""
        merged: dict[str, Any] = {}
        if base_headers:
            merged.update(base_headers)
        if self._mcp_headers:
            merged.update(self._mcp_headers)
        if self.header_provider is not None:
            merged.update(self._call_header_provider(run_context=run_context, agent=agent, team=team))
        return merged

    async def _cleanup_stale_sessions(self) -> None:
        """Clean up sessions older than TTL to prevent memory leaks."""
        if not self._run_sessions:
            return

        now = time.time()
        stale_run_ids = [
            run_id
            for run_id, (_, created_at) in self._run_sessions.items()
            if now - created_at > self._session_ttl_seconds
        ]

        for run_id in stale_run_ids:
            log_debug(f"Cleaning up stale MCP sessions for run_id={run_id}")
            await self.cleanup_run_session(run_id)

    def should_use_temporary_run_session(self, run_context: Optional["RunContext"] = None) -> bool:
        """Return True when a tool call should avoid the run-session cache."""
        return bool(
            self.refresh_connection
            and self.header_provider is not None
            and run_context is not None
            and self.transport in ("sse", "streamable-http")
        )

    @asynccontextmanager
    async def get_temporary_session_for_run(
        self,
        run_context: Optional["RunContext"] = None,
        agent: Optional["Agent"] = None,
        team: Optional["Team"] = None,
    ) -> AsyncIterator[MCPSession]:
        """
        Create a dynamic-header session for one tool call and close it in the
        same task that opened it.

        This path is intentionally used only for refresh_connection=True. The
        MCP HTTP transports keep anyio cancel scopes inside their async context
        managers, and those scopes can fail noisily when a cached context is
        entered in one task and later exited from another.
        """
        if not self.should_use_temporary_run_session(run_context):
            if self.session is None:
                raise ValueError("Session is not initialized")
            yield self.session
            return

        dynamic_headers = self._merge_http_headers(run_context=run_context, agent=agent, team=team)

        if self.transport not in ("sse", "streamable-http"):
            if self.session is None:
                raise ValueError("Session is not initialized")
            yield self.session
            return

        client = _build_fastmcp_client(
            self.transport,
            self._connection_params(dynamic_headers),
            self.server_params,
            self.timeout_seconds,
            self.protocol_mode,
        )
        async with client as session:
            yield session

    async def get_session_for_run(
        self,
        run_context: Optional["RunContext"] = None,
        agent: Optional["Agent"] = None,
        team: Optional["Team"] = None,
    ) -> MCPSession:
        """
        Get or create a session for the given run context.

        If header_provider is set and run_context is provided, creates a new session
        with dynamic headers merged into the connection config.

        Args:
            run_context: The RunContext for the current agent run
            agent: The Agent instance (if running within an agent)
            team: The Team instance (if running within a team)

        Returns:
            The session object for the run: a fastmcp Client for an internally-created
            connection, or the caller-supplied ClientSession.
        """
        # If no header_provider or no run_context, use the default session
        if not self.header_provider or not run_context:
            if self.session is None:
                raise ValueError("Session is not initialized")
            return self.session

        run_id = run_context.run_id

        # Fast path: return existing session without acquiring the lock,
        # but ensure it is still within the configured TTL.
        if run_id in self._run_sessions:
            session, created_at = self._run_sessions[run_id]
            ttl = getattr(self, "_session_ttl_seconds", None)
            if not ttl or (time.time() - created_at) <= ttl:
                return session
            # Stale session: fall through to the slow path where
            # cleanup_run_session properly exits context managers.

        # Slow path: serialize session creation so parallel tool calls
        # sharing the same run_id don't each create (and overwrite) sessions.
        async with self._session_creation_lock:
            # Opportunistically clean up stale sessions from other runs
            await self._cleanup_stale_sessions()

            # Re-check after acquiring lock (another coroutine may have created it)
            if run_id in self._run_sessions:
                session, created_at = self._run_sessions[run_id]
                if time.time() - created_at <= self._session_ttl_seconds:
                    return session
                # Stale under lock — clean up before recreating
                await self.cleanup_run_session(run_id)

            # Create a new session with dynamic headers for this run
            log_debug(f"Creating new session for run_id={run_id} with dynamic headers")

            # Generate dynamic headers from the provider (merged with static headers)
            dynamic_headers = self._merge_http_headers(run_context=run_context, agent=agent, team=team)

            # Create new session with merged headers based on transport type
            if self.transport not in ("sse", "streamable-http"):
                # stdio doesn't support headers, fall back to default session
                log_warning(f"Cannot use dynamic headers with {self.transport} transport, using default session")
                if self.session is None:
                    raise ValueError("Session is not initialized")
                return self.session

            # The client unwinds itself if the handshake fails, so a partially-entered
            # connection needs no hand-rolled teardown here.
            context = _build_fastmcp_client(
                self.transport,
                self._connection_params(dynamic_headers),
                self.server_params,
                self.timeout_seconds,
                self.protocol_mode,
            )
            session = await context.__aenter__()

            # One Client is transport and session both, so a single context is stored and
            # cleanup exits it exactly once.
            self._run_sessions[run_id] = (session, time.time())
            self._run_session_contexts[run_id] = context

            return session

    async def cleanup_run_session(self, run_id: str) -> None:
        """
        Clean up the session for a specific run.

        Note: Cleanup may fail due to async context manager limitations when
        contexts are entered/exited across different tasks. Errors are logged
        but not raised.
        """
        if run_id not in self._run_sessions:
            return

        try:
            # Get the context managers
            session_context = self._run_session_contexts.get(run_id)

            # Try to clean up session context
            # Silently ignore cleanup errors - these are harmless
            if session_context is not None:
                try:
                    await session_context.__aexit__(None, None, None)
                except BaseException:
                    pass  # Silently ignore (includes CancelledError)

            # Remove from tracking regardless of cleanup success
            # The connections will be cleaned up by garbage collection
            del self._run_sessions[run_id]
            del self._run_session_contexts[run_id]

        except BaseException:
            pass  # Silently ignore all cleanup errors

    async def is_alive(self) -> bool:
        """Whether the connection is still usable.

        Only meaningful on the session-based era. The 2026-07-28 era removed ping and
        holds no session to probe, so with ``protocol_mode="auto"`` against a modern
        server this reports True without sending anything: a dead server surfaces on the
        next real request instead.
        """
        if self.session is None:
            return False
        try:
            # No-ops on the sessionless 2026 era, which has no ping and no connection
            # to keep alive -- so a modern-era client reports alive rather than failing.
            await ping_session(self.session)
            return True
        except Exception:
            return False

    async def _safe_cleanup(self) -> None:
        """Close any partially-entered MCP contexts"""
        if self._session_context is not None:
            try:
                await self._session_context.__aexit__(None, None, None)
            except BaseException:
                pass
            self._session_context = None
            self.session = None

        if self._context is not None:
            try:
                await self._context.aclose()
            except BaseException:
                try:
                    await self._context.__aexit__(None, None, None)
                except BaseException:
                    pass
            self._context = None

        self._active_contexts = []
        self._initialized = False

    async def connect(self, force: bool = False):
        """Initialize a MCPTools instance and connect to the contextual MCP server"""

        if force:
            # Clean up the session and context so we force a new connection
            self.session = None
            self._context = None
            self._session_context = None
            self._initialized = False
            self._connection_task = None
            self._active_contexts = []

        if self._initialized:
            return

        try:
            await self._connect()
        except Exception as e:
            log_error(f"Failed to connect to {str(self)}: {e}")
            await self._safe_cleanup()

    def _connection_params(self, extra_headers: Optional[dict] = None) -> dict:
        """Resolve server_params into a plain dict, filling in the url and merging headers.

        stdio carries no url or headers, so it returns an empty dict and the caller
        reads the command off ``server_params`` instead.
        """
        if self.transport not in ("sse", "streamable-http"):
            return {}

        params = asdict(self.server_params) if self.server_params is not None else {}  # type: ignore[arg-type]
        if "url" not in params or params["url"] is None:
            params["url"] = self.url
        if extra_headers:
            params["headers"] = {**(params.get("headers") or {}), **extra_headers}
        return params

    async def _connect(self) -> None:
        """Connects to the MCP server and initializes the tools"""

        if self._initialized:
            return

        if self.session is not None:
            await self.initialize()
            return

        # Merge static headers and header_provider output for the handshake.
        # Secured MCP servers require auth headers during session initialization,
        # not only on subsequent tool calls.
        init_headers = self._merge_http_headers()

        if self.transport == "stdio" and self.server_params is None:
            raise ValueError("server_params must be provided when using stdio transport.")

        params = self._connection_params(init_headers)

        # One fastmcp Client owns the transport, the session and the handshake, so a
        # partially-entered connection unwinds itself instead of being unwound by hand.
        self._session_context = _build_fastmcp_client(
            self.transport,  # type: ignore[arg-type]
            params,
            self.server_params,
            self.timeout_seconds,
            self.protocol_mode,
        )
        self.session = await self._session_context.__aenter__()  # type: ignore[attr-defined]
        self._active_contexts.append(self._session_context)

        # Initialize with the new session
        await self.initialize()

    async def close(self) -> None:
        """Close the MCP connection and clean up resources"""
        if not self._initialized:
            return

        import warnings

        # Suppress async generator cleanup warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*async_generator.*")
            warnings.filterwarnings("ignore", message=".*cancel scope.*")

            try:
                # Clean up all per-run sessions first
                run_ids = list(self._run_sessions.keys())
                for run_id in run_ids:
                    await self.cleanup_run_session(run_id)

                # Clean up the main session
                if self._session_context is not None:
                    try:
                        await self._session_context.__aexit__(None, None, None)
                    except (RuntimeError, Exception):
                        pass  # Silently ignore cleanup errors
                    self.session = None
                    self._session_context = None

                if self._context is not None:
                    try:
                        await self._context.__aexit__(None, None, None)
                    except (RuntimeError, Exception):
                        pass  # Silently ignore cleanup errors
                    self._context = None
            except (RuntimeError, BaseException):
                pass  # Silently ignore all cleanup errors

        self._initialized = False

    async def __aenter__(self) -> "MCPTools":
        await self._connect()
        return self

    async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
        """Exit the async context manager."""
        if self._session_context is not None:
            await self._session_context.__aexit__(_exc_type, _exc_val, _exc_tb)
            self.session = None
            self._session_context = None

        if self._context is not None:
            await self._context.__aexit__(_exc_type, _exc_val, _exc_tb)
            self._context = None

        self._initialized = False

    async def build_tools(self) -> None:
        """Build the tools for the MCP toolkit"""
        if self.session is None:
            raise ValueError("Session is not initialized")

        try:
            # Get the list of tools from the MCP server
            listed = await self.session.list_tools()
            # fastmcp's Client yields a plain list; a user-supplied ClientSession
            # yields a ListToolsResult carrying .tools.
            available_tools = listed if isinstance(listed, list) else listed.tools

            self._check_tools_filters(
                available_tools=[tool.name for tool in available_tools],
                include_tools=self.include_tools,
                exclude_tools=self.exclude_tools,
            )

            # Filter tools based on include/exclude lists
            filtered_tools = []
            for tool in available_tools:
                if self.exclude_tools and tool.name in self.exclude_tools:
                    continue
                if self.include_tools is None or tool.name in self.include_tools:
                    filtered_tools.append(tool)

            # Get tool name prefix if available
            tool_name_prefix = ""
            if self.tool_name_prefix is not None:
                tool_name_prefix = self.tool_name_prefix + "_"

            # Register the tools with the toolkit
            for tool in filtered_tools:
                try:
                    # Get an entrypoint for the tool
                    entrypoint = get_entrypoint_for_tool(
                        tool=tool,
                        session=self.session,
                        mcp_tools_instance=self,
                    )
                    # Create a Function for the tool
                    # Apply toolkit-level settings
                    tool_name = tool.name
                    stop_after = tool_name in self.stop_after_tool_call_tools
                    show_result = tool_name in self.show_result_tools or stop_after

                    f = Function(
                        name=tool_name_prefix + tool_name,
                        description=tool.description,
                        parameters=tool.input_schema,
                        entrypoint=entrypoint,
                        # Set skip_entrypoint_processing to True to avoid processing the entrypoint
                        skip_entrypoint_processing=True,
                        # Apply toolkit-level settings for HITL and control flow
                        requires_confirmation=tool_name in self.requires_confirmation_tools,
                        external_execution=tool_name in self.external_execution_required_tools,
                        stop_after_tool_call=stop_after,
                        show_result=show_result,
                        # Apply toolkit-level cache settings
                        cache_results=self.cache_results,
                        cache_dir=self.cache_dir,
                        cache_ttl=self.cache_ttl,
                    )

                    # Register the Function with the toolkit
                    self.functions[f.name] = f
                    log_debug(f"Function: {f.name} registered with {self.name}")
                except Exception as e:
                    log_error(f"Failed to register tool {tool.name}: {str(e)}")

        except Exception:
            log_error(f"Failed to get tools for {str(self)}")
            raise

    async def initialize(self) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""
        if self._initialized:
            return

        try:
            if self.session is None:
                raise ValueError("Session is not initialized")

            # fastmcp's Client performs the handshake on entry, and on the modern
            # (sessionless) era there is no initialize step to repeat -- calling it there
            # raises. Anything else, including a caller-supplied ClientSession, still
            # needs the explicit call.
            if not _is_fastmcp_client(self.session):
                await self.session.initialize()

            await self.build_tools()

            self._initialized = True

        except Exception:
            log_error("Failed to initialize MCP toolkit")
