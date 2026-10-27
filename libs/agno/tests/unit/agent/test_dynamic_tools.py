"""Integration tests for tools added while an Agent run is active."""

import asyncio
import copy
import json
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

import pytest

from agno.agent import Agent
from agno.models.base import Model
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.tools.function import Function
from agno.tools.toolkit import Toolkit

ResponseStep = Union[ModelResponse, Callable[[Sequence[Message]], ModelResponse]]


class ScriptedModel(Model):
    """Provider-free model that records schemas and returns scripted replies."""

    def __init__(self) -> None:
        super().__init__(id="scripted-test-model")
        self.scripts: Dict[str, List[ResponseStep]] = {}
        self.call_counts: Dict[str, int] = defaultdict(int)
        self.provider_schemas: Dict[str, List[List[Dict[str, Any]]]] = defaultdict(list)

    def set_script(self, prompt: str, replies: List[ResponseStep]) -> None:
        self.scripts[prompt] = replies

    def _reply(self, messages: Sequence[Message], tools: Optional[List[Dict[str, Any]]]) -> ModelResponse:
        prompt = next(
            (
                message.content
                for message in messages
                if message.role == "user" and isinstance(message.content, str) and message.content.startswith("case:")
            ),
            None,
        )
        if prompt is None:
            raise AssertionError("scripted model did not receive the original case prompt")

        self.provider_schemas[prompt].append(copy.deepcopy(tools or []))
        call_index = self.call_counts[prompt]
        self.call_counts[prompt] += 1
        if prompt not in self.scripts or call_index >= len(self.scripts[prompt]):
            raise AssertionError(f"unexpected provider request {call_index + 1} for {prompt}")

        reply = self.scripts[prompt][call_index]
        if callable(reply):
            return reply(messages)
        return copy.deepcopy(reply)

    def invoke(self, messages: Sequence[Message], tools: Optional[List[Dict[str, Any]]] = None, **kwargs: Any):
        return self._reply(messages, tools)

    async def ainvoke(self, messages: Sequence[Message], tools: Optional[List[Dict[str, Any]]] = None, **kwargs: Any):
        return self._reply(messages, tools)

    def invoke_stream(self, messages: Sequence[Message], tools: Optional[List[Dict[str, Any]]] = None, **kwargs: Any):
        yield self._reply(messages, tools)

    async def ainvoke_stream(
        self, messages: Sequence[Message], tools: Optional[List[Dict[str, Any]]] = None, **kwargs: Any
    ):
        yield self._reply(messages, tools)

    def _parse_provider_response(self, response: Any, **kwargs: Any) -> ModelResponse:
        return response

    def _parse_provider_response_delta(self, response: Any) -> ModelResponse:
        return response


def _tool_call(name: str, arguments: Optional[Dict[str, Any]] = None) -> ModelResponse:
    call = {
        "id": f"call-{name}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments or {})},
    }
    return ModelResponse(tool_calls=[call])


def _finish_from_tool_result(messages: Sequence[Message]) -> ModelResponse:
    tool_results = [message.content for message in messages if message.role == "tool"]
    return ModelResponse(content=f"seen:{tool_results[-1] if tool_results else 'missing'}")


def _schema_names(model: ScriptedModel, prompt: str, request_index: int) -> List[str]:
    return [
        tool["function"]["name"]
        for tool in model.provider_schemas[prompt][request_index]
        if tool.get("type") == "function"
    ]


def _assert_callable_schema(model: ScriptedModel, prompt: str, request_index: int, name: str) -> None:
    schemas = model.provider_schemas[prompt][request_index]
    matches = [tool["function"] for tool in schemas if tool.get("function", {}).get("name") == name]
    assert len(matches) == 1
    assert matches[0]["parameters"]["properties"]["label"]["type"] == "string"


def _callable_tool(name: str, results: Optional[List[str]] = None, prefix: str = "") -> Callable[..., str]:
    def dynamic_tool(label: str, run_context: RunContext) -> str:
        if results is not None:
            results.append(f"{prefix}{run_context.session_id}:{label}")
        return f"{prefix}{run_context.session_id}:{label}"

    dynamic_tool.__name__ = name
    dynamic_tool.__doc__ = "Return the current run session and label."
    return dynamic_tool


def _make_loader(agent: Agent, tool: Union[Callable[..., Any], Function, Toolkit]) -> Callable[..., str]:
    def load_dynamic_tool(run_context: RunContext) -> str:
        agent.add_tool(tool)
        return f"loaded:{run_context.session_id}"

    return load_dynamic_tool


def _agent_with_loader(
    model: ScriptedModel,
    name: str,
    tool: Union[Callable[..., Any], Function, Toolkit],
    tool_hooks: Optional[List[Callable]] = None,
) -> Agent:
    agent = Agent(name=name, model=model, tools=[], tool_hooks=tool_hooks, telemetry=False)
    agent.set_tools([_make_loader(agent, tool)])
    return agent


def _tool_hook(hook_calls: List[str]) -> Callable[..., Any]:
    def record_dynamic_tool(function_name: str, func: Callable[..., Any], args: Dict[str, Any]) -> Any:
        if function_name.startswith("dynamic_"):
            hook_calls.append(function_name)
        return func(**args)

    return record_dynamic_tool


def _async_tool_hook(hook_calls: List[str]) -> Callable[..., Any]:
    async def record_dynamic_tool(function_name: str, func: Callable[..., Any], args: Dict[str, Any]) -> Any:
        if function_name.startswith("dynamic_"):
            hook_calls.append(function_name)
        return await func(**args)

    return record_dynamic_tool


def _run_sync(agent: Agent, prompt: str, session_id: str, stream: bool = False) -> RunOutput:
    result = agent.run(
        input=prompt,
        session_id=session_id,
        stream=stream,
        stream_events=False,
        yield_run_output=stream,
    )
    if isinstance(result, RunOutput):
        return result
    return next(item for item in result if isinstance(item, RunOutput))


async def _run_async(agent: Agent, prompt: str, session_id: str, stream: bool = False) -> RunOutput:
    result = agent.arun(
        input=prompt,
        session_id=session_id,
        stream=stream,
        stream_events=False,
        yield_run_output=stream,
    )
    if not stream:
        return await result
    async for item in result:
        if isinstance(item, RunOutput):
            return item
    raise AssertionError("stream did not yield a RunOutput")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mode", "stream"),
    [("sync", False), ("sync", True), ("async", False), ("async", True)],
    ids=["run", "run-stream", "arun", "arun-stream"],
)
async def test_added_callable_is_callable_in_same_agent_run(mode: str, stream: bool) -> None:
    model = ScriptedModel()
    prompt = "case:dynamic-loop"
    session_id = f"session-{mode}-{stream}"
    hook_calls: List[str] = []
    agent = _agent_with_loader(model, "dynamic-tool-agent", _callable_tool("dynamic_echo"), [_tool_hook(hook_calls)])
    model.set_script(
        prompt,
        [_tool_call("load_dynamic_tool"), _tool_call("dynamic_echo", {"label": "ok"}), _finish_from_tool_result],
    )

    output = (
        _run_sync(agent, prompt, session_id, stream=stream)
        if mode == "sync"
        else await _run_async(agent, prompt, session_id, stream=stream)
    )

    expected = f"{session_id}:ok"
    assert output.content == f"seen:{expected}"
    assert hook_calls == ["dynamic_echo"]
    assert "dynamic_echo" not in _schema_names(model, prompt, 0)
    assert "dynamic_echo" in _schema_names(model, prompt, 1)
    _assert_callable_schema(model, prompt, 1, "dynamic_echo")


@pytest.mark.asyncio
async def test_added_tool_configuration_is_available_on_later_runs() -> None:
    model = ScriptedModel()
    first_prompt = "case:persistent-first"
    next_prompt = "case:persistent-next"
    dynamic_tool = _callable_tool("dynamic_persistent")
    agent = _agent_with_loader(model, "persistent-tool-agent", dynamic_tool)
    model.set_script(
        first_prompt,
        [
            _tool_call("load_dynamic_tool"),
            _tool_call("dynamic_persistent", {"label": "first"}),
            _finish_from_tool_result,
        ],
    )
    model.set_script(next_prompt, [_tool_call("dynamic_persistent", {"label": "later"}), _finish_from_tool_result])

    first = _run_sync(agent, first_prompt, "persistent-first")
    later = await _run_async(agent, next_prompt, "persistent-later")

    assert first.content == "seen:persistent-first:first"
    assert later.content == "seen:persistent-later:later"
    assert "dynamic_persistent" in _schema_names(model, next_prompt, 0)
    _assert_callable_schema(model, next_prompt, 0, "dynamic_persistent")


@pytest.mark.asyncio
async def test_async_dynamic_toolkit_uses_async_implementation_and_agent_hooks() -> None:
    model = ScriptedModel()
    prompt = "case:async-toolkit"
    hook_calls: List[str] = []

    def sync_dynamic_echo(label: str, run_context: RunContext) -> str:
        return f"sync:{run_context.session_id}:{label}"

    async def async_dynamic_echo(label: str, run_context: RunContext) -> str:
        return f"async:{run_context.session_id}:{label}"

    sync_dynamic_echo.__name__ = "dynamic_echo"
    toolkit = Toolkit(
        name="dynamic-toolkit",
        tools=[sync_dynamic_echo],
        async_tools=[(async_dynamic_echo, "dynamic_echo")],
    )
    agent = _agent_with_loader(model, "async-toolkit-agent", toolkit, [_async_tool_hook(hook_calls)])
    model.set_script(
        prompt,
        [_tool_call("load_dynamic_tool"), _tool_call("dynamic_echo", {"label": "ok"}), _finish_from_tool_result],
    )

    output = await _run_async(agent, prompt, "async-session")

    assert output.content == "seen:async:async-session:ok"
    assert hook_calls == ["dynamic_echo"]
    assert "dynamic_echo" in _schema_names(model, prompt, 1)
    _assert_callable_schema(model, prompt, 1, "dynamic_echo")


@pytest.mark.asyncio
async def test_dynamic_add_tool_isolated_between_interleaved_runs_on_same_agent() -> None:
    model = ScriptedModel()
    both_loaders_waiting = asyncio.Event()
    loader_sessions: List[str] = []
    agent = Agent(name="interleaved-tool-agent", model=model, tools=[], telemetry=False)

    async def load_session_tool(run_context: RunContext) -> str:
        loader_sessions.append(run_context.session_id)
        if len(loader_sessions) == 2:
            both_loaders_waiting.set()
        await both_loaders_waiting.wait()
        name = f"dynamic_{run_context.session_id}"
        agent.add_tool(_callable_tool(name))
        return f"loaded:{run_context.session_id}"

    agent.set_tools([load_session_tool])
    for session_id in ("alpha", "beta"):
        prompt = f"case:interleaved-{session_id}"
        model.set_script(
            prompt,
            [
                _tool_call("load_session_tool"),
                _tool_call(f"dynamic_{session_id}", {"label": "ok"}),
                _finish_from_tool_result,
            ],
        )

    alpha, beta = await asyncio.gather(
        _run_async(agent, "case:interleaved-alpha", "alpha"),
        _run_async(agent, "case:interleaved-beta", "beta"),
    )

    assert alpha.content == "seen:alpha:ok"
    assert beta.content == "seen:beta:ok"
    for session_id in ("alpha", "beta"):
        prompt = f"case:interleaved-{session_id}"
        names = _schema_names(model, prompt, 1)
        assert f"dynamic_{session_id}" in names
        other = "beta" if session_id == "alpha" else "alpha"
        assert f"dynamic_{other}" not in names
        _assert_callable_schema(model, prompt, 1, f"dynamic_{session_id}")


@pytest.mark.asyncio
async def test_added_function_with_duplicate_name_does_not_replace_initial_callable() -> None:
    model = ScriptedModel()
    prompt = "case:duplicate-name"
    original_results: List[str] = []
    replacement_results: List[str] = []

    duplicate_action = _callable_tool("duplicate_action", original_results, "original:")
    replacement_action = _callable_tool("duplicate_action", replacement_results, "replacement:")
    replacement = Function(name="duplicate_action", entrypoint=replacement_action)
    agent = Agent(name="duplicate-tool-agent", model=model, tools=[duplicate_action], telemetry=False)
    agent.add_tool(_make_loader(agent, replacement))
    model.set_script(
        prompt,
        [_tool_call("load_dynamic_tool"), _tool_call("duplicate_action", {"label": "ok"}), _finish_from_tool_result],
    )

    output = await _run_async(agent, prompt, "duplicate-session")

    assert output.content == "seen:original:duplicate-session:ok"
    assert original_results == ["original:duplicate-session:ok"]
    assert replacement_results == []
    assert _schema_names(model, prompt, 1).count("duplicate_action") == 1


@pytest.mark.asyncio
async def test_confirmed_dynamic_function_can_continue_run() -> None:
    model = ScriptedModel()
    prompt = "case:confirmed-dynamic-tool"
    executed: List[str] = []

    function = Function(
        name="confirm_dynamic", entrypoint=_callable_tool("confirm_dynamic", executed), requires_confirmation=True
    )
    agent = _agent_with_loader(model, "confirmed-tool-agent", function)
    model.set_script(
        prompt,
        [_tool_call("load_dynamic_tool"), _tool_call("confirm_dynamic", {"label": "yes"}), _finish_from_tool_result],
    )

    paused = _run_sync(agent, prompt, "confirmed-session")

    assert paused.requirements
    requirement = paused.requirements[0]
    assert requirement.needs_confirmation
    requirement.confirm()
    completed = agent.continue_run(run_response=paused, requirements=[requirement])

    assert isinstance(completed, RunOutput)
    assert completed.content == "seen:confirmed-session:yes"
    assert executed == ["confirmed-session:yes"]
    assert "confirm_dynamic" in _schema_names(model, prompt, 1)
    assert "confirm_dynamic" in _schema_names(model, prompt, 2)
    _assert_callable_schema(model, prompt, 1, "confirm_dynamic")
