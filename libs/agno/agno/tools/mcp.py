from contextlib import AsyncExitStack
from os import environ
from types import TracebackType
from typing import List, Optional, Union

from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_debug, logger
from agno.utils.mcp import get_entrypoint_for_tool

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


class MCPTools(Toolkit):
    """
    A toolkit for integrating Model Context Protocol (MCP) servers with Agno agents.
    This allows agents to access tools, resources, and prompts exposed by MCP servers.

    Can be used in two ways:
    1. Direct initialization with a ClientSession
    2. As an async context manager with StdioServerParameters
    3. As an async context manager with `command` directly specified
    """

    def __init__(
        self,
        command: Optional[str] = None,
        *,
        env: Optional[dict[str, str]] = None,
        server_params: Optional[StdioServerParameters] = None,
        session: Optional[ClientSession] = None,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        **kwargs,
    ):
        """
        Initialize the MCP toolkit.

        Args:
            session: An initialized MCP ClientSession connected to an MCP server
            server_params: StdioServerParameters for creating a new session
            command: The command to run to start the server. Should be used in conjunction with env.
            env: The environment variables to pass to the server. Should be used in conjunction with command.
            client: The underlying MCP client (optional, used to prevent garbage collection)
            include_tools: Optional list of tool names to include (if None, includes all)
            exclude_tools: Optional list of tool names to exclude (if None, excludes none)
        """
        super().__init__(name="MCPToolkit", **kwargs)

        if session is None and server_params is None and command is None:
            raise ValueError("Either session or server_params or command must be provided")

        self.session: Optional[ClientSession] = session
        self.server_params: Optional[StdioServerParameters] = server_params

        # Merge provided env with system env
        if env is not None:
            env = {
                **environ,
                **env,
            }
        else:
            env = {**environ}

        if command is not None:
            from shlex import split

            parts = split(command)
            if not parts:
                raise ValueError("Empty command string")
            cmd = parts[0]
            arguments = parts[1:] if len(parts) > 1 else []
            self.server_params = StdioServerParameters(command=cmd, args=arguments, env=env)

        self._client = client
        self._stdio_context = None
        self._session_context = None
        self._initialized = False

    async def __aenter__(self) -> "MCPTools":
        """Enter the async context manager."""

        if self.session is not None:
            # Already has a session, just initialize
            if not self._initialized:
                await self.initialize()
            return self

        # Create a new session using stdio_client
        if self.server_params is None:
            raise ValueError("server_params must be provided when using as context manager")

        self._stdio_context = stdio_client(self.server_params)  # type: ignore
        read, write = await self._stdio_context.__aenter__()  # type: ignore

        self._session_context = ClientSession(read, write)  # type: ignore
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

        if self._stdio_context is not None:
            await self._stdio_context.__aexit__(exc_type, exc_val, exc_tb)
            self._stdio_context = None

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

    Can be used in two ways:
    1. Direct initialization with a ClientSession
    2. As an async context manager with StdioServerParameters
    """

    def __init__(
        self,
        commands: Optional[List[str]] = None,
        *,
        env: Optional[dict[str, str]] = None,
        server_params_list: Optional[List[StdioServerParameters]] = None,
        client=None,
        include_tools: Optional[list[str]] = None,
        exclude_tools: Optional[list[str]] = None,
        **kwargs,
    ):
        """
        Initialize the MCP toolkit.

        Args:
            server_params_list: List of StdioServerParameters for creating new sessions
            commands: List of commands to run to start the servers. Should be used in conjunction with env.
            env: The environment variables to pass to the servers. Should be used in conjunction with commands.
            client: The underlying MCP client (optional, used to prevent garbage collection)
            include_tools: Optional list of tool names to include (if None, includes all)
            exclude_tools: Optional list of tool names to exclude (if None, excludes none)
        """
        super().__init__(name="MultiMCPToolkit", **kwargs)

        if server_params_list is None and commands is None:
            raise ValueError("Either server_params_list or commands must be provided")

        self.server_params_list: List[StdioServerParameters] = server_params_list or []
        self.commands: Optional[List[str]] = commands

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

        self._async_exit_stack = AsyncExitStack()

        self._client = client

    async def __aenter__(self) -> "MultiMCPTools":
        """Enter the async context manager."""

        for server_params in self.server_params_list:
            stdio_transport = await self._async_exit_stack.enter_async_context(stdio_client(server_params))
            read, write = stdio_transport
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
