from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Union, cast
from unittest.mock import MagicMock

import pytest

import agno.team._default_tools as default_tools
import agno.team._task_tools as task_tools
from agno.agent import Agent
from agno.run import RunContext
from agno.run.agent import RunCompletedEvent, RunOutput
from agno.run.team import TeamRunOutput
from agno.session import TeamSession
from agno.team._member_execution import run_member_sync, stream_member_sync
from agno.team.mode import TeamMode
from agno.team.task import TaskList, TaskStatus
from agno.team.team import Team
from agno.tools.function import Function


class MCPTools:
    initialized = True


@dataclass
class MockedMember:
    member: Agent
    run_mock: MagicMock
    arun_mock: MagicMock


@dataclass
class MockedSubteam:
    team: Team
    run_mock: MagicMock
    arun_mock: MagicMock


def _make_team(
    member: Union[Agent, Team],
    *,
    mode: TeamMode = TeamMode.coordinate,
    delegate_to_all_members: bool = False,
) -> Team:
    team = Team(name="Leader", members=[member], mode=mode, delegate_to_all_members=delegate_to_all_members)
    team.delegate_to_all_members = delegate_to_all_members
    return team


def _make_member(*, with_mcp: bool, content: str, session_key: str = "path") -> MockedMember:
    member = Agent(
        name="Worker",
        id="worker",
        tools=[cast(Any, MCPTools())] if with_mcp else [],
    )
    run_mock = MagicMock(side_effect=RuntimeError("sync run path should not be used for this test"))

    def fake_arun(
        *args: Any,
        session_state: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ):
        async def fake_stream():
            if session_state is not None:
                session_state[session_key] = content
            yield RunCompletedEvent(
                agent_id=member.id,
                agent_name=member.name,
                run_id=run_id,
                content=content,
                session_state=session_state,
            )
            yield RunOutput(
                run_id=run_id,
                agent_id=member.id,
                agent_name=member.name,
                content=content,
            )

        async def fake_result():
            if session_state is not None:
                session_state[session_key] = content
            return RunOutput(
                run_id=run_id,
                agent_id=member.id,
                agent_name=member.name,
                content=content,
            )

        if stream:
            return fake_stream()
        return fake_result()

    arun_mock = MagicMock(side_effect=fake_arun)
    cast(Any, member).run = run_mock
    cast(Any, member).arun = arun_mock
    return MockedMember(member=member, run_mock=run_mock, arun_mock=arun_mock)


def _make_subteam(*, with_mcp_member: bool, content: str, session_key: str = "subteam") -> MockedSubteam:
    nested_member = _make_member(with_mcp=with_mcp_member, content=content, session_key=session_key).member
    subteam = Team(name="Subteam", id="subteam", members=[nested_member])
    run_mock = MagicMock(side_effect=RuntimeError("sync run path should not be used for this test"))

    def fake_arun(
        *args: Any,
        session_state: dict[str, Any] | None = None,
        run_id: str | None = None,
        stream: bool = False,
        **kwargs: Any,
    ):
        async def fake_stream():
            if session_state is not None:
                session_state[session_key] = content
            yield RunCompletedEvent(
                agent_id=subteam.id,
                agent_name=subteam.name,
                run_id=run_id,
                content=content,
                session_state=session_state,
            )
            yield TeamRunOutput(
                run_id=run_id,
                team_id=subteam.id,
                team_name=subteam.name,
                content=content,
            )

        async def fake_result():
            if session_state is not None:
                session_state[session_key] = content
            return TeamRunOutput(
                run_id=run_id,
                team_id=subteam.id,
                team_name=subteam.name,
                content=content,
            )

        if stream:
            return fake_stream()
        return fake_result()

    arun_mock = MagicMock(side_effect=fake_arun)
    cast(Any, subteam).run = run_mock
    cast(Any, subteam).arun = arun_mock
    return MockedSubteam(team=subteam, run_mock=run_mock, arun_mock=arun_mock)


def _make_team_context() -> tuple[TeamRunOutput, RunContext, TeamSession]:
    return (
        TeamRunOutput(run_id="team-run", session_id="team-session", content="leader"),
        RunContext(run_id="team-run", session_id="team-session", session_state={}),
        TeamSession(session_id="team-session"),
    )


def _get_tool(functions: List[Function], name: str) -> Function:
    return next(function for function in functions if function.name == name)


def _call_tool(function: Function, **kwargs: Any) -> list[Any]:
    assert function.entrypoint is not None
    entrypoint = cast(Any, function.entrypoint)
    return list(entrypoint(**kwargs))


def _make_stream_items(member: Agent, content: str, run_id: str) -> list[Any]:
    return [
        RunCompletedEvent(
            agent_id=member.id,
            agent_name=member.name,
            run_id=run_id,
            content=content,
        ),
        RunOutput(
            run_id=run_id,
            agent_id=member.id,
            agent_name=member.name,
            content=content,
        ),
    ]


async def _collect(async_iterator: Any) -> list[Any]:
    results = []
    async for item in async_iterator:
        results.append(item)
    return results


async def _acall_tool(function: Function, **kwargs: Any) -> list[Any]:
    assert function.entrypoint is not None
    entrypoint = cast(Any, function.entrypoint)
    return await _collect(entrypoint(**kwargs))


@pytest.mark.asyncio
async def test_run_member_sync_uses_active_loop_safe_arun_bridge_for_mcp_agents():
    mocked_member = _make_member(with_mcp=True, content="via arun", session_key="helper")
    member = mocked_member.member

    result = run_member_sync(
        member,
        input="delegate",
        user_id="user-1",
        session_id="team-session",
        session_state={},
        run_id="member-run",
    )

    assert result.content == "via arun"
    assert result.run_id == "member-run"
    mocked_member.run_mock.assert_not_called()
    mocked_member.arun_mock.assert_called_once()


def test_stream_member_sync_uses_threaded_arun_bridge_for_mcp_agents():
    mocked_member = _make_member(with_mcp=True, content="via stream arun", session_key="helper_stream")
    member = mocked_member.member

    results = list(
        stream_member_sync(
            member,
            input="delegate",
            user_id="user-1",
            session_id="team-session",
            session_state={},
            stream=True,
            stream_events=True,
            run_id="member-run",
            yield_run_output=True,
        )
    )

    assert len(results) == 2
    assert isinstance(results[0], RunCompletedEvent)
    assert isinstance(results[1], RunOutput)
    assert results[1].content == "via stream arun"
    mocked_member.run_mock.assert_not_called()
    mocked_member.arun_mock.assert_called_once()


def test_run_member_sync_uses_arun_for_subteams_with_mcp_members():
    mocked_subteam = _make_subteam(with_mcp_member=True, content="subteam via arun", session_key="subteam_helper")

    result = run_member_sync(
        mocked_subteam.team,
        input="delegate",
        user_id="user-1",
        session_id="team-session",
        session_state={},
        run_id="member-run",
    )

    assert result.content == "subteam via arun"
    assert result.run_id == "member-run"
    mocked_subteam.run_mock.assert_not_called()
    mocked_subteam.arun_mock.assert_called_once()


def test_run_member_sync_keeps_non_mcp_agents_on_run():
    member = Agent(name="Worker", id="worker", tools=[])
    expected = RunOutput(run_id="member-run", agent_id=member.id, agent_name=member.name, content="via run")
    run_mock = MagicMock(return_value=expected)
    arun_mock = MagicMock(side_effect=RuntimeError("async path should not be used for non-MCP members"))
    cast(Any, member).run = run_mock
    cast(Any, member).arun = arun_mock

    result = run_member_sync(member, input="delegate", run_id="member-run")

    assert result is expected
    run_mock.assert_called_once()
    arun_mock.assert_not_called()


def test_stream_member_sync_keeps_non_mcp_agents_on_run():
    member = Agent(name="Worker", id="worker", tools=[])
    expected = iter(_make_stream_items(member, "via stream run", "member-run"))
    run_mock = MagicMock(return_value=expected)
    arun_mock = MagicMock(side_effect=RuntimeError("async path should not be used for non-MCP members"))
    cast(Any, member).run = run_mock
    cast(Any, member).arun = arun_mock

    results = list(
        stream_member_sync(
            member,
            input="delegate",
            stream=True,
            stream_events=True,
            run_id="member-run",
            yield_run_output=True,
        )
    )

    assert len(results) == 2
    assert isinstance(results[0], RunCompletedEvent)
    assert isinstance(results[1], RunOutput)
    run_mock.assert_called_once()
    arun_mock.assert_not_called()


def test_sync_default_delegation_routes_mcp_agents_via_arun():
    mocked_member = _make_member(with_mcp=True, content="delegated via arun", session_key="delegate")
    member = mocked_member.member
    team = _make_team(member)
    run_response, run_context, session = _make_team_context()

    delegate_tool = team._get_delegate_task_function(
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
    )

    results = _call_tool(delegate_tool, member_id=member.id, task="Use MCP")

    assert results == ["delegated via arun"]
    assert run_context.session_state == {"delegate": "delegated via arun"}
    assert run_response.member_responses is not None
    assert run_response.member_responses[0].parent_run_id == run_response.run_id
    mocked_member.run_mock.assert_not_called()
    mocked_member.arun_mock.assert_called_once()


def test_sync_default_stream_delegation_routes_mcp_agents_via_stream_helper(monkeypatch: pytest.MonkeyPatch):
    mocked_member = _make_member(with_mcp=True, content="stream delegated", session_key="delegate_stream")
    member = mocked_member.member
    team = _make_team(member)
    run_response, run_context, session = _make_team_context()
    helper_calls: list[str] = []

    def fake_stream_helper(member_agent: Agent, **kwargs: Any):
        helper_calls.append(kwargs["run_id"])
        return iter(_make_stream_items(member_agent, "stream delegated", kwargs["run_id"]))

    monkeypatch.setattr(default_tools, "stream_member_sync", fake_stream_helper)

    delegate_tool = team._get_delegate_task_function(
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        stream=True,
        stream_events=True,
    )

    results = _call_tool(delegate_tool, member_id=member.id, task="Use MCP")

    assert any(isinstance(result, RunCompletedEvent) for result in results)
    assert helper_calls
    mocked_member.run_mock.assert_not_called()


def test_sync_default_delegation_routes_mcp_subteams_via_arun():
    mocked_subteam = _make_subteam(with_mcp_member=True, content="subteam delegated", session_key="delegate_subteam")
    team = _make_team(mocked_subteam.team)
    run_response, run_context, session = _make_team_context()

    delegate_tool = team._get_delegate_task_function(
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
    )

    results = _call_tool(delegate_tool, member_id=mocked_subteam.team.id, task="Use MCP")

    assert results == ["subteam delegated"]
    assert run_context.session_state == {"delegate_subteam": "subteam delegated"}
    mocked_subteam.run_mock.assert_not_called()
    mocked_subteam.arun_mock.assert_called_once()


def test_sync_default_delegation_to_all_members_routes_mcp_agents_via_arun():
    mocked_member = _make_member(with_mcp=True, content="delegated to all via arun", session_key="delegate_all_sync")
    member = mocked_member.member
    team = _make_team(member, delegate_to_all_members=True)
    run_response, run_context, session = _make_team_context()

    delegate_tool = team._get_delegate_task_function(
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
    )

    results = _call_tool(delegate_tool, task="Use MCP")

    assert results == [f"Agent {member.name}: delegated to all via arun"]
    assert run_context.session_state is not None
    assert run_context.session_state["delegate_all_sync"] == "delegated to all via arun"
    mocked_member.run_mock.assert_not_called()
    mocked_member.arun_mock.assert_called_once()


def test_sync_default_delegation_to_all_members_routes_mcp_agents_via_stream_helper(
    monkeypatch: pytest.MonkeyPatch,
):
    mocked_member = _make_member(with_mcp=True, content="all members stream", session_key="delegate_all")
    member = mocked_member.member
    team = _make_team(member, delegate_to_all_members=True)
    run_response, run_context, session = _make_team_context()
    helper_calls: list[str] = []

    def fake_stream_helper(member_agent: Agent, **kwargs: Any):
        helper_calls.append(kwargs["run_id"])
        return iter(_make_stream_items(member_agent, "all members stream", kwargs["run_id"]))

    monkeypatch.setattr(default_tools, "stream_member_sync", fake_stream_helper)

    delegate_tool = team._get_delegate_task_function(
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        stream=True,
        stream_events=True,
    )

    results = _call_tool(delegate_tool, task="Use MCP")

    assert any(isinstance(result, RunCompletedEvent) for result in results)
    assert helper_calls
    mocked_member.run_mock.assert_not_called()


def test_sync_execute_task_routes_mcp_agents_via_arun():
    mocked_member = _make_member(with_mcp=True, content="task via arun", session_key="execute")
    member = mocked_member.member
    team = _make_team(member, mode=TeamMode.tasks)
    run_response, run_context, session = _make_team_context()
    task_list = TaskList()
    task = task_list.create_task(title="Inspect MCP", assignee=member.id)

    tools = task_tools._get_task_management_tools(
        team=team,
        task_list=task_list,
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        async_mode=False,
    )

    results = _call_tool(_get_tool(tools, "execute_task"), task_id=task.id, member_id=member.id)

    assert results == [f"Task [{task.id}] completed. Result: task via arun"]
    assert task.status == TaskStatus.completed
    assert task.result == "task via arun"
    assert run_context.session_state is not None
    assert run_context.session_state["execute"] == "task via arun"
    assert "_team_tasks" in run_context.session_state
    assert run_response.member_responses is not None
    assert run_response.member_responses[0].parent_run_id == run_response.run_id
    mocked_member.run_mock.assert_not_called()
    mocked_member.arun_mock.assert_called_once()


def test_sync_execute_task_stream_routes_mcp_agents_via_stream_helper(monkeypatch: pytest.MonkeyPatch):
    mocked_member = _make_member(with_mcp=True, content="stream task via helper", session_key="execute_stream")
    member = mocked_member.member
    team = _make_team(member, mode=TeamMode.tasks)
    run_response, run_context, session = _make_team_context()
    task_list = TaskList()
    task = task_list.create_task(title="Inspect MCP", assignee=member.id)
    helper_calls: list[str] = []

    def fake_stream_helper(member_agent: Agent, **kwargs: Any):
        helper_calls.append(kwargs["run_id"])
        return iter(_make_stream_items(member_agent, "stream task via helper", kwargs["run_id"]))

    monkeypatch.setattr(task_tools, "stream_member_sync", fake_stream_helper)

    tools = task_tools._get_task_management_tools(
        team=team,
        task_list=task_list,
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        async_mode=False,
        stream=True,
        stream_events=True,
    )

    results = _call_tool(_get_tool(tools, "execute_task"), task_id=task.id, member_id=member.id)

    assert any(isinstance(result, RunCompletedEvent) for result in results)
    assert helper_calls
    mocked_member.run_mock.assert_not_called()


def test_sync_execute_tasks_parallel_routes_through_shared_helper(monkeypatch: pytest.MonkeyPatch):
    mocked_member = _make_member(with_mcp=True, content="parallel via arun", session_key="parallel")
    member = mocked_member.member
    team = _make_team(member, mode=TeamMode.tasks)
    run_response, run_context, session = _make_team_context()
    task_list = TaskList()
    task = task_list.create_task(title="Parallel MCP", assignee=member.id)
    helper_calls: list[str] = []
    original_helper = task_tools.run_member_sync

    def spy_helper(member_agent: Agent, **kwargs: Any):
        helper_calls.append(kwargs["run_id"])
        return original_helper(member_agent, **kwargs)

    monkeypatch.setattr(task_tools, "run_member_sync", spy_helper)

    tools = task_tools._get_task_management_tools(
        team=team,
        task_list=task_list,
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        async_mode=False,
    )

    results = _call_tool(_get_tool(tools, "execute_tasks_parallel"), task_ids=[task.id])

    assert results == [f"Task [{task.id}] completed. Result: parallel via arun"]
    assert helper_calls
    assert task.status == TaskStatus.completed
    assert task.result == "parallel via arun"
    assert run_context.session_state is not None
    assert run_context.session_state["parallel"] == "parallel via arun"
    assert "_team_tasks" in run_context.session_state
    assert run_response.member_responses is not None
    assert run_response.member_responses[0].parent_run_id == run_response.run_id
    mocked_member.run_mock.assert_not_called()
    mocked_member.arun_mock.assert_called_once()


@pytest.mark.asyncio
async def test_async_default_delegation_keeps_direct_arun(monkeypatch: pytest.MonkeyPatch):
    mocked_member = _make_member(with_mcp=True, content="async delegate", session_key="async_delegate")
    member = mocked_member.member
    team = _make_team(member)
    run_response, run_context, session = _make_team_context()
    monkeypatch.setattr(default_tools, "run_member_sync", lambda *args, **kwargs: pytest.fail("sync helper was used"))

    delegate_tool = team._get_delegate_task_function(
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        async_mode=True,
    )

    results = await _acall_tool(delegate_tool, member_id=member.id, task="Use MCP")

    assert results == ["async delegate"]
    mocked_member.run_mock.assert_not_called()
    mocked_member.arun_mock.assert_called_once()


@pytest.mark.asyncio
async def test_async_execute_task_keeps_direct_arun(monkeypatch: pytest.MonkeyPatch):
    mocked_member = _make_member(with_mcp=True, content="async task", session_key="async_execute")
    member = mocked_member.member
    team = _make_team(member, mode=TeamMode.tasks)
    run_response, run_context, session = _make_team_context()
    task_list = TaskList()
    task = task_list.create_task(title="Async MCP", assignee=member.id)
    monkeypatch.setattr(task_tools, "run_member_sync", lambda *args, **kwargs: pytest.fail("sync helper was used"))

    tools = task_tools._get_task_management_tools(
        team=team,
        task_list=task_list,
        run_response=run_response,
        run_context=run_context,
        session=session,
        team_run_context={},
        async_mode=True,
    )

    results = await _acall_tool(_get_tool(tools, "execute_task"), task_id=task.id, member_id=member.id)

    assert results == [f"Task [{task.id}] completed. Result: async task"]
    mocked_member.run_mock.assert_not_called()
    mocked_member.arun_mock.assert_called_once()
