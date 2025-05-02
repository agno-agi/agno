from functools import partial
from uuid import uuid4

from agno.utils.log import log_debug, log_exception

try:
    from mcp import ClientSession
    from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent
    from mcp.types import Tool as MCPTool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


from agno.media import ImageArtifact


def get_entrypoint_for_tool(tool: MCPTool, session: ClientSession):
    """
    Return an entrypoint for an MCP tool.

    Args:
        tool: The MCP tool to create an entrypoint for
        session: The session to use

    Returns:
        Callable: The entrypoint function for the tool
    """
    from agno.agent import Agent

    async def call_tool(agent: Agent, tool_name: str, **kwargs) -> str:
        try:
            log_debug(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
            result: CallToolResult = await session.call_tool(tool_name, kwargs)  # type: ignore

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
                        content=getattr(content_item, "data", None),
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
            log_exception(f"Failed to call MCP tool '{tool_name}': {e}")
            return f"Error: {e}"

    return partial(call_tool, tool_name=tool.name, tool_description=tool.description)
