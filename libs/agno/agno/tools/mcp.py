import asyncio
import weakref
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass
from datetime import timedelta
from types import TracebackType
from typing import Any, Dict, List, Literal, Optional, Union

from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_debug, log_info, log_warning, logger
from agno.utils.mcp import get_entrypoint_for_tool

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import get_default_environment, stdio_client
    from mcp.client.streamable_http import streamablehttp_client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


def _prepare_command(command: str) -> list[str]:
    """Sanitize a command and split it into parts before using it to run a MCP server."""
    from shlex import split

    # Block dangerous characters
    if any(char in command for char in ["&", "|", ";", "`", "$", "(", ")"]):
        raise ValueError("MCP command can't contain shell metacharacters")

    parts = split(command)
    if not parts:
        raise ValueError("MCP command can't be empty")

    # Only allow specific executables
    ALLOWED_COMMANDS = {
        # Python
        "python",
        "python3",
        "uv",
        "uvx",
        "pipx",
        # Node
        "node",
        "npm",
        "npx",
        "yarn",
        "pnpm",
        "bun",
        # Other runtimes
        "deno",
        "java",
        "ruby",
    }

    executable = parts[0].split("/")[-1]
    if executable not in ALLOWED_COMMANDS:
        raise ValueError(f"MCP command needs to use one of the following executables: {ALLOWED_COMMANDS}")

    return parts


@dataclass
class SSEClientParams:
    """Parameters for SSE client connection."""

    url: str
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = 5
    sse_read_timeout: Optional[float] = 60 * 5


@dataclass
class StreamableHTTPClientParams:
    """Parameters for Streamable HTTP client connection."""

    url: str
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[timedelta] = timedelta(seconds=30)
    sse_read_timeout: Optional[timedelta] = timedelta(seconds=60 * 5)
    terminate_on_close: Optional[bool] = None


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
        transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
        server_params: Optional[Union[StdioServerParameters, SSEClientParams, StreamableHTTPClientParams]] = None,
        session: Optional[ClientSession] = None,
        timeout_seconds: int = 5,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
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
            transport: The transport protocol to use, either "stdio" or "sse" or "streamable-http"
        """
        super().__init__(name="MCPTools", **kwargs)

        if transport == "sse":
            log_info("SSE as a standalone transport is deprecated. Please use Streamable HTTP instead.")

        # Set these after `__init__` to bypass the `_check_tools_filters`
        # because tools are not available until `initialize()` is called.
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools

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

        self.timeout_seconds = timeout_seconds
        self.session: Optional[ClientSession] = session
        self.server_params: Optional[Union[StdioServerParameters, SSEClientParams, StreamableHTTPClientParams]] = (
            server_params
        )
        self.transport = transport
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
            parts = _prepare_command(command)
            cmd = parts[0]
            arguments = parts[1:] if len(parts) > 1 else []
            self.server_params = StdioServerParameters(command=cmd, args=arguments, env=env)

        self._client = client
        self._context = None
        self._session_context = None
        self._initialized = False
        self._connection_task = None

        def cleanup():
            """Cancel active connections"""
            if self._connection_task and not self._connection_task.done():
                self._connection_task.cancel()

        # Setup cleanup logic before the instance is garbage collected
        self._cleanup_finalizer = weakref.finalize(self, cleanup)

    async def connect(self):
        """Initialize a MCPTools instance and connect to the contextual MCP server"""
        if self._initialized:
            return

        await self._connect()

    def _start_connection(self):
        """Ensure there are no active connections and setup a new one"""
        if self._connection_task is None or self._connection_task.done():
            self._connection_task = asyncio.create_task(self._connect())  # type: ignore

    async def _connect(self) -> None:
        """Connects to the MCP server and initializes the tools"""
        if self._initialized:
            return

        if self.session is not None:
            await self.initialize()
            return

        if not hasattr(self, "_active_contexts"):
            self._active_contexts: list[Any] = []

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
        if self._session_context is not None:
            await self._session_context.__aexit__(None, None, None)
            self.session = None
            self._session_context = None

        if self._context is not None:
            await self._context.__aexit__(None, None, None)
            self._context = None

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

    async def initialize(self) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""
        if self._initialized:
            return

        try:
            if self.session is None:
                raise ValueError("Failed to establish session connection")

            # Initialize the session if not already initialized
            await self.session.initialize()

            # Get the list of tools from the MCP server
            available_tools = await self.session.list_tools()

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

            # Register the tools with the toolkit
            for tool in filtered_tools:
                try:
                    # Get an entrypoint for the tool
                    entrypoint = get_entrypoint_for_tool(tool, self.session)
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
                    logger.error(f"Failed to register tool {tool.name}: {e}")

            log_debug(f"{self.name} initialized with {len(filtered_tools)} tools")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to get MCP tools: {e}")
            raise


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
            List[Union[SSEClientParams, StdioServerParameters, StreamableHTTPClientParams]]
        ] = None,
        timeout_seconds: int = 5,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
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
                parts = _prepare_command(command)
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
        self._initialized = False
        self._connection_task = None
        self._active_contexts: list[Any] = []
        self._used_as_context_manager = False

        self._client = client

        def cleanup():
            """Cancel active connections"""
            if self._connection_task and not self._connection_task.done():
                self._connection_task.cancel()

        # Setup cleanup logic before the instance is garbage collected
        self._cleanup_finalizer = weakref.finalize(self, cleanup)

    async def connect(self):
        """Initialize a MultiMCPTools instance and connect to the MCP servers"""
        if self._initialized:
            return

        await self._connect()

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
            **kwargs,
        )

        await instance._connect()
        return instance

    def _start_connection(self):
        """Ensure there are no active connections and setup a new one"""
        if self._connection_task is None or self._connection_task.done():
            self._connection_task = asyncio.create_task(self._connect())  # type: ignore

    async def _connect(self) -> None:
        """Connects to the MCP servers and initializes the tools"""
        if self._initialized:
            return

        for server_params in self.server_params_list:
            # Handle stdio connections
            if isinstance(server_params, StdioServerParameters):
                stdio_transport = await self._async_exit_stack.enter_async_context(stdio_client(server_params))
                self._active_contexts.append(stdio_transport)
                read, write = stdio_transport
                session = await self._async_exit_stack.enter_async_context(
                    ClientSession(read, write, read_timeout_seconds=timedelta(seconds=self.timeout_seconds))
                )
                self._active_contexts.append(session)
                await self.initialize(session)
            # Handle SSE connections
            elif isinstance(server_params, SSEClientParams):
                client_connection = await self._async_exit_stack.enter_async_context(
                    sse_client(**asdict(server_params))
                )
                self._active_contexts.append(client_connection)
                read, write = client_connection
                session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))
                self._active_contexts.append(session)
                await self.initialize(session)

            # Handle Streamable HTTP connections
            elif isinstance(server_params, StreamableHTTPClientParams):
                client_connection = await self._async_exit_stack.enter_async_context(
                    streamablehttp_client(**asdict(server_params))
                )
                self._active_contexts.append(client_connection)
                read, write = client_connection[0:2]
                session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))
                self._active_contexts.append(session)
                await self.initialize(session)

        self._initialized = True

    async def close(self) -> None:
        """Close the MCP connections and clean up resources"""
        await self._async_exit_stack.aclose()
        self._initialized = False

    async def __aenter__(self) -> "MultiMCPTools":
        """Enter the async context manager."""
        await self._connect()
        return self

    async def __aexit__(
        self,
        exc_type: Union[type[BaseException], None],
        exc_val: Union[BaseException, None],
        exc_tb: Union[TracebackType, None],
    ):
        """Exit the async context manager."""
        await self._async_exit_stack.aclose()

    async def initialize(self, session: ClientSession) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""

        try:
            # Initialize the session if not already initialized
            await session.initialize()

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
                    logger.error(f"Failed to register tool {tool.name}: {e}")

            log_debug(f"{self.name} initialized with {len(filtered_tools)} tools")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to get MCP tools: {e}")
            raise
