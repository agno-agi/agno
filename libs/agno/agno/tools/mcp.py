from functools import partial
from typing import Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import log_debug, logger

try:
    from mcp import ClientSession, ListToolsResult, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent
    from mcp.types import Tool as MCPTool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


class MCPTools(Toolkit):
    """
    A toolkit for integrating Model Context Protocol (MCP) servers with Agno agents.
    This allows agents to access tools, resources, and prompts exposed by MCP servers.

    Can be used in two ways:
    1. Direct initialization with a ClientSession
    2. As an async context manager with StdioServerParameters
    """

    def __init__(
        self,
        session: Optional[ClientSession] = None,
        server_params: Optional[StdioServerParameters] = None,
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
            client: The underlying MCP client (optional, used to prevent garbage collection)
            include_tools: Optional list of tool names to include (if None, includes all)
            exclude_tools: Optional list of tool names to exclude (if None, excludes none)
        """
        super().__init__(name="MCPToolkit", **kwargs)

        if session is None and server_params is None:
            raise ValueError("Either session or server_params must be provided")

        self.session: Optional[ClientSession] = session
        self.server_params: Optional[StdioServerParameters] = server_params
        self.available_tools: Optional[ListToolsResult] = None
        self._client = client
        self._stdio_context = None
        self._session_context = None
        self._initialized = False
        self.include_tools = include_tools
        self.exclude_tools = exclude_tools or []

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
            self.available_tools = await self.session.list_tools()

            # Filter tools based on include/exclude lists
            filtered_tools = []
            for tool in self.available_tools.tools:
                if tool.name in self.exclude_tools:
                    continue
                if self.include_tools is None or tool.name in self.include_tools:
                    filtered_tools.append(tool)

            # Register the tools with the toolkit
            for tool in filtered_tools:
                try:
                    # Get an entrypoint for the tool
                    entrypoint = self.get_entrypoint_for_tool(tool)

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

    def get_entrypoint_for_tool(self, tool: MCPTool):
        """
        Return an entrypoint for an MCP tool.

        Args:
            tool: The MCP tool to create an entrypoint for

        Returns:
            Callable: The entrypoint function for the tool
        """

        async def call_tool(agent: Agent, tool_name: str, **kwargs) -> str:
            try:
                log_debug(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
                result: CallToolResult = await self.session.call_tool(tool_name, kwargs)  # type: ignore

                # Return an error if the tool call failed
                if result.isError:
                    raise Exception(f"Error from MCP tool '{tool_name}': {result.content}")

                # Process the result content
                response_str = ""
                for content_item in result.content:
                    if isinstance(content_item, TextContent):
                        response_str += content_item.text + "\n"
                    elif isinstance(content_item, ImageContent):
                        # Handle image content if present
                        img_artifact = ImageArtifact(
                            id=str(uuid4()),
                            url=getattr(content_item, "url", None),
                            base64_data=getattr(content_item, "data", None),
                            mime_type=getattr(content_item, "mimeType", "image/png"),
                        )
                        agent.add_image(img_artifact)
                        response_str += "Image has been generated and added to the response.\n"
                    elif isinstance(content_item, EmbeddedResource):
                        # Handle embedded resources
                        response_str += f"[Embedded resource: {content_item.resource.model_dump_json()}]\n"
                    else:
                        # Handle other content types
                        response_str += f"[Unsupported content type: {content_item.type}]\n"

                return response_str.strip()
            except Exception as e:
                logger.exception(f"Failed to call MCP tool '{tool_name}': {e}")
                return f"Error: {e}"

        return partial(call_tool, tool_name=tool.name, tool_description=tool.description)
