from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass
from datetime import timedelta
from os import environ
from types import TracebackType
from typing import Any, Dict, List, Literal, Optional, Union

from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_debug, logger
from agno.utils.mcp import get_entrypoint_for_tool

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.sse import sse_client
    from mcp.client.stdio import stdio_client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


@dataclass
class SSEClientParams:
    """Parameters for SSE client connection."""

    url: str
    headers: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None
    sse_read_timeout: Optional[float] = None


class MCPTools(Toolkit):
    """
    A toolkit for integrating Model Context Protocol (MCP) servers with Agno agents.
    This allows agents to access tools, resources, and prompts exposed by MCP servers.

    Can be used in three ways:
    1. Direct initialization with a ClientSession
    2. As an async context manager with StdioServerParameters
    3. As an async context manager with SSE endpoints
    """

    def __init__(
        self,
        command: Optional[str] = None,
        *,
        url: Optional[str] = None,
        env: Optional[dict[str, str]] = None,
        transport: Literal["stdio", "sse"] = "stdio",
        server_params: Optional[Union[StdioServerParameters, SSEClientParams]] = None,
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
            url: The URL endpoint for SSE connection when transport is "sse".
            env: The environment variables to pass to the server. Should be used in conjunction with command.
            client: The underlying MCP client (optional, used to prevent garbage collection)
            timeout_seconds: Read timeout in seconds for the MCP client
            include_tools: Optional list of tool names to include (if None, includes all)
            exclude_tools: Optional list of tool names to exclude (if None, excludes none)
            transport: The transport protocol to use, either "stdio" or "sse"
        """
        super().__init__(name="MCPTools", **kwargs)

        # Set these after `__init__` to bypass the `_check_tools_filters`
        # beacuse tools are not available until `initialize()` is called.
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools

        if session is None and server_params is None:
            if transport == "sse" and url is None:
                raise ValueError("One of 'url' or 'server_params' parameters must be provided when using SSE transport")
            if transport == "stdio" and command is None:
                raise ValueError(
                    "One of 'command' or 'server_params' parameters must be provided when using stdio transport"
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

        self.timeout_seconds = timeout_seconds
        self.session: Optional[ClientSession] = session
        self.server_params: Optional[Union[StdioServerParameters, SSEClientParams]] = server_params
        self.transport = transport
        self.url = url

        # Merge provided env with system env
        if env is not None:
            env = {
                **environ,
                **env,
            }
        else:
            env = {**environ}

        if command is not None and transport != "sse":
            from shlex import split

            parts = split(command)
            if not parts:
                raise ValueError("Empty command string")
            cmd = parts[0]
            arguments = parts[1:] if len(parts) > 1 else []
            self.server_params = StdioServerParameters(command=cmd, args=arguments, env=env)

        self._client = client
        self._context = None
        self._session_context = None
        self._initialized = False

    async def __aenter__(self) -> "MCPTools":
        """Enter the async context manager."""

        if self.session is not None:
            # Already has a session, just initialize
            if not self._initialized:
                await self.initialize()
            return self

        # Create a new session using stdio_client or sse_client based on transport
        if self.transport == "sse":
            sse_args = asdict(self.server_params) if self.server_params is not None else {}  # type: ignore
            if "url" not in sse_args:
                sse_args["url"] = self.url
            self._context = sse_client(**sse_args)  # type: ignore
        else:
            if self.server_params is None:
                raise ValueError("server_params must be provided when using stdio transport.")
            self._context = stdio_client(self.server_params)  # type: ignore

        read, write = await self._context.__aenter__()  # type: ignore

        self._session_context = ClientSession(read, write, read_timeout_seconds=timedelta(self.timeout_seconds))  # type: ignore
        self.session = await self._session_context.__aenter__()  # type: ignore

        # Initialize with the new session
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager."""
        if self._session_context is not None:
            await self._session_context.__aexit__(exc_type, exc_val, exc_tb)
            self.session = None
            self._session_context = None

        if self._context is not None:
            await self._context.__aexit__(exc_type, exc_val, exc_tb)
            self._context = None

        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""
        if self._initialized:
            return

        try:
            if self.session is None:
                raise ValueError("Session is not available. Use as context manager or provide a session.")

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
    3. As an async context manager with SSE endpoints
    """

    def __init__(
        self,
        commands: Optional[List[str]] = None,
        urls: Optional[List[str]] = None,
        *,
        env: Optional[dict[str, str]] = None,
        server_params_list: Optional[List[Union[SSEClientParams, StdioServerParameters]]] = None,
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
            urls: List of URLs for SSE endpoints.
            server_params_list: List of StdioServerParameters or SSEClientParams for creating new sessions.
            env: The environment variables to pass to the servers. Should be used in conjunction with commands.
            client: The underlying MCP client (optional, used to prevent garbage collection).
            timeout_seconds: Timeout in seconds for managing timeouts for Client Session if Agent or Tool doesn't respond.
            include_tools: Optional list of tool names to include (if None, includes all).
            exclude_tools: Optional list of tool names to exclude (if None, excludes none).
        """
        super().__init__(name="MultiMCPTools", **kwargs)

        # Set these after `__init__` to bypass the `_check_tools_filters`
        # beacuse tools are not available until `initialize()` is called.
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools

        if server_params_list is None and commands is None and urls is None:
            raise ValueError("Either server_params_list or commands or urls must be provided")

        self.server_params_list: List[Union[SSEClientParams, StdioServerParameters]] = server_params_list or []
        self.timeout_seconds = timeout_seconds
        self.commands: Optional[List[str]] = commands
        self.urls: Optional[List[str]] = urls

        # Merge provided env with system env
        if env is not None:
            env = {
                **environ,
                **env,
            }
        else:
            env = {**environ}

        if commands is not None:
            from shlex import split

            for command in commands:
                parts = split(command)
                if not parts:
                    raise ValueError("Empty command string")
                cmd = parts[0]
                arguments = parts[1:] if len(parts) > 1 else []
                self.server_params_list.append(StdioServerParameters(command=cmd, args=arguments, env=env))

        if urls is not None:
            for url in urls:
                self.server_params_list.append(SSEClientParams(url=url))

        self._async_exit_stack = AsyncExitStack()

        self._client = client

    async def __aenter__(self) -> "MultiMCPTools":
        """Enter the async context manager."""

        for server_params in self.server_params_list:
            # Handle stdio connections
            if isinstance(server_params, StdioServerParameters):
                stdio_transport = await self._async_exit_stack.enter_async_context(stdio_client(server_params))
                read, write = stdio_transport
                session = await self._async_exit_stack.enter_async_context(
                    ClientSession(read, write, read_timeout_seconds=timedelta(self.timeout_seconds))
                )

                await self.initialize(session)

            # Handle SSE connections
            if isinstance(server_params, SSEClientParams):
                sse_args = asdict(server_params)
                sse_transport = await self._async_exit_stack.enter_async_context(sse_client(**sse_args))
                read, write = sse_transport
                session = await self._async_exit_stack.enter_async_context(ClientSession(read, write))

                await self.initialize(session)

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
