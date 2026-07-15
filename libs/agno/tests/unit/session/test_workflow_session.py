from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput
from agno.session.workflow import WorkflowSession


def _make_agent_run(messages):
    return RunOutput(run_id="run-1", messages=messages)


def _make_team_run(team_id, messages):
    return TeamRunOutput(run_id="run-1", team_id=team_id, messages=messages)


def test_get_messages_from_agent_runs_limit_one_returns_only_system_message():
    session = WorkflowSession(session_id="s1", workflow_id="w1")
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="u1"),
        Message(role="assistant", content="a1"),
        Message(role="user", content="u2"),
        Message(role="assistant", content="a2"),
    ]
    run = _make_agent_run(messages)

    result = session.get_messages_from_agent_runs(runs=[run], limit=1)

    assert len(result) == 1
    assert result[0].role == "system"


def test_get_messages_from_agent_runs_limit_zero_returns_empty_without_system():
    session = WorkflowSession(session_id="s1", workflow_id="w1")
    messages = [
        Message(role="user", content="u1"),
        Message(role="assistant", content="a1"),
    ]
    run = _make_agent_run(messages)

    result = session.get_messages_from_agent_runs(runs=[run], limit=0)

    assert result == []


def test_get_messages_from_team_runs_limit_one_returns_only_system_message():
    session = WorkflowSession(session_id="s1", workflow_id="w1")
    messages = [
        Message(role="system", content="sys"),
        Message(role="user", content="u1"),
        Message(role="assistant", content="a1"),
        Message(role="user", content="u2"),
        Message(role="assistant", content="a2"),
    ]
    run = _make_team_run("team-1", messages)

    result = session.get_messages_from_team_runs(team_id="team-1", runs=[run], limit=1)

    assert len(result) == 1
    assert result[0].role == "system"


def test_get_messages_from_team_runs_limit_zero_returns_empty_without_system():
    session = WorkflowSession(session_id="s1", workflow_id="w1")
    messages = [
        Message(role="user", content="u1"),
        Message(role="assistant", content="a1"),
    ]
    run = _make_team_run("team-1", messages)

    result = session.get_messages_from_team_runs(team_id="team-1", runs=[run], limit=0)

    assert result == []
