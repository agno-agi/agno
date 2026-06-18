from typing import Any

import pytest

from agno.agent import Agent
from agno.models.response import ToolExecution
from agno.run import RunContext, RunStatus
from agno.run.agent import RunOutput, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._task_tools import _get_task_management_tools
from agno.team.task import TaskList
from agno.team.team import Team


def _build_parallel_tool(*, async_mode: bool = False):
    member = Agent(name="Worker")
    task_list = TaskList()
    task = task_list.create_task(
        title="Use worker tool",
        description="Ask the worker to use its tool.",
        assignee="worker",
    )
    run_context = RunContext(run_id="team-run", session_id="session", session_state={})
    run_response = TeamRunOutput(run_id="team-run", session_id="session")
    team = Team(name="Parallel Team", members=[member], stream_member_events=True, telemetry=False)
    session = TeamSession(session_id="session")
    tool_execution = ToolExecution(tool_call_id="call-1", tool_name="worker_tool", tool_args={"x": 1})

    def _member_run_output(run_id: str | None) -> RunOutput:
        return RunOutput(
            run_id=run_id,
            agent_name="Worker",
            content="worker result",
            tools=[tool_execution],
            status=RunStatus.completed,
            messages=[],
        )

    def fake_run(input: Any, *, stream: bool = False, run_id: str | None = None, **kwargs: Any):
        if not stream:
            return _member_run_output(run_id)

        def _stream():
            yield ToolCallStartedEvent(run_id=run_id, agent_name="Worker", tool=tool_execution)
            yield ToolCallCompletedEvent(
                run_id=run_id,
                agent_name="Worker",
                tool=tool_execution,
                content="worker result",
            )
            yield _member_run_output(run_id)

        return _stream()

    def fake_arun(input: Any, *, stream: bool = False, run_id: str | None = None, **kwargs: Any):
        if not stream:

            async def _run_output():
                return _member_run_output(run_id)

            return _run_output()

        async def _stream():
            yield ToolCallStartedEvent(run_id=run_id, agent_name="Worker", tool=tool_execution)
            yield ToolCallCompletedEvent(
                run_id=run_id,
                agent_name="Worker",
                tool=tool_execution,
                content="worker result",
            )
            yield _member_run_output(run_id)

        return _stream()

    member.run = fake_run  # type: ignore[method-assign]
    member.arun = fake_arun  # type: ignore[method-assign]

    tools = _get_task_management_tools(
        team=team,
        task_list=task_list,
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        stream=True,
        stream_events=True,
        async_mode=async_mode,
    )
    execute_parallel = next(tool for tool in tools if tool.name == "execute_tasks_parallel")
    return execute_parallel, task


def _assert_member_tool_events_forwarded(events: list[Any]):
    started_events = [event for event in events if isinstance(event, ToolCallStartedEvent)]
    completed_events = [event for event in events if isinstance(event, ToolCallCompletedEvent)]

    assert started_events
    assert completed_events
    assert started_events[0].parent_run_id == "team-run"
    assert completed_events[0].parent_run_id == "team-run"


def test_execute_tasks_parallel_forwards_member_tool_events():
    execute_parallel, task = _build_parallel_tool()

    events = list(execute_parallel.entrypoint(task_ids=[task.id]))

    _assert_member_tool_events_forwarded(events)


@pytest.mark.asyncio
async def test_aexecute_tasks_parallel_forwards_member_tool_events():
    execute_parallel, task = _build_parallel_tool(async_mode=True)

    events = []
    async for event in execute_parallel.entrypoint(task_ids=[task.id]):
        events.append(event)

    _assert_member_tool_events_forwarded(events)
