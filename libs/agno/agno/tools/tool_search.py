import json
from typing import Any, Callable, Dict, List, Optional, Union

from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


class AgnoToolSearch(Toolkit):
    """Built-in toolkit for searching discoverable tools.
    This toolkit allows agents to search for available tools at runtime.
    Tools passed to this toolkit are indexed and can be searched by name
    or description, returning full schema information.
    """

    def __init__(
        self,
        discoverable_tools: Optional[List[Union[Toolkit, Callable, Function]]] = None,
        **kwargs: Any,
    ):
        """Initialize the AgnoToolSearch toolkit.

        Args:
            discoverable_tools: Tools that can be discovered via search.
                Can be Toolkit instances, callables, or Function instances.
            **kwargs: Additional arguments passed to the parent Toolkit class.
        """
        self._input_discoverable_tools = discoverable_tools or []
        self._discoverable_functions: Dict[str, Function] = {}
        self._process_discoverable_tools()

        super().__init__(name="agno_tool_search", tools=[self.search_tools], **kwargs)

    def _process_discoverable_tools(self) -> None:
        """Process and index all discoverable tools."""
        for tool in self._input_discoverable_tools:
            if isinstance(tool, Toolkit):
                # Extract all functions from the toolkit
                for name, func in tool.functions.items():
                    # Process entrypoint to ensure schema is generated
                    func_copy = func.model_copy(deep=True)
                    func_copy.process_entrypoint()
                    self._discoverable_functions[name] = func_copy
            elif isinstance(tool, Function):
                # Process entrypoint to ensure schema is generated
                func_copy = tool.model_copy(deep=True)
                func_copy.process_entrypoint()
                self._discoverable_functions[tool.name] = func_copy
            elif callable(tool):
                # Convert callable to Function
                func = Function.from_callable(tool)
                self._discoverable_functions[func.name] = func

    def search_tools(self, query: str) -> str:
        """Search for available tools by name or description.

        Use this tool to discover what tools are available for use.
        The search matches against tool names and descriptions.

        Args:
            query: Search query to match against tool names and descriptions.
                Use keywords related to the functionality you're looking for.

        Returns:
            JSON string containing matching tools with their full schema including
            name, description, and parameter definitions.
        """
        query_lower = query.lower()
        matching_tools: List[Dict[str, Any]] = []

        for name, func in self._discoverable_functions.items():
            # Check if query matches name or description
            name_match = query_lower in name.lower()
            description_match = func.description and query_lower in func.description.lower()

            if name_match or description_match:
                tool_info = {
                    "name": func.name,
                    "description": func.description,
                    "parameters": func.parameters,
                }
                matching_tools.append(tool_info)

        result = {
            "tools": matching_tools,
            "total_matches": len(matching_tools),
            "query": query,
        }

        return json.dumps(result, indent=2)

    def list_all_tools(self) -> str:
        """List all available discoverable tools.

        Use this tool to get a complete list of all tools that can be searched.

        Returns:
            JSON string containing all discoverable tools with their full schema.
        """
        all_tools: List[Dict[str, Any]] = []

        for name, func in self._discoverable_functions.items():
            tool_info = {
                "name": func.name,
                "description": func.description,
                "parameters": func.parameters,
            }
            all_tools.append(tool_info)

        result = {
            "tools": all_tools,
            "total_tools": len(all_tools),
        }

        return json.dumps(result, indent=2)
