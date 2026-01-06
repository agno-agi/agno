import json
from functools import partial
from typing import TYPE_CHECKING, Optional, Union
from uuid import uuid4

from agno.utils.log import log_debug, log_exception

try:
    from mcp import ClientSession
    from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent
    from mcp.types import Tool as MCPTool
except (ImportError, ModuleNotFoundError):
    raise ImportError("`mcp` not installed. Please install using `pip install mcp`")


from agno.media import Image
from agno.tools.function import ToolResult

if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run import RunContext
    from agno.team.team import Team
    from agno.tools.mcp.mcp import MCPTools
    from agno.tools.mcp.multi_mcp import MultiMCPTools


def get_entrypoint_for_tool(
    tool: MCPTool,
    session: ClientSession,
    mcp_tools_instance: Optional[Union["MCPTools", "MultiMCPTools"]] = None,
    server_idx: int = 0,
):
    """
    Return an entrypoint for an MCP tool.

    Args:
        tool: The MCP tool to create an entrypoint for
        session: The MCP ClientSession to use
        mcp_tools_instance: Optional MCPTools or MultiMCPTools instance
        server_idx: Index of the server (for MultiMCPTools)

    Returns:
        Callable: The entrypoint function for the tool
    """

    async def call_tool(
        tool_name: str,
        run_context: Optional["RunContext"] = None,
        agent: Optional["Agent"] = None,
        team: Optional["Team"] = None,
        **kwargs,
    ) -> ToolResult:
        # Execute the MCP tool call
        try:
            # Get the appropriate session for this run
            # If mcp_tools_instance has header_provider and run_context is provided,
            # this will create/reuse a session with dynamic headers
            if mcp_tools_instance and hasattr(mcp_tools_instance, "get_session_for_run"):
                # Import here to avoid circular imports
                from agno.tools.mcp.multi_mcp import MultiMCPTools

                # For MultiMCPTools, pass server_idx; for MCPTools, only pass run_context
                if isinstance(mcp_tools_instance, MultiMCPTools):
                    active_session = await mcp_tools_instance.get_session_for_run(
                        run_context=run_context, server_idx=server_idx, agent=agent, team=team
                    )
                else:
                    active_session = await mcp_tools_instance.get_session_for_run(
                        run_context=run_context, agent=agent, team=team
                    )
            else:
                active_session = session

            try:
                await active_session.send_ping()
            except Exception as e:
                log_exception(e)

            log_debug(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
            result: CallToolResult = await active_session.call_tool(tool_name, kwargs)  # type: ignore

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


def prepare_command(command: str) -> list[str]:
    """Sanitize a command and split it into parts before using it to run a MCP server."""
    import os
    import shutil
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
        "docker",
    }

    executable = parts[0].split("/")[-1]

    # Check if it's a relative path starting with ./ or ../
    if executable.startswith("./") or executable.startswith("../"):
        # Allow relative paths to binaries
        return parts

    # Check if it's an absolute path to a binary
    if executable.startswith("/") and os.path.isfile(executable):
        # Allow absolute paths to existing files
        return parts

    # Check if it's a binary in current directory without ./
    if "/" not in executable and os.path.isfile(executable):
        # Allow binaries in current directory
        return parts

    # Check if it's a binary in PATH
    if shutil.which(executable):
        return parts

    if executable not in ALLOWED_COMMANDS:
        raise ValueError(f"MCP command needs to use one of the following executables: {ALLOWED_COMMANDS}")

    first_part = parts[0]
    executable = first_part.split("/")[-1]

    # Allow known commands
    if executable in ALLOWED_COMMANDS:
        return parts

    # Allow relative paths to custom binaries
    if first_part.startswith(("./", "../")):
        return parts

    # Allow absolute paths to existing files
    if first_part.startswith("/") and os.path.isfile(first_part):
        return parts

    # Allow binaries in current directory without ./
    if "/" not in first_part and os.path.isfile(first_part):
        return parts

    # Allow binaries in PATH
    if shutil.which(first_part):
        return parts

    raise ValueError(f"MCP command needs to use one of the following executables: {ALLOWED_COMMANDS}")
