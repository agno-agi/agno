import json
from typing import Any, Callable, Dict, List, Optional, Union

from agno.tools.function import Function, FunctionCall
from agno.tools.toolkit import Toolkit


class DiscoverableTools(Toolkit):
    """Toolkit to dynamically search, load and run tools.

    This is useful to avoid loading all tool information into
    the context upfront, and instead load only what is needed.

    With this Toolkit Agents will be able to:
    1. Search for available tools at runtime, by name or description
    2. List all discoverable tools
    3. Execute discovered tools
    """

    def __init__(
        self,
        discoverable_tools: Optional[List[Union[Toolkit, Callable, Function]]] = None,
        **kwargs: Any,
    ):
        """Initialize the DiscoverableTools toolkit.

        Args:
            discoverable_tools: Tools that can be discovered and executed via search.
                Can be Toolkit instances, callables, or Function instances.
            **kwargs: Additional arguments passed to the parent Toolkit class.
        """
        self._input_discoverable_tools = discoverable_tools or []
        self._discoverable_functions: Dict[str, Function] = {}
        self._process_discoverable_tools()

        super().__init__(
            name="discoverable_tools",
            tools=[self.search_tools, self.list_all_tools, self.use_tool],
            **kwargs,
        )

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
                func.process_entrypoint()
                self._discoverable_functions[func.name] = func

    def search_tools(self, query: str) -> str:
        """Search for available tools by name or description.

        Use this tool to discover what tools are available for use.
        The search matches against tool names and descriptions using word-level matching.
        Any word from the query matching any word in the tool name or description
        will return that tool as a result.

        Args:
            query: Search query to match against tool names and descriptions.
                Use keywords related to the functionality you're looking for.
                Examples: "weather", "send email", "database query"

        Returns:
            JSON string containing matching tools with their full schema including
            name, description, and parameter definitions.
        """
        # Split query into words for flexible matching
        query_words = set(query.lower().split())
        matching_tools: List[Dict[str, Any]] = []

        for name, func in self._discoverable_functions.items():
            # Create searchable text from name and description
            name_words = set(name.lower().replace("_", " ").split())
            description_words = set()
            if func.description:
                description_words = set(func.description.lower().split())

            all_tool_words = name_words | description_words

            # Check if any query word matches any tool word (word-level matching)
            # Also check for substring matches within words for partial matching
            match_found = False
            for query_word in query_words:
                # Direct word match
                if query_word in all_tool_words:
                    match_found = True
                    break
                # Substring match (e.g., "weather" in "get_weather" or description)
                if any(query_word in tool_word for tool_word in all_tool_words):
                    match_found = True
                    break
                # Check if query word is substring of name or description
                if query_word in name.lower() or (func.description and query_word in func.description.lower()):
                    match_found = True
                    break

            if match_found:
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

    def use_tool(self, tool_name: str, parameters: Optional[Dict[str, Any]] = None) -> str:
        """Execute a discovered tool by name with the provided arguments.

        Use this tool to execute any tool that was found via search_tools or list_all_tools.
        First search for the tool to get its schema, then call this with the tool name
        and appropriate arguments.

        Args:
            tool_name: The exact name of the tool to execute (as returned by search_tools).
            parameters: A dictionary of arguments to pass to the tool.
                The keys should match the parameter names from the tool's schema.

        Returns:
            The result of the tool execution as a JSON string, or an error message
            if the tool is not found or execution fails.

        Example:
            After searching and finding a tool named "get_weather" with parameter "city",
            call: use_tool(tool_name="get_weather", parameters={"city": "London"})
        """
        # Check if the tool exists
        if tool_name not in self._discoverable_functions:
            available_tools = list(self._discoverable_functions.keys())
            return json.dumps(
                {
                    "status": "error",
                    "error": f"Tool '{tool_name}' not found",
                    "available_tools": available_tools,
                },
                indent=2,
            )

        func = self._discoverable_functions[tool_name]

        # Ensure parameters is a dict
        if parameters is None:
            parameters = {}

        try:
            # Create a FunctionCall and execute it
            function_call = FunctionCall(
                function=func,
                arguments=parameters,
            )
            execution_result = function_call.execute()

            # Check for execution errors
            if execution_result.status == "failure":
                return json.dumps(
                    {
                        "status": "error",
                        "tool_name": tool_name,
                        "error": execution_result.error or "Unknown execution error",
                    },
                    indent=2,
                )

            # Return the result
            result = execution_result.result

            # If a result is already a string (e.g., JSON), return as-is
            if isinstance(result, str):
                return result

            # Otherwise, serialize to JSON
            return json.dumps(
                {
                    "status": "success",
                    "tool_name": tool_name,
                    "result": result,
                },
                indent=2,
            )

        except Exception as e:
            return json.dumps(
                {
                    "status": "error",
                    "tool_name": tool_name,
                    "error": str(e),
                },
                indent=2,
            )
