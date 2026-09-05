"""Rejected user-input tools must not execute when a requirements payload answers them.

Fixes #9451. Case 4 of handle_tool_call_updates previously ran any
requires_user_input tool after filling answered fields, without consulting
_t.confirmed. An @approval(type="required") user-input tool that an admin
rejected still executed with the client's values.
"""

from typing import Any, AsyncIterator, Iterator, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agno.agent._tools import (
    ahandle_tool_call_updates,
    ahandle_tool_call_updates_stream,
    handle_tool_call_updates,
    handle_tool_call_updates_stream,
)
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.messages import RunMessages
from agno.tools.function import Function, UserInputField


def _agent() -> MagicMock:
    agent = MagicMock()
    agent.model = MagicMock()
    agent.db = None
    agent.id = "agent-1"
    agent.name = "test-agent"
    agent.events_to_skip = None
    agent.store_events = False
    return agent


def _tool(*, confirmed: Any = None) -> ToolExecution:
    return ToolExecution(
        tool_call_id="tc-wire-1",
        tool_name="submit_wire",
        tool_args={"amount": 1},
        requires_user_input=True,
        confirmed=confirmed,
        user_input_schema=[UserInputField(name="amount", field_type=int, value=999)],
    )


def _run(tool: ToolExecution) -> RunOutput:
    return RunOutput(run_id="run-1", session_id="sess-1", tools=[tool])


def _functions() -> List[Function]:
    return [Function(name="submit_wire", description="Submit a wire", entrypoint=lambda amount: f"sent {amount}")]


def _fake_run_tool(*_args, **_kwargs) -> Iterator[Any]:
    return iter(())


async def _fake_arun_tool(*_args, **_kwargs) -> AsyncIterator[Any]:
    if False:
        yield None


def test_rejected_user_input_tool_does_not_execute_sync():
    tool = _tool(confirmed=False)
    run_messages = RunMessages()
    with (
        patch("agno.agent._tools.run_tool", side_effect=_fake_run_tool) as run_tool,
        patch("agno.agent._tools.reject_tool_call") as reject,
        patch("agno.agent._tools._maybe_create_audit_approval") as audit,
    ):
        handle_tool_call_updates(_agent(), _run(tool), run_messages, _functions())

    run_tool.assert_not_called()
    reject.assert_called_once()
    audit.assert_called_once()
    assert audit.call_args.args[-1] == "rejected"
    assert tool.tool_call_error is True
    assert tool.confirmed is False
    assert tool.requires_user_input is False
    assert tool.answered is True
    assert tool.confirmation_note == "Tool call was rejected"
    # Reject must not bind the payload's answered fields onto the tool.
    assert tool.tool_args == {"amount": 1}


def test_confirmed_user_input_tool_still_executes_sync():
    tool = _tool(confirmed=True)
    run_messages = RunMessages()
    with (
        patch("agno.agent._tools.run_tool", side_effect=_fake_run_tool) as run_tool,
        patch("agno.agent._tools.reject_tool_call") as reject,
        patch("agno.agent._tools._maybe_create_audit_approval") as audit,
    ):
        handle_tool_call_updates(_agent(), _run(tool), run_messages, _functions())

    run_tool.assert_called_once()
    reject.assert_not_called()
    audit.assert_called_once()
    assert audit.call_args.args[-1] == "approved"
    assert tool.requires_user_input is False
    assert tool.answered is True
    assert tool.tool_args == {"amount": 999}


def test_unconfirmed_user_input_tool_still_executes_sync():
    """Plain user-input (no approval record, confirmed=None) is unchanged."""
    tool = _tool(confirmed=None)
    run_messages = RunMessages()
    with (
        patch("agno.agent._tools.run_tool", side_effect=_fake_run_tool) as run_tool,
        patch("agno.agent._tools.reject_tool_call") as reject,
        patch("agno.agent._tools._maybe_create_audit_approval") as audit,
    ):
        handle_tool_call_updates(_agent(), _run(tool), run_messages, _functions())

    run_tool.assert_called_once()
    reject.assert_not_called()
    audit.assert_called_once()
    assert audit.call_args.args[-1] == "approved"
    assert tool.tool_args == {"amount": 999}


def test_rejected_user_input_tool_does_not_execute_stream():
    tool = _tool(confirmed=False)
    run_messages = RunMessages()
    with (
        patch("agno.agent._tools.run_tool", side_effect=_fake_run_tool) as run_tool,
        patch("agno.agent._tools.reject_tool_call") as reject,
        patch("agno.agent._tools._maybe_create_audit_approval") as audit,
    ):
        list(handle_tool_call_updates_stream(_agent(), _run(tool), run_messages, _functions()))

    run_tool.assert_not_called()
    reject.assert_called_once()
    assert audit.call_args.args[-1] == "rejected"
    assert tool.tool_call_error is True
    assert tool.tool_args == {"amount": 1}


@pytest.mark.asyncio
async def test_rejected_user_input_tool_does_not_execute_async():
    tool = _tool(confirmed=False)
    run_messages = RunMessages()
    with (
        patch("agno.agent._tools.arun_tool", side_effect=_fake_arun_tool) as arun_tool,
        patch("agno.agent._tools.reject_tool_call") as reject,
        patch("agno.agent._tools._amaybe_create_audit_approval", new_callable=AsyncMock) as audit,
    ):
        await ahandle_tool_call_updates(_agent(), _run(tool), run_messages, _functions())

    arun_tool.assert_not_called()
    reject.assert_called_once()
    audit.assert_awaited_once()
    assert audit.await_args.args[-1] == "rejected"
    assert tool.tool_call_error is True
    assert tool.tool_args == {"amount": 1}


@pytest.mark.asyncio
async def test_rejected_user_input_tool_does_not_execute_async_stream():
    tool = _tool(confirmed=False)
    run_messages = RunMessages()
    with (
        patch("agno.agent._tools.arun_tool", side_effect=_fake_arun_tool) as arun_tool,
        patch("agno.agent._tools.reject_tool_call") as reject,
        patch("agno.agent._tools._amaybe_create_audit_approval", new_callable=AsyncMock) as audit,
    ):
        events = []
        async for event in ahandle_tool_call_updates_stream(_agent(), _run(tool), run_messages, _functions()):
            events.append(event)

    assert events == []
    arun_tool.assert_not_called()
    reject.assert_called_once()
    audit.assert_awaited_once()
    assert audit.await_args.args[-1] == "rejected"
    assert tool.tool_call_error is True
    assert tool.tool_args == {"amount": 1}


@pytest.mark.asyncio
async def test_confirmed_user_input_tool_still_executes_async():
    tool = _tool(confirmed=True)
    run_messages = RunMessages()
    with (
        patch("agno.agent._tools.arun_tool", side_effect=_fake_arun_tool) as arun_tool,
        patch("agno.agent._tools.reject_tool_call") as reject,
        patch("agno.agent._tools._amaybe_create_audit_approval", new_callable=AsyncMock) as audit,
    ):
        await ahandle_tool_call_updates(_agent(), _run(tool), run_messages, _functions())

    arun_tool.assert_called_once()
    reject.assert_not_called()
    assert audit.await_args.args[-1] == "approved"
    assert tool.tool_args == {"amount": 999}
