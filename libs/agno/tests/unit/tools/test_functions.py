from typing import Any, Callable, Dict

import pytest
from pydantic import ValidationError

from agno.tools.decorator import tool
from agno.tools.function import Function, FunctionCall


def test_function_initialization():
    """Test basic Function initialization with required and optional parameters."""
    # Test with minimal required parameters
    func = Function(name="test_function")
    assert func.name == "test_function"
    assert func.description is None
    assert func.parameters == {"type": "object", "properties": {}, "required": []}
    assert func.strict is None
    assert func.entrypoint is None

    # Test with all parameters
    func = Function(
        name="test_function",
        description="Test function description",
        parameters={"type": "object", "properties": {"param1": {"type": "string"}}, "required": ["param1"]},
        strict=True,
        instructions="Test instructions",
        add_instructions=True,
        requires_confirmation=True,
        requires_user_input=True,
        user_input_fields=["param1"],
        external_execution=True,
        cache_results=True,
        cache_dir="/tmp",
        cache_ttl=7200,
    )
    assert func.name == "test_function"
    assert func.description == "Test function description"
    assert func.parameters["properties"]["param1"]["type"] == "string"
    assert func.strict is True
    assert func.instructions == "Test instructions"
    assert func.add_instructions is True
    assert func.requires_confirmation is True
    assert func.requires_user_input is True
    assert func.user_input_fields == ["param1"]
    assert func.external_execution is True
    assert func.cache_results is True
    assert func.cache_dir == "/tmp"
    assert func.cache_ttl == 7200


def test_decorator_instantiation():
    """Test instantiating a Function from a decorator."""

    @tool
    def test_func(param1: str, param2: int = 42) -> str:
        """Test function with parameters."""
        return f"{param1}-{param2}"

    assert isinstance(test_func, Function)
    test_func.process_entrypoint()

    assert test_func.name == "test_func"
    assert test_func.description == "Test function with parameters."
    assert test_func.entrypoint is not None
    assert test_func.parameters["properties"]["param1"]["type"] == "string"
    assert test_func.parameters["properties"]["param2"]["type"] == "number"
    assert "param1" in test_func.parameters["required"]
    assert "param2" not in test_func.parameters["required"]


def test_function_to_dict():
    """Test the to_dict method returns the correct dictionary representation."""
    func = Function(
        name="test_function",
        description="Test description",
        parameters={"type": "object", "properties": {"param1": {"type": "string"}}, "required": ["param1"]},
        strict=True,
        requires_confirmation=True,
        external_execution=True,
    )

    result = func.to_dict()
    assert isinstance(result, dict)
    assert result["name"] == "test_function"
    assert result["description"] == "Test description"
    assert result["parameters"]["properties"]["param1"]["type"] == "string"
    assert result["strict"] is True
    assert result["requires_confirmation"] is True
    assert result["external_execution"] is True
    assert "instructions" not in result
    assert "add_instructions" not in result
    assert "entrypoint" not in result


def test_function_from_callable():
    """Test creating a Function from a callable."""

    def test_func(param1: str, param2: int = 42) -> str:
        """Test function with parameters.

        Args:
            param1: First parameter
            param2: Second parameter with default value
        """
        return f"{param1}-{param2}"

    func = Function.from_callable(test_func)
    assert func.name == "test_func"
    assert "Test function with parameters" in func.description
    assert "param1" in func.parameters["properties"]
    assert "param2" in func.parameters["properties"]
    assert func.parameters["properties"]["param1"]["type"] == "string"
    assert func.parameters["properties"]["param2"]["type"] == "number"
    assert "param1" in func.parameters["required"]
    assert "param2" not in func.parameters["required"]  # Because it has a default value


def test_wrap_callable():
    """Test wrapping a callable."""

    @tool
    def test_func(param1: str, param2: int) -> str:
        """Test function with parameters."""
        return f"{param1}-{param2}"

    assert isinstance(test_func, Function)
    assert test_func.entrypoint is not None

    test_func.process_entrypoint()
    assert isinstance(test_func, Function)
    assert test_func.entrypoint is not None
    assert test_func.entrypoint(param1="test", param2=42) == "test-42"
    with pytest.raises(ValidationError):
        test_func.entrypoint(param1="test")
    assert test_func.entrypoint._wrapped_for_validation is True

    test_func.process_entrypoint()
    assert isinstance(test_func, Function)
    assert test_func.entrypoint is not None
    assert test_func.entrypoint(param1="test", param2=42) == "test-42"
    with pytest.raises(ValidationError):
        test_func.entrypoint(param1="test")
    assert test_func.entrypoint._wrapped_for_validation is True


def test_function_from_callable_strict():
    """Test creating a Function from a callable with strict mode."""

    def test_func(param1: str, param2: int = 42) -> str:
        """Test function with parameters."""
        return f"{param1}-{param2}"

    func = Function.from_callable(test_func, strict=True)
    assert func.name == "test_func"
    assert "param1" in func.parameters["required"]
    assert "param2" in func.parameters["required"]  # In strict mode, all parameters are required


def test_function_process_entrypoint():
    """Test processing the entrypoint of a Function."""

    def test_func(param1: str, param2: int = 42) -> str:
        """Test function with parameters."""
        return f"{param1}-{param2}"

    func = Function(name="test_func", entrypoint=test_func, skip_entrypoint_processing=False)

    func.process_entrypoint()
    assert func.parameters["properties"]["param1"]["type"] == "string"
    assert func.parameters["properties"]["param2"]["type"] == "number"
    assert "param1" in func.parameters["required"]
    assert "param2" not in func.parameters["required"]


def test_function_process_entrypoint_with_user_input():
    """Test processing the entrypoint with user input fields."""

    def test_func(param1: str, param2: int = 42) -> str:
        """Test function with parameters."""
        return f"{param1}-{param2}"

    func = Function(name="test_func", entrypoint=test_func, requires_user_input=True, user_input_fields=["param1"])

    func.process_entrypoint()

    assert func.user_input_schema is not None
    assert len(func.user_input_schema) == 2

    assert func.user_input_schema[0].name == "param1"
    assert func.user_input_schema[0].field_type is str
    assert func.user_input_schema[1].name == "param2"
    assert func.user_input_schema[1].field_type is int


def test_function_process_entrypoint_skip_processing():
    """Test that entrypoint processing is skipped when skip_entrypoint_processing is True."""

    def test_func(param1: str, param2: int = 42) -> str:
        """Test function with parameters."""
        return f"{param1}-{param2}"

    original_parameters = {"type": "object", "properties": {"custom": {"type": "string"}}, "required": ["custom"]}

    func = Function(
        name="test_func", entrypoint=test_func, parameters=original_parameters, skip_entrypoint_processing=True
    )

    func.process_entrypoint()
    assert func.parameters == original_parameters  # Parameters should remain unchanged


def test_function_process_schema_for_strict():
    """Test processing schema for strict mode."""
    func = Function(
        name="test_func",
        parameters={
            "type": "object",
            "properties": {"param1": {"type": "string"}, "param2": {"type": "number"}},
            "required": ["param1"],
        },
    )

    func.process_schema_for_strict()
    assert "param1" in func.parameters["required"]
    assert "param2" in func.parameters["required"]  # All properties should be required in strict mode


def test_function_cache_key_generation():
    """Test generation of cache keys for function calls."""
    func = Function(name="test_func", cache_results=True, cache_dir="/tmp")

    entrypoint_args = {"param1": "value1", "param2": 42}
    call_args = {"extra": "data"}

    cache_key = func._get_cache_key(entrypoint_args, call_args)
    assert isinstance(cache_key, str)
    # Hash updated to use json.dumps with sort_keys=True for consistent ordering
    assert cache_key == "d76d42a06e815b6402e24486f1f61805"


def test_function_cache_key_dict_order_independence():
    """Test that cache keys are identical regardless of dictionary key order."""
    func = Function(name="test_func", cache_results=True, cache_dir="/tmp")

    # Same data, different key orders
    args1 = {"param1": "value1", "param2": 42, "param3": "value3"}
    args2 = {"param3": "value3", "param1": "value1", "param2": 42}
    args3 = {"param2": 42, "param3": "value3", "param1": "value1"}

    cache_key1 = func._get_cache_key(args1)
    cache_key2 = func._get_cache_key(args2)
    cache_key3 = func._get_cache_key(args3)

    # Should generate identical cache keys
    assert cache_key1 == cache_key2 == cache_key3


def test_function_cache_file_path():
    """Test generation of cache file paths."""
    func = Function(name="test_func", cache_results=True, cache_dir="/tmp")

    cache_key = "test_key"
    cache_file = func._get_cache_file_path(cache_key)
    assert cache_file.startswith("/tmp/")
    assert "test_func" in cache_file
    assert "test_key" in cache_file


def test_function_cache_operations(tmp_path):
    """Test caching operations (save and retrieve)."""
    import json
    import os

    func = Function(name="test_func", cache_results=True, cache_dir=str(tmp_path))

    # Test saving to cache
    test_result = {"result": "test_data"}
    cache_file = os.path.join(str(tmp_path), "test_cache.json")
    func._save_to_cache(cache_file, test_result)

    # Verify cache file exists and contains correct data
    assert os.path.exists(cache_file)
    with open(cache_file, "r") as f:
        cached_data = json.load(f)
    assert cached_data["result"] == {"result": "test_data"}

    # Test retrieving from cache
    retrieved_result = func._get_cached_result(cache_file)
    assert retrieved_result == test_result

    # Test retrieving non-existent cache
    non_existent_file = os.path.join(str(tmp_path), "non_existent.json")
    assert func._get_cached_result(non_existent_file) is None


def test_function_cache_ttl(tmp_path):
    """Test cache TTL functionality."""
    import os
    import time

    func = Function(
        name="test_func",
        cache_results=True,
        cache_dir=str(tmp_path),
        cache_ttl=1,  # 1 second TTL
    )

    # Save test data to cache
    test_result = {"result": "test_data"}
    cache_file = os.path.join(str(tmp_path), "test_cache.json")
    func._save_to_cache(cache_file, test_result)

    # Verify cache is valid immediately
    assert func._get_cached_result(cache_file) == test_result

    # Wait for cache to expire
    time.sleep(1.1)

    # Verify cache is no longer valid
    assert func._get_cached_result(cache_file) is None


def test_function_call_initialization():
    """Test FunctionCall initialization."""
    func = Function(name="test_func")
    call = FunctionCall(function=func)
    assert call.function == func
    assert call.arguments is None
    assert call.result is None
    assert call.call_id is None
    assert call.error is None

    # Test with all parameters
    call = FunctionCall(
        function=func, arguments={"param1": "value1"}, result="test_result", call_id="test_id", error="test_error"
    )
    assert call.function == func
    assert call.arguments == {"param1": "value1"}
    assert call.result == "test_result"
    assert call.call_id == "test_id"
    assert call.error == "test_error"


def test_function_call_get_call_str():
    """Test the get_call_str method."""
    func = Function(name="test_func", description="Test function")
    call = FunctionCall(function=func, arguments={"param1": "value1", "param2": 42})

    call_str = call.get_call_str()
    assert "test_func" in call_str
    assert "param1" in call_str
    assert "value1" in call_str
    assert "param2" in call_str
    assert "42" in call_str


def test_function_call_execution():
    """Test function call execution."""

    def test_func(param1: str, param2: int = 42) -> str:
        return f"{param1}-{param2}"

    func = Function(name="test_func", entrypoint=test_func)

    call = FunctionCall(function=func, arguments={"param1": "value1", "param2": 42})

    result = call.execute()
    assert result.status == "success"
    assert result.result == "value1-42"
    assert result.error is None


def test_function_call_execution_with_error():
    """Test function call execution with error handling."""

    def test_func(param1: str) -> str:
        raise ValueError("Test error")

    func = Function(name="test_func", entrypoint=test_func)

    call = FunctionCall(function=func, arguments={"param1": "value1"})

    result = call.execute()
    assert result.status == "failure"
    assert result.error is not None
    assert "Test error" in result.error


def test_function_call_with_hooks():
    """Test function call execution with pre and post hooks."""
    pre_hook_called = False
    post_hook_called = False

    def pre_hook():
        nonlocal pre_hook_called
        pre_hook_called = True

    def post_hook():
        nonlocal post_hook_called
        post_hook_called = True

    def test_func(param1: str) -> str:
        return f"processed-{param1}"

    func = Function(name="test_func", entrypoint=test_func, pre_hook=pre_hook, post_hook=post_hook)

    call = FunctionCall(function=func, arguments={"param1": "value1"})

    result = call.execute()
    assert result.status == "success"
    assert result.result == "processed-value1"
    assert pre_hook_called
    assert post_hook_called


def test_function_call_with_tool_hooks():
    """Test function call execution with tool hooks."""
    hook_calls = []

    def tool_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
        hook_calls.append(("before", function_name, arguments))
        result = function_call(**arguments)
        hook_calls.append(("after", function_name, result))
        return result

    @tool(tool_hooks=[tool_hook])
    def test_func(param1: str) -> str:
        return f"processed-{param1}"

    test_func.process_entrypoint()

    call = FunctionCall(function=test_func, arguments={"param1": "value1"})

    result = call.execute()
    assert result.status == "success"
    assert result.result == "processed-value1"
    assert len(hook_calls) == 2
    assert hook_calls[0][0] == "before"
    assert hook_calls[0][1] == "test_func"
    assert hook_calls[1][0] == "after"
    assert hook_calls[1][2] == "processed-value1"


@pytest.mark.asyncio
async def test_function_call_async_execution():
    """Test async function call execution."""

    async def test_func(param1: str, param2: int = 42) -> str:
        return f"{param1}-{param2}"

    func = Function(name="test_func", entrypoint=test_func)

    call = FunctionCall(function=func, arguments={"param1": "value1", "param2": 42})

    result = await call.aexecute()
    assert result.status == "success"
    assert result.result == "value1-42"
    assert result.error is None


@pytest.mark.asyncio
async def test_function_call_async_execution_with_error():
    """Test async function call execution with error handling."""

    async def test_func(param1: str) -> str:
        raise ValueError("Test error")

    func = Function(name="test_func", entrypoint=test_func)

    call = FunctionCall(function=func, arguments={"param1": "value1"})

    result = await call.aexecute()
    assert result.status == "failure"
    assert result.error is not None
    assert "Test error" in result.error


@pytest.mark.asyncio
async def test_function_call_async_with_hooks():
    """Test async function call execution with pre and post hooks."""
    pre_hook_called = False
    post_hook_called = False

    async def pre_hook():
        nonlocal pre_hook_called
        pre_hook_called = True

    async def post_hook():
        nonlocal post_hook_called
        post_hook_called = True

    @tool(pre_hook=pre_hook, post_hook=post_hook)
    async def test_func(param1: str) -> str:
        return f"processed-{param1}"

    test_func.process_entrypoint()

    call = FunctionCall(function=test_func, arguments={"param1": "value1"})

    result = await call.aexecute()
    assert result.status == "success"
    assert result.result == "processed-value1"
    assert pre_hook_called
    assert post_hook_called


@pytest.mark.asyncio
async def test_function_call_async_with_tool_hooks():
    """Test async function call execution with tool hooks."""
    hook_calls = []

    async def tool_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
        hook_calls.append(("before", function_name, arguments))
        result = await function_call(**arguments)
        hook_calls.append(("after", function_name, result))
        return result

    @tool(tool_hooks=[tool_hook])
    async def test_func(param1: str) -> str:
        return f"processed-{param1}"

    test_func.process_entrypoint()

    call = FunctionCall(function=test_func, arguments={"param1": "value1"})

    result = await call.aexecute()

    assert result.status == "success"
    assert result.result == "processed-value1"
    assert len(hook_calls) == 2
    assert hook_calls[0][0] == "before"
    assert hook_calls[0][1] == "test_func"
    assert hook_calls[1][0] == "after"
    assert hook_calls[1][2] == "processed-value1"


def test_tool_decorator_basic():
    """Test basic @tool decorator usage."""

    @tool
    def basic_func() -> str:
        """Basic test function."""
        return "test"

    assert isinstance(basic_func, Function)
    assert basic_func.name == "basic_func"
    assert basic_func.description == "Basic test function."
    assert basic_func.entrypoint is not None
    assert basic_func.parameters["type"] == "object"
    assert basic_func.parameters["properties"] == {}
    assert basic_func.parameters["required"] == []


def test_tool_decorator_with_config():
    """Test @tool decorator with configuration options."""

    @tool(
        name="custom_name",
        description="Custom description",
        strict=True,
        instructions="Custom instructions",
        add_instructions=False,
        show_result=True,
        stop_after_tool_call=True,
        requires_confirmation=True,
        cache_results=True,
        cache_dir="/tmp",
        cache_ttl=7200,
    )
    def configured_func() -> str:
        """Original docstring."""
        return "test"

    assert isinstance(configured_func, Function)
    assert configured_func.name == "custom_name"
    assert configured_func.description == "Custom description"
    assert configured_func.strict is True
    assert configured_func.instructions == "Custom instructions"
    assert configured_func.add_instructions is False
    assert configured_func.show_result is True
    assert configured_func.stop_after_tool_call is True
    assert configured_func.requires_confirmation is True
    assert configured_func.cache_results is True
    assert configured_func.cache_dir == "/tmp"
    assert configured_func.cache_ttl == 7200


def test_tool_decorator_with_user_input():
    """Test @tool decorator with user input configuration."""

    @tool(requires_user_input=True, user_input_fields=["param1"])
    def user_input_func(param1: str, param2: int = 42) -> str:
        """Function requiring user input."""
        return f"{param1}-{param2}"

    assert isinstance(user_input_func, Function)
    assert user_input_func.requires_user_input is True
    assert user_input_func.user_input_fields == ["param1"]
    user_input_func.process_entrypoint()
    assert user_input_func.user_input_schema is not None
    assert len(user_input_func.user_input_schema) == 2
    assert user_input_func.user_input_schema[0].name == "param1"
    assert user_input_func.user_input_schema[0].field_type is str
    assert user_input_func.user_input_schema[1].name == "param2"
    assert user_input_func.user_input_schema[1].field_type is int


def test_tool_decorator_with_hooks():
    """Test @tool decorator with pre and post hooks."""
    pre_hook_called = False
    post_hook_called = False

    def pre_hook():
        nonlocal pre_hook_called
        pre_hook_called = True

    def post_hook():
        nonlocal post_hook_called
        post_hook_called = True

    @tool(pre_hook=pre_hook, post_hook=post_hook)
    def hooked_func() -> str:
        return "test"

    assert isinstance(hooked_func, Function)
    assert hooked_func.pre_hook == pre_hook
    assert hooked_func.post_hook == post_hook


def test_tool_decorator_with_tool_hooks():
    """Test @tool decorator with tool hooks."""
    hook_calls = []

    def tool_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
        hook_calls.append(("before", function_name, arguments))
        result = function_call(**arguments)
        hook_calls.append(("after", function_name, result))
        return result

    @tool(tool_hooks=[tool_hook])
    def tool_hooked_func(param1: str) -> str:
        return f"processed-{param1}"

    assert isinstance(tool_hooked_func, Function)
    assert tool_hooked_func.tool_hooks == [tool_hook]


def test_tool_decorator_async():
    """Test @tool decorator with async function."""

    @tool
    async def async_func() -> str:
        """Async test function."""
        return "test"

    assert isinstance(async_func, Function)
    assert async_func.name == "async_func"
    assert async_func.description == "Async test function."
    assert async_func.entrypoint is not None


def test_tool_decorator_async_generator():
    """Test @tool decorator with async generator function."""

    @tool
    async def async_gen_func():
        """Async generator test function."""
        yield "test"

    assert isinstance(async_gen_func, Function)
    assert async_gen_func.name == "async_gen_func"
    assert async_gen_func.description == "Async generator test function."
    assert async_gen_func.entrypoint is not None


def test_tool_decorator_invalid_config():
    """Test @tool decorator with invalid configuration."""
    with pytest.raises(ValueError, match="Invalid tool configuration arguments"):

        @tool(invalid_arg=True)
        def invalid_func():
            pass


def test_tool_decorator_exclusive_flags():
    """Test @tool decorator with mutually exclusive flags."""
    with pytest.raises(
        ValueError,
        match="Only one of 'requires_user_input', 'requires_confirmation', or 'external_execution' can be set to True",
    ):

        @tool(requires_user_input=True, requires_confirmation=True)
        def exclusive_flags_func():
            pass


def test_tool_decorator_with_agent_team_params():
    """Test @tool decorator with agent and team parameters."""

    @tool
    def agent_team_func(agent: Any, team: Any, param1: str) -> str:
        """Function with agent and team parameters."""
        return f"{param1}"

    assert isinstance(agent_team_func, Function)
    agent_team_func.process_entrypoint()
    assert "agent" not in agent_team_func.parameters["properties"]
    assert "team" not in agent_team_func.parameters["properties"]
    assert "param1" in agent_team_func.parameters["properties"]
    assert agent_team_func.parameters["properties"]["param1"]["type"] == "string"


def test_tool_decorator_with_complex_types():
    """Test @tool decorator with complex parameter types."""
    from typing import Dict, List, Optional

    @tool
    def complex_types_func(param1: List[str], param2: Dict[str, int], param3: Optional[bool] = None) -> str:
        """Function with complex parameter types."""
        return "test"

    assert isinstance(complex_types_func, Function)
    complex_types_func.process_entrypoint()
    assert complex_types_func.parameters["properties"]["param1"]["type"] == "array"
    assert complex_types_func.parameters["properties"]["param1"]["items"]["type"] == "string"
    assert complex_types_func.parameters["properties"]["param2"]["type"] == "object"
    assert complex_types_func.parameters["properties"]["param3"]["type"] == "boolean"
    assert "param3" not in complex_types_func.parameters["required"]
