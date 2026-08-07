from types import SimpleNamespace

import pytest

from agno.agent import _tools
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.messages import RunMessages
from agno.tools.function import UserInputField


def _paused_member_tool(*, answered: bool | None = None, value=None) -> ToolExecution:
    return ToolExecution(
        tool_name="collect_info",
        requires_user_input=True,
        answered=answered,
        user_input_schema=[UserInputField(name="note", field_type=str, value=value)],
        tool_args={},
    )


def _run_context(tool: ToolExecution):
    return SimpleNamespace(model=None), RunOutput(tools=[tool]), RunMessages()


def test_member_user_input_stays_paused_until_answered(monkeypatch):
    tool = _paused_member_tool()
    agent, run_response, run_messages = _run_context(tool)
    monkeypatch.setattr(_tools, "run_tool", lambda *args, **kwargs: pytest.fail("unanswered tool was executed"))

    _tools.handle_tool_call_updates(agent, run_response, run_messages, tools=[])

    assert tool.requires_user_input is True
    assert tool.answered is None
    assert tool.tool_args == {}


def test_member_user_input_stream_stays_paused_until_answered(monkeypatch):
    tool = _paused_member_tool()
    agent, run_response, run_messages = _run_context(tool)
    monkeypatch.setattr(_tools, "run_tool", lambda *args, **kwargs: pytest.fail("unanswered tool was executed"))

    assert list(_tools.handle_tool_call_updates_stream(agent, run_response, run_messages, tools=[])) == []
    assert tool.requires_user_input is True


@pytest.mark.asyncio
async def test_async_member_user_input_stays_paused_until_answered(monkeypatch):
    tool = _paused_member_tool()
    agent, run_response, run_messages = _run_context(tool)
    monkeypatch.setattr(_tools, "arun_tool", lambda *args, **kwargs: pytest.fail("unanswered tool was executed"))

    await _tools.ahandle_tool_call_updates(agent, run_response, run_messages, tools=[])

    assert tool.requires_user_input is True


@pytest.mark.asyncio
async def test_async_member_user_input_stream_stays_paused_until_answered(monkeypatch):
    tool = _paused_member_tool()
    agent, run_response, run_messages = _run_context(tool)
    monkeypatch.setattr(_tools, "arun_tool", lambda *args, **kwargs: pytest.fail("unanswered tool was executed"))

    events = []
    async for event in _tools.ahandle_tool_call_updates_stream(agent, run_response, run_messages, tools=[]):
        events.append(event)

    assert events == []
    assert tool.requires_user_input is True


def test_member_user_input_executes_after_complete_answer(monkeypatch):
    tool = _paused_member_tool(answered=True, value="provided")
    agent, run_response, run_messages = _run_context(tool)
    executed: list[bool] = []

    def fake_run_tool(*args, **kwargs):
        executed.append(True)
        return iter(())

    monkeypatch.setattr(_tools, "run_tool", fake_run_tool)

    _tools.handle_tool_call_updates(agent, run_response, run_messages, tools=[])

    assert executed == [True]
    assert tool.requires_user_input is False
    assert tool.tool_args == {"note": "provided"}
