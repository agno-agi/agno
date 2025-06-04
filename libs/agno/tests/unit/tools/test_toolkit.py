"""Unit tests for Toolkit class."""

import pytest

from agno.tools.toolkit import Toolkit


def example_func(a: int, b: int) -> int:
    """Example function for testing."""
    return a + b


def another_func(x: str) -> str:
    """Another example function for testing."""
    return x.upper()


def third_func(y: float) -> float:
    """Third example function for testing."""
    return y * 2


@pytest.fixture
def basic_toolkit():
    """Create a basic Toolkit instance with a single function."""
    return Toolkit(name="basic_toolkit", tools=[example_func], auto_register=True)


@pytest.fixture
def multi_func_toolkit():
    """Create a Toolkit instance with multiple functions."""
    return Toolkit(name="multi_func_toolkit", tools=[example_func, another_func, third_func], auto_register=True)


@pytest.fixture
def toolkit_with_instructions():
    """Create a Toolkit instance with instructions."""
    return Toolkit(
        name="toolkit_with_instructions",
        tools=[example_func],
        instructions="These are test instructions",
        add_instructions=True,
        auto_register=True,
    )


def test_toolkit_initialization():
    """Test basic toolkit initialization without tools."""
    toolkit = Toolkit(name="empty_toolkit")

    assert toolkit.name == "empty_toolkit"
    assert toolkit.tools == []
    assert len(toolkit.functions) == 0
    assert toolkit.instructions is None
    assert toolkit.add_instructions is False


def test_toolkit_with_tools_initialization(basic_toolkit):
    """Test toolkit initialization with tools."""
    assert basic_toolkit.name == "basic_toolkit"
    assert len(basic_toolkit.tools) == 1
    assert basic_toolkit.tools[0] == example_func
    assert len(basic_toolkit.functions) == 1
    assert "example_func" in basic_toolkit.functions


def test_tool_registration():
    """Test manual registration of tools."""
    toolkit = Toolkit(name="manual_toolkit", auto_register=False)
    assert len(toolkit.functions) == 0

    toolkit.register(example_func)
    assert len(toolkit.functions) == 1
    assert "example_func" in toolkit.functions

    toolkit.register(another_func)
    assert len(toolkit.functions) == 2
    assert "another_func" in toolkit.functions


def test_custom_function_name():
    """Test registering a function with a custom name."""
    toolkit = Toolkit(name="custom_name_toolkit", auto_register=False)
    toolkit.register(example_func, name="custom_add")

    assert len(toolkit.functions) == 1
    assert "custom_add" in toolkit.functions
    assert "example_func" not in toolkit.functions


def test_toolkit_with_instructions(toolkit_with_instructions):
    """Test toolkit with instructions."""
    assert toolkit_with_instructions.instructions == "These are test instructions"
    assert toolkit_with_instructions.add_instructions is True


def test_include_tools():
    """Test initializing toolkit with include_tools parameter."""
    toolkit = Toolkit(
        name="include_toolkit",
        tools=[example_func, another_func, third_func],
        include_tools=["example_func", "third_func"],
        auto_register=True,
    )

    assert len(toolkit.functions) == 2
    assert "example_func" in toolkit.functions
    assert "another_func" not in toolkit.functions
    assert "third_func" in toolkit.functions


def test_exclude_tools():
    """Test initializing toolkit with exclude_tools parameter."""
    toolkit = Toolkit(
        name="exclude_toolkit",
        tools=[example_func, another_func, third_func],
        exclude_tools=["another_func"],
        auto_register=True,
    )

    assert len(toolkit.functions) == 2
    assert "example_func" in toolkit.functions
    assert "another_func" not in toolkit.functions
    assert "third_func" in toolkit.functions


def test_invalid_include_tools():
    """Test error when including a non-existent tool."""
    with pytest.raises(ValueError):
        Toolkit(name="invalid_include", tools=[example_func], include_tools=["non_existent_func"], auto_register=True)


def test_invalid_exclude_tools():
    """Test error when excluding a non-existent tool."""
    with pytest.raises(ValueError):
        Toolkit(name="invalid_exclude", tools=[example_func], exclude_tools=["non_existent_func"], auto_register=True)


def test_caching_parameters():
    """Test initialization with caching parameters."""
    toolkit = Toolkit(
        name="caching_toolkit",
        tools=[example_func],
        cache_results=True,
        cache_ttl=7200,
        cache_dir="/tmp/cache",
        auto_register=True,
    )

    assert toolkit.cache_results is True
    assert toolkit.cache_ttl == 7200
    assert toolkit.cache_dir == "/tmp/cache"


def test_toolkit_repr(multi_func_toolkit):
    """Test the string representation of a toolkit."""
    repr_str = repr(multi_func_toolkit)

    assert "<Toolkit" in repr_str
    assert "name=multi_func_toolkit" in repr_str
    assert "functions=" in repr_str
    assert "example_func" in repr_str
    assert "another_func" in repr_str
    assert "third_func" in repr_str


def test_auto_register_true(multi_func_toolkit):
    """Test automatic registration with auto_register=True."""
    assert len(multi_func_toolkit.functions) == 3
    assert "example_func" in multi_func_toolkit.functions
    assert "another_func" in multi_func_toolkit.functions
    assert "third_func" in multi_func_toolkit.functions


def test_auto_register_false():
    """Test no automatic registration with auto_register=False."""
    toolkit = Toolkit(name="no_auto_toolkit", tools=[example_func, another_func], auto_register=False)

    assert len(toolkit.functions) == 0


def test_include_and_exclude_tools_interaction():
    """Test the interaction between include_tools and exclude_tools."""
    toolkit = Toolkit(
        name="interaction_toolkit",
        tools=[example_func, another_func, third_func],
        include_tools=["example_func", "another_func"],
        exclude_tools=["another_func"],
        auto_register=True,
    )

    assert len(toolkit.functions) == 1
    assert "example_func" in toolkit.functions
    assert "another_func" not in toolkit.functions
    assert "third_func" not in toolkit.functions


def test_duplicate_tool_registration():
    """Test registering the same tool multiple times."""
    toolkit = Toolkit(name="duplicate_toolkit", auto_register=False)

    toolkit.register(example_func)
    toolkit.register(example_func)  # Register same function again

    assert len(toolkit.functions) == 1
    assert "example_func" in toolkit.functions


def test_invalid_tool_name():
    """Test registering a tool with an invalid name."""
    toolkit = Toolkit(name="invalid_name_toolkit", auto_register=False)

    toolkit.register(example_func, name="invalid-name")
    assert "invalid-name" in toolkit.functions


def test_none_tool_registration():
    """Test registering None as a tool."""
    toolkit = Toolkit(name="none_toolkit", auto_register=False)

    toolkit.register(None, name="none_tool")
    assert "none_tool" in toolkit.functions


def test_non_callable_tool_registration():
    """Test registering a non-callable object as a tool"""
    toolkit = Toolkit(name="non_callable_toolkit", auto_register=False)

    # Use a non-callable object (string) to test the error handling
    with pytest.raises(AttributeError):
        toolkit.register("not_a_function", name="string_tool")


def test_empty_tool_list():
    """Test initializing toolkit with an empty tool list."""
    toolkit = Toolkit(name="empty_tools_toolkit", tools=[], auto_register=True)

    assert len(toolkit.tools) == 0
    assert len(toolkit.functions) == 0


def test_toolkit_with_none_instructions():
    """Test toolkit with None instructions."""
    toolkit = Toolkit(
        name="none_instructions_toolkit",
        tools=[example_func],
        instructions=None,
        add_instructions=True,
        auto_register=True,
    )

    assert toolkit.instructions is None
    assert toolkit.add_instructions is True
