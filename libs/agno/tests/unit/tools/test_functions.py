import sys
from typing import Any, Callable, Dict, List, Optional

import pytest
from pydantic import BaseModel, ValidationError

import agno.tools.function as function_module
from agno.models.message import Message
from agno.run.base import RunContext
from agno.tools import Toolkit
from agno.tools.decorator import tool
from agno.tools.function import Function, FunctionCall, ToolResult


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
    assert test_func.parameters["properties"]["param2"]["type"] == "integer"
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
    assert func.parameters["properties"]["param2"]["type"] == "integer"
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


def test_wrap_callable_caches_pydantic_version_lookup(mocker):
    """Pydantic package metadata should only be read once across many tool wraps."""
    function_module._get_pydantic_version.cache_clear()
    version_spy = mocker.spy(function_module, "version")

    def test_func(value: str) -> str:
        return value

    for _ in range(100):
        Function._wrap_callable(test_func)

    assert version_spy.call_count == 1


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
    assert func.parameters["properties"]["param2"]["type"] == "integer"
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


def test_function_process_entrypoint_with_user_input_excludes_run_context():
    """Test that user_input_schema excludes run_context when requires_user_input=True."""

    def test_func(run_context: RunContext, param1: str, param2: int = 42) -> str:
        """Test function with run_context and user input.

        Args:
            param1 (str): First parameter.
            param2 (int): Second parameter.
        """
        return f"{param1}-{param2}"

    func = Function(name="test_func", entrypoint=test_func, requires_user_input=True, user_input_fields=["param1"])
    func.process_entrypoint()

    assert func.user_input_schema is not None
    field_names = [f.name for f in func.user_input_schema]
    assert "run_context" not in field_names
    assert "param1" in field_names
    assert "param2" in field_names
    assert len(func.user_input_schema) == 2


def test_function_process_entrypoint_with_user_input_excludes_all_framework_params():
    """Test that user_input_schema excludes all framework-injected params (agent, team, self, media)."""
    from agno.agent.agent import Agent
    from agno.team.team import Team

    def test_func(agent: Agent, team: Team, run_context: RunContext, param1: str) -> str:
        """Test function.

        Args:
            param1 (str): First parameter.
        """
        return param1

    func = Function(name="test_func", entrypoint=test_func, requires_user_input=True, user_input_fields=[])
    func.process_entrypoint()

    assert func.user_input_schema is not None
    field_names = [f.name for f in func.user_input_schema]
    assert field_names == ["param1"]


def test_function_process_entrypoint_with_user_input_excludes_by_type():
    """Test that user_input_schema excludes params by type, not just name (e.g. my_ctx: RunContext)."""
    from agno.agent.agent import Agent
    from agno.team.team import Team

    def test_func(my_ctx: RunContext, my_agent: Agent, my_team: Team, param1: str) -> str:
        """Test function.

        Args:
            param1 (str): First parameter.
        """
        return param1

    func = Function(name="test_func", entrypoint=test_func, requires_user_input=True, user_input_fields=["param1"])
    func.process_entrypoint()

    assert func.user_input_schema is not None
    field_names = [f.name for f in func.user_input_schema]
    assert "my_ctx" not in field_names
    assert "my_agent" not in field_names
    assert "my_team" not in field_names
    assert field_names == ["param1"]


def test_user_input_with_run_context_execution():
    """Test that a tool with requires_user_input=True and run_context executes without error."""

    @tool(requires_user_input=True, user_input_fields=["to_address"])
    def send_email(run_context: RunContext, subject: str, body: str, to_address: str) -> str:
        """Send an email.

        Args:
            subject (str): The subject.
            body (str): The body.
            to_address (str): The address.
        """
        count = run_context.session_state.get("sent", 0)
        run_context.session_state["sent"] = count + 1
        return f"Sent to {to_address}"

    send_email.process_entrypoint()

    # Verify run_context is not in user_input_schema
    field_names = [f.name for f in (send_email.user_input_schema or [])]
    assert "run_context" not in field_names
    assert "subject" in field_names
    assert "body" in field_names
    assert "to_address" in field_names

    # Verify execution succeeds without "multiple values for keyword argument" error
    run_context = RunContext(run_id="test", session_id="test", session_state={"sent": 0})
    send_email._run_context = run_context

    fc = FunctionCall(function=send_email, arguments={"subject": "Hi", "body": "Hello", "to_address": "a@b.com"})
    result = fc.execute()
    assert result.status == "success"
    assert result.result == "Sent to a@b.com"
    assert run_context.session_state["sent"] == 1


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


def test_function_cache_file_path(tmp_path):
    """Test generation of cache file paths."""
    import os

    func = Function(name="test_func", cache_results=True, cache_dir=str(tmp_path))

    cache_key = "test_key"
    cache_file = func._get_cache_file_path(cache_key)
    assert cache_file == os.path.join(str(tmp_path), "functions", "test_func", "test_key.json")


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


def test_function_call_execution_no_arguments():
    """Test sync execution of a no-parameter tool called with no arguments."""

    def test_func() -> str:
        return "no-args-result"

    func = Function(name="test_func", entrypoint=test_func)

    call = FunctionCall(function=func, arguments=None)

    result = call.execute()
    assert result.status == "success"
    assert result.result == "no-args-result"
    assert result.error is None


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
async def test_function_call_async_execution_no_arguments():
    """Test async execution of a no-parameter tool called with no arguments."""

    async def test_func() -> str:
        return "no-args-result"

    func = Function(name="test_func", entrypoint=test_func)

    call = FunctionCall(function=func, arguments=None)

    result = await call.aexecute()
    assert result.status == "success"
    assert result.result == "no-args-result"
    assert result.error is None


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


@pytest.mark.asyncio
async def test_function_call_async_with_empty_tool_hooks():
    """Async coroutine entrypoint with tool_hooks=[] executes correctly.

    Sanity check for the no-hooks branch of _build_nested_execution_chain_async.
    Note: a regular async coroutine returned through the (pre-fix) sync
    fallback was still awaited at the outer call site in aexecute, so this
    case did not break on main — it is kept as a symmetry check alongside the
    async-generator regression test below.
    """

    async def async_func(param1: str) -> str:
        return f"async-{param1}"

    func = Function(name="async_func", entrypoint=async_func, tool_hooks=[])
    func.process_entrypoint()

    call = FunctionCall(function=func, arguments={"param1": "value1"})

    result = await call.aexecute()
    assert result.status == "success"
    assert result.result == "async-value1"
    assert result.error is None


@pytest.mark.asyncio
async def test_function_call_async_generator_with_empty_tool_hooks():
    """Async generator entrypoint with tool_hooks=[] must not crash.

    Regression test for the actual failure surfaced by the fix for #7716:
    on main, `_build_nested_execution_chain_async` returned the sync
    `execute_entrypoint` when `tool_hooks=[]`. For an async generator, that
    returned the generator object, which the outer ``await execution_chain(...)``
    in ``aexecute`` then tried to await — raising::

        TypeError: object async_generator can't be used in 'await' expression

    With the fix (returning `execute_entrypoint_async`), the async generator
    is preserved without being awaited, and the caller can iterate it.
    """

    async def async_gen(param1: str):
        yield f"chunk-1-{param1}"
        yield f"chunk-2-{param1}"

    func = Function(name="async_gen", entrypoint=async_gen, tool_hooks=[])
    func.process_entrypoint()

    call = FunctionCall(function=func, arguments={"param1": "value1"})

    result = await call.aexecute()
    assert result.status == "success", f"unexpected failure: {result.error}"
    assert result.error is None

    # The result must be a live async generator the caller can iterate.
    chunks = [chunk async for chunk in result.result]
    assert chunks == ["chunk-1-value1", "chunk-2-value1"]


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


def test_tool_decorator_with_agent_team_type_annotations():
    """Test @tool decorator skips validation when parameter types are Agent/Team,
    even when parameter names differ from 'agent'/'team' (issue #6344)."""
    from agno.agent.agent import Agent
    from agno.team.team import Team

    @tool
    def func_with_agent_type(my_agent: Agent, query: str) -> str:
        """Function with Agent type but non-standard parameter name."""
        return query

    assert isinstance(func_with_agent_type, Function)
    func_with_agent_type.process_entrypoint()
    # Should not have _wrapped_for_validation since validation was skipped
    assert not getattr(func_with_agent_type.entrypoint, "_wrapped_for_validation", False)
    assert "query" in func_with_agent_type.parameters["properties"]
    assert "my_agent" not in func_with_agent_type.parameters["properties"]

    @tool
    def func_with_team_type(my_team: Team, query: str) -> str:
        """Function with Team type but non-standard parameter name."""
        return query

    assert isinstance(func_with_team_type, Function)
    func_with_team_type.process_entrypoint()
    assert not getattr(func_with_team_type.entrypoint, "_wrapped_for_validation", False)
    assert "query" in func_with_team_type.parameters["properties"]
    assert "my_team" not in func_with_team_type.parameters["properties"]


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


def test_function_cache_pydantic_model(tmp_path):
    """Test caching operations with Pydantic BaseModel results."""
    import json
    import os

    class OrderResponse(BaseModel):
        success: bool
        data: Optional[dict] = None

    func = Function(name="test_func", cache_results=True, cache_dir=str(tmp_path))

    # Test saving a Pydantic model to cache
    test_result = OrderResponse(success=True, data={"id": 123, "status": "delivered"})
    cache_file = os.path.join(str(tmp_path), "test_pydantic_cache.json")
    func._save_to_cache(cache_file, test_result)

    # Verify cache file exists and contains correct data
    assert os.path.exists(cache_file)
    with open(cache_file, "r") as f:
        cached_data = json.load(f)
    assert cached_data["result"] == {"success": True, "data": {"id": 123, "status": "delivered"}}

    # Test retrieving from cache returns the dict representation
    retrieved_result = func._get_cached_result(cache_file)
    assert retrieved_result == {"success": True, "data": {"id": 123, "status": "delivered"}}


def test_function_cache_pydantic_model_nested(tmp_path):
    """Test caching operations with nested Pydantic BaseModel results."""
    import json
    import os

    class Address(BaseModel):
        street: str
        city: str

    class User(BaseModel):
        name: str
        address: Address

    func = Function(name="test_func", cache_results=True, cache_dir=str(tmp_path))

    test_result = User(name="John", address=Address(street="123 Main St", city="Springfield"))
    cache_file = os.path.join(str(tmp_path), "test_nested_cache.json")
    func._save_to_cache(cache_file, test_result)

    assert os.path.exists(cache_file)
    with open(cache_file, "r") as f:
        cached_data = json.load(f)
    assert cached_data["result"] == {"name": "John", "address": {"street": "123 Main St", "city": "Springfield"}}

    retrieved_result = func._get_cached_result(cache_file)
    assert retrieved_result == {"name": "John", "address": {"street": "123 Main St", "city": "Springfield"}}


def test_param_description_without_docstring_type():
    """Test that parameter descriptions don't get a '(None)' prefix when the docstring omits type annotations."""

    def my_tool(currency_code: str, amount: float) -> dict:
        """Convert currency.

        Args:
            currency_code: The ISO currency code.
            amount: The amount to convert.
        """
        return {}

    func = Function.from_callable(my_tool)
    props = func.parameters["properties"]

    # Descriptions should NOT start with "(None)"
    assert not props["currency_code"]["description"].startswith("(None)")
    assert not props["amount"]["description"].startswith("(None)")
    assert props["currency_code"]["description"] == "The ISO currency code."
    assert props["amount"]["description"] == "The amount to convert."


def test_param_description_with_docstring_type():
    """Test that parameter descriptions preserve the type prefix when the docstring includes type annotations."""

    def my_tool(currency_code: str, amount: float) -> dict:
        """Convert currency.

        Args:
            currency_code (str): The ISO currency code.
            amount (float): The amount to convert.
        """
        return {}

    func = Function.from_callable(my_tool)
    props = func.parameters["properties"]

    # Descriptions should include the docstring type prefix
    assert props["currency_code"]["description"] == "(str) The ISO currency code."
    assert props["amount"]["description"] == "(float) The amount to convert."


def test_pre_hook_receives_messages_via_run_context():
    """Test that pre-hook can access current run message history via run_context.messages."""
    captured_messages: Optional[List[Message]] = None

    def pre_hook(run_context: RunContext):
        nonlocal captured_messages
        captured_messages = run_context.messages

    def test_func(param1: str) -> str:
        return f"processed-{param1}"

    # Create a run context with a message history
    run_context = RunContext(run_id="test-run", session_id="test-session")
    run_context.messages = [
        Message(role="system", content="You are a helpful assistant."),
        Message(role="user", content="Hello"),
        Message(role="assistant", content="Hi there!"),
    ]

    func = Function(name="test_func", entrypoint=test_func, pre_hook=pre_hook)
    func._run_context = run_context

    call = FunctionCall(function=func, arguments={"param1": "value1"})
    result = call.execute()

    assert result.status == "success"
    assert result.result == "processed-value1"
    assert captured_messages is not None
    assert len(captured_messages) == 3
    assert captured_messages[0].role == "system"
    assert captured_messages[1].role == "user"
    assert captured_messages[1].content == "Hello"
    assert captured_messages[2].role == "assistant"
    # Verify it's a copy (not the same reference), so hook mutations don't affect the run
    assert captured_messages is not run_context.messages
    assert captured_messages == run_context.messages


def test_pre_hook_messages_is_none_when_no_run_context():
    """Test that run_context.messages is None when messages haven't been set."""
    hook_result: Dict[str, Any] = {}

    def pre_hook(run_context: RunContext):
        hook_result["messages"] = run_context.messages
        hook_result["called"] = True

    def test_func(param1: str) -> str:
        return f"processed-{param1}"

    # RunContext with no messages set (defaults to None)
    run_context = RunContext(run_id="test-run", session_id="test-session")
    func = Function(name="test_func", entrypoint=test_func, pre_hook=pre_hook)
    func._run_context = run_context

    call = FunctionCall(function=func, arguments={"param1": "value1"})
    result = call.execute()

    assert result.status == "success"
    assert hook_result["called"] is True
    assert hook_result["messages"] is None


@pytest.mark.asyncio
async def test_async_pre_hook_receives_messages_via_run_context():
    """Test that async pre-hook can access current run message history via run_context.messages."""
    captured_messages: Optional[List[Message]] = None

    async def pre_hook(run_context: RunContext):
        nonlocal captured_messages
        captured_messages = run_context.messages

    async def test_func(param1: str) -> str:
        return f"processed-{param1}"

    run_context = RunContext(run_id="test-run", session_id="test-session")
    run_context.messages = [
        Message(role="user", content="What is the weather?"),
        Message(role="assistant", content="Let me check that for you."),
    ]

    func = Function(name="test_func", entrypoint=test_func, pre_hook=pre_hook)
    func._run_context = run_context

    call = FunctionCall(function=func, arguments={"param1": "value1"})
    result = await call.aexecute()

    assert result.status == "success"
    assert result.result == "processed-value1"
    assert captured_messages is not None
    assert len(captured_messages) == 2
    assert captured_messages[0].content == "What is the weather?"
    # Verify it's a copy (not the same reference), so hook mutations don't affect the run
    assert captured_messages is not run_context.messages
    assert captured_messages == run_context.messages


def test_post_hook_receives_messages_via_run_context():
    """Test that post-hook can access current run message history via run_context.messages."""
    captured_messages: Optional[List[Message]] = None

    def post_hook(run_context: RunContext):
        nonlocal captured_messages
        captured_messages = run_context.messages

    def test_func(param1: str) -> str:
        return f"processed-{param1}"

    run_context = RunContext(run_id="test-run", session_id="test-session")
    run_context.messages = [
        Message(role="user", content="Do something"),
    ]

    func = Function(name="test_func", entrypoint=test_func, post_hook=post_hook)
    func._run_context = run_context

    call = FunctionCall(function=func, arguments={"param1": "value1"})
    result = call.execute()

    assert result.status == "success"
    assert captured_messages is not None
    assert len(captured_messages) == 1
    assert captured_messages[0].content == "Do something"
    # Verify it's a copy (not the same reference), so hook mutations don't affect the run
    assert captured_messages is not run_context.messages
    assert captured_messages == run_context.messages


def test_tool_hook_receives_messages_via_run_context():
    """Test that tool hooks can access current run message history via run_context.messages."""
    captured_messages: Optional[List[Message]] = None

    def tool_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any], run_context: RunContext):
        nonlocal captured_messages
        captured_messages = run_context.messages
        return function_call(**arguments)

    @tool(tool_hooks=[tool_hook])
    def test_func(param1: str) -> str:
        return f"processed-{param1}"

    test_func.process_entrypoint()

    run_context = RunContext(run_id="test-run", session_id="test-session")
    run_context.messages = [
        Message(role="user", content="Use the tool"),
    ]

    test_func._run_context = run_context

    call = FunctionCall(function=test_func, arguments={"param1": "value1"})
    result = call.execute()

    assert result.status == "success"
    assert result.result == "processed-value1"
    assert captured_messages is not None
    assert len(captured_messages) == 1
    assert captured_messages[0].content == "Use the tool"
    # Verify it's a copy (not the same reference), so hook mutations don't affect the run
    assert captured_messages is not run_context.messages
    assert captured_messages == run_context.messages


# ----------------------------------------------------------------------
# Framework-injected parameters: schema exclusion and the drop guard
# ----------------------------------------------------------------------


def _passthrough_tool_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    return function_call(**arguments)


def test_agno_channels_excluded_from_from_callable_schema():
    """`_agno_` channels are never advertised to the model by from_callable."""

    def fn(query: str, _agno_run_context: Optional[RunContext] = None, _agno_agent: Optional[Any] = None) -> str:
        return query

    for strict in (False, True):
        func = Function.from_callable(fn, strict=strict)
        properties = func.parameters["properties"]
        assert "_agno_run_context" not in properties
        assert "_agno_agent" not in properties
        assert "_agno_run_context" not in func.parameters["required"]
        assert "_agno_agent" not in func.parameters["required"]
        assert list(properties) == ["query"]


def test_required_agno_channel_excluded_from_required_list():
    """A channel with no default must not land in `required` either."""

    def fn(_agno_run_context, query: str) -> str:
        return query

    func = Function.from_callable(fn)
    assert func.parameters["required"] == ["query"]

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    assert func.parameters["required"] == ["query"]


def test_a_tools_own_fc_parameter_stays_model_facing():
    """`fc` is injected but not reserved: a tool may use the name for its own argument."""

    def book_flight(fc: str, seats: int) -> str:
        return f"{fc}/{seats}"

    func = Function(name="book_flight", entrypoint=book_flight)
    func.process_entrypoint()
    assert set(func.parameters["properties"]) == {"fc", "seats"}

    for hooks in (None, [_passthrough_tool_hook]):
        func.tool_hooks = hooks
        result = FunctionCall(function=func, arguments={"fc": "AA123", "seats": 2}).execute()
        assert result.status == "success"
        assert result.result == "AA123/2"


def test_fc_typed_as_functioncall_is_injected_and_leaves_a_valid_schema():
    """An `fc: FunctionCall` param has no JSON schema, so it must not be listed as required."""

    received: Dict[str, Any] = {}

    def audit(fc: FunctionCall, note: str) -> str:
        received["fc"] = fc
        return note

    func = Function(name="audit", entrypoint=audit)
    func.process_entrypoint()
    assert list(func.parameters["properties"]) == ["note"]
    assert func.parameters["required"] == ["note"]

    call = FunctionCall(function=func, arguments={"note": "n"})
    assert call.execute().status == "success"
    assert received["fc"] is call


def test_required_never_names_a_property_the_schema_does_not_have():
    """required must stay a subset of properties on every construction path."""

    def fn(fc: FunctionCall, note: str, count: int = 1) -> str:
        return note

    for func in (Function.from_callable(fn), Function(name="fn", entrypoint=fn)):
        if func.entrypoint is not None and not func.parameters.get("properties"):
            func.process_entrypoint()
        assert set(func.parameters["required"]) <= set(func.parameters["properties"])


def test_unrecognised_agno_prefixed_param_stays_model_facing():
    """Only the three real channels are reserved; the prefix itself is not."""

    def fn(_agno_batch_id: str, rows: int) -> str:
        return f"{_agno_batch_id}:{rows}"

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    assert set(func.parameters["properties"]) == {"_agno_batch_id", "rows"}

    call = FunctionCall(function=func, arguments={"_agno_batch_id": "b1", "rows": 2})
    result = call.execute()
    assert result.status == "success"
    assert result.result == "b1:2"


@pytest.mark.parametrize("with_hooks", [False, True])
def test_spoofed_agno_channel_is_dropped(with_hooks):
    """A model-supplied `_agno_run_context` never reaches the entrypoint."""

    seen: Dict[str, Any] = {}

    def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        seen["user_id"] = getattr(_agno_run_context, "user_id", None)
        return query

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    func.tool_hooks = [_passthrough_tool_hook] if with_hooks else None
    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")

    call = FunctionCall(
        function=func,
        arguments={"query": "q", "_agno_run_context": {"user_id": "victim", "session_id": "s9", "run_id": "r9"}},
    )
    result = call.execute()
    assert result.status == "success"
    assert seen["user_id"] == "real-user"
    assert call.arguments == {"query": "q"}


def test_spoofed_agno_channel_is_dropped_even_when_declared_in_the_schema():
    """The `_agno_` channels are internal, so a hand-written schema cannot re-open them."""

    seen: Dict[str, Any] = {}

    def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        seen["user_id"] = getattr(_agno_run_context, "user_id", None)
        return query

    func = Function(
        name="fn",
        entrypoint=fn,
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}, "_agno_run_context": {"type": "object"}},
            "required": ["query"],
        },
        skip_entrypoint_processing=True,
    )
    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")

    call = FunctionCall(function=func, arguments={"query": "q", "_agno_run_context": {"user_id": "victim"}})
    assert call.execute().status == "success"
    assert seen["user_id"] == "real-user"


@pytest.mark.parametrize("with_hooks", [False, True])
def test_spoofed_public_run_context_is_dropped(with_hooks):
    """The documented `run_context` parameter is framework-owned too."""

    seen: Dict[str, Any] = {}

    def fn(query: str, run_context: Optional[RunContext] = None) -> str:
        seen["user_id"] = getattr(run_context, "user_id", None)
        return query

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    func.tool_hooks = [_passthrough_tool_hook] if with_hooks else None
    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")

    call = FunctionCall(function=func, arguments={"query": "q", "run_context": {"user_id": "victim"}})
    assert call.execute().status == "success"
    assert seen["user_id"] == "real-user"


def test_spoofed_type_excluded_param_is_dropped():
    """A param excluded by annotation is owned by the framework, whatever it is named."""

    seen: Dict[str, Any] = {}

    def fn(query: str, ctx: RunContext = None) -> str:  # type: ignore[assignment]
        seen["user_id"] = getattr(ctx, "user_id", None)
        return query

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    assert list(func.parameters["properties"]) == ["query"]
    assert func._framework_params is not None and "ctx" in func._framework_params

    call = FunctionCall(function=func, arguments={"query": "q", "ctx": {"user_id": "victim", "session_id": "s9"}})
    assert call.execute().status == "success"
    assert seen["user_id"] is None
    assert call.arguments == {"query": "q"}


def test_type_excluded_spoof_is_dropped_for_a_decorated_toolkit_method():
    """Toolkit rebuilds each @tool method as a skip_entrypoint_processing Function."""

    class Kit(Toolkit):
        def __init__(self):
            super().__init__(name="kit", tools=[self.audit])

        @tool()
        def audit(self, note: str, ctx: RunContext = None) -> str:  # type: ignore[assignment]
            return f"caller={getattr(ctx, 'user_id', None)}"

    func = Kit().functions["audit"]
    func.process_entrypoint()
    assert func.skip_entrypoint_processing is True
    assert list(func.parameters["properties"]) == ["note"]
    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")

    call = FunctionCall(
        function=func,
        arguments={"note": "n", "ctx": {"run_id": "r9", "session_id": "s9", "user_id": "ATTACKER"}},
    )
    result = call.execute()
    assert result.status == "success"
    # The spoof is dropped and the parameter receives the caller's real context:
    # a name excluded from the schema is filled by the framework, never left dead.
    assert result.result == "caller=real-user"


def test_schema_declared_media_name_keeps_the_model_value_on_both_paths():
    """A wrapper may expose the wrapped tool's own `files` argument; the schema says so."""

    received: Dict[str, Any] = {}

    def fn(files, note: str) -> str:
        received.update({"files": files, "note": note})
        return "ok"

    for hooks in ([_passthrough_tool_hook], None):
        received.clear()
        func = Function(
            name="fn",
            entrypoint=fn,
            parameters={
                "type": "object",
                "properties": {"files": {"type": "array"}, "note": {"type": "string"}},
                "required": ["files", "note"],
            },
        )
        func.process_entrypoint()
        func.tool_hooks = hooks
        call = FunctionCall(function=func, arguments={"files": ["a.pdf"], "note": "n"})
        result = call.execute()
        assert result.status == "success"
        assert received == {"files": ["a.pdf"], "note": "n"}


@pytest.mark.parametrize("with_hooks", [False, True])
def test_a_schema_can_never_hand_the_model_an_identity_parameter(with_hooks):
    """Unlike media, run_context stays framework-owned even when the schema declares it."""

    seen: Dict[str, Any] = {}

    def fn(run_context, note: str) -> str:
        seen["user_id"] = getattr(run_context, "user_id", None)
        return "ok"

    func = Function(
        name="fn",
        entrypoint=fn,
        parameters={
            "type": "object",
            "properties": {"run_context": {"type": "object"}, "note": {"type": "string"}},
            "required": ["note"],
        },
    )
    func.process_entrypoint()
    func.tool_hooks = [_passthrough_tool_hook] if with_hooks else None
    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")

    call = FunctionCall(
        function=func,
        arguments={"note": "n", "run_context": {"run_id": "r9", "session_id": "s9", "user_id": "victim"}},
    )
    result = call.execute()
    assert result.status == "success"
    assert seen["user_id"] == "real-user"


def test_dropped_arguments_are_logged_and_the_original_dict_is_untouched():
    """The pre-drop dict is referenced by the emitted ToolExecution, so it is rebound."""

    def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        return query

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()

    call = FunctionCall(function=func, arguments={"query": "q", "_agno_run_context": {"user_id": "victim"}})
    # models/base.py hands this exact dict to the ToolExecution it emits on tool_call_started.
    emitted = call.arguments

    warnings: List[str] = []
    original_log_warning = function_module.log_warning
    function_module.log_warning = lambda message: warnings.append(str(message))
    try:
        assert call.execute().status == "success"
    finally:
        function_module.log_warning = original_log_warning

    assert emitted == {"query": "q", "_agno_run_context": {"user_id": "victim"}}
    assert call.arguments == {"query": "q"}
    assert any("_agno_run_context" in warning for warning in warnings)


def test_arguments_are_sanitized_before_the_pre_hook_runs():
    """A pre-hook used as an authorization gate must not read a discarded identity."""

    seen: Dict[str, Any] = {}

    def pre_hook(fc: FunctionCall):
        seen["arguments"] = dict(fc.arguments or {})

    def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        return query

    func = Function(name="fn", entrypoint=fn, pre_hook=pre_hook)
    func.process_entrypoint()

    call = FunctionCall(function=func, arguments={"query": "q", "_agno_run_context": {"user_id": "victim"}})
    assert call.execute().status == "success"
    assert seen["arguments"] == {"query": "q"}


@pytest.mark.asyncio
async def test_spoofed_agno_channel_is_dropped_on_the_async_path():
    """aexecute must sanitize exactly as execute does."""

    seen: Dict[str, Any] = {}

    async def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        seen["user_id"] = getattr(_agno_run_context, "user_id", None)
        return query

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")

    call = FunctionCall(function=func, arguments={"query": "q", "_agno_run_context": {"user_id": "victim"}})
    result = await call.aexecute()
    assert result.status == "success"
    assert seen["user_id"] == "real-user"
    assert call.arguments == {"query": "q"}


def test_session_state_propagates_through_the_agno_run_context_channel():
    """A tool given the `_agno_` channel still reports its session_state writes."""

    def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        if _agno_run_context is not None and _agno_run_context.session_state is not None:
            _agno_run_context.session_state["touched"] = True
        return query

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    func._run_context = RunContext(run_id="r1", session_id="s1", session_state={"existing": 1})

    result = FunctionCall(function=func, arguments={"query": "q"}).execute()
    assert result.status == "success"
    assert result.updated_session_state == {"existing": 1, "touched": True}


@pytest.mark.asyncio
async def test_session_state_propagates_through_the_agno_run_context_channel_async():
    """The async path reports session_state writes through the `_agno_` channel too."""

    async def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        if _agno_run_context is not None and _agno_run_context.session_state is not None:
            _agno_run_context.session_state["touched"] = True
        return query

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    func._run_context = RunContext(run_id="r1", session_id="s1", session_state={"existing": 1})

    result = await FunctionCall(function=func, arguments={"query": "q"}).aexecute()
    assert result.status == "success"
    assert result.updated_session_state == {"existing": 1, "touched": True}


def test_non_dict_session_state_is_not_reported():
    """A non-dict session_state cannot be merged, so it is reported as absent."""

    def fn(query: str, _agno_run_context: Optional[Any] = None) -> str:
        return query

    class _Context:
        user_id = "u"
        session_id = "s"
        session_state = "not-a-dict"

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    func._run_context = _Context()  # type: ignore[assignment]

    result = FunctionCall(function=func, arguments={"query": "q"}).execute()
    assert result.status == "success"
    assert result.updated_session_state is None


def test_framework_params_survive_the_per_run_function_copy():
    """agent/_tools.py deep-copies a @tool Function per run without reprocessing it."""

    @tool()
    def fetch(query: str, ctx: RunContext = None) -> str:  # type: ignore[assignment]
        return f"ctx_user={getattr(ctx, 'user_id', None)}"

    assert fetch._framework_params == {"ctx"}

    for deep in (False, True):
        runtime = fetch.model_copy(deep=deep)
        assert runtime._framework_params == {"ctx"}
        runtime._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")
        call = FunctionCall(
            function=runtime,
            arguments={"query": "q", "ctx": {"run_id": "r9", "session_id": "s9", "user_id": "victim"}},
        )
        result = call.execute()
        assert result.status == "success"
        # The copy keeps the guard: the spoof is dropped and the real context injected.
        assert result.result == "ctx_user=real-user"


@pytest.mark.asyncio
async def test_arguments_are_sanitized_before_the_pre_hook_runs_async():
    """The async path must sanitize before its pre-hook too."""

    seen: Dict[str, Any] = {}

    async def pre_hook(fc: FunctionCall):
        seen["arguments"] = dict(fc.arguments or {})

    async def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        return query

    func = Function(name="fn", entrypoint=fn, pre_hook=pre_hook)
    func.process_entrypoint()

    call = FunctionCall(function=func, arguments={"query": "q", "_agno_run_context": {"user_id": "victim"}})
    assert (await call.aexecute()).status == "success"
    assert seen["arguments"] == {"query": "q"}


def test_media_channel_ignores_a_model_supplied_value():
    """Media is injected by the framework; a model-supplied value is not a substitute."""

    seen: Dict[str, Any] = {}

    def fn(note: str, files=None) -> str:
        seen["files"] = files
        return note

    func = Function(name="fn", entrypoint=fn)
    func.process_entrypoint()
    assert list(func.parameters["properties"]) == ["note"]

    call = FunctionCall(function=func, arguments={"note": "n", "files": ["evil.pdf"]})
    assert call.execute().status == "success"
    assert seen["files"] is None


def test_injected_name_is_dropped_even_when_process_entrypoint_never_ran():
    """The entrypoint_args term must keep protecting skip_entrypoint_processing Functions."""

    seen: Dict[str, Any] = {}

    def fn(query: str, agent=None) -> str:
        seen["agent"] = agent
        return query

    func = Function(
        name="fn",
        entrypoint=fn,
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        skip_entrypoint_processing=True,
    )
    assert func._framework_params is None

    call = FunctionCall(function=func, arguments={"query": "q", "agent": "spoof"})
    assert call.execute().status == "success"
    assert seen["agent"] is None


def test_strict_processing_does_not_require_an_injected_parameter():
    """process_schema_for_strict rewrites required, so it must honour the same exclusions."""

    def fn(query: str, _agno_run_context: Optional[RunContext] = None) -> str:
        return query

    func = Function(
        name="fn",
        entrypoint=fn,
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "_agno_run_context": {"type": "object"},
                "agent": {"type": "string"},
            },
            "required": ["query"],
        },
        skip_entrypoint_processing=True,
    )
    func.process_entrypoint(strict=True)
    assert func.parameters["required"] == ["query"]


# ----------------------------------------------------------------------
# Regression: the guard must also engage on the from_callable path
# (Agent(tools=[fn]) registers plain callables without process_entrypoint)
# ----------------------------------------------------------------------


@pytest.mark.parametrize("with_hooks", [False, True])
def test_type_excluded_identity_is_protected_on_the_from_callable_path(with_hooks):
    """`Agent(tools=[fn])` builds the Function via from_callable and never runs
    process_entrypoint. A RunContext-typed param must still be kept out of the model
    schema and have a model-supplied value dropped -- otherwise the injection guard is
    inert exactly on the most common registration path."""

    seen: Dict[str, Any] = {}

    def fetch(query: str, ctx: RunContext = None) -> str:  # type: ignore[assignment]
        seen["user_id"] = getattr(ctx, "user_id", None)
        return query

    func = Function.from_callable(fetch)
    # The typed identity param is neither advertised to the model nor left unguarded.
    assert list(func.parameters["properties"]) == ["query"]
    assert func._framework_params is not None and "ctx" in func._framework_params

    func = func.model_copy(deep=True)  # mirrors _tools.py's per-registration copy
    func.tool_hooks = [_passthrough_tool_hook] if with_hooks else None
    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")

    call = FunctionCall(
        function=func,
        arguments={"query": "q", "ctx": {"run_id": "r9", "session_id": "s9", "user_id": "ATTACKER"}},
    )
    result = call.execute()
    assert result.status == "success"
    # The spoof is dropped and the caller's real context is injected in its place.
    assert seen["user_id"] == "real-user"
    assert call.arguments == {"query": "q"}


@pytest.mark.parametrize("bad_properties", [[{"q": {"type": "string"}}], 5, "nope"])
def test_malformed_schema_properties_does_not_abort_the_run(bad_properties):
    """A remote/hand-written schema whose `properties` is not a dict (an MCP server can
    hand one over verbatim) must fail gracefully to a normal call, not raise out of
    execute() -- the guard runs before execute()'s try, so a raise would kill the run."""

    def fn(q: str) -> str:
        return q

    func = Function(
        name="fn",
        entrypoint=fn,
        parameters={"type": "object", "properties": bad_properties, "required": ["q"]},
        skip_entrypoint_processing=True,
    )
    result = FunctionCall(function=func, arguments={"q": "hello"}).execute()
    assert result.status == "success"
    assert result.result == "hello"


def test_user_parameters_without_properties_key_keeps_description():
    """process_entrypoint on a user-supplied parameters dict lacking `properties` must not
    KeyError (which the broad except swallows) and silently drop the description."""

    def tool_b(x: str) -> str:
        """Tool b docstring."""
        return x

    func = Function(name="tool_b", entrypoint=tool_b, parameters={"type": "object", "required": ["x"]})
    func.process_entrypoint()
    assert func.description and "docstring" in func.description.lower()
    assert func.parameters.get("required") == []


def test_optional_framework_typed_param_is_excluded_and_guarded():
    # Optional[RunContext] must get the same treatment as a bare RunContext
    # annotation: out of the model schema and into the framework params.
    from typing import Optional as Opt

    from agno.run import RunContext
    from agno.tools.function import Function

    def fetch(query: str, ctx: Opt[RunContext] = None) -> str:
        return "ok"

    function = Function.from_callable(fetch)
    function.process_entrypoint()
    properties = (function.parameters or {}).get("properties") or {}
    assert set(properties) == {"query"}
    assert "ctx" in (function._framework_params or set())


def test_mixed_union_param_stays_model_fillable():
    # A union mixing a framework media type with a model-fillable type belongs
    # to the model: it stays in the schema and a model-supplied value reaches
    # the entrypoint.
    from typing import Union as Un

    from agno.media import Image
    from agno.tools.function import Function, FunctionCall

    def describe_source(source: Un[str, Image]) -> str:
        """Describe a source."""
        return f"described {source!r}"

    function = Function.from_callable(describe_source)
    function.process_entrypoint()
    properties = (function.parameters or {}).get("properties") or {}
    assert "source" in properties
    assert "source" not in (function._framework_params or set())

    call = FunctionCall(function=function, arguments={"source": "https://example.com/cat.png"})
    result = call.execute()
    assert result.status == "success"
    assert "cat.png" in (result.result or "")


def test_optional_media_param_stays_model_fillable():
    # Optional[File] is a model-fillable parameter: media is injected by
    # parameter name only, so a type-based exclusion would leave it forever
    # unfilled.
    from typing import Optional as Opt

    from agno.media import File
    from agno.tools.function import Function

    def summarize(query: str, doc: Opt[File] = None) -> str:
        """Summarize."""
        return "ok"

    function = Function.from_callable(summarize)
    function.process_entrypoint()
    properties = (function.parameters or {}).get("properties") or {}
    assert set(properties) == {"query", "doc"}
    assert "doc" not in (function._framework_params or set())


def test_identity_and_media_unions_land_on_opposite_sides():
    # A union naming an identity type is framework-owned even when it also
    # names a model-fillable type: a model-supplied dict could coerce into a
    # live RunContext carrying a chosen user_id. A union naming a media type
    # is not, because media is injected by parameter name only.
    from typing import Union as Un

    from agno.media import Image
    from agno.run import RunContext
    from agno.tools.function import Function

    def fetch(query: str, ctx: Un[str, RunContext] = "none", picture: Un[str, Image] = "none") -> str:
        return "ok"

    function = Function.from_callable(fetch)
    function.process_entrypoint()
    properties = (function.parameters or {}).get("properties") or {}
    assert set(properties) == {"query", "picture"}
    assert "ctx" in (function._framework_params or set())
    assert "picture" not in (function._framework_params or set())


def test_framework_typed_return_annotation_keeps_argument_validation():
    # The return annotation is not a parameter: a tool returning an Agent must
    # still get pydantic coercion for the arguments the model sends.
    from typing import Optional as Opt

    from agno.agent.agent import Agent
    from agno.tools.function import Function, FunctionCall

    seen = {}

    def spawn_worker(count: int, role: str) -> Opt[Agent]:
        """Spawn a worker."""
        seen["count"] = count
        return None

    function = Function.from_callable(spawn_worker)
    function.process_entrypoint()
    call = FunctionCall(function=function, arguments={"count": "3", "role": "worker"})
    call.execute()
    assert seen["count"] == 3


def test_type_alias_identity_param_is_excluded_and_guarded():
    # get_type_hints leaves a type alias unresolved; the guard must unwrap it
    # so an aliased RunContext parameter is not model-fillable.
    from typing import Optional as Opt

    from agno.run import RunContext
    from agno.tools.function import Function

    MaybeContext = Opt[RunContext]

    def audit(query: str, ctx: MaybeContext = None) -> str:
        return "ok"

    function = Function.from_callable(audit)
    function.process_entrypoint()
    properties = (function.parameters or {}).get("properties") or {}
    assert set(properties) == {"query"}
    assert "ctx" in (function._framework_params or set())


def test_optional_agent_param_registers_and_is_excluded():
    # from_callable must register a tool with an Optional[Agent] parameter:
    # the union skips the validate_call wrapper (pydantic cannot resolve the
    # Agent class hierarchy) and the parameter stays out of the model schema.
    from typing import Optional as Opt

    from agno.agent.agent import Agent
    from agno.tools.function import Function

    def lookup(query: str, owner: Opt[Agent] = None) -> str:
        """Lookup."""
        return "ok"

    function = Function.from_callable(lookup)
    function.process_entrypoint()
    properties = (function.parameters or {}).get("properties") or {}
    assert set(properties) == {"query"}
    assert "owner" in (function._framework_params or set())


# ----------------------------------------------------------------------------
# Exclusion and injection must name the same annotations.
#
# _is_framework_typed decides what to hide from the model; _build_entrypoint_args
# decides what to fill. An annotation hidden by the first and skipped by the second
# is filled by nobody: a required parameter raises on every call, and one with a
# default silently keeps it forever.
# ----------------------------------------------------------------------------


def _media_agent():
    from agno.agent.agent import Agent

    return Agent(id="real-host", name="Host")


def test_bare_media_typed_param_is_hidden_but_not_dropped_on_the_process_entrypoint_path():
    """Media is injected by reserved NAME only (images/videos/audios/files), so on
    the Toolkit/@tool path a bare media-typed parameter under any other name is
    hidden from the model, as at 2.8.7: exposing it emits an Image schema that is
    invalid under strict mode, failing the whole request rather than one call.

    Hidden is where it stops. The parameter must NOT join _framework_params, or
    the argument guard drops a value supplied for it -- and since the caller's own
    media never lands on this parameter under any behaviour, that displaces
    nothing and leaves it unfillable by anything. v2.8.7 kept the value."""
    from agno.media import Image

    def caption(image: Image, style: str = "short") -> str:
        return f"{getattr(image, 'url', image)}|{style}"

    func = Function(name="caption", entrypoint=caption)
    func.process_entrypoint()

    assert set((func.parameters or {})["properties"]) == {"style"}
    assert "image" not in ((func.parameters or {}).get("required") or [])
    assert "image" not in (func._framework_params or set())

    func._agent = _media_agent()
    result = FunctionCall(function=func, arguments={"image": {"url": "http://x/a.png"}, "style": "long"}).execute()
    assert result.status == "success"
    assert result.result == "http://x/a.png|long"


def test_bare_media_typed_param_with_a_default_is_not_dropped_either():
    """The default-carrying case of the same rule, and the silent half of the
    regression it guards: a dropped value reports success with the default."""
    from agno.media import Image

    def search(query: str, pic: Image = None) -> str:  # type: ignore[assignment]
        return f"{query}|{getattr(pic, 'url', pic)}"

    func = Function(name="search", entrypoint=search)
    func.process_entrypoint()
    assert "pic" not in (func.parameters or {})["properties"]
    assert "pic" not in (func._framework_params or set())

    result = FunctionCall(function=func, arguments={"query": "cats", "pic": {"url": "http://x/b.png"}}).execute()
    assert result.status == "success"
    assert result.result == "cats|http://x/b.png"


def test_bare_media_typed_param_stays_model_fillable_on_the_plain_callable_path():
    """from_callable never hid media by type at 2.8.7: a plain callable passed as
    Agent(tools=[fn]) exposes `pic: Image` to the model, whose dict pydantic
    coerces into an Image. Hiding it here would break tools that work today."""
    from agno.media import Image

    def describe(query: str, pic: Image = None) -> str:  # type: ignore[assignment]
        return f"{query}|{getattr(pic, 'url', pic)}"

    func = Function.from_callable(describe)
    assert "pic" in (func.parameters or {})["properties"]
    assert "pic" not in (func._framework_params or set())

    result = FunctionCall(function=func, arguments={"query": "cats", "pic": {"url": "http://x/b.png"}}).execute()
    assert result.status == "success"
    assert result.result == "cats|http://x/b.png"


def test_variadic_identity_params_are_never_keyword_bound():
    """*args/**kwargs annotated with an identity type can never take a keyword
    bind: Python rejects `rest=None` outright and validate_call rejects
    `extra=None`. Injection skips them, as at 2.8.7, and they bind their own
    empty containers."""

    from agno.agent.agent import Agent

    def vp(query: str, *rest: Agent) -> str:
        return f"{query}|{rest}"

    def vk(query: str, **extra: RunContext) -> str:
        return f"{query}|{extra}"

    for fn, expected in ((vp, "q|()"), (vk, "q|{}")):
        func = Function(name=fn.__name__, entrypoint=fn)
        func.process_entrypoint()
        result = FunctionCall(function=func, arguments={"query": "q"}).execute()
        assert result.status == "success", f"{fn.__name__}: {result.result}"
        assert result.result == expected


def test_identity_typed_param_binds_none_when_the_wielder_has_no_such_object():
    """A tool registered on a Team has no Agent. `owner: Agent` is hidden from
    the model, so injection binds it to None rather than leaving a required
    parameter no one can fill."""
    from agno.agent.agent import Agent

    def owner_tool(q: str, owner: Agent) -> str:
        return f"{q}|{owner}"

    func = Function.from_callable(owner_tool)
    assert set((func.parameters or {})["properties"]) == {"q"}

    result = FunctionCall(function=func, arguments={"q": "hi"}).execute()
    assert result.status == "success"
    assert result.result == "hi|None"

    injected = _media_agent()
    func._agent = injected
    result = FunctionCall(function=func, arguments={"q": "hi"}).execute()
    assert result.status == "success"
    assert result.result == f"hi|{injected}"


def test_union_naming_agent_beside_an_ordinary_type_stays_model_fillable():
    """`owner: Union[str, Agent]` keeps a half the model can legitimately fill. The
    model can only ever send JSON, so it receives a string, never a live Agent."""
    from typing import Union as Un

    from agno.agent.agent import Agent

    def assign(task: str, owner: Un[str, Agent]) -> str:
        return f"{task}->{owner}"

    func = Function(name="assign", entrypoint=assign)
    func.process_entrypoint()
    assert set((func.parameters or {})["properties"]) == {"task", "owner"}

    func._agent = _media_agent()
    result = FunctionCall(function=func, arguments={"task": "ship", "owner": "alice"}).execute()
    assert result.status == "success"
    assert result.result == "ship->alice"


def test_identity_only_union_is_excluded_and_injected():
    """`Optional[Agent]` has no model-fillable half, so it is hidden -- and therefore
    has to be injected, or a required parameter would raise on every call."""
    from typing import Optional as Opt

    from agno.agent.agent import Agent

    seen: Dict[str, Any] = {}

    def notify(msg: str, owner: Opt[Agent]) -> str:
        seen["owner_id"] = getattr(owner, "id", None)
        return msg

    func = Function(name="notify", entrypoint=notify)
    func.process_entrypoint()
    assert set((func.parameters or {})["properties"]) == {"msg"}

    func._agent = _media_agent()
    result = FunctionCall(function=func, arguments={"msg": "m", "owner": {"id": "ATTACKER"}}).execute()
    assert result.status == "success"
    assert seen["owner_id"] == "real-host"


def test_run_context_union_is_excluded_even_beside_an_ordinary_type():
    """RunContext is the one identity type pydantic can build from a model dict:
    validate_call is skipped for Agent/Team parameters but not for this one. An
    exposed `Union[str, RunContext]` would coerce {"user_id": ...} into a live
    RunContext and hand the model the caller's identity."""
    from typing import Union as Un

    seen: Dict[str, Any] = {}

    def fetch(query: str, ctx: Un[str, RunContext] = "none") -> str:
        seen["type"] = type(ctx).__name__
        seen["user_id"] = getattr(ctx, "user_id", None)
        return query

    func = Function(name="fetch", entrypoint=fetch)
    func.process_entrypoint()
    assert set((func.parameters or {})["properties"]) == {"query"}

    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")
    result = FunctionCall(
        function=func,
        arguments={"query": "q", "ctx": {"run_id": "r9", "session_id": "s9", "user_id": "ATTACKER"}},
    ).execute()
    assert result.status == "success"
    # The spoof is dropped and the caller's own context is injected in its place.
    assert seen["type"] == "RunContext"
    assert seen["user_id"] == "real-user"


def test_run_context_typed_param_under_its_own_name_is_injected():
    """A bare `ctx: RunContext` is excluded by type, so it must be filled by type too."""
    seen: Dict[str, Any] = {}

    def audit(note: str, ctx: RunContext = None) -> str:  # type: ignore[assignment]
        seen["user_id"] = getattr(ctx, "user_id", None)
        return note

    func = Function.from_callable(audit)
    assert set((func.parameters or {})["properties"]) == {"note"}

    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")
    assert FunctionCall(function=func, arguments={"note": "n"}).execute().status == "success"
    assert seen["user_id"] == "real-user"


def test_return_annotation_is_never_injected_as_an_argument():
    """get_type_hints reports the return annotation under "return". It is not a
    parameter, and passing it as a keyword would raise."""
    from typing import Optional as Opt

    from agno.agent.agent import Agent

    def spawn(count: int) -> Opt[Agent]:
        return None

    func = Function(name="spawn", entrypoint=spawn)
    func.process_entrypoint()
    func._agent = _media_agent()
    call = FunctionCall(function=func, arguments={"count": 2})
    assert "return" not in call._build_entrypoint_args()
    assert call.execute().status == "success"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 type alias syntax needs 3.12")
def test_nested_type_alias_inside_a_union_is_still_identity():
    """A PEP 695 alias nested inside a union is a TypeAliasType, not a type. Unless
    each union member is unwrapped before the check, `type C = RunContext;
    type M = C | None` slips past both the schema exclusion and the injection guard,
    and pydantic coerces a model-supplied dict into a live RunContext."""
    namespace: Dict[str, Any] = {"RunContext": RunContext}
    exec("type Ctx = RunContext\ntype MaybeCtx = Ctx | None", namespace)
    exec(
        "def fetch(query: str, ctx: MaybeCtx = None) -> str:\n"
        "    return f\"{type(ctx).__name__}:{getattr(ctx, 'user_id', ctx)}\"",
        namespace,
    )

    func = Function(name="fetch", entrypoint=namespace["fetch"])
    func.process_entrypoint()
    assert set((func.parameters or {})["properties"]) == {"query"}

    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")
    result = FunctionCall(
        function=func,
        arguments={"query": "q", "ctx": {"run_id": "r9", "session_id": "s9", "user_id": "ATTACKER"}},
    ).execute()
    assert result.status == "success"
    assert result.result == "RunContext:real-user"


def test_union_of_two_identity_types_falls_through_to_the_one_available():
    """The injection loop must stop at the first type the framework can supply, not
    the first the annotation mentions. `Union[Agent, Team]` on a team names Agent
    first; stopping there leaves the parameter hidden and unfilled, and a required
    one raises on every call."""
    from typing import Union as Un

    from agno.agent.agent import Agent
    from agno.team.team import Team

    def dispatch(task: str, to: Un[Agent, Team]) -> str:
        return type(to).__name__

    func = Function(name="dispatch", entrypoint=dispatch)
    func.process_entrypoint()
    assert set((func.parameters or {})["properties"]) == {"task"}

    # Only a team is available: the Agent arm names first but supplies nothing.
    func._team = Team(id="t", name="T", members=[Agent(id="m", name="M")])
    result = FunctionCall(function=func, arguments={"task": "x"}).execute()
    assert result.status == "success"
    assert result.result == "Team"

    # With both, the first named arm still wins.
    func._agent = Agent(id="a", name="A")
    assert FunctionCall(function=func, arguments={"task": "x"}).execute().result == "Agent"


@pytest.mark.skipif(sys.version_info < (3, 12), reason="PEP 695 type alias syntax needs 3.12")
@pytest.mark.parametrize("annotation", ["Two", "Three", "MaybeTwo"])
def test_chained_type_aliases_are_unwrapped_to_the_end(annotation):
    """Aliases chain. One unwrap step leaves `type One = RunContext; type Two = One`
    model-facing, and pydantic then builds a live RunContext from the model's dict
    -- handing it the caller's identity. Unwrapping repeats to the end."""
    namespace: Dict[str, Any] = {"RunContext": RunContext}
    exec("type One = RunContext\ntype Two = One\ntype Three = Two\ntype MaybeTwo = Two | None", namespace)
    exec(
        f"def fetch(query: str, ctx: {annotation} = None) -> str:\n"
        "    return f\"{type(ctx).__name__}:{getattr(ctx, 'user_id', ctx)}\"",
        namespace,
    )

    func = Function(name="fetch", entrypoint=namespace["fetch"])
    func.process_entrypoint()
    assert set((func.parameters or {})["properties"]) == {"query"}

    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="real-user")
    result = FunctionCall(
        function=func,
        arguments={"query": "q", "ctx": {"run_id": "r9", "session_id": "s9", "user_id": "ATTACKER"}},
    ).execute()
    assert result.status == "success"
    assert result.result == "RunContext:real-user"


# =============================================================================
# Cache key identity tests
# =============================================================================


def test_cached_results_do_not_leak_across_users(tmp_path):
    """A cache_results tool that takes run_context must key per user: one
    user's cached result must never be served to another user."""
    executions = []

    def whoami(run_context: RunContext) -> str:
        executions.append(run_context.user_id)
        return f"secret for {run_context.user_id}"

    func = Function(name="whoami", entrypoint=whoami, cache_results=True, cache_dir=str(tmp_path))

    func._run_context = RunContext(run_id="r1", session_id="s-alice", user_id="alice")
    result_alice = FunctionCall(function=func).execute()

    func._run_context = RunContext(run_id="r2", session_id="s-bob", user_id="bob")
    result_bob = FunctionCall(function=func).execute()

    assert result_alice.result == "secret for alice"
    assert result_bob.result == "secret for bob"
    assert executions == ["alice", "bob"]


@pytest.mark.asyncio
async def test_cached_results_do_not_leak_across_users_async(tmp_path):
    """Async variant: per-user cache keys through aexecute."""
    executions = []

    async def whoami(run_context: RunContext) -> str:
        executions.append(run_context.user_id)
        return f"secret for {run_context.user_id}"

    func = Function(name="whoami", entrypoint=whoami, cache_results=True, cache_dir=str(tmp_path))

    func._run_context = RunContext(run_id="r1", session_id="s-alice", user_id="alice")
    result_alice = await FunctionCall(function=func).aexecute()

    func._run_context = RunContext(run_id="r2", session_id="s-bob", user_id="bob")
    result_bob = await FunctionCall(function=func).aexecute()

    assert result_alice.result == "secret for alice"
    assert result_bob.result == "secret for bob"
    assert executions == ["alice", "bob"]


def test_cache_hits_across_runs_for_same_user_and_session(tmp_path):
    """run_id must stay out of the cache key: the same user and session hit
    the cache across runs."""
    executions = []

    def whoami(run_context: RunContext) -> str:
        executions.append(run_context.user_id)
        return f"secret for {run_context.user_id}"

    func = Function(name="whoami", entrypoint=whoami, cache_results=True, cache_dir=str(tmp_path))

    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="alice")
    FunctionCall(function=func).execute()

    func._run_context = RunContext(run_id="r2", session_id="s1", user_id="alice")
    result = FunctionCall(function=func).execute()

    assert result.result == "secret for alice"
    assert executions == ["alice"]


@pytest.mark.asyncio
async def test_cache_hits_across_runs_for_same_user_and_session_async(tmp_path):
    """Async variant: run_id stays out of the cache key."""
    executions = []

    async def whoami(run_context: RunContext) -> str:
        executions.append(run_context.user_id)
        return f"secret for {run_context.user_id}"

    func = Function(name="whoami", entrypoint=whoami, cache_results=True, cache_dir=str(tmp_path))

    func._run_context = RunContext(run_id="r1", session_id="s1", user_id="alice")
    await FunctionCall(function=func).aexecute()

    func._run_context = RunContext(run_id="r2", session_id="s1", user_id="alice")
    result = await FunctionCall(function=func).aexecute()

    assert result.result == "secret for alice"
    assert executions == ["alice"]


# =============================================================================
# Cached ToolResult round-trip tests
# =============================================================================


def test_cached_tool_result_round_trips_as_tool_result(tmp_path):
    """A cached ToolResult must come back as a ToolResult on a hit, not as a
    plain dict."""

    def get_data() -> ToolResult:
        return ToolResult(content="hello", metadata={"structured_content": {"k": "v"}})

    func = Function(name="get_data", entrypoint=get_data, cache_results=True, cache_dir=str(tmp_path))

    first = FunctionCall(function=func).execute()
    second = FunctionCall(function=func).execute()

    assert isinstance(first.result, ToolResult)
    assert isinstance(second.result, ToolResult)
    assert second.result.content == "hello"
    assert second.result.metadata == {"structured_content": {"k": "v"}}


@pytest.mark.asyncio
async def test_cached_tool_result_round_trips_as_tool_result_async(tmp_path):
    """Async variant: cached ToolResult round-trips through aexecute."""

    async def get_data() -> ToolResult:
        return ToolResult(content="hello", metadata={"structured_content": {"k": "v"}})

    func = Function(name="get_data", entrypoint=get_data, cache_results=True, cache_dir=str(tmp_path))

    first = await FunctionCall(function=func).aexecute()
    second = await FunctionCall(function=func).aexecute()

    assert isinstance(first.result, ToolResult)
    assert isinstance(second.result, ToolResult)
    assert second.result.content == "hello"
    assert second.result.metadata == {"structured_content": {"k": "v"}}


def test_tool_result_with_media_is_not_cached(tmp_path):
    """Media bytes do not survive a JSON round trip; a ToolResult carrying
    media is executed every time instead of being served media-stripped."""
    from agno.media import Image

    executions = []

    def get_image() -> ToolResult:
        executions.append(1)
        return ToolResult(content="image attached", images=[Image(content=b"\x89PNG raw")])

    func = Function(name="get_image", entrypoint=get_image, cache_results=True, cache_dir=str(tmp_path))

    FunctionCall(function=func).execute()
    second = FunctionCall(function=func).execute()

    assert len(executions) == 2
    assert isinstance(second.result, ToolResult)
    assert second.result.images[0].content == b"\x89PNG raw"


@pytest.mark.asyncio
async def test_tool_result_with_media_is_not_cached_async(tmp_path):
    """Async variant: media-bearing ToolResults are never served from cache."""
    from agno.media import Image

    executions = []

    async def get_image() -> ToolResult:
        executions.append(1)
        return ToolResult(content="image attached", images=[Image(content=b"\x89PNG raw")])

    func = Function(name="get_image", entrypoint=get_image, cache_results=True, cache_dir=str(tmp_path))

    await FunctionCall(function=func).aexecute()
    second = await FunctionCall(function=func).aexecute()

    assert len(executions) == 2
    assert isinstance(second.result, ToolResult)
    assert second.result.images[0].content == b"\x89PNG raw"


# =============================================================================
# Hooks on cache hit tests
# =============================================================================


def test_hooks_run_on_cache_hit(tmp_path):
    """tool_hooks and post_hook must run on a cache hit, with the cached
    result substituted for the entrypoint call, so audit hooks never miss a
    tool call."""
    events = []

    def audit_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
        events.append("tool_hook")
        return function_call(**arguments)

    def post_hook():
        events.append("post_hook")

    def compute(x: int) -> str:
        events.append("entrypoint")
        return f"value {x}"

    func = Function(
        name="compute",
        entrypoint=compute,
        cache_results=True,
        cache_dir=str(tmp_path),
        tool_hooks=[audit_hook],
        post_hook=post_hook,
    )

    first = FunctionCall(function=func, arguments={"x": 1}).execute()
    assert first.result == "value 1"
    assert events == ["tool_hook", "entrypoint", "post_hook"]

    events.clear()
    second = FunctionCall(function=func, arguments={"x": 1}).execute()
    assert second.result == "value 1"
    assert events == ["tool_hook", "post_hook"]


@pytest.mark.asyncio
async def test_hooks_run_on_cache_hit_async(tmp_path):
    """Async variant: hooks run on cache hits through aexecute."""
    events = []

    async def audit_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
        events.append("tool_hook")
        return await function_call(**arguments)

    async def post_hook():
        events.append("post_hook")

    async def compute(x: int) -> str:
        events.append("entrypoint")
        return f"value {x}"

    func = Function(
        name="compute",
        entrypoint=compute,
        cache_results=True,
        cache_dir=str(tmp_path),
        tool_hooks=[audit_hook],
        post_hook=post_hook,
    )

    first = await FunctionCall(function=func, arguments={"x": 1}).aexecute()
    assert first.result == "value 1"
    assert events == ["tool_hook", "entrypoint", "post_hook"]

    events.clear()
    second = await FunctionCall(function=func, arguments={"x": 1}).aexecute()
    assert second.result == "value 1"
    assert events == ["tool_hook", "post_hook"]


def test_result_transforming_hook_not_applied_twice_on_cache_hit(tmp_path):
    """The cache must store the raw entrypoint return, not the hook-chain
    output: hooks run again on a hit, so caching their output would apply a
    result-transforming hook twice."""
    executions = []

    def redacting_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
        return f"[audited] {function_call(**arguments)}"

    def compute(x: int) -> str:
        executions.append(x)
        return f"value {x}"

    func = Function(
        name="compute",
        entrypoint=compute,
        cache_results=True,
        cache_dir=str(tmp_path),
        tool_hooks=[redacting_hook],
    )

    first = FunctionCall(function=func, arguments={"x": 1}).execute()
    second = FunctionCall(function=func, arguments={"x": 1}).execute()

    assert first.result == "[audited] value 1"
    assert second.result == "[audited] value 1"
    assert executions == [1]


@pytest.mark.asyncio
async def test_result_transforming_hook_not_applied_twice_on_cache_hit_async(tmp_path):
    """Async variant: raw entrypoint return cached, hook applied once per call."""
    executions = []

    async def redacting_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
        return f"[audited] {await function_call(**arguments)}"

    async def compute(x: int) -> str:
        executions.append(x)
        return f"value {x}"

    func = Function(
        name="compute",
        entrypoint=compute,
        cache_results=True,
        cache_dir=str(tmp_path),
        tool_hooks=[redacting_hook],
    )

    first = await FunctionCall(function=func, arguments={"x": 1}).aexecute()
    second = await FunctionCall(function=func, arguments={"x": 1}).aexecute()

    assert first.result == "[audited] value 1"
    assert second.result == "[audited] value 1"
    assert executions == [1]


def test_cached_base_model_revalidates_against_return_annotation(tmp_path):
    """A cached BaseModel result is validated back into the entrypoint's
    declared return type on a hit, instead of coming back as a plain dict."""

    class Weather(BaseModel):
        city: str
        temp_c: int

    def get_weather(city: str) -> Weather:
        return Weather(city=city, temp_c=20)

    func = Function(name="get_weather", entrypoint=get_weather, cache_results=True, cache_dir=str(tmp_path))

    first = FunctionCall(function=func, arguments={"city": "Paris"}).execute()
    second = FunctionCall(function=func, arguments={"city": "Paris"}).execute()

    assert isinstance(first.result, Weather)
    assert isinstance(second.result, Weather)
    assert second.result == first.result


@pytest.mark.asyncio
async def test_cached_base_model_revalidates_against_return_annotation_async(tmp_path):
    """Async variant of the BaseModel cache round-trip."""

    class Weather(BaseModel):
        city: str
        temp_c: int

    async def get_weather(city: str) -> Weather:
        return Weather(city=city, temp_c=20)

    func = Function(name="get_weather", entrypoint=get_weather, cache_results=True, cache_dir=str(tmp_path))

    first = await FunctionCall(function=func, arguments={"city": "Paris"}).aexecute()
    second = await FunctionCall(function=func, arguments={"city": "Paris"}).aexecute()

    assert isinstance(first.result, Weather)
    assert isinstance(second.result, Weather)
    assert second.result == first.result
