from typing import Any, Callable, Dict, List, Literal, Optional, Union
from warnings import warn

from agno.tools.function import Function
from agno.tools.mcp import MCPTools
from agno.utils.log import logger

try:
    from toolbox_core import ToolboxClient  # type: ignore
except ImportError:
    raise ImportError("`toolbox_core` not installed. Please install using `pip install -U toolbox-core`.")


class MCPToolsMeta(type):
    """Metaclass for MCPTools to ensure proper initialization with AgentOS"""

    @property
    def __name__(cls):
        return "MCPTools"


class MCPToolbox(MCPTools, metaclass=MCPToolsMeta):
    """
    A toolkit that combines MCPTools server connectivity with MCP Toolbox for Databases client (toolbox-core).

    MCPToolbox connects to an MCP Toolbox server and registers all available tools, then uses
    toolbox-core to filter those tools by toolset or tool name. This enables agents to
    receive only the specific tools they need while maintaining full MCP execution capabilities.
    """

    def __init__(
        self,
        url: str,
        toolsets: Optional[List[str]] = None,
        tool_name: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        transport: Literal["stdio", "sse", "streamable-http"] = "streamable-http",
        append_mcp_to_url: bool = True,
        **kwargs,
    ):
        """Initialize MCPToolbox with filtering capabilities.

        Args:
            url (str): Base URL for the toolbox service.
            toolsets (Optional[List[str]], optional): List of toolset names to filter tools by. Defaults to None.
            tool_name (Optional[str], optional): Single tool name to load. Defaults to None.
            headers (Optional[Dict[str, Any]], optional): Headers for toolbox-core client requests. Defaults to None.
            transport (Literal["stdio", "sse", "streamable-http"], optional): MCP transport protocol. Defaults to "streamable-http".
            append_mcp_to_url (bool, optional): Whether to append "/mcp" to the URL if it doesn't end with it. Defaults to True.

        """
        if append_mcp_to_url and not url.endswith("/mcp"):
            url = url + "/mcp"

        super().__init__(url=url, transport=transport, **kwargs)

        self.name = "toolbox_client"
        self.toolbox_url = url
        self.toolsets = toolsets
        self.tool_name = tool_name
        self.headers = headers
        self._core_client_initialized = False

        # Validate that only one of toolsets or tool_name is provided
        filter_params = [toolsets, tool_name]
        non_none_params = [p for p in filter_params if p is not None]
        if len(non_none_params) > 1:
            raise ValueError("Only one of toolsets or tool_name can be specified")

    async def connect(self):
        """Initialize MCPToolbox instance and connect to the MCP server."""
        # First, connect to MCP server and load all available tools
        await super().connect()

        if self._core_client_initialized:
            return

        # Then, connect to the ToolboxClient and filter tools based on toolsets or tool_name
        await self._connect_toolbox_client()

    async def _connect_toolbox_client(self):
        try:
            if self.toolsets is not None or self.tool_name is not None:
                self.__core_client = ToolboxClient(
                    url=self.toolbox_url,
                    client_headers=self.headers,
                )
                self._core_client_initialized = True

                if self.toolsets is not None:
                    # Load multiple toolsets
                    all_functions = await self.load_multiple_toolsets(toolset_names=self.toolsets)
                    # Replace functions dict with filtered subset
                    filtered_functions = {func.name: func for func in all_functions}
                    self.functions = filtered_functions
                elif self.tool_name is not None:
                    tool = await self.load_tool(tool_name=self.tool_name)
                    # Replace functions dict with just this single tool
                    self.functions = {tool.name: tool}
        except Exception as e:
            raise RuntimeError(f"Failed to connect to ToolboxClient: {e}") from e

    def _handle_auth_params(
        self,
        auth_token_getters: dict[str, Callable[[], str]] = {},
        auth_tokens: Optional[dict[str, Callable[[], str]]] = None,
        auth_headers: Optional[dict[str, Callable[[], str]]] = None,
    ):
        """handle authentication parameters for toolbox-core client"""
        if auth_tokens:
            if auth_token_getters:
                warn(
                    "Both `auth_token_getters` and `auth_tokens` are provided. `auth_tokens` is deprecated, and `auth_token_getters` will be used.",
                    DeprecationWarning,
                )
            else:
                warn(
                    "Argument `auth_tokens` is deprecated. Use `auth_token_getters` instead.",
                    DeprecationWarning,
                )
                auth_token_getters = auth_tokens

        if auth_headers:
            if auth_token_getters:
                warn(
                    "Both `auth_token_getters` and `auth_headers` are provided. `auth_headers` is deprecated, and `auth_token_getters` will be used.",
                    DeprecationWarning,
                )
            else:
                warn(
                    "Argument `auth_headers` is deprecated. Use `auth_token_getters` instead.",
                    DeprecationWarning,
                )
                auth_token_getters = auth_headers
        return auth_token_getters

    async def load_tool(
        self,
        tool_name: str,
        auth_token_getters: dict[str, Callable[[], str]] = {},
        auth_tokens: Optional[dict[str, Callable[[], str]]] = None,
        auth_headers: Optional[dict[str, Callable[[], str]]] = None,
        bound_params: dict[str, Union[Any, Callable[[], Any]]] = {},
    ) -> Function:
        """Loads the tool with the given tool name from the Toolbox service.

        Args:
            tool_name (str): The name of the tool to load.
            auth_token_getters (dict[str, Callable[[], str]], optional): A mapping of authentication source names to functions that retrieve ID tokens. Defaults to {}.
            auth_tokens (Optional[dict[str, Callable[[], str]]], optional): Deprecated. Use `auth_token_getters` instead.
            auth_headers (Optional[dict[str, Callable[[], str]]], optional): Deprecated. Use `auth_token_getters` instead.
            bound_params (dict[str, Union[Any, Callable[[], Any]]], optional): A mapping of parameter names to their bound values. Defaults to {}.

        Raises:
            RuntimeError: If the tool is not found in the MCP functions registry.

        Returns:
            Function: The loaded tool function.
        """
        auth_token_getters = self._handle_auth_params(
            auth_token_getters=auth_token_getters,
            auth_tokens=auth_tokens,
            auth_headers=auth_headers,
        )

        core_sync_tool = await self.__core_client.load_tool(
            name=tool_name,
            auth_token_getters=auth_token_getters,
            bound_params=bound_params,
        )
        # Return the Function object from our MCP functions registry
        if core_sync_tool._name in self.functions:
            return self.functions[core_sync_tool._name]
        else:
            raise RuntimeError(f"Tool '{tool_name}' was not found in MCP functions registry")

    async def load_toolset(
        self,
        toolset_name: Optional[str] = None,
        auth_token_getters: dict[str, Callable[[], str]] = {},
        auth_tokens: Optional[dict[str, Callable[[], str]]] = None,
        auth_headers: Optional[dict[str, Callable[[], str]]] = None,
        bound_params: dict[str, Union[Any, Callable[[], Any]]] = {},
        strict: bool = False,
    ) -> List[Function]:
        """Loads tools from the configured toolset.

        Args:
            toolset_name (Optional[str], optional): The name of the toolset to load. Defaults to None.
            auth_token_getters (dict[str, Callable[[], str]], optional): A mapping of authentication source names to functions that retrieve ID tokens. Defaults to {}.
            auth_tokens (Optional[dict[str, Callable[[], str]]], optional): Deprecated. Use `auth_token_getters` instead.
            auth_headers (Optional[dict[str, Callable[[], str]]], optional): Deprecated. Use `auth_token_getters` instead.
            bound_params (dict[str, Union[Any, Callable[[], Any]]], optional): A mapping of parameter names to their bound values. Defaults to {}.
            strict (bool, optional): If True, raises an error if *any* loaded tool instance fails
                to utilize all of the given parameters or auth tokens. (if any
                provided). If False (default), raises an error only if a
                user-provided parameter or auth token cannot be applied to *any*
                loaded tool across the set.

        Returns:
            List[Function]: A list of all tools loaded from the Toolbox.
        """
        auth_token_getters = self._handle_auth_params(
            auth_token_getters=auth_token_getters,
            auth_tokens=auth_tokens,
            auth_headers=auth_headers,
        )

        core_sync_tools = await self.__core_client.load_toolset(
            name=toolset_name,
            auth_token_getters=auth_token_getters,
            bound_params=bound_params,
            strict=strict,
        )

        tools = []
        for core_sync_tool in core_sync_tools:
            if core_sync_tool._name in self.functions:
                tools.append(self.functions[core_sync_tool._name])
            else:
                logger.debug(f"Tool '{core_sync_tool._name}' from toolset '{toolset_name}' not available in MCP server")
        return tools

    async def load_multiple_toolsets(
        self,
        toolset_names: List[str],
        auth_token_getters: dict[str, Callable[[], str]] = {},
        bound_params: dict[str, Union[Any, Callable[[], Any]]] = {},
        strict: bool = False,
    ) -> List[Function]:
        """Load tools from multiple toolsets.

        Args:
            toolset_names (List[str]): A list of toolset names to load.
            auth_token_getters (dict[str, Callable[[], str]], optional): A mapping of authentication source names to functions that retrieve ID tokens. Defaults to {}.
            bound_params (dict[str, Union[Any, Callable[[], Any]]], optional): A mapping of parameter names to their bound values. Defaults to {}.
            strict (bool, optional): If True, raises an error if *any* loaded tool instance fails to utilize all of the given parameters or auth tokens. Defaults to False.

        Returns:
            List[Function]: A list of all tools loaded from the specified toolsets.
        """
        all_tools = []
        for toolset_name in toolset_names:
            tools = await self.load_toolset(
                toolset_name=toolset_name,
                auth_token_getters=auth_token_getters,
                bound_params=bound_params,
                strict=strict,
            )
            all_tools.extend(tools)
        return all_tools

    async def close(self):
        """Close the underlying asynchronous client."""
        if self._core_client_initialized and hasattr(self, "_MCPToolbox__core_client"):
            await self.__core_client.close()
        await super().close()

    async def load_toolset_safe(self, toolset_name: str) -> List[str]:
        """Safely load a toolset and return tool names."""
        try:
            tools = await self.load_toolset(toolset_name)
            return [tool.name for tool in tools]
        except Exception as e:
            raise RuntimeError(f"Failed to load toolset '{toolset_name}': {e}") from e

    def get_client(self) -> ToolboxClient:
        """Get the underlying ToolboxClient."""
        if not self._core_client_initialized:
            raise RuntimeError("ToolboxClient not initialized. Call connect() first.")
        return self.__core_client

    async def __aenter__(self):
        """Initialize the direct toolbox client."""
        await super().__aenter__()
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up the toolbox client."""
        # Close ToolboxClient first, then MCP client
        if self._core_client_initialized and hasattr(self, "_MCPToolbox__core_client"):
            await self.__core_client.close()
        await super().__aexit__(exc_type, exc_val, exc_tb)
