"""Tests for Step.get_chat_history / Step.aget_chat_history.

When no session_id is passed, both helpers fall back to the executor's current
session, matching Agent.get_chat_history and Team.get_chat_history.
"""

import asyncio

import pytest

from agno.agent import Agent
from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession
from agno.team import Team
from agno.workflow.step import Step


def _messages() -> list[Message]:
    return [Message(role="user", content="hello"), Message(role="assistant", content="hi there")]


def _workflow_session(executor_run) -> WorkflowSession:
    session = WorkflowSession(session_id="wf-session", workflow_id="wf-1")
    session.upsert_run(WorkflowRunOutput(run_id="wf-run-1", step_executor_runs=[executor_run]))
    return session


@pytest.fixture
def agent() -> Agent:
    agent = Agent(id="agent-1", session_id="wf-session", cache_session=True)
    run = RunOutput(run_id="run-1", agent_id="agent-1", status=RunStatus.completed, messages=_messages())
    agent._set_cached_session(_workflow_session(run))  # type: ignore[arg-type]
    return agent


@pytest.fixture
def team() -> Team:
    team = Team(id="team-1", members=[Agent(name="member")], session_id="wf-session", cache_session=True)
    run = TeamRunOutput(run_id="run-1", team_id="team-1", status=RunStatus.completed, messages=_messages())
    team._set_cached_session(_workflow_session(run))  # type: ignore[arg-type]
    return team


def _contents(messages: list[Message]) -> list:
    return [m.content for m in messages]


def test_agent_step_get_chat_history_defaults_to_current_session(agent: Agent):
    step = Step(agent=agent)

    assert _contents(step.get_chat_history()) == ["hello", "hi there"]
    assert _contents(step.get_chat_history(session_id="wf-session")) == ["hello", "hi there"]


def test_team_step_get_chat_history_defaults_to_current_session(team: Team):
    step = Step(team=team)

    assert _contents(step.get_chat_history()) == ["hello", "hi there"]
    assert _contents(step.get_chat_history(session_id="wf-session")) == ["hello", "hi there"]


def test_agent_step_aget_chat_history_defaults_to_current_session(agent: Agent):
    step = Step(agent=agent)

    assert _contents(asyncio.run(step.aget_chat_history())) == ["hello", "hi there"]


def test_team_step_aget_chat_history_defaults_to_current_session(team: Team):
    step = Step(team=team)

    assert _contents(asyncio.run(step.aget_chat_history())) == ["hello", "hi there"]
