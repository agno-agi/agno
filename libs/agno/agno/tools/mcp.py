from functools import partial
from typing import Optional
from uuid import uuid4

from agno.agent import Agent
from agno.media import ImageArtifact
from agno.tools import Toolkit
from agno.tools.function import Function
from agno.utils.log import logger

try:
    from mcp import ClientSession, ListToolsResult
    from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent
    from mcp.types import Tool as MCPTool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


class MCPTools(Toolkit):
    """
    A toolkit for integrating Model Context Protocol (MCP) servers with Agno agents.
    This allows agents to access tools, resources, and prompts exposed by MCP servers.
    """

    def __init__(
        self,
        session: ClientSession,
        client=None,
    ):
        """
        Initialize the MCP toolkit with a connected MCP client session.

        Args:
            session: An initialized MCP ClientSession connected to an MCP server
            client: The underlying MCP client (optional, used to prevent garbage collection)
        """
        super().__init__(name="MCPToolkit")
        self.session: ClientSession = session
        self.available_tools: Optional[ListToolsResult] = None
        self._client = client

    async def initialize(self) -> None:
        """Initialize the MCP toolkit by getting available tools from the MCP server"""
        try:
            # Initialize the session if not already initialized
            await self.session.initialize()

            # Get the list of tools from the MCP server
            self.available_tools = await self.session.list_tools()

            # Register the tools with the toolkit
            for tool in self.available_tools.tools:
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
                    logger.debug(f"Function: {f.name} registered with {self.name}")
                except Exception as e:
                    logger.error(f"Failed to register tool {tool.name}: {e}")

            logger.debug(f"{self.name} initialized with {len(self.available_tools.tools)} tools")
        except Exception as e:
            logger.error(f"Failed to get MCP tools: {e}")

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
                logger.debug(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
                result: CallToolResult = await self.session.call_tool(tool_name, kwargs)

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

        return partial(call_tool, tool_name=tool.name)
