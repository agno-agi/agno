"""Deserializing real persisted runs must not consume their caller-owned records."""

import json

import pytest

from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb
from agno.metrics import RunMetrics
from agno.models.message import Message
from agno.run.agent import RunCompletedEvent as AgentCompleted
from agno.run.agent import RunOutput
from agno.run.team import RunCompletedEvent as TeamCompleted
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput
from agno.session.agent import AgentSession
from agno.session.team import TeamSession
from agno.session.workflow import WorkflowSession
from agno.workflow.types import WorkflowMetrics


def agent_run():
    return RunOutput(
        run_id="agent-run",
        agent_id="agent",
        messages=[Message(role="assistant", content="Retained")],
        metrics=RunMetrics(input_tokens=3),
    )


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_reconstruct_sqlite_session_twice_without_consuming_raw_runs(tmp_path, kind):
    if kind == "agent":
        session = AgentSession(session_id="native", agent_id="agent", runs=[agent_run()])
        session_type = SessionType.AGENT
    elif kind == "team":
        run = TeamRunOutput(
            run_id="team-run",
            team_id="team",
            messages=[Message(role="assistant", content="Team")],
            member_responses=[agent_run()],
            metrics=RunMetrics(input_tokens=5),
        )
        session = TeamSession(session_id="native", team_id="team", runs=[run])
        session_type = SessionType.TEAM
    else:
        run = WorkflowRunOutput(
            run_id="workflow-run",
            workflow_id="workflow",
            workflow_name="Workflow",
            step_executor_runs=[agent_run()],
            metadata={"retained": True},
            metrics=WorkflowMetrics(steps={}, duration=1.0),
        )
        session = WorkflowSession(session_id="native", workflow_id="workflow", workflow_name="Workflow", runs=[run])
        session_type = SessionType.WORKFLOW
    db = SqliteDb(db_file=str(tmp_path / "runs.db"))
    try:
        db.upsert_session(session)
        db.upsert_run(session.runs[0], "native")
        raw = db.get_session("native", session_type=session_type, deserialize=False)
        assert raw is not None
        assert len(raw["runs"]) == 1
        before = json.dumps(raw, sort_keys=True)
        first = type(session).from_dict(raw)
        assert json.dumps(raw, sort_keys=True) == before
        second = type(session).from_dict(raw)
        assert first.to_dict() == second.to_dict()
        assert len(first.runs) == 1
        rebuilt = first.runs[0]
        assert rebuilt.metrics.to_dict() == session.runs[0].metrics.to_dict()
        if kind == "agent":
            assert rebuilt.messages[0].content == "Retained"
        elif kind == "team":
            assert rebuilt.messages[0].content == "Team"
            assert rebuilt.member_responses[0].messages[0].content == "Retained"
        else:
            assert rebuilt.metadata == {"retained": True}
            assert rebuilt.step_executor_runs[0].messages[0].content == "Retained"
    finally:
        db.db_engine.dispose()


@pytest.mark.parametrize("kind", ["agent", "team", "workflow"])
def test_event_reconstruction_keeps_serialized_fields(kind):
    if kind == "agent":
        event = AgentCompleted(run_id="native", agent_id="agent", metrics=RunMetrics(input_tokens=3))
    elif kind == "team":
        event = TeamCompleted(
            run_id="native", team_id="team", member_responses=[agent_run()], metrics=RunMetrics(input_tokens=5)
        )
    else:
        event = WorkflowCompletedEvent(
            run_id="native", workflow_id="workflow", metrics=WorkflowMetrics(steps={}, duration=1.0)
        )
    payload = json.loads(event.to_json())
    before = json.dumps(payload, sort_keys=True)
    first = type(event).from_dict(payload)
    assert json.dumps(payload, sort_keys=True) == before
    second = type(event).from_dict(payload)
    assert first.to_dict() == second.to_dict()
    assert first.metrics.to_dict() == event.metrics.to_dict()


def test_legacy_run_wrapper_remains_reusable():
    payload = {"run": agent_run().to_dict()}
    before = json.dumps(payload, sort_keys=True)
    first = RunOutput.from_dict(payload)
    assert json.dumps(payload, sort_keys=True) == before
    second = RunOutput.from_dict(payload)
    assert first.to_dict() == second.to_dict()
