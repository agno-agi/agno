import asyncio
import json
from typing import TYPE_CHECKING, Any, Dict, Optional, Protocol, runtime_checkable
from uuid import uuid4

from agno.utils.log import log_debug, log_error, log_exception

try:
    from mcp.shared.exceptions import MCPError
    from mcp.types import CallToolResult, EmbeddedResource, ImageContent, TextContent
    from mcp.types import Tool as MCPTool
except ModuleNotFoundError:
    raise ImportError("`mcp` not installed. Please install using `pip install 'mcp>=2.1.0,<3.0.0'`")


from agno.media import Image
from agno.tools.function import ToolResult


@runtime_checkable
class MCPSession(Protocol):
    """The session surface this package uses, satisfied by both session types.

    A connection is driven either by a ``fastmcp.Client`` the toolkit built or by a
    ``ClientSession`` the caller supplied. The two are unrelated classes, so this
    structural type is what lets the shared code paths stay checked instead of falling
    back to ``Any``.

    Only the three methods every caller needs are required. Liveness probing is left
    out deliberately: ``ClientSession`` spells it ``send_ping`` and ``fastmcp.Client``
    spells it ``ping``, so ``ping_session`` resolves it by name at the one call site.
    """

    async def call_tool(
        self, name: str, arguments: Optional[Dict[str, Any]] = None, *args: Any, **kwargs: Any
    ) -> Any: ...

    async def list_tools(self, *args: Any, **kwargs: Any) -> Any: ...

    async def initialize(self, *args: Any, **kwargs: Any) -> Any: ...


if TYPE_CHECKING:
    from agno.agent import Agent
    from agno.run import RunContext
    from agno.team.team import Team
    from agno.tools.mcp.mcp import MCPTools


def get_default_toolkit_name(
    url: Optional[str] = None,
    command: Optional[str] = None,
    server_params: Optional[Any] = None,
    fallback: str = "MCPTools",
) -> str:
    """Derive a stable toolkit name from MCP connection parameters.

    Distinct servers produce distinct names so that multiple MCP toolkits can
    coexist in one Registry: they stay distinguishable in listings, selectable
    by name, and are not collapsed by structural deduplication. The name is
    derived at construction time (no connection needed): from the URL for HTTP
    transports, from the command for stdio, or from the equivalent fields of
    ``server_params``. Query strings and fragments are dropped from URLs so
    credentials passed as query parameters never end up in the toolkit name.

    Returns ``fallback`` when no connection parameters are available (e.g. the
    toolkit wraps an existing session).
    """
    target: Optional[str] = None
    if url:
        target = _strip_url_for_name(url)
    elif command:
        target = command
    elif server_params is not None:
        params_url = getattr(server_params, "url", None)
        params_command = getattr(server_params, "command", None)
        if params_url:
            target = _strip_url_for_name(params_url)
        elif params_command:
            args = getattr(server_params, "args", None) or []
            target = " ".join([str(params_command), *(str(arg) for arg in args)])

    if not target:
        return fallback

    slug = "".join(char if char.isalnum() else "_" for char in target.lower())
    while "__" in slug:
        slug = slug.replace("__", "_")
    slug = slug.strip("_")
    if not slug:
        return fallback
    return f"mcp_{slug}"[:64]


def _strip_url_for_name(url: str) -> str:
    """Reduce a URL to scheme-less host + path, dropping userinfo, query and fragment.

    Everything that can carry credentials (``user:pass@`` userinfo, query
    parameters, fragments) is removed so it can never leak into the toolkit
    name, which surfaces in registry listings and persisted configs.
    """
    remainder = url.split("://", 1)[-1]
    remainder = remainder.split("?", 1)[0].split("#", 1)[0]
    authority, slash, path = remainder.partition("/")
    if "@" in authority:
        authority = authority.rsplit("@", 1)[-1]
    return authority + slash + path


def _is_fastmcp_client(session: Any) -> bool:
    """True when the session is a fastmcp Client rather than a raw ClientSession."""
    try:
        from fastmcp import Client
    except ModuleNotFoundError:
        return False
    return isinstance(session, Client)


async def ping_session(session: MCPSession) -> None:
    """Send an MCP ping, or do nothing when the negotiated protocol has none.

    The sessionless 2026-07-28 era removed ping, so a client that negotiated it would
    raise "Method not found" on every probe. There is no connection to keep alive
    there, so skipping is the correct behaviour rather than a swallowed failure.
    """
    protocol_version = getattr(session, "protocol_version", None)
    # Compare only a real version string: a mock attribute must not look like an era.
    if isinstance(protocol_version, str) and protocol_version >= "2026-07-28":
        return

    # A ClientSession exposes send_ping(); fastmcp's Client exposes ping(). Neither is
    # on MCPSession, which is why both are resolved by name here rather than called.
    ping = getattr(session, "send_ping", None) or getattr(session, "ping")
    await ping()


def get_entrypoint_for_tool(
    tool: MCPTool,
    session: MCPSession,
    mcp_tools_instance: Optional["MCPTools"] = None,
):
    """
    Return an entrypoint for an MCP tool.

    Args:
        tool: The MCP tool to create an entrypoint for
        session: The MCP ClientSession to use
        mcp_tools_instance: Optional MCPTools instance

    Returns:
        Callable: The entrypoint function for the tool
    """

    async def call_tool(
        _agno_run_context: Optional["RunContext"] = None,
        _agno_agent: Optional["Agent"] = None,
        _agno_team: Optional["Team"] = None,
        **kwargs,
    ) -> ToolResult:
        # Framework-injected params use the `_agno_` prefix so they cannot
        # collide with MCP tool arguments named "run_context", "agent" and
        # "team".
        # The executed tool is pinned to the tool this entrypoint was built
        # for: call-time arguments cannot change it. A model-supplied
        # "tool_name" argument stays in **kwargs and is forwarded to the
        # server as an ordinary argument of the declared tool.
        tool_name = tool.name

        async def _call_with_session(active_session: MCPSession) -> ToolResult:
            try:
                await ping_session(active_session)
            except Exception as e:
                log_exception(e)

            log_debug(f"Calling MCP Tool '{tool_name}' with args: {kwargs}")
            # fastmcp's Client raises ToolError on a failed call, where a ClientSession
            # returns is_error=True. Ask it not to, so both types land on the is_error
            # branch below: a failing tool is ordinary model-loop traffic, and routing it
            # through the generic handler drops the result's meta/structured_content and
            # logs a stack trace for it. Only fastmcp's Client takes the kwarg.
            if _is_fastmcp_client(active_session):
                result: CallToolResult = await active_session.call_tool(tool_name, kwargs, raise_on_error=False)
            else:
                result = await active_session.call_tool(tool_name, kwargs)

            # Return an error if the tool call failed
            if result.is_error:
                return ToolResult(
                    content=f"Error from MCP tool '{tool_name}': {result.content}",
                    metadata=_build_mcp_metadata(result),
                )

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

                                image_bytes: Optional[bytes]
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
                        mime_type=getattr(content_item, "mime_type", "image/png"),
                    )
                    images.append(img_artifact)
                    response_str += "Image has been generated and added to the response.\n"
                elif isinstance(content_item, EmbeddedResource):
                    # Handle embedded resources
                    response_str += f"[Embedded resource: {content_item.resource.model_dump_json(by_alias=True)}]\n"
                else:
                    # Handle other content types
                    response_str += f"[Unsupported content type: {content_item.type}]\n"

            if not response_str.strip():
                response_str = _serialize_structured_content(result) or ""

            return ToolResult(
                content=response_str.strip(),
                metadata=_build_mcp_metadata(result),
                images=images if images else None,
            )

        # Execute the MCP tool call
        try:
            # Get the appropriate session for this run.
            # If mcp_tools_instance has header_provider and run_context is provided,
            # this will create/reuse a session with dynamic headers.
            if mcp_tools_instance and hasattr(mcp_tools_instance, "get_session_for_run"):
                if (
                    hasattr(mcp_tools_instance, "should_use_temporary_run_session")
                    and mcp_tools_instance.should_use_temporary_run_session(_agno_run_context)
                    and hasattr(mcp_tools_instance, "get_temporary_session_for_run")
                ):
                    async with mcp_tools_instance.get_temporary_session_for_run(
                        run_context=_agno_run_context,
                        agent=_agno_agent,
                        team=_agno_team,
                    ) as active_session:
                        return await _call_with_session(active_session)

                active_session = await mcp_tools_instance.get_session_for_run(
                    run_context=_agno_run_context, agent=_agno_agent, team=_agno_team
                )
                return await _call_with_session(active_session)

            return await _call_with_session(session)
        except asyncio.CancelledError:
            raise
        except MCPError as e:
            msg = f"MCP tool '{tool_name}' failed: {e}. The MCP server may be unreachable or the request timed out."
            log_error(msg)
            return ToolResult(content=msg)
        except Exception as e:
            log_exception(f"Failed to call MCP tool '{tool_name}': {e}")
            return ToolResult(content=f"Error: {e}")

    return call_tool


def _build_mcp_metadata(result: "CallToolResult") -> Optional[Dict[str, Any]]:
    """Collect a tool result's extra MCP data into a single ToolResult.metadata dict.

    Protocol `_meta` and the tool's `structuredContent` are stored as the reserved keys
    `meta` and `structured_content` rather than as separate ToolResult fields, so future MCP
    additions become new keys here instead of new attributes. `getattr` guards both: older MCP
    servers (mcp < 1.10.0) expose no `structuredContent`, so the key is simply omitted. Returns
    None when there is nothing to preserve.
    """
    metadata: Dict[str, Any] = {}
    if getattr(result, "meta", None) is not None:
        metadata["meta"] = result.meta
    structured_content = getattr(result, "structured_content", None)
    if structured_content is not None:
        metadata["structured_content"] = structured_content
    return metadata or None


def _serialize_structured_content(result: "CallToolResult") -> Optional[str]:
    """Serialize structuredContent so structured-only MCP responses reach the model loop."""
    structured_content = getattr(result, "structured_content", None)
    if structured_content is None:
        return None

    try:
        return json.dumps(structured_content, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(structured_content)


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
