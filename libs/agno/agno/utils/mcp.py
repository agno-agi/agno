import json
from functools import partial
from uuid import uuid4

from agno.utils.log import log_debug, log_exception

try:
    from mcp import ClientSession
    from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent
    from mcp.types import Tool as MCPTool

    # New additions
    from mcp.types import Prompt as MCPPrompt
    from mcp.types import GetPromptResult  
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


from agno.media import Image
from agno.tools.function import ToolResult


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

    async def call_tool(agent: Agent, tool_name: str, **kwargs) -> ToolResult:
        try:
            log_debug(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
            result: CallToolResult = await session.call_tool(tool_name, kwargs)  # type: ignore

            # Return an error if the tool call failed
            if result.isError:
                return ToolResult(content=f"Error from MCP tool '{tool_name}': {result.content}")

            # Process the result content
            response_str = ""
            images = []

            for content_item in result.content:
                if isinstance(content_item, TextContent):
                    text_content = content_item.text

                    # Parse as JSON to check for custom image format
                    try:
                        parsed_json = json.loads(text_content)
                        if (
                            isinstance(parsed_json, dict)
                            and parsed_json.get("type") == "image"
                            and "data" in parsed_json
                        ):
                            log_debug("Found custom JSON image format in TextContent")

                            # Extract image data
                            image_data = parsed_json.get("data")
                            mime_type = parsed_json.get("mimeType", "image/png")

                            if image_data and isinstance(image_data, str):
                                import base64

                                try:
                                    image_bytes = base64.b64decode(image_data)
                                except Exception as e:
                                    log_debug(f"Failed to decode base64 image data: {e}")
                                    image_bytes = None

                                if image_bytes:
                                    img_artifact = Image(
                                        id=str(uuid4()),
                                        url=None,
                                        content=image_bytes,
                                        mime_type=mime_type,
                                    )
                                    images.append(img_artifact)
                                    response_str += "Image has been generated and added to the response.\n"
                                    continue

                    except (json.JSONDecodeError, TypeError):
                        pass

                    response_str += text_content + "\n"

                elif isinstance(content_item, ImageContent):
                    # Handle standard MCP ImageContent
                    image_data = getattr(content_item, "data", None)

                    if image_data and isinstance(image_data, str):
                        import base64

                        try:
                            image_data = base64.b64decode(image_data)
                        except Exception as e:
                            log_debug(f"Failed to decode base64 image data: {e}")
                            image_data = None

                    img_artifact = Image(
                        id=str(uuid4()),
                        url=getattr(content_item, "url", None),
                        content=image_data,
                        mime_type=getattr(content_item, "mimeType", "image/png"),
                    )
                    images.append(img_artifact)
                    response_str += "Image has been generated and added to the response.\n"
                elif isinstance(content_item, EmbeddedResource):
                    # Handle embedded resources
                    response_str += f"[Embedded resource: {content_item.resource.model_dump_json()}]\n"
                else:
                    # Handle other content types
                    response_str += f"[Unsupported content type: {content_item.type}]\n"

            return ToolResult(
                content=response_str.strip(),
                images=images if images else None,
            )
        except Exception as e:
            log_exception(f"Failed to call MCP tool '{tool_name}': {e}")
            return ToolResult(content=f"Error: {e}")

    return partial(call_tool, tool_name=tool.name)

# ADD THIS NEW FUNCTION
def get_entrypoint_for_prompt(prompt: MCPPrompt, session: ClientSession):
    """
    Return an entrypoint for an MCP prompt.

    Args:
        prompt: The MCP prompt to create an entrypoint for
        session: The session to use

    Returns:
        Callable: The entrypoint function for the prompt
    """
    from agno.agent import Agent

    async def get_prompt(agent: Agent, prompt_name: str, **kwargs) -> str:
        try:
            log_debug(f"Retrieving MCP Prompt '{prompt_name}' with args: {kwargs}")
            
            # Convert all arguments to strings (get_prompt expects dict[str, str])
            arguments = {k: str(v) for k, v in kwargs.items()} if kwargs else None
            
            # Call the MCP get_prompt method
            result: GetPromptResult = await session.get_prompt(prompt_name, arguments)  # type: ignore

            # Extract text content from all messages
            messages = []
            for message in result.messages:
                # Handle different content types
                if hasattr(message.content, 'text'):
                    messages.append(message.content.text)
                elif isinstance(message.content, TextContent):
                    messages.append(message.content.text)
                else:
                    # Fallback for other content types
                    messages.append(str(message.content))
            
            # Join all messages with double newlines
            return "\n\n".join(messages) if messages else ""
            
        except Exception as e:
            log_exception(f"Failed to retrieve MCP prompt '{prompt_name}': {e}")
            return f"Error retrieving prompt: {e}"

    return partial(get_prompt, prompt_name=prompt.name)