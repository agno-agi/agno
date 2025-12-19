"""Unit tests for Toolkit class."""

import pytest

from agno.tools import Toolkit, tool
from agno.tools.function import Function


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


# =============================================================================
# Tests for @tool decorator on class methods
# =============================================================================


class TestToolDecoratorOnClassMethods:
    """Tests for using @tool decorator on class methods within a Toolkit."""

    def test_tool_decorator_basic_registration(self):
        """Test that @tool decorated methods are registered correctly."""

        class MyToolkit(Toolkit):
            def __init__(self):
                self.multiplier = 2
                super().__init__(name="test_toolkit", tools=[self.multiply])

            @tool()
            def multiply(self, x: int) -> int:
                """Multiply x by the multiplier."""
                return x * self.multiplier

        toolkit = MyToolkit()

        assert len(toolkit.functions) == 1
        assert "multiply" in toolkit.functions
        assert isinstance(toolkit.functions["multiply"], Function)

    def test_tool_decorator_stop_after_tool_call(self):
        """Test that stop_after_tool_call is preserved from decorator."""

        class MyToolkit(Toolkit):
            def __init__(self):
                super().__init__(name="test_toolkit", tools=[self.my_tool])

            @tool(stop_after_tool_call=True)
            def my_tool(self, x: int) -> int:
                """A tool that stops after call."""
                return x * 2

        toolkit = MyToolkit()
        func = toolkit.functions["my_tool"]

        assert func.stop_after_tool_call is True
        assert func.show_result is True  # Automatically set when stop_after_tool_call=True

    def test_tool_decorator_show_result(self):
        """Test that show_result is preserved from decorator."""

        class MyToolkit(Toolkit):
            def __init__(self):
                super().__init__(name="test_toolkit", tools=[self.my_tool])

            @tool(show_result=True)
            def my_tool(self, x: int) -> int:
                """A tool that shows result."""
                return x * 2

        toolkit = MyToolkit()
        func = toolkit.functions["my_tool"]

        assert func.show_result is True

    def test_tool_decorator_self_binding(self):
        """Test that self is properly bound to the method."""

        class MyToolkit(Toolkit):
            def __init__(self, value: int):
                self.value = value
                super().__init__(name="test_toolkit", tools=[self.get_value])

            @tool()
            def get_value(self) -> int:
                """Get the stored value."""
                return self.value

        toolkit = MyToolkit(value=42)
        func = toolkit.functions["get_value"]

        # Call the entrypoint directly - self should be bound
        result = func.entrypoint()
        assert result == 42

    def test_tool_decorator_with_parameters(self):
        """Test that method parameters are correctly processed."""

        class MyToolkit(Toolkit):
            def __init__(self):
                self.base = 10
                super().__init__(name="test_toolkit", tools=[self.add_to_base])

            @tool()
            def add_to_base(self, x: int, y: int = 5) -> int:
                """Add x and y to the base value."""
                return self.base + x + y

        toolkit = MyToolkit()
        func = toolkit.functions["add_to_base"]

        # Check parameters - self should be excluded
        assert "self" not in func.parameters.get("properties", {})
        assert "x" in func.parameters.get("properties", {})

        # Call the function
        result = func.entrypoint(x=3, y=2)
        assert result == 15  # 10 + 3 + 2

    def test_tool_decorator_with_session_state(self):
        """Test that session_state parameter is handled correctly."""

        class MyToolkit(Toolkit):
            def __init__(self):
                super().__init__(name="test_toolkit", tools=[self.update_state])

            @tool()
            def update_state(self, key: str, value: str, session_state) -> str:
                """Update session state."""
                session_state[key] = value
                return f"Set {key}={value}"

        toolkit = MyToolkit()
        func = toolkit.functions["update_state"]

        # session_state should be excluded from parameters
        assert "session_state" not in func.parameters.get("properties", {})
        assert "key" in func.parameters.get("properties", {})
        assert "value" in func.parameters.get("properties", {})

    def test_tool_decorator_multiple_methods(self):
        """Test multiple @tool decorated methods in same toolkit."""

        class MyToolkit(Toolkit):
            def __init__(self):
                self.counter = 0
                super().__init__(
                    name="test_toolkit",
                    tools=[self.increment, self.decrement, self.get_count],
                )

            @tool()
            def increment(self) -> int:
                """Increment counter."""
                self.counter += 1
                return self.counter

            @tool()
            def decrement(self) -> int:
                """Decrement counter."""
                self.counter -= 1
                return self.counter

            @tool(stop_after_tool_call=True)
            def get_count(self) -> int:
                """Get current count."""
                return self.counter

        toolkit = MyToolkit()

        assert len(toolkit.functions) == 3
        assert "increment" in toolkit.functions
        assert "decrement" in toolkit.functions
        assert "get_count" in toolkit.functions

        # Only get_count should have stop_after_tool_call
        assert toolkit.functions["increment"].stop_after_tool_call is False
        assert toolkit.functions["decrement"].stop_after_tool_call is False
        assert toolkit.functions["get_count"].stop_after_tool_call is True

    def test_tool_decorator_mixed_with_regular_methods(self):
        """Test toolkit with both @tool decorated and regular methods."""

        class MyToolkit(Toolkit):
            def __init__(self):
                super().__init__(
                    name="test_toolkit",
                    tools=[self.decorated_tool, self.regular_method],
                )

            @tool(show_result=True)
            def decorated_tool(self, x: int) -> int:
                """A decorated tool."""
                return x * 2

            def regular_method(self, x: int) -> int:
                """A regular method registered as tool."""
                return x * 3

        toolkit = MyToolkit()

        assert len(toolkit.functions) == 2
        assert "decorated_tool" in toolkit.functions
        assert "regular_method" in toolkit.functions

        # Decorated tool should have show_result from decorator
        assert toolkit.functions["decorated_tool"].show_result is True
        # Regular method should have default show_result
        assert toolkit.functions["regular_method"].show_result is False

    def test_get_tool_name_with_function_object(self):
        """Test _get_tool_name helper with Function objects."""

        @tool(name="custom_name")
        def standalone_func() -> str:
            """A standalone function."""
            return "result"

        toolkit = Toolkit(name="test_toolkit")

        # Test with Function object
        assert toolkit._get_tool_name(standalone_func) == "custom_name"
        # Test with regular callable
        assert toolkit._get_tool_name(example_func) == "example_func"
