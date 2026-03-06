import inspect
import time
import warnings
import weakref
from contextlib import AsyncExitStack
from dataclasses import asdict
from datetime import timedelta
from types import TracebackType
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Literal, Optional, Tuple, Union

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


class MultiMCPTools(Toolkit):
    """
    A toolkit for integrating multiple Model Context Protocol (MCP) servers with Agno agents.
    This allows agents to access tools, resources, and prompts exposed by MCP servers.

    Can be used in three ways:
    1. Direct initialization with a ClientSession
    2. As an async context manager with StdioServerParameters
    3. As an async context manager with SSE or Streamable HTTP endpoints
    """

    def __init__(
        self,
        commands: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        urls_transports: Optional[List[Literal["sse", "streamable-http"]]] = None,
        *,
        env: Optional[dict[str, str]] = None,
        server_params_list: Optional[
            list[Union[SSEClientParams, StdioServerParameters, StreamableHTTPClientParams]]
        ] = None,
        timeout_seconds: int = 10,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        refresh_connection: bool = False,
        allow_partial_failure: bool = False,
        header_provider: Optional[Callable[..., dict[str, Any]]] = None,
        **kwargs,
    ):
        """
        Initialize the MCP toolkit.

        Args:
            commands: List of commands to run to start the servers. Should be used in conjunction with env.
            urls: List of URLs for SSE and/or Streamable HTTP endpoints.
            urls_transports: List of transports to use for the given URLs.
            server_params_list: List of StdioServerParameters or SSEClientParams or StreamableHTTPClientParams for creating new sessions.
            env: The environment variables to pass to the servers. Should be used in conjunction with commands.
            client: The underlying MCP client (optional, used to prevent garbage collection).
            timeout_seconds: Timeout in seconds for managing timeouts for Client Session if Agent or Tool doesn't respond.
            include_tools: Optional list of tool names to include (if None, includes all).
            exclude_tools: Optional list of tool names to exclude (if None, excludes none).
            allow_partial_failure: If True, allows toolkit to initialize even if some MCP servers fail to connect. If False, any failure will raise an exception.
            refresh_connection: If True, the connection and tools will be refreshed on each run
            header_provider: Header provider function for all servers. Takes RunContext and returns dict of HTTP headers.
        """
        warnings.warn(
            "The MultiMCPTools class is deprecated and will be removed in a future version. Please use multiple MCPTools instances instead.",
            DeprecationWarning,
            stacklevel=2,
        )

        super().__init__(name="MultiMCPTools", **kwargs)

        if urls_transports is not None:
            if "sse" in urls_transports:
                log_info("SSE as a standalone transport is deprecated. Please use Streamable HTTP instead.")

        if urls is not None:
            if urls_transports is None:
                log_warning(
                    "The default transport 'streamable-http' will be used. You can explicitly set the transports by providing the urls_transports parameter."
                )
            else:
                if len(urls) != len(urls_transports):
                    raise ValueError("urls and urls_transports must be of the same length")

        # Set these after `__init__` to bypass the `_check_tools_filters`
        # beacuse tools are not available until `initialize()` is called.
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools
        self.refresh_connection = refresh_connection

        self.header_provider = header_provider

        # Validate header_provider signature
        if header_provider:
            try:
                # Just verify we can inspect the signature - no parameter requirements
                inspect.signature(header_provider)
            except Exception as e:
                log_warning(f"Could not validate header_provider signature: {e}")

        if server_params_list is None and commands is None and urls is None:
            raise ValueError("Either server_params_list or commands or urls must be provided")

        self.server_params_list: List[Union[SSEClientParams, StdioServerParameters, StreamableHTTPClientParams]] = (
            server_params_list or []
        )
        self.timeout_seconds = timeout_seconds
        self.commands: Optional[List[str]] = commands
        self.urls: Optional[List[str]] = urls
        # Merge provided env with system env
        if env is not None:
            env = {
                **get_default_environment(),
                **env,
            }
        else:
            env = get_default_environment()

        if commands is not None:
            for command in commands:
                parts = prepare_command(command)
                cmd = parts[0]
                arguments = parts[1:] if len(parts) > 1 else []
                self.server_params_list.append(StdioServerParameters(command=cmd, args=arguments, env=env))

        if urls is not None:
            if urls_transports is not None:
                for url, transport in zip(urls, urls_transports):
                    if transport == "streamable-http":
                        self.server_params_list.append(StreamableHTTPClientParams(url=url))
                    else:
                        self.server_params_list.append(SSEClientParams(url=url))
            else:
                for url in urls:
                    self.server_params_list.append(StreamableHTTPClientParams(url=url))

        self._async_exit_stack = AsyncExitStack()

        self._client = client

        self._initialized = False
        self._connection_task = None
        self._successful_connections = 0
        self._sessions: list[ClientSession] = []
        self._session_to_server_idx: Dict[int, int] = {}  # Maps session list index to server params index

        # Session management for per-agent-run sessions with dynamic headers
        # For MultiMCP, we track sessions per (run_id, server_idx) since we have multiple servers
        # Maps (run_id, server_idx) to (session, timestamp) for TTL-based cleanup
        self._run_sessions: Dict[Tuple[str, int], Tuple[ClientSession, float]] = {}
        self._run_session_contexts: Dict[Tuple[str, int], Any] = {}  # Maps (run_id, server_idx) to context managers
        self._session_ttl_seconds: float = 300.0  # 5 minutes default TTL

        self.allow_partial_failure = allow_partial_failure

        def cleanup():
            """Cancel active connections"""
            if self._connection_task and not self._connection_task.done():
                self._connection_task.cancel()

        # Setup cleanup logic before the instance is garbage collected
        self._cleanup_finalizer = weakref.finalize(self, cleanup)

    @property
    def initialized(self) -> bool:
        return self._initialized

    async def is_alive(self) -> bool:
        try:
            for session in self._sessions:
                await session.send_ping()
            return True
        except (RuntimeError, BaseException):
            return False

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
        stale_keys = [
            cache_key
            for cache_key, (_, created_at) in self._run_sessions.items()
            if now - created_at > self._session_ttl_seconds
        ]

        for run_id, server_idx in stale_keys:
            log_debug(f"Cleaning up stale session for run_id={run_id}, server_idx={server_idx}")
            await self.cleanup_run_session(run_id, server_idx)

    async def get_session_for_run(
        self,
        run_context: Optional["RunContext"] = None,
        server_idx: int = 0,
        agent: Optional["Agent"] = None,
        team: Optional["Team"] = None,
    ) -> ClientSession:
        """
        Get or create a session for the given run_context and server index.

        If header_provider is configured and run_context is provided, this creates
        a new session with dynamic headers for this specific agent run and server.

        Args:
            run_context: The RunContext containing user_id, metadata, etc.
            server_idx: Index of the server in self._sessions list
            agent: The Agent instance (if running within an agent)
            team: The Team instance (if running within a team)

        Returns:
            ClientSession: Either the default session or a per-run session with dynamic headers
        """
        # If no header_provider or no run_context, use the default session
        if not self.header_provider or not run_context:
            # Return the default session for this server
            if server_idx < len(self._sessions):
                return self._sessions[server_idx]
            raise ValueError(f"Server index {server_idx} out of range")

        # Lazy cleanup of stale sessions
        await self._cleanup_stale_sessions()

        # Check if we already have a session for this (run_id, server_idx)
        run_id = run_context.run_id
        cache_key = (run_id, server_idx)
        if cache_key in self._run_sessions:
            session, _ = self._run_sessions[cache_key]
            return session

        # Create a new session with dynamic headers for this run and server
        log_debug(f"Creating new session for run_id={run_id}, server_idx={server_idx} with dynamic headers")

        # Generate dynamic headers from the provider
        dynamic_headers = self._call_header_provider(run_context=run_context, agent=agent, team=team)

        # Get the server params for this server index
        if server_idx >= len(self.server_params_list):
            raise ValueError(f"Server index {server_idx} out of range")

        server_params = self.server_params_list[server_idx]

        # Create new session with merged headers based on transport type
        if isinstance(server_params, SSEClientParams):
            params_dict = asdict(server_params)
            existing_headers = params_dict.get("headers") or {}
            params_dict["headers"] = {**existing_headers, **dynamic_headers}

            context = sse_client(**params_dict)  # type: ignore
            client_timeout = min(self.timeout_seconds, params_dict.get("timeout", self.timeout_seconds))

        elif isinstance(server_params, StreamableHTTPClientParams):
            params_dict = asdict(server_params)
            existing_headers = params_dict.get("headers") or {}
            params_dict["headers"] = {**existing_headers, **dynamic_headers}

            context = streamablehttp_client(**params_dict)  # type: ignore
            params_timeout = params_dict.get("timeout", self.timeout_seconds)
            if isinstance(params_timeout, timedelta):
                params_timeout = int(params_timeout.total_seconds())
            client_timeout = min(self.timeout_seconds, params_timeout)
        else:
            # stdio doesn't support headers, fall back to default session
            log_warning(
                f"Cannot use dynamic headers with stdio transport for server {server_idx}, using default session"
            )
            if server_idx < len(self._sessions):
                return self._sessions[server_idx]
            raise ValueError(f"Server index {server_idx} out of range")

        # Enter the context and create session
        session_params = await context.__aenter__()  # type: ignore
        read, write = session_params[0:2]

        session_context = ClientSession(read, write, read_timeout_seconds=timedelta(seconds=client_timeout))  # type: ignore
        session = await session_context.__aenter__()  # type: ignore

        # Initialize the session
        await session.initialize()

        # Store the session with timestamp and context for cleanup
        self._run_sessions[cache_key] = (session, time.time())
        self._run_session_contexts[cache_key] = (context, session_context)

        return session

    async def cleanup_run_session(self, run_id: str, server_idx: int) -> None:
        """Clean up a per-run session."""
        cache_key = (run_id, server_idx)
        if cache_key not in self._run_sessions:
            return

        try:
            context, session_context = self._run_session_contexts[cache_key]

            # Exit session context - silently ignore errors
            try:
                await session_context.__aexit__(None, None, None)
            except (RuntimeError, Exception):
                pass  # Silently ignore

            # Exit transport context - silently ignore errors
            try:
                await context.__aexit__(None, None, None)
            except (RuntimeError, Exception):
                pass  # Silently ignore

        except Exception:
            pass  # Silently ignore all cleanup errors
        finally:
            # Remove from cache
            self._run_sessions.pop(cache_key, None)
            self._run_session_contexts.pop(cache_key, None)

    async def connect(self, force: bool = False):
        """Initialize a MultiMCPTools instance and connect to the MCP servers"""

        if force:
            # Clean up the session and context so we force a new connection
            self._sessions = []
            self._successful_connections = 0
            self._initialized = False
            self._connection_task = None

        if self._initialized:
            return

        try:
            await self._connect()
        except (RuntimeError, BaseException) as e:
            log_error(f"Failed to connect to {str(self)}: {e}")

    @classmethod
    async def create_and_connect(
        cls,
        commands: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        urls_transports: Optional[List[Literal["sse", "streamable-http"]]] = None,
        *,
        env: Optional[dict[str, str]] = None,
        server_params_list: Optional[
            List[Union[SSEClientParams, StdioServerParameters, StreamableHTTPClientParams]]
        ] = None,
        timeout_seconds: int = 5,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        refresh_connection: bool = False,
        **kwargs,
    ) -> "MultiMCPTools":
        """Initialize a MultiMCPTools instance and connect to the MCP servers"""
        instance = cls(
            commands=commands,
            urls=urls,
            urls_transports=urls_transports,
            env=env,
            server_params_list=server_params_list,
            timeout_seconds=timeout_seconds,
            client=client,
            include_tools=include_tools,
            exclude_tools=exclude_tools,
            refresh_connection=refresh_connection,
            **kwargs,
        )

        await instance._connect()
        return instance

    async def _connect(self) -> None:
        """Connects to the MCP servers and initializes the tools"""
        if self._initialized:
            return

        server_connection_errors = []

        for server_idx, server_params in enumerate(self.server_params_list):
            try:
                # Handle stdio connections
                if isinstance(server_params, StdioServerParameters):
                    stdio_transport = await self._async_exit_stack.enter_async_context(stdio_client(server_params))
                    read, write = stdio_transport
                    session = await self._async_exit_stack.enter_async_context(
                        ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self.timeout_seconds))
                    )
                    await self.initialize(session, server_idx)
                    self._successful_connections += 1

                # Handle SSE connections
                elif isinstance(server_params, SSEClientParams):
                    client_connection = await self._async_exit_stack.enter_async_context(
                        sse_client(**asdict(server_params))
                    )
                    read, write = client_connection
                    session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))
                    await self.initialize(session, server_idx)
                    self._successful_connections += 1

                # Handle Streamable HTTP connections
                elif isinstance(server_params, StreamableHTTPClientParams):
                    client_connection = await self._async_exit_stack.enter_async_context(
                        streamablehttp_client(**asdict(server_params))
                    )
                    read, write = client_connection[0:2]
                    session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))
                    await self.initialize(session, server_idx)
                    self._successful_connections += 1

            except Exception as e:
                if not self.allow_partial_failure:
                    raise ValueError(f"MCP connection failed: {e}")

                log_error(f"Failed to initialize MCP server with params {server_params}: {e}")
                server_connection_errors.append(str(e))
                continue

        if self._successful_connections > 0:
            await self.build_tools()

        if self._successful_connections == 0 and server_connection_errors:
            raise ValueError(f"All MCP connections failed: {server_connection_errors}")

        if not self._initialized and self._successful_connections > 0:
            self._initialized = True

    async def close(self) -> None:
        """Close the MCP connections and clean up resources"""
        if not self._initialized:
            return

        import warnings

        # Suppress async generator cleanup warnings
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", category=RuntimeWarning, message=".*async_generator.*")
            warnings.filterwarnings("ignore", message=".*cancel scope.*")

            try:
                # Clean up all per-run sessions first
                cache_keys = list(self._run_sessions.keys())
                for run_id, server_idx in cache_keys:
                    await self.cleanup_run_session(run_id, server_idx)

                # Clean up main sessions
                await self._async_exit_stack.aclose()
                self._sessions = []
                self._successful_connections = 0

            except (RuntimeError, BaseException):
                pass  # Silently ignore all cleanup errors

        self._initialized = False

    async def __aenter__(self) -> "MultiMCPTools":
        """Enter the async context manager."""
        try:
            await self._connect()
        except (RuntimeError, BaseException) as e:
            log_error(f"Failed to connect to {str(self)}: {e}")
        return self

    async def __aexit__(
        self,
        exc_type: Union[type[BaseException], None],
        exc_val: Union[BaseException, None],
        exc_tb: Union[TracebackType, None],
    ):
        """Exit the async context manager."""
        await self._async_exit_stack.aclose()
        self._initialized = False
        self._successful_connections = 0

    async def build_tools(self) -> None:
        for session_list_idx, session in enumerate(self._sessions):
            # Get the list of tools from the MCP server
            available_tools = await session.list_tools()

            # Filter tools based on include/exclude lists
            filtered_tools = []
            for tool in available_tools.tools:
                if self.exclude_tools and tool.name in self.exclude_tools:
                    continue
                if self.include_tools is None or tool.name in self.include_tools:
                    filtered_tools.append(tool)

            # Register the tools with the toolkit
            for tool in filtered_tools:
                try:
                    # Get an entrypoint for the tool
                    entrypoint = get_entrypoint_for_tool(
                        tool=tool,
                        session=session,
                        mcp_tools_instance=self,  # Pass self to enable dynamic headers
                        server_idx=session_list_idx,  # Pass session list index for session lookup
                    )

                    # Create a Function for the tool
                    f = Function(
                        name=tool.name,
                        description=tool.description,
                        parameters=tool.inputSchema,
                        entrypoint=entrypoint,
                        # Set skip_entrypoint_processing to True to avoid processing the entrypoint
                        skip_entrypoint_processing=True,
                    )

                    # Register the Function with the toolkit
                    self.functions[f.name] = f
                    log_debug(f"Function: {f.name} registered with {self.name}")
                except Exception as e:
                    log_error(f"Failed to register tool {tool.name}: {e}")
                    raise

    async def initialize(self, session: ClientSession, server_idx: int = 0) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""

        try:
            # Initialize the session if not already initialized
            await session.initialize()

            # Track which server index this session belongs to
            session_list_idx = len(self._sessions)
            self._sessions.append(session)
            self._session_to_server_idx[session_list_idx] = server_idx

            self._initialized = True
        except Exception as e:
            log_error(f"Failed to get MCP tools: {e}")
            raise
