"""Tests for the DiscoverableTools toolkit."""

import json

from agno.tools.discoverable_tools import DiscoverableTools
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit


def sample_add(a: int, b: int) -> str:
    """Add two numbers together.

    Args:
        a: First number to add
        b: Second number to add

    Returns:
        JSON string with the sum
    """
    return json.dumps({"result": a + b})


def sample_multiply(x: float, y: float) -> str:
    """Multiply two numbers together.

    Args:
        x: First number to multiply
        y: Second number to multiply

    Returns:
        JSON string with the product
    """
    return json.dumps({"result": x * y})


def sample_search(query: str, max_results: int = 5) -> str:
    """Search for information using a query.

    Args:
        query: The search query
        max_results: Maximum number of results to return

    Returns:
        JSON string with search results
    """
    return json.dumps({"results": [], "query": query})


class SampleToolkit(Toolkit):
    """Sample toolkit for testing."""

    def __init__(self, **kwargs):
        super().__init__(
            name="sample_toolkit",
            tools=[self.toolkit_add, self.toolkit_subtract],
            **kwargs,
        )

    def toolkit_add(self, a: int, b: int) -> str:
        """Add two numbers in the toolkit.

        Args:
            a: First number
            b: Second number

        Returns:
            The sum as JSON
        """
        return json.dumps({"result": a + b})

    def toolkit_subtract(self, a: int, b: int) -> str:
        """Subtract two numbers in the toolkit.

        Args:
            a: First number
            b: Second number

        Returns:
            The difference as JSON
        """
        return json.dumps({"result": a - b})


# Tests for DiscoverableTools initialization


def test_agno_tool_search_with_callables():
    """Test DiscoverableTools initialization with callable functions."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add, sample_multiply])

    assert len(tool_search._discoverable_functions) == 2
    assert "sample_add" in tool_search._discoverable_functions
    assert "sample_multiply" in tool_search._discoverable_functions


def test_agno_tool_search_with_toolkit():
    """Test DiscoverableTools initialization with a Toolkit instance."""
    toolkit = SampleToolkit()
    tool_search = DiscoverableTools(discoverable_tools=[toolkit])

    assert len(tool_search._discoverable_functions) == 2
    assert "toolkit_add" in tool_search._discoverable_functions
    assert "toolkit_subtract" in tool_search._discoverable_functions


def test_agno_tool_search_with_function_instance():
    """Test DiscoverableTools initialization with a Function instance."""
    func = Function.from_callable(sample_add)
    tool_search = DiscoverableTools(discoverable_tools=[func])

    assert len(tool_search._discoverable_functions) == 1
    assert "sample_add" in tool_search._discoverable_functions


def test_agno_tool_search_with_mixed_tools():
    """Test DiscoverableTools initialization with mixed tool types."""
    toolkit = SampleToolkit()
    func = Function.from_callable(sample_search)

    tool_search = DiscoverableTools(discoverable_tools=[toolkit, sample_multiply, func])

    assert len(tool_search._discoverable_functions) == 4
    assert "toolkit_add" in tool_search._discoverable_functions
    assert "toolkit_subtract" in tool_search._discoverable_functions
    assert "sample_multiply" in tool_search._discoverable_functions
    assert "sample_search" in tool_search._discoverable_functions


def test_agno_tool_search_empty():
    """Test DiscoverableTools initialization with no tools."""
    tool_search = DiscoverableTools()

    assert len(tool_search._discoverable_functions) == 0


# Tests for search_tools method


def test_search_tools_by_name():
    """Test searching tools by name."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add, sample_multiply])

    result = json.loads(tool_search.search_tools("add"))

    assert result["total_matches"] == 1
    assert len(result["tools"]) == 1
    assert result["tools"][0]["name"] == "sample_add"


def test_search_tools_by_description():
    """Test searching tools by description."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add, sample_multiply, sample_search])

    result = json.loads(tool_search.search_tools("multiply"))

    assert result["total_matches"] == 1
    assert len(result["tools"]) == 1
    assert result["tools"][0]["name"] == "sample_multiply"


def test_search_tools_multiple_matches():
    """Test searching tools with multiple matches."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add, sample_multiply])

    # Both tools mention "number" in description
    result = json.loads(tool_search.search_tools("number"))

    assert result["total_matches"] == 2


def test_search_tools_no_matches():
    """Test searching tools with no matches."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add, sample_multiply])

    result = json.loads(tool_search.search_tools("nonexistent"))

    assert result["total_matches"] == 0
    assert len(result["tools"]) == 0


def test_search_tools_case_insensitive():
    """Test that search is case insensitive."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add])

    result_lower = json.loads(tool_search.search_tools("add"))
    result_upper = json.loads(tool_search.search_tools("ADD"))
    result_mixed = json.loads(tool_search.search_tools("AdD"))

    assert result_lower["total_matches"] == 1
    assert result_upper["total_matches"] == 1
    assert result_mixed["total_matches"] == 1


def test_search_tools_returns_full_schema():
    """Test that search results include full parameter schema."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add])

    result = json.loads(tool_search.search_tools("add"))

    assert result["total_matches"] == 1
    tool_info = result["tools"][0]

    assert "name" in tool_info
    assert "description" in tool_info
    assert "parameters" in tool_info
    assert "properties" in tool_info["parameters"]
    assert "a" in tool_info["parameters"]["properties"]
    assert "b" in tool_info["parameters"]["properties"]


def test_search_tools_includes_query():
    """Test that search results include the original query."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add])

    result = json.loads(tool_search.search_tools("test_query"))

    assert result["query"] == "test_query"


# Tests for list_all_tools method


def test_list_all_tools():
    """Test listing all discoverable tools."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add, sample_multiply, sample_search])

    result = json.loads(tool_search.list_all_tools())

    assert result["total_tools"] == 3
    assert len(result["tools"]) == 3

    tool_names = [t["name"] for t in result["tools"]]
    assert "sample_add" in tool_names
    assert "sample_multiply" in tool_names
    assert "sample_search" in tool_names


def test_list_all_tools_empty():
    """Test listing tools when none are registered."""
    tool_search = DiscoverableTools()

    result = json.loads(tool_search.list_all_tools())

    assert result["total_tools"] == 0
    assert len(result["tools"]) == 0


# Tests for discoverable flag on Function


def test_function_discoverable_flag_default():
    """Test that Function.discoverable defaults to False."""
    func = Function(name="test_func")

    assert func.discoverable is False


def test_function_discoverable_flag_true():
    """Test that Function.discoverable can be set to True."""
    func = Function(name="test_func", discoverable=True)

    assert func.discoverable is True


def test_toolkit_discoverable_tools_parameter():
    """Test that Toolkit supports discoverable_tools parameter."""
    toolkit = Toolkit(
        name="test_toolkit",
        tools=[sample_add, sample_multiply],
        discoverable_tools=["sample_add"],
    )

    # sample_add should be marked as discoverable
    assert toolkit.functions["sample_add"].discoverable is True
    # sample_multiply should not be discoverable
    assert toolkit.functions["sample_multiply"].discoverable is False


# Tests for use_tool method


def test_use_tool_executes_callable():
    """Test executing a discovered callable tool."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add, sample_multiply])

    result = json.loads(tool_search.use_tool("sample_add", parameters={"a": 5, "b": 3}))

    assert result["result"] == 8


def test_use_tool_executes_multiply():
    """Test executing a multiply tool with float arguments."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_multiply])

    result = json.loads(tool_search.use_tool("sample_multiply", parameters={"x": 2.5, "y": 4.0}))

    assert result["result"] == 10.0


def test_use_tool_with_toolkit_function():
    """Test executing a tool from a Toolkit."""
    toolkit = SampleToolkit()
    tool_search = DiscoverableTools(discoverable_tools=[toolkit])

    result = json.loads(tool_search.use_tool("toolkit_add", parameters={"a": 10, "b": 20}))

    assert result["result"] == 30


def test_use_tool_toolkit_subtract():
    """Test executing subtract tool from a Toolkit."""
    toolkit = SampleToolkit()
    tool_search = DiscoverableTools(discoverable_tools=[toolkit])

    result = json.loads(tool_search.use_tool("toolkit_subtract", parameters={"a": 100, "b": 40}))

    assert result["result"] == 60


def test_use_tool_not_found():
    """Test error when tool is not found."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add])

    result = json.loads(tool_search.use_tool("nonexistent_tool", parameters={}))

    assert result["status"] == "error"
    assert "not found" in result["error"]
    assert "sample_add" in result["available_tools"]


def test_use_tool_with_optional_params():
    """Test executing a tool with optional parameters."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_search])

    # Call with only required param
    result = json.loads(tool_search.use_tool("sample_search", parameters={"query": "test"}))

    assert result["query"] == "test"


def test_use_tool_with_none_input():
    """Test executing a tool with None as parameters."""

    def no_args_tool() -> str:
        """A tool that takes no arguments."""
        return json.dumps({"message": "success"})

    tool_search = DiscoverableTools(discoverable_tools=[no_args_tool])

    result = json.loads(tool_search.use_tool("no_args_tool", parameters=None))

    assert result["message"] == "success"


def test_use_tool_with_empty_dict():
    """Test executing a tool with empty dict as parameters."""

    def no_args_tool() -> str:
        """A tool that takes no arguments."""
        return json.dumps({"message": "success"})

    tool_search = DiscoverableTools(discoverable_tools=[no_args_tool])

    result = json.loads(tool_search.use_tool("no_args_tool", parameters={}))

    assert result["message"] == "success"


def test_use_tool_returns_non_json_result():
    """Test executing a tool that returns a non-JSON serializable result."""

    def returns_dict(value: str) -> dict:
        """A tool that returns a dict directly."""
        return {"value": value, "processed": True}

    tool_search = DiscoverableTools(discoverable_tools=[returns_dict])

    result = json.loads(tool_search.use_tool("returns_dict", parameters={"value": "test"}))

    assert result["status"] == "success"
    assert result["tool_name"] == "returns_dict"
    assert result["result"]["value"] == "test"
    assert result["result"]["processed"] is True


def test_use_tool_registers_in_toolkit():
    """Test that use_tool is registered as a toolkit function."""
    tool_search = DiscoverableTools(discoverable_tools=[sample_add])

    # Check that use_tool is in the toolkit's functions
    assert "use_tool" in tool_search.functions
    assert "search_tools" in tool_search.functions
    assert "list_all_tools" in tool_search.functions
