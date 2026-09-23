"""Tests for reading a workflow step's executor chat history."""

from agno.agent import Agent
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession
from agno.team import Team
from agno.workflow.step import Step


def test_get_chat_history_uses_agent_current_session_when_id_omitted():
    session = WorkflowSession(session_id="session-1", workflow_id="workflow-1")
    messages = [Message(role="user", content="hello")]
    executor = Agent(id="agent-1", session_id=session.session_id, cache_session=True)
    executor.workflow_id = session.workflow_id
    run = RunOutput(run_id="run-1", agent_id=executor.id, messages=messages)
    session.upsert_run(WorkflowRunOutput(run_id="workflow-run-1", step_executor_runs=[run]))
    executor._set_cached_session(session)

    assert [message.content for message in Step(agent=executor).get_chat_history()] == ["hello"]


def test_get_chat_history_uses_team_current_session_when_id_omitted():
    session = WorkflowSession(session_id="session-1", workflow_id="workflow-1")
    messages = [Message(role="user", content="hello")]
    executor = Team(id="team-1", members=[], session_id=session.session_id, cache_session=True)
    executor.workflow_id = session.workflow_id
    run = TeamRunOutput(run_id="run-1", team_id=executor.id, messages=messages)
    session.upsert_run(WorkflowRunOutput(run_id="workflow-run-1", step_executor_runs=[run]))
    executor._set_cached_session(session)

    assert [message.content for message in Step(team=executor).get_chat_history()] == ["hello"]
