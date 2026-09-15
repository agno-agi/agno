"""A member run that ends unverified must reach the leader as a failure, not as a result.

Covers the delegate tools (single member, all members, a verified member, respond_directly) and
the tasks-mode tools (execute_task, execute_tasks_parallel), plus the child_run_id link a
re-entered leader stamps on the right delegate call.
"""

from typing import List, Optional

import pytest

from agno.agent import Agent
from agno.db.in_memory import InMemoryDb
from agno.models.response import ModelResponse
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.team import Team
from agno.team.task import TASK_LIST_KEY, Task, TaskList, TaskStatus, load_task_list
from agno.verifiers import VerificationConfig

from .conftest import MODES, ScriptedModel, _run_variant, _text, _tool_call, fail_once

DRAFT = "member claims done"
NOTE = "Member 'member' ended UNVERIFIED (exhausted): [FAIL] <lambda>: report.md is missing"


def _unverified_member(name: str = "member", draft: Optional[str] = None) -> Agent:
    return Agent(
        name=name,
        id=name,
        model=ScriptedModel([_text(f"{name} claims done" if draft is None else draft)]),
        verifiers=[lambda run_output: "report.md is missing\nmore detail"],
        verification=VerificationConfig(max_attempts=1),
        telemetry=False,
    )


def _tool_results(out: TeamRunOutput, tool_name: str) -> List[str]:
    return [str(tool.result) for tool in (out.tools or []) if tool.tool_name == tool_name]


def _seeded_state(*task_ids: str) -> dict:
    task_list = TaskList(tasks=[Task(id=task_id, title=f"task {task_id}", assignee="member") for task_id in task_ids])
    return {TASK_LIST_KEY: task_list.to_dict()}


# ---------------------------------------------------------------------------
# delegate_task_to_member / delegate_task_to_members
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", ["single_member", "all_members", "verified_member", "respond_directly"])
@MODES
async def test_delegation_notes_an_unverified_member(case, mode):
    tool_name = "delegate_task_to_members" if case == "all_members" else "delegate_task_to_member"
    arguments = {"task": "do the thing"} if case == "all_members" else {"member_id": "member", "task": "do the thing"}
    leader = ScriptedModel([_tool_call(tool_name, "tc-deleg", arguments), _text("All done.")])
    members = [_unverified_member()]
    team_kwargs = {}
    if case == "all_members":
        members.append(_unverified_member("other"))
        team_kwargs["delegate_to_all_members"] = True
    elif case == "verified_member":
        members = [
            Agent(
                name="member",
                id="member",
                model=ScriptedModel([_text("member ok")]),
                verifiers=[lambda run_output: True],
                telemetry=False,
            )
        ]
    elif case == "respond_directly":
        team_kwargs["respond_directly"] = True
    team = Team(members=members, model=leader, telemetry=False, **team_kwargs)
    out = await _run_variant(team, mode)

    (result,) = _tool_results(out, tool_name)
    if case in ("verified_member", "respond_directly"):
        # The note is for a leader that reads the result; a direct response passes the draft through.
        assert "UNVERIFIED" not in result
        return
    assert {run.status for run in out.member_responses} == {RunStatus.unverified}
    assert NOTE in result
    if case == "all_members":
        assert "Member 'other' ended UNVERIFIED (exhausted)" in result
    else:
        # The draft is still there: the note explains it, it does not hide it.
        assert DRAFT in result


# ---------------------------------------------------------------------------
# tasks mode: execute_task / execute_tasks_parallel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ["execute_task", "execute_tasks_parallel"])
@pytest.mark.parametrize("draft", [DRAFT, ""], ids=["with_draft", "without_draft"])
@pytest.mark.parametrize("mode", ["run", "arun"])
async def test_tasks_mode_fails_the_task_of_an_unverified_member(tool_name, draft, mode):
    task_ids = ("t1",) if tool_name == "execute_task" else ("t1", "t2")
    arguments = (
        {"task_id": "t1", "member_id": "member"} if tool_name == "execute_task" else {"task_ids": list(task_ids)}
    )
    leader = ScriptedModel(
        [
            _tool_call(tool_name, "tc-exec", arguments),
            _tool_call("mark_all_complete", "tc-done", {"summary": "gave up"}),
            _text("Could not finish."),
        ]
    )
    team = Team(
        members=[_unverified_member(draft=draft)],
        model=leader,
        mode="tasks",
        db=InMemoryDb(),
        session_state=_seeded_state(*task_ids),
        telemetry=False,
    )
    out = await _run_variant(team, mode)

    expected = f"{DRAFT}\n{NOTE}" if draft else NOTE
    (result,) = _tool_results(out, tool_name)
    for task_id in task_ids:
        assert f"Task [{task_id}] failed: " in result
    assert NOTE in result
    assert (DRAFT in result) is bool(draft)
    task_list = load_task_list(team.get_session_state(session_id=out.session_id))
    assert {task.status for task in task_list.tasks} == {TaskStatus.failed}
    assert {task.result for task in task_list.tasks} == {expected}


class _RaisingModel(ScriptedModel):
    def _next(self, kwargs=None) -> ModelResponse:
        raise RuntimeError("provider down")


@pytest.mark.parametrize("use_async", [False, True], ids=["sync", "async"])
async def test_execute_task_of_an_errored_member_records_the_failure(use_async):
    member = Agent(name="member", id="member", model=_RaisingModel([_text("unused")]), telemetry=False)
    leader = ScriptedModel(
        [
            _tool_call("execute_task", "tc-exec", {"task_id": "t1", "member_id": "member"}),
            _tool_call("mark_all_complete", "tc-done", {"summary": "gave up"}),
            _text("Could not finish."),
        ]
    )
    team = Team(
        members=[member],
        model=leader,
        mode="tasks",
        db=InMemoryDb(),
        session_state=_seeded_state("t1"),
        telemetry=False,
    )
    out = await team.arun("go") if use_async else team.run("go")

    task = load_task_list(team.get_session_state(session_id=out.session_id)).get_task("t1")
    assert out.member_responses[0].status == RunStatus.error
    assert task.status == TaskStatus.failed
    assert task.result == (str(out.member_responses[0].content) if out.member_responses[0].content else "Task failed")
    assert "UNVERIFIED" not in task.result


# ---------------------------------------------------------------------------
# child_run_id: a re-entered leader links each delegate call to its own member run.
# Streaming only: the non-stream loops append tool executions after the model
# call returns, so there is no entry to stamp while the tool runs.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tool_name", ["delegate_task_to_member", "execute_task"])
@pytest.mark.parametrize("mode", ["run_stream", "arun_stream"])
async def test_reentered_leader_links_each_call_to_its_own_member_run(tool_name, mode):
    member = Agent(name="member", id="member", model=ScriptedModel([_text("member ok")]), telemetry=False)
    if tool_name == "delegate_task_to_member":
        first, second = {"member_id": "member", "task": "first"}, {"member_id": "member", "task": "second"}
        script = [
            _tool_call(tool_name, "tc-1", first),
            _text("claimed done"),
            _tool_call(tool_name, "tc-2", second),
            _text("actually done"),
        ]
        team = Team(members=[member], model=ScriptedModel(script), verifiers=[fail_once()], telemetry=False)
        key, expected = "task", ["first", "second"]
    else:
        script = [
            _tool_call(tool_name, "tc-1", {"task_id": "t1", "member_id": "member"}),
            _tool_call("mark_all_complete", "tc-done-1", {"summary": "done"}),
            _text("claimed done"),
            _tool_call(tool_name, "tc-2", {"task_id": "t2", "member_id": "member"}),
            _tool_call("mark_all_complete", "tc-done-2", {"summary": "done"}),
            _text("actually done"),
        ]
        team = Team(
            members=[member],
            model=ScriptedModel(script),
            mode="tasks",
            session_state=_seeded_state("t1", "t2"),
            verifiers=[fail_once()],
            telemetry=False,
        )
        key, expected = "task_id", ["t1", "t2"]
    out = await _run_variant(team, mode)

    assert out.status == RunStatus.completed
    calls = [tool for tool in out.tools if tool.tool_name == tool_name]
    assert [tool.tool_args[key] for tool in calls] == expected
    member_run_ids = [run.run_id for run in out.member_responses]
    assert len(member_run_ids) == 2
    assert [tool.child_run_id for tool in calls] == member_run_ids
