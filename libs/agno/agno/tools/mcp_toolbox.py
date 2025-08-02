from typing import Any, Callable, Dict, List, Literal, Optional, Union
from warnings import warn

from agno.tools.function import Function

from .mcp import MCPTools

try:
    from toolbox_core import ToolboxClient
except ImportError:
    raise ImportError("`toolbox_core` not installed. Please install using `pip install toolbox-core`.")


class MCPToolbox(MCPTools):
    def __init__(
        self,
        url: str = None,
        toolsets: Optional[List[str]] = None,
        tool_name: Optional[str] = None,
        headers: Optional[Dict[str, Any]] = None,
        transport: Literal["stdio", "sse", "streamable-http"] = "streamable-http",
        **kwargs,
    ):
        super().__init__(url=url + "/mcp", transport=transport, **kwargs)

        self.name = "toolbox_client"
        self.toolbox_url = url
        self.toolsets = toolsets
        self.tool_name = tool_name
        self.headers = headers

        # Validate that only one of toolset_name, toolsets, or tool_name is provided
        filter_params = [toolsets, tool_name]
        non_none_params = [p for p in filter_params if p is not None]
        if len(non_none_params) > 1:
            raise ValueError("Only one of toolsets, or tool_name can be specified")

    async def load_tool(
        self,
        tool_name: str,
        auth_token_getters: dict[str, Callable[[], str]] = {},
        auth_tokens: Optional[dict[str, Callable[[], str]]] = None,
        auth_headers: Optional[dict[str, Callable[[], str]]] = None,
        bound_params: dict[str, Union[Any, Callable[[], Any]]] = {},
    ) -> Function:
        """
        Loads the tool with the given tool name from the Toolbox service.

        Args:
            tool_name: The name of the tool to load.
            auth_token_getters: An optional mapping of authentication source
                names to functions that retrieve ID tokens.
            auth_tokens: Deprecated. Use `auth_token_getters` instead.
            auth_headers: Deprecated. Use `auth_token_getters` instead.
            bound_params: An optional mapping of parameter names to their
                bound values.

        Returns:
            A tool loaded from the Toolbox.
        """
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

        core_sync_tool = await self.__core_client.load_tool(
            name=tool_name,
            auth_token_getters=auth_token_getters,
            bound_params=bound_params,
        )
        return self.functions[core_sync_tool._name]

    async def load_toolset(
        self,
        toolset_name: Optional[str] = None,
        auth_token_getters: dict[str, Callable[[], str]] = {},
        auth_tokens: Optional[dict[str, Callable[[], str]]] = None,
        auth_headers: Optional[dict[str, Callable[[], str]]] = None,
        bound_params: dict[str, Union[Any, Callable[[], Any]]] = {},
        strict: bool = False,
    ) -> List[Function]:
        """
        Loads tools from the Toolbox service, optionally filtered by toolset
        name.

        Args:
            toolset_name: The name of the toolset to load. If not provided,
                all tools are loaded.
            auth_token_getters: An optional mapping of authentication source
                names to functions that retrieve ID tokens.
            auth_tokens: Deprecated. Use `auth_token_getters` instead.
            auth_headers: Deprecated. Use `auth_token_getters` instead.
            bound_params: An optional mapping of parameter names to their
                bound values.
            strict: If True, raises an error if *any* loaded tool instance fails
                to utilize all of the given parameters or auth tokens. (if any
                provided). If False (default), raises an error only if a
                user-provided parameter or auth token cannot be applied to *any*
                loaded tool across the set.

        Returns:
            A list of all tools loaded from the Toolbox.
        """
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
        return tools

    async def load_multiple_toolsets(
        self,
        toolset_names: List[str],
        auth_token_getters: dict[str, Callable[[], str]] = {},
        bound_params: dict[str, Union[Any, Callable[[], Any]]] = {},
        strict: bool = False,
    ) -> List[Function]:
        """
        Load tools from multiple toolsets.

        Args:
            toolset_names: List of toolset names to load.
            auth_token_getters: An optional mapping of authentication source
                names to functions that retrieve ID tokens.
            bound_params: An optional mapping of parameter names to their
                bound values.
            strict: If True, raises an error if *any* loaded tool instance fails
                to utilize all of the given parameters or auth tokens.

        Returns:
            A list of all tools loaded from the specified toolsets.
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
        await self.__core_client.close()

    async def load_toolset_safe(self, toolset_name: str) -> List[str]:
        """Safely load a toolset and return tool names."""
        try:
            tools = await self.load_toolset(toolset_name)
            return [tool.name for tool in tools]
        except Exception as e:
            raise RuntimeError(f"Failed to load toolset '{toolset_name}': {e}") from e

    def get_client(self) -> ToolboxClient:
        """Get the underlying ToolboxClient."""
        return self.__core_client

    async def __aenter__(self):
        """Initialize the direct toolbox client."""

        await super().__aenter__()
        self.__core_client = ToolboxClient(
            url=self.toolbox_url,
            client_headers=self.headers,
        )
        if self.toolsets is not None:
            # Load multiple toolsets
            all_functions = await self.load_multiple_toolsets(toolset_names=self.toolsets)
            # Filter functions to only include those from the specified toolsets
            filtered_functions = {func.name: func for func in all_functions}
            self.functions = filtered_functions
        elif self.tool_name is not None:
            tool = await self.load_tool(tool_name=self.tool_name)
            # Create a functions dict with just this single tool
            self.functions = {tool.name: tool}
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up the toolbox client."""
        # Close core client first
        await self.close()
        await super().__aexit__(exc_type, exc_val, exc_tb)
