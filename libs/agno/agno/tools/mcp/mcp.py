import inspect
import time
import weakref
from dataclasses import asdict
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Callable, Literal, Optional, Tuple, Union

from agno.tools import Toolkit
from agno.tools.function import Function
from agno.tools.mcp.params import SSEClientParams, StreamableHTTPClientParams
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.mcp import get_entrypoint_for_tool, prepare_command

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run import RunContext
    from agno.team.team import Team

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import get_default_environment, stdio_client
    from mcp.client.streamable_http import streamablehttp_client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


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
        header_provider: Optional[Callable[..., dict[str, Any]]] = None,
        **kwargs,
    ):
        """
        Initialize the MCP toolkit.

        Args:
            session: An initialized MCP ClientSession connected to an MCP server
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
            header_provider: Optional function to generate dynamic HTTP headers.
                Only relevant with HTTP transports (Streamable HTTP or SSE).
                Creates a new session per agent run with dynamic headers merged into connection config.
        """
        # Extract these before super().__init__() to bypass early validation
        # (tools aren't available until build_tools() is called)
        requires_confirmation_tools = kwargs.pop("requires_confirmation_tools", None)
        external_execution_required_tools = kwargs.pop("external_execution_required_tools", None)
        stop_after_tool_call_tools = kwargs.pop("stop_after_tool_call_tools", None)
        show_result_tools = kwargs.pop("show_result_tools", None)

        super().__init__(name="MCPTools", **kwargs)

        if url is not None:
            if transport is None:
                transport = "streamable-http"
            elif transport == "stdio":
                log_warning(
                    "Transport cannot be 'stdio' when url is provided. Setting transport to 'streamable-http' instead."
                )
                transport = "streamable-http"

        if transport == "sse":
            log_info("SSE as a standalone transport is deprecated. Please use Streamable HTTP instead.")

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
        self.session: Optional[ClientSession] = session
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
        self._run_sessions: dict[str, Tuple[ClientSession, float]] = {}
        self._run_session_contexts: dict[str, Any] = {}  # Maps run_id to session context managers
        self._session_ttl_seconds: float = 300.0  # 5 minutes TTL for MCP sessions

        def cleanup():
            """Cancel active connections"""
            if self._connection_task and not self._connection_task.done():
                self._connection_task.cancel()

        # Setup cleanup logic before the instance is garbage collected
        self._cleanup_finalizer = weakref.finalize(self, cleanup)

    @property
    def initialized(self) -> bool:
        return self._initialized

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
            log_warning(f"Error calling header_provider: {e}")
            return {}

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

    async def get_session_for_run(
        self,
        run_context: Optional["RunContext"] = None,
        agent: Optional["Agent"] = None,
        team: Optional["Team"] = None,
    ) -> ClientSession:
        """
        Get or create a session for the given run context.

        If header_provider is set and run_context is provided, creates a new session
        with dynamic headers merged into the connection config.

        Args:
            run_context: The RunContext for the current agent run
            agent: The Agent instance (if running within an agent)
            team: The Team instance (if running within a team)

        Returns:
            ClientSession for the run
        """
        # If no header_provider or no run_context, use the default session
        if not self.header_provider or not run_context:
            if self.session is None:
                raise ValueError("Session is not initialized")
            return self.session

        # Lazy cleanup of stale sessions
        await self._cleanup_stale_sessions()

        # Check if we already have a session for this run
        run_id = run_context.run_id
        if run_id in self._run_sessions:
            session, _ = self._run_sessions[run_id]
            return session

        # Create a new session with dynamic headers for this run
        log_debug(f"Creating new session for run_id={run_id} with dynamic headers")

        # Generate dynamic headers from the provider
        dynamic_headers = self._call_header_provider(run_context=run_context, agent=agent, team=team)

        # Create new session with merged headers based on transport type
        if self.transport == "sse":
            sse_params = asdict(self.server_params) if self.server_params is not None else {}  # type: ignore
            if "url" not in sse_params:
                sse_params["url"] = self.url

            # Merge dynamic headers into existing headers
            existing_headers = sse_params.get("headers", {})
            sse_params["headers"] = {**existing_headers, **dynamic_headers}

            context = sse_client(**sse_params)  # type: ignore
            client_timeout = min(self.timeout_seconds, sse_params.get("timeout", self.timeout_seconds))

        elif self.transport == "streamable-http":
            streamable_http_params = asdict(self.server_params) if self.server_params is not None else {}  # type: ignore
            if "url" not in streamable_http_params:
                streamable_http_params["url"] = self.url

            # Merge dynamic headers into existing headers
            existing_headers = streamable_http_params.get("headers", {})
            streamable_http_params["headers"] = {**existing_headers, **dynamic_headers}

            context = streamablehttp_client(**streamable_http_params)  # type: ignore
            params_timeout = streamable_http_params.get("timeout", self.timeout_seconds)
            if isinstance(params_timeout, timedelta):
                params_timeout = int(params_timeout.total_seconds())
            client_timeout = min(self.timeout_seconds, params_timeout)
        else:
            # stdio doesn't support headers, fall back to default session
            log_warning(f"Cannot use dynamic headers with {self.transport} transport, using default session")
            if self.session is None:
                raise ValueError("Session is not initialized")
            return self.session

        # Enter the context and create session
        session_params = await context.__aenter__()  # type: ignore
        read, write = session_params[0:2]

        session_context = ClientSession(read, write, read_timeout_seconds=timedelta(seconds=client_timeout))  # type: ignore
        session = await session_context.__aenter__()  # type: ignore

        # Initialize the session
        await session.initialize()

        # Store the session with timestamp and context for cleanup
        self._run_sessions[run_id] = (session, time.time())
        self._run_session_contexts[run_id] = (context, session_context)

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
            context, session_context = self._run_session_contexts.get(run_id, (None, None))

            # Try to clean up session context
            # Silently ignore cleanup errors - these are harmless
            if session_context is not None:
                try:
                    await session_context.__aexit__(None, None, None)
                except (RuntimeError, Exception):
                    pass  # Silently ignore

            # Try to clean up transport context
            if context is not None:
                try:
                    await context.__aexit__(None, None, None)
                except (RuntimeError, Exception):
                    pass  # Silently ignore

            # Remove from tracking regardless of cleanup success
            # The connections will be cleaned up by garbage collection
            del self._run_sessions[run_id]
            del self._run_session_contexts[run_id]

        except Exception:
            pass  # Silently ignore all cleanup errors

    async def is_alive(self) -> bool:
        if self.session is None:
            return False
        try:
            await self.session.send_ping()
            return True
        except (RuntimeError, BaseException):
            return False

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
        except (RuntimeError, BaseException) as e:
            log_error(f"Failed to connect to {str(self)}: {e}")

    async def _connect(self) -> None:
        """Connects to the MCP server and initializes the tools"""

        if self._initialized:
            return

        if self.session is not None:
            await self.initialize()
            return

        # Create a new studio session
        if self.transport == "sse":
            sse_params = asdict(self.server_params) if self.server_params is not None else {}  # type: ignore
            if "url" not in sse_params:
                sse_params["url"] = self.url
            self._context = sse_client(**sse_params)  # type: ignore
            client_timeout = min(self.timeout_seconds, sse_params.get("timeout", self.timeout_seconds))

        # Create a new streamable HTTP session
        elif self.transport == "streamable-http":
            streamable_http_params = asdict(self.server_params) if self.server_params is not None else {}  # type: ignore
            if "url" not in streamable_http_params:
                streamable_http_params["url"] = self.url
            self._context = streamablehttp_client(**streamable_http_params)  # type: ignore
            params_timeout = streamable_http_params.get("timeout", self.timeout_seconds)
            if isinstance(params_timeout, timedelta):
                params_timeout = int(params_timeout.total_seconds())
            client_timeout = min(self.timeout_seconds, params_timeout)

        else:
            if self.server_params is None:
                raise ValueError("server_params must be provided when using stdio transport.")
            self._context = stdio_client(self.server_params)  # type: ignore
            client_timeout = self.timeout_seconds

        session_params = await self._context.__aenter__()  # type: ignore
        self._active_contexts.append(self._context)
        read, write = session_params[0:2]

        self._session_context = ClientSession(read, write, read_timeout_seconds=timedelta(seconds=client_timeout))  # type: ignore
        self.session = await self._session_context.__aenter__()  # type: ignore
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
            available_tools = await self.session.list_tools()  # type: ignore

            self._check_tools_filters(
                available_tools=[tool.name for tool in available_tools.tools],
                include_tools=self.include_tools,
                exclude_tools=self.exclude_tools,
            )

            # Filter tools based on include/exclude lists
            filtered_tools = []
            for tool in available_tools.tools:
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
                        session=self.session,  # type: ignore
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
                        parameters=tool.inputSchema,
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
                    log_error(f"Failed to register tool {tool.name}: {e}")

        except (RuntimeError, BaseException) as e:
            log_error(f"Failed to get tools for {str(self)}: {e}")
            raise

    async def initialize(self) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""
        if self._initialized:
            return

        try:
            if self.session is None:
                raise ValueError("Session is not initialized")

            # Initialize the session if not already initialized
            await self.session.initialize()

            await self.build_tools()

            self._initialized = True

        except (RuntimeError, BaseException) as e:
            log_error(f"Failed to initialize MCP toolkit: {e}")
