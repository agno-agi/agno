"""A sub-team borrows parent history only while its delegated run is executing."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from agno.exceptions import RunCancelledException
from agno.models.message import Message
from agno.run.base import RunContext, RunStatus
from agno.run.team import RunContentEvent, TeamRunOutput
from agno.session.team import TeamSession
from agno.team._default_tools import _get_delegate_task_function
from agno.team._storage import _read_or_create_session
from agno.team._task_tools import _get_task_management_tools
from agno.team.task import TaskList
from agno.team.team import Team

SESSION_ID = "delegation-cleanup-session"
TOOL_KINDS = ["delegate", "delegate_all", "task", "tasks_parallel"]


@pytest.fixture
def delegation():
    member = Team(id="member", name="Member", members=[], cache_session=True)
    own_run = TeamRunOutput(run_id="member-own-run", team_id=member.id, session_id=SESSION_ID)
    member._cached_session = TeamSession(session_id=SESSION_ID, team_id=member.id, runs=[own_run])
    root = Team(id="root", name="Root", members=[member])
    parent_run = TeamRunOutput(
        run_id="parent-history",
        team_id=root.id,
        session_id=SESSION_ID,
        messages=[Message(role="user", content="Parent history")],
    )
    session = TeamSession(session_id=SESSION_ID, team_id=root.id, runs=[parent_run])
    return root, member, session


def _entrypoint(delegation, kind, *, async_mode=False, stream=False):
    root, _, session = delegation
    options = dict(
        run_response=TeamRunOutput(team_id=root.id, session_id=SESSION_ID),
        run_context=RunContext(run_id="root-current-run", session_id=SESSION_ID, session_state={}),
        session=session,
        team_run_context={},
        async_mode=async_mode,
        stream=stream,
    )
    if kind.startswith("delegate"):
        root.delegate_to_all_members = kind == "delegate_all"
        tool = _get_delegate_task_function(root, **options)
        arguments = {"task": "Do the task"}
        if kind == "delegate":
            arguments["member_id"] = "member"
    else:
        task_list = TaskList()
        task = task_list.create_task(title="Task", description="Do the task", assignee="member")
        tools = _get_task_management_tools(root, task_list=task_list, **options)
        name = "execute_tasks_parallel" if kind == "tasks_parallel" else "execute_task"
        tool = next(tool for tool in tools if tool.name == name)
        arguments = {"task_ids": [task.id]} if kind == "tasks_parallel" else {"task_id": task.id, "member_id": "member"}
    return tool.entrypoint(**arguments)


def _borrow_history(delegation):
    _, member, parent_session = delegation
    session = _read_or_create_session(member, session_id=SESSION_ID)
    assert member._delegated_session is parent_session
    assert [run.run_id for run in session.runs] == ["parent-history", "member-own-run"]


def _assert_released(delegation):
    _, member, parent_session = delegation
    assert member._delegated_session is None
    assert [run.run_id for run in member._cached_session.runs] == ["member-own-run"]
    assert [run.run_id for run in parent_session.runs] == ["parent-history"]


@pytest.mark.parametrize("kind", TOOL_KINDS)
def test_member_exception_releases_borrowed_history(delegation, kind):
    _, member, _ = delegation

    def fail(**kwargs):
        _borrow_history(delegation)
        raise RuntimeError("member failed")

    member.run = fail
    invocation = _entrypoint(delegation, kind)
    if kind.startswith("delegate"):
        with pytest.raises(RuntimeError, match="member failed"):
            list(invocation)
    else:
        assert "member failed" in "".join(list(invocation))
    _assert_released(delegation)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", TOOL_KINDS)
async def test_async_member_exception_releases_borrowed_history(delegation, kind):
    _, member, _ = delegation

    async def fail(**kwargs):
        _borrow_history(delegation)
        raise RuntimeError("member failed")

    member.arun = fail
    invocation = _entrypoint(delegation, kind, async_mode=True)
    if kind == "delegate":
        with pytest.raises(RuntimeError, match="member failed"):
            [chunk async for chunk in invocation]
    else:
        # Fan-out delegates and task tools preserve their existing error-reporting contract.
        assert "member failed" in "".join([chunk async for chunk in invocation])
    _assert_released(delegation)


@pytest.mark.parametrize("kind", ["delegate", "delegate_all", "task"])
def test_closing_member_stream_releases_borrowed_history(delegation, kind):
    _, member, _ = delegation

    def stream(**kwargs):
        _borrow_history(delegation)
        yield RunContentEvent(content="partial")
        pytest.fail("A closed delegation must not resume the member stream")

    member.run = stream
    invocation = _entrypoint(delegation, kind, stream=True)
    assert next(invocation).content == "partial"
    invocation.close()
    _assert_released(delegation)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["delegate", "delegate_all", "task"])
async def test_closing_async_member_stream_releases_borrowed_history(delegation, kind):
    _, member, _ = delegation
    waiting = asyncio.Event()

    async def stream(**kwargs):
        _borrow_history(delegation)
        yield RunContentEvent(content="partial")
        await waiting.wait()

    member.arun = stream
    invocation = _entrypoint(delegation, kind, async_mode=True, stream=True)
    assert (await invocation.__anext__()).content == "partial"
    await invocation.aclose()
    _assert_released(delegation)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", TOOL_KINDS)
async def test_cancelling_member_task_releases_borrowed_history(delegation, kind):
    _, member, _ = delegation
    started = asyncio.Event()

    async def wait(**kwargs):
        _borrow_history(delegation)
        started.set()
        await asyncio.Event().wait()

    member.arun = wait
    invocation = _entrypoint(delegation, kind, async_mode=True)

    async def consume():
        return [chunk async for chunk in invocation]

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    _assert_released(delegation)


@pytest.mark.parametrize("kind", TOOL_KINDS)
def test_postprocessing_failure_cannot_retain_borrowed_history(delegation, kind, monkeypatch):
    _, member, _ = delegation

    def run(**kwargs):
        _borrow_history(delegation)
        return TeamRunOutput(run_id="new-member-run", team_id=member.id, session_id=SESSION_ID, content="done")

    member.run = run
    monkeypatch.setattr("agno.team._run._member_run_for_storage", Mock(side_effect=RuntimeError("storage failed")))
    invocation = _entrypoint(delegation, kind)
    if kind == "tasks_parallel":
        assert "storage failed" in "".join(list(invocation))
    else:
        with pytest.raises(RuntimeError, match="storage failed"):
            list(invocation)
    _assert_released(delegation)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", TOOL_KINDS)
async def test_async_postprocessing_failure_cannot_retain_borrowed_history(delegation, kind, monkeypatch):
    _, member, _ = delegation

    async def run(**kwargs):
        _borrow_history(delegation)
        return TeamRunOutput(run_id="new-member-run", team_id=member.id, session_id=SESSION_ID, content="done")

    member.arun = run
    monkeypatch.setattr(
        "agno.team._run._amember_run_for_storage", AsyncMock(side_effect=RuntimeError("storage failed"))
    )
    invocation = _entrypoint(delegation, kind, async_mode=True)
    if kind == "delegate_all":
        assert "storage failed" in "".join([chunk async for chunk in invocation])
    else:
        with pytest.raises(RuntimeError, match="storage failed"):
            [chunk async for chunk in invocation]
    _assert_released(delegation)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", TOOL_KINDS)
@pytest.mark.parametrize("async_mode", [False, True])
async def test_success_keeps_the_members_own_new_run(delegation, kind, async_mode):
    _, member, parent_session = delegation

    def run(**kwargs):
        _borrow_history(delegation)
        output = TeamRunOutput(run_id="new-member-run", team_id=member.id, session_id=SESSION_ID, content="done")
        member._cached_session.upsert_run(output)
        return output

    async def arun(**kwargs):
        return run(**kwargs)

    member.run = run
    member.arun = arun
    invocation = _entrypoint(delegation, kind, async_mode=async_mode)
    results = [chunk async for chunk in invocation] if async_mode else list(invocation)

    assert "done" in "".join(results)
    assert member._delegated_session is None
    assert [run.run_id for run in member._cached_session.runs] == ["member-own-run", "new-member-run"]
    assert [run.run_id for run in parent_session.runs] == ["parent-history", "new-member-run"]


@pytest.mark.asyncio
@pytest.mark.parametrize("async_mode", [False, True])
async def test_task_error_is_reported_after_releasing_history(delegation, async_mode):
    _, member, _ = delegation

    def fail(**kwargs):
        _borrow_history(delegation)
        raise RuntimeError("member failed")

    async def afail(**kwargs):
        fail(**kwargs)

    member.run = fail
    member.arun = afail
    invocation = _entrypoint(delegation, "task", async_mode=async_mode)
    try:
        result = await invocation.__anext__() if async_mode else next(invocation)
        assert "member failed" in result
        _assert_released(delegation)
    finally:
        if async_mode:
            await invocation.aclose()
        else:
            invocation.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", TOOL_KINDS)
@pytest.mark.parametrize("async_mode", [False, True])
async def test_cancelled_partial_run_remains_in_member_cache(delegation, kind, async_mode):
    _, member, parent_session = delegation

    def run(**kwargs):
        _borrow_history(delegation)
        output = TeamRunOutput(
            run_id="cancelled-member-run",
            team_id=member.id,
            session_id=SESSION_ID,
            content="partial result",
            status=RunStatus.cancelled,
        )
        member._cached_session.upsert_run(output)
        return output

    async def arun(**kwargs):
        return run(**kwargs)

    member.run = run
    member.arun = arun
    invocation = _entrypoint(delegation, kind, async_mode=async_mode)
    try:
        if async_mode:
            [chunk async for chunk in invocation]
        else:
            list(invocation)
    except RunCancelledException:
        pass

    assert member._delegated_session is None
    assert [run.run_id for run in member._cached_session.runs] == ["member-own-run", "cancelled-member-run"]
    assert [run.run_id for run in parent_session.runs] == ["parent-history", "cancelled-member-run"]
