"""Harness agents (Claude Code, Codex) as workflow steps.

A harness step runs on the workflow's session id like any step, keeps its native conversation in a
session of its own, and leaves storing its runs to the workflow.
"""

import asyncio

from fastapi.testclient import TestClient

from agno.db.base import SessionType
from agno.os import AgentOS
from agno.run.base import RunStatus
from agno.workflow import Loop, Parallel, Step, Workflow
from tests.unit.team.test_external_agent_members import _member, db, sdk  # noqa: F401


def _workflow(db, steps) -> Workflow:  # noqa: F811
    return Workflow(id="wf", name="WF", steps=steps, db=db)


def test_a_harness_step_runs_and_the_workflow_stores_its_run(db, sdk):  # noqa: F811
    coder = _member(db)
    output = _workflow(db, [Step(name="code", agent=coder)]).run("Write hello.py", session_id="w1")

    assert output.status == RunStatus.completed and output.content == "answer from sdk-1"
    assert "Write hello.py" in sdk.calls[0]["prompt"]
    [step_run] = output.step_executor_runs
    assert step_run.agent_id == "claude-coder" and step_run.parent_run_id == output.run_id

    workflow_session = db.get_session(session_id="w1", session_type=SessionType.WORKFLOW)
    assert workflow_session is not None and [run.run_id for run in workflow_session.runs] == [output.run_id]
    # Sessions share one id space, so the step must not write an agent row on the workflow's id.
    same_id = db.get_session(session_id="w1", session_type=SessionType.AGENT)
    assert same_id is None or same_id.agent_id is None

    state = db.get_session(session_id="w1:claude-coder", session_type=SessionType.AGENT)
    assert state is not None and (state.metadata or {}).get("workflow_id") == "wf"
    assert state.session_data["claude_sdk_session_id"] == "sdk-1"
    assert not state.runs, "the step's runs are stored by the workflow, never twice"


def test_a_harness_agent_listed_directly_in_steps_resumes_its_conversation_next_run(db, sdk):  # noqa: F811
    coder = _member(db)
    workflow = _workflow(db, [coder])

    first = workflow.run("first", session_id="w1")
    second = workflow.run("second", session_id="w1")

    assert first.status == second.status == RunStatus.completed
    assert [call["resume"] for call in sdk.calls] == [None, "sdk-1"]
    assert second.content == "answer from sdk-1"


def test_streamed_and_async_workflows_run_a_harness_step(db, sdk):  # noqa: F811
    coder = _member(db)

    streamed = list(
        _workflow(db, [Step(name="code", agent=coder)]).run(
            "stream it", session_id="w-stream", stream=True, stream_events=True
        )
    )
    assert getattr(streamed[-1], "event", None) == "WorkflowCompleted"
    assert any(
        getattr(event, "agent_id", None) == "claude-coder" and getattr(event, "content", None) == "answer from sdk-1"
        for event in streamed
    )

    async def run_async():
        output = await _workflow(db, [Step(name="code", agent=coder)]).arun("async", session_id="w-async")
        events = [
            event
            async for event in _workflow(db, [Step(name="code", agent=coder)]).arun(
                "async stream", session_id="w-async-stream", stream=True, stream_events=True
            )
        ]
        return output, events

    output, events = asyncio.run(run_async())
    assert output.status == RunStatus.completed and output.content == "answer from sdk-2"
    assert getattr(events[-1], "event", None) == "WorkflowCompleted"
    for session_id in ("w-stream", "w-async", "w-async-stream"):
        same_id = db.get_session(session_id=session_id, session_type=SessionType.AGENT)
        assert same_id is None or same_id.agent_id is None
        assert db.get_session(session_id=f"{session_id}:claude-coder", session_type=SessionType.AGENT) is not None


def test_harness_steps_inside_parallel_and_loop_keep_separate_conversations(db, sdk):  # noqa: F811
    coder, reviewer = _member(db, "claude-coder"), _member(db, "claude-reviewer")
    workflow = _workflow(
        db,
        [
            Parallel(coder, reviewer, name="both"),
            Loop(steps=[Step(name="again", agent=coder)], max_iterations=2, name="loop"),
        ],
    )

    output = workflow.run("go", session_id="w1")

    assert output.status == RunStatus.completed
    coder_state = db.get_session(session_id="w1:claude-coder", session_type=SessionType.AGENT)
    reviewer_state = db.get_session(session_id="w1:claude-reviewer", session_type=SessionType.AGENT)
    assert coder_state.session_data["claude_sdk_session_id"] != reviewer_state.session_data["claude_sdk_session_id"]
    # The coder resumed its own conversation on both loop iterations.
    coder_session = coder_state.session_data["claude_sdk_session_id"]
    assert [call["resume"] for call in sdk.calls].count(coder_session) == 2


def test_a_harness_agent_still_saves_standalone_runs_after_a_workflow_run(db, sdk):  # noqa: F811
    coder = _member(db)
    _workflow(db, [Step(name="code", agent=coder)]).run("in workflow", session_id="w1")

    solo = coder.run("on my own", session_id="solo")

    session = db.get_session(session_id="solo", session_type=SessionType.AGENT)
    assert session is not None and session.workflow_id is None
    assert [run.run_id for run in session.runs] == [solo.run_id]
    assert db.get_session(session_id="solo:claude-coder", session_type=SessionType.AGENT) is None


def test_agentos_lists_a_harness_step_on_the_workflow(db, sdk):  # noqa: F811
    coder = _member(db)
    workflow = _workflow(db, [Step(name="code", agent=coder)])
    app = AgentOS(id="os", agents=[coder], workflows=[workflow], db=db, telemetry=False).get_app()

    with TestClient(app) as client:
        response = client.get("/workflows/wf")

    assert response.status_code == 200, response.text
    [step] = response.json()["steps"]
    assert step["agent"]["id"] == "claude-coder" and step["agent"]["metadata"]["sdk"] == "claude-agent-sdk"


def test_a_harness_steps_chat_history_comes_from_the_workflow_session(db, sdk):  # noqa: F811
    coder = _member(db)
    step = Step(name="code", agent=coder)
    _workflow(db, [step]).run("Write hello.py", session_id="w1")

    history = step.get_chat_history(session_id="w1")
    async_history = asyncio.run(step.aget_chat_history(session_id="w1"))

    assert [message.content for message in history] == [message.content for message in async_history]
    assert any(message.content == "answer from sdk-1" for message in history)


def test_a_sandboxed_steps_options_name_its_own_session_and_link_it_to_the_workflow(db, sdk):  # noqa: F811
    coder = _member(db)
    forwarded = coder._sandboxed_member_kwargs(
        {"run_id": "r1", "session_id": "w1", "session_state": {}, "run_context": object()}, "w1", "r1", workflow_id="wf"
    )
    assert forwarded == {
        "run_id": "r1.sandbox",
        "session_id": "w1:claude-coder",
        "_session_metadata": {"workflow_id": "wf"},
    }


def test_the_same_harness_agent_in_two_parallel_branches_is_refused_when_the_workflow_is_built(db, sdk):  # noqa: F811
    import pytest

    from agno.team import Team

    coder = _member(db)
    # One agent keeps one conversation per workflow session, which cannot take two turns at once.
    with pytest.raises(ValueError, match="claude-coder"):
        Parallel(Step(name="a", agent=coder), Step(name="b", agent=coder))
    with pytest.raises(ValueError, match="claude-coder"):
        Parallel(coder, Step(name="b", team=Team(id="t", members=[coder])))
    # Different harness agents, and native agents, can run side by side.
    Parallel(coder, _member(db, "claude-reviewer"))


def test_the_same_harness_agent_in_sequential_steps_continues_one_conversation(db, sdk):  # noqa: F811
    coder = _member(db)
    output = _workflow(db, [Step(name="plan", agent=coder), Step(name="build", agent=coder)]).run("go", session_id="w1")

    assert output.status == RunStatus.completed
    assert [call["resume"] for call in sdk.calls] == [None, "sdk-1"]


def test_a_harness_steps_chat_history_reads_the_workflow_db_when_the_agent_has_none(db, sdk):  # noqa: F811
    from agno.agents.claude import ClaudeAgent

    coder = ClaudeAgent(id="claude-coder", name="Coder")
    step = Step(name="code", agent=coder)
    _workflow(db, [step]).run("first", session_id="n1")

    assert any(message.content == "answer from sdk-1" for message in step.get_chat_history(session_id="n1"))
    history = asyncio.run(step.aget_chat_history(session_id="n1"))
    assert any(message.content == "answer from sdk-1" for message in history)


def test_a_harness_step_without_a_workflow_id_is_refused(db, sdk):  # noqa: F811
    import pytest

    from agno.run.workflow import WorkflowRunOutput
    from agno.workflow.step import _harness_step_kwargs

    with pytest.raises(ValueError, match="workflow id"):
        _harness_step_kwargs(_member(db), WorkflowRunOutput(run_id="r1", workflow_id=None))
