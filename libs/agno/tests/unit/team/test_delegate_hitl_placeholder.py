from unittest.mock import AsyncMock, MagicMock

import pytest

from agno.agent import Agent
from agno.models.response import ToolExecution
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutput
from agno.run.requirement import RunRequirement
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._default_tools import _get_delegate_task_function
from agno.team.team import Team


def _paused_member_output() -> RunOutput:
    requirement = RunRequirement(
        ToolExecution(
            tool_name="external_tool",
            tool_call_id="external-call",
            external_execution_required=True,
        )
    )
    return RunOutput(
        run_id="member-run",
        status=RunStatus.paused,
        requirements=[requirement],
    )


def _delegation_context(member: Agent, *, async_mode: bool):
    team = Team(name="Router", members=[member], respond_directly=True)
    run_output = TeamRunOutput(
        run_id="team-run",
        session_id="session-1",
        tools=[
            ToolExecution(
                tool_name="delegate_task_to_member",
                tool_call_id="delegate-call",
            )
        ],
    )
    run_context = RunContext(run_id="team-run", session_id="session-1", session_state={})
    session = TeamSession(session_id="session-1")
    delegate = _get_delegate_task_function(
        team,
        run_output,
        run_context,
        session,
        {},
        async_mode=async_mode,
    )
    return delegate, run_output


def _assert_pause_linkage(run_output: TeamRunOutput) -> None:
    assert run_output.tools is not None
    assert run_output.tools[0].child_run_id == "member-run"
    assert run_output.requirements is not None
    assert run_output.requirements[0].member_run_id == "member-run"


def test_paused_member_delegate_does_not_yield_placeholder() -> None:
    member = Agent(id="worker", name="Worker")
    member.run = MagicMock(return_value=_paused_member_output())
    delegate, run_output = _delegation_context(member, async_mode=False)

    assert delegate.show_result is True
    assert list(delegate.entrypoint(member_id="worker", task="do it")) == []
    _assert_pause_linkage(run_output)


@pytest.mark.asyncio
async def test_paused_member_async_delegate_does_not_yield_placeholder() -> None:
    member = Agent(id="worker", name="Worker")
    member.arun = AsyncMock(return_value=_paused_member_output())
    delegate, run_output = _delegation_context(member, async_mode=True)

    assert delegate.show_result is True
    output = [item async for item in delegate.entrypoint(member_id="worker", task="do it")]
    assert output == []
    _assert_pause_linkage(run_output)
