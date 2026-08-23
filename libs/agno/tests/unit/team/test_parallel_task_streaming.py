import pytest

from agno.agent.agent import Agent
from agno.models.response import ToolExecution
from agno.run import RunContext
from agno.run.agent import RunOutput, ToolCallCompletedEvent, ToolCallStartedEvent
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._task_tools import _get_task_management_tools
from agno.team.task import TaskList
from agno.team.team import Team


def test_execute_tasks_parallel_forwards_member_tool_events() -> None:
    worker = Agent(id="worker", name="Worker")
    team = Team(name="Test Team", members=[worker], stream_member_events=True)
    task_list = TaskList()
    task = task_list.create_task("check weather", assignee="worker")
    run_response = TeamRunOutput(run_id="team-run", session_id="session")
    run_context = RunContext(run_id="team-run", session_id="session", session_state={})
    session = TeamSession(session_id="session")

    def fake_run(**kwargs):
        assert kwargs["stream"] is True
        assert kwargs["stream_events"] is True
        yield ToolCallStartedEvent(tool=ToolExecution(tool_name="get_weather"))
        yield ToolCallCompletedEvent(tool=ToolExecution(tool_name="get_weather"), content="sunny")
        yield RunOutput(run_id=kwargs["run_id"], session_id="session", content="sunny")

    worker.run = fake_run  # type: ignore[method-assign]

    tools = _get_task_management_tools(
        team=team,
        task_list=task_list,
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        stream=True,
        stream_events=True,
    )
    execute_tasks_parallel = next(tool for tool in tools if tool.name == "execute_tasks_parallel")

    events = list(execute_tasks_parallel.entrypoint(task_ids=[task.id]))  # type: ignore[misc]

    assert any(isinstance(event, ToolCallStartedEvent) for event in events)
    assert any(isinstance(event, ToolCallCompletedEvent) for event in events)
    assert task.result == "sunny"


@pytest.mark.asyncio
async def test_aexecute_tasks_parallel_forwards_member_tool_events() -> None:
    worker = Agent(id="worker", name="Worker")
    team = Team(name="Test Team", members=[worker], stream_member_events=True)
    task_list = TaskList()
    task = task_list.create_task("check weather", assignee="worker")
    run_response = TeamRunOutput(run_id="team-run", session_id="session")
    run_context = RunContext(run_id="team-run", session_id="session", session_state={})
    session = TeamSession(session_id="session")

    async def fake_arun(**kwargs):
        assert kwargs["stream"] is True
        assert kwargs["stream_events"] is True
        yield ToolCallStartedEvent(tool=ToolExecution(tool_name="get_weather"))
        yield ToolCallCompletedEvent(tool=ToolExecution(tool_name="get_weather"), content="sunny")
        yield RunOutput(run_id=kwargs["run_id"], session_id="session", content="sunny")

    worker.arun = fake_arun  # type: ignore[method-assign]

    tools = _get_task_management_tools(
        team=team,
        task_list=task_list,
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        stream=True,
        stream_events=True,
        async_mode=True,
    )
    execute_tasks_parallel = next(tool for tool in tools if tool.name == "execute_tasks_parallel")

    events = []
    async for event in execute_tasks_parallel.entrypoint(task_ids=[task.id]):  # type: ignore[misc]
        events.append(event)

    assert any(isinstance(event, ToolCallStartedEvent) for event in events)
    assert any(isinstance(event, ToolCallCompletedEvent) for event in events)
    assert task.result == "sunny"
