import weakref
from contextlib import AsyncExitStack
from dataclasses import asdict
from datetime import timedelta
from types import TracebackType
from typing import List, Literal, Optional, Union

from agno.tools import Toolkit
from agno.tools.function import Function
from agno.tools.mcp.params import SSEClientParams, StreamableHTTPClientParams
from agno.utils.log import log_debug, log_error, log_info, log_warning
from agno.utils.mcp import get_entrypoint_for_tool, prepare_command

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
        """
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

        for server_params in self.server_params_list:
            try:
                # Handle stdio connections
                if isinstance(server_params, StdioServerParameters):
                    stdio_transport = await self._async_exit_stack.enter_async_context(stdio_client(server_params))
                    read, write = stdio_transport
                    session = await self._async_exit_stack.enter_async_context(
                        ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self.timeout_seconds))
                    )
                    await self.initialize(session)
                    self._successful_connections += 1

                # Handle SSE connections
                elif isinstance(server_params, SSEClientParams):
                    client_connection = await self._async_exit_stack.enter_async_context(
                        sse_client(**asdict(server_params))
                    )
                    read, write = client_connection
                    session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))
                    await self.initialize(session)
                    self._successful_connections += 1

                # Handle Streamable HTTP connections
                elif isinstance(server_params, StreamableHTTPClientParams):
                    client_connection = await self._async_exit_stack.enter_async_context(
                        streamablehttp_client(**asdict(server_params))
                    )
                    read, write = client_connection[0:2]
                    session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))
                    await self.initialize(session)
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

        try:
            await self._async_exit_stack.aclose()
            self._sessions = []
            self._successful_connections = 0

        except (RuntimeError, BaseException) as e:
            log_error(f"Failed to close MCP connections: {e}")

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
        for session in self._sessions:
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
                    entrypoint = get_entrypoint_for_tool(tool, session)

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

    async def initialize(self, session: ClientSession) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""

        try:
            # Initialize the session if not already initialized
            await session.initialize()

            self._sessions.append(session)
            self._initialized = True
        except Exception as e:
            log_error(f"Failed to get MCP tools: {e}")
            raise
