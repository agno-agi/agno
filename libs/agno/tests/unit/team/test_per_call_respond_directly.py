"""Unit tests for per-call respond_directly on delegate_task_to_member."""

from unittest.mock import MagicMock

import pytest

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from agno.run import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._messages import _get_mode_instructions
from agno.team.mode import TeamMode
from agno.team.team import Team
from agno.tools.function import Function, FunctionCall


def _delegate_function(team: Team) -> Function:
    return team._get_delegate_task_function(
        session=TeamSession(session_id="test-session"),
        run_response=TeamRunOutput(content="ok"),
        run_context=RunContext(session_state={}, run_id="test-run", session_id="test-session"),
        team_run_context={},
    )


def test_function_call_effective_overrides_default_to_function():
    func = Function(name="demo", show_result=False, stop_after_tool_call=False)
    fc = FunctionCall(function=func)

    assert fc.effective_show_result() is False
    assert fc.effective_stop_after_tool_call() is False


def test_function_call_effective_overrides_take_precedence():
    func = Function(name="demo", show_result=False, stop_after_tool_call=False)
    fc = FunctionCall(
        function=func,
        override_show_result=True,
        override_stop_after_tool_call=True,
    )

    assert fc.effective_show_result() is True
    assert fc.effective_stop_after_tool_call() is True
    # Shared Function flags remain unchanged
    assert func.show_result is False
    assert func.stop_after_tool_call is False


def test_create_function_call_result_uses_override():
    model = OpenAIChat(id="gpt-4o")
    func = Function(name="demo", show_result=False, stop_after_tool_call=False)
    fc = FunctionCall(
        function=func,
        call_id="call-1",
        override_stop_after_tool_call=True,
    )

    message = model.create_function_call_result(fc, success=True, output="member output")

    assert message.stop_after_tool_call is True
    assert message.content == "member output"


def test_delegate_schema_includes_respond_directly():
    member = Agent(name="Writer", model=OpenAIChat(id="gpt-4o"), role="Write content")
    team = Team(name="Content Team", model=OpenAIChat(id="gpt-4o"), members=[member], mode=TeamMode.coordinate)

    delegate_func = _delegate_function(team)

    assert "respond_directly" in delegate_func.parameters["properties"]
    assert "respond_directly" not in delegate_func.parameters.get("required", [])
    assert delegate_func.pre_hook is not None
    # Coordinate mode keeps Function-level flags off by default
    assert delegate_func.stop_after_tool_call is False
    assert delegate_func.show_result is False


def test_pre_hook_sets_overrides_when_respond_directly_true():
    member = Agent(name="Writer", model=OpenAIChat(id="gpt-4o"), role="Write content")
    team = Team(name="Content Team", model=OpenAIChat(id="gpt-4o"), members=[member], mode=TeamMode.coordinate)
    delegate_func = _delegate_function(team)

    fc = FunctionCall(
        function=delegate_func,
        arguments={"member_id": "writer", "task": "Write the article", "respond_directly": True},
    )
    assert delegate_func.pre_hook is not None
    delegate_func.pre_hook(fc)

    assert fc.override_show_result is True
    assert fc.override_stop_after_tool_call is True
    assert fc.effective_show_result() is True
    assert fc.effective_stop_after_tool_call() is True
    assert delegate_func.stop_after_tool_call is False
    assert delegate_func.show_result is False


def test_pre_hook_noop_when_respond_directly_false():
    member = Agent(name="Writer", model=OpenAIChat(id="gpt-4o"), role="Write content")
    team = Team(name="Content Team", model=OpenAIChat(id="gpt-4o"), members=[member], mode=TeamMode.coordinate)
    delegate_func = _delegate_function(team)

    fc = FunctionCall(
        function=delegate_func,
        arguments={"member_id": "writer", "task": "Research first", "respond_directly": False},
    )
    assert delegate_func.pre_hook is not None
    delegate_func.pre_hook(fc)

    assert fc.override_show_result is None
    assert fc.override_stop_after_tool_call is None
    assert fc.effective_show_result() is False
    assert fc.effective_stop_after_tool_call() is False


def test_route_mode_still_sets_function_level_flags():
    member = Agent(name="Writer", model=OpenAIChat(id="gpt-4o"), role="Write content")
    team = Team(name="Router", model=OpenAIChat(id="gpt-4o"), members=[member], mode=TeamMode.route)

    delegate_func = _delegate_function(team)

    assert delegate_func.stop_after_tool_call is True
    assert delegate_func.show_result is True


def test_coordinate_instructions_mention_respond_directly():
    team = Team(name="test", members=[], mode=TeamMode.coordinate)
    instructions = _get_mode_instructions(team)

    assert "respond_directly=True" in instructions
    assert "respond_directly=False" in instructions
    assert "final deliverable" in instructions


def test_run_function_call_honors_per_call_overrides():
    """show_result + stop_after_tool_call overrides apply during run_function_call."""
    from agno.models.response import ModelResponseEvent

    model = OpenAIChat(id="gpt-4o")

    def fake_delegate(member_id: str, task: str, respond_directly: bool = False):
        yield "Hello from member"

    func = Function.from_callable(fake_delegate, name="delegate_task_to_member")

    def _apply_overrides(fc: FunctionCall) -> None:
        if (fc.arguments or {}).get("respond_directly"):
            fc.override_show_result = True
            fc.override_stop_after_tool_call = True

    func.pre_hook = _apply_overrides

    fc = FunctionCall(
        function=func,
        call_id="call-1",
        arguments={"member_id": "writer", "task": "Write it", "respond_directly": True},
    )
    results: list = []
    events = list(model.run_function_call(fc, function_call_results=results))

    # show_result yields ModelResponse(content=...)
    assert any(getattr(e, "content", None) == "Hello from member" for e in events)

    completed = [e for e in events if getattr(e, "event", None) == ModelResponseEvent.tool_call_completed.value]
    assert len(completed) == 1
    assert completed[0].tool_executions is not None
    assert completed[0].tool_executions[0].stop_after_tool_call is True

    assert len(results) == 1
    assert results[0].stop_after_tool_call is True
    assert results[0].content == "Hello from member"

    # Function-level flags still False — override is per-call only
    assert func.show_result is False
    assert func.stop_after_tool_call is False


@pytest.mark.asyncio
async def test_arun_function_call_honors_per_call_overrides():
    """Async path also honors per-call show_result / stop_after overrides."""
    from agno.models.response import ModelResponseEvent

    model = OpenAIChat(id="gpt-4o")

    async def fake_delegate(member_id: str, task: str, respond_directly: bool = False):
        yield "Hello from member async"

    func = Function.from_callable(fake_delegate, name="delegate_task_to_member")

    def _apply_overrides(fc: FunctionCall) -> None:
        if (fc.arguments or {}).get("respond_directly"):
            fc.override_show_result = True
            fc.override_stop_after_tool_call = True

    func.pre_hook = _apply_overrides

    fc = FunctionCall(
        function=func,
        call_id="call-async-1",
        arguments={"member_id": "writer", "task": "Write it", "respond_directly": True},
    )
    results: list = []
    events = []
    async for event in model.arun_function_calls([fc], function_call_results=results):
        events.append(event)

    assert any(getattr(e, "content", None) == "Hello from member async" for e in events)

    completed = [e for e in events if getattr(e, "event", None) == ModelResponseEvent.tool_call_completed.value]
    assert len(completed) == 1
    assert completed[0].tool_executions is not None
    assert completed[0].tool_executions[0].stop_after_tool_call is True
    assert len(results) == 1
    assert results[0].stop_after_tool_call is True


def test_broadcast_has_no_respond_directly_param():
    member = Agent(name="Writer", model=OpenAIChat(id="gpt-4o"), role="Write content")
    team = Team(name="Broadcast", model=OpenAIChat(id="gpt-4o"), members=[member], mode=TeamMode.broadcast)

    model = MagicMock()
    model.supports_native_structured_outputs = False
    tools = team._determine_tools_for_model(
        model=model,
        run_response=TeamRunOutput(content="ok"),
        run_context=RunContext(session_state={}, run_id="run-id", session_id="session-id"),
        team_run_context={},
        session=TeamSession(session_id="session-id"),
        input_message="hi",
        check_mcp_tools=False,
    )

    delegate = next(t for t in tools if getattr(t, "name", None) == "delegate_task_to_members")
    assert "respond_directly" not in (delegate.parameters or {}).get("properties", {})
