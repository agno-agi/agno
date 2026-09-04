"""Regression tests for child_run_id linking on concurrent member delegations.

A single model turn can emit several ``delegate_task_to_member`` tool calls, which the
team then runs concurrently. Each tool execution recorded on the team run must keep the
run id of the member it delegated to, rather than the run id of whichever member
happened to finish last.
"""

import asyncio
from typing import List

import pytest

from agno.agent.agent import Agent
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunContext
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._default_tools import _get_delegate_task_function
from agno.team.team import Team


def _member(index: int, delay: float) -> Agent:
    """A member whose run takes ``delay`` seconds and returns a distinct run id."""
    member = Agent(name=f"Worker{index}", id=f"worker-{index}")

    async def fake_arun(*args, **kwargs):
        await asyncio.sleep(delay)
        return RunOutput(
            run_id=f"member-run-{index}",
            agent_id=f"worker-{index}",
            agent_name=f"Worker{index}",
            content=f"Response from Worker{index}",
        )

    member.arun = fake_arun  # type: ignore[method-assign]
    return member


def _delegation_tools(count: int) -> List[ToolExecution]:
    return [
        ToolExecution(
            tool_call_id=f"call_{index}",
            tool_name="delegate_task_to_member",
            tool_args={"member_id": f"worker-{index}", "task": f"task {index}"},
        )
        for index in range(1, count + 1)
    ]


async def _run_delegations(team: Team, run_response: TeamRunOutput) -> None:
    delegate_function = _get_delegate_task_function(
        team=team,
        run_response=run_response,
        run_context=RunContext(run_id="team-run-1", session_id="session-1", session_state={}),
        session=TeamSession(session_id="session-1", team_id="team-1"),
        team_run_context={},
        async_mode=True,
    )

    async def delegate(tool: ToolExecution) -> None:
        async for _ in delegate_function.entrypoint(**tool.tool_args):  # type: ignore[misc]
            pass

    await asyncio.gather(*(delegate(tool) for tool in run_response.tools or []))


@pytest.mark.asyncio
async def test_concurrent_delegations_keep_their_own_child_run_id():
    """The slowest member must not overwrite the child_run_id of the other delegations."""
    # Worker1 finishes last, so under the previous name-only match it won every entry.
    members = [_member(1, 0.05), _member(2, 0.0)]
    team = Team(name="Test Team", id="team-1", members=members)
    run_response = TeamRunOutput(
        run_id="team-run-1", team_id="team-1", session_id="session-1", tools=_delegation_tools(2)
    )

    await _run_delegations(team, run_response)

    assert [tool.child_run_id for tool in run_response.tools] == ["member-run-1", "member-run-2"]


@pytest.mark.asyncio
async def test_single_delegation_still_links_its_child_run_id():
    """The common case of one delegation per turn is unchanged."""
    team = Team(name="Test Team", id="team-1", members=[_member(1, 0.0)])
    run_response = TeamRunOutput(
        run_id="team-run-1", team_id="team-1", session_id="session-1", tools=_delegation_tools(1)
    )

    await _run_delegations(team, run_response)

    assert run_response.tools[0].child_run_id == "member-run-1"
