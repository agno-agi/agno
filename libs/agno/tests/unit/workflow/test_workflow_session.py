"""Unit tests for WorkflowSession."""

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput
from agno.session.workflow import WorkflowSession


def _messages(with_system: bool) -> list[Message]:
    """Build a run's messages, optionally led by a single system message."""
    prefix = [Message(role="system", content="sys")] if with_system else []
    return prefix + [
        Message(role="user", content="u1"),
        Message(role="assistant", content="a1"),
        Message(role="user", content="u2"),
        Message(role="assistant", content="a2"),
    ]


def _make_agent_run(messages: list[Message], run_id: str = "run-1") -> RunOutput:
    """Create an agent RunOutput to nest as a workflow step executor run."""
    return RunOutput(run_id=run_id, agent_id="agent-1", status=RunStatus.completed, messages=messages)


def _make_team_run(messages: list[Message], run_id: str = "run-1") -> TeamRunOutput:
    """Create a team TeamRunOutput to nest as a workflow step executor run."""
    return TeamRunOutput(run_id=run_id, team_id="team-1", status=RunStatus.completed, messages=messages)


def _session_with(*executor_runs) -> WorkflowSession:
    """Build a WorkflowSession with one workflow run wrapping each executor run."""
    session = WorkflowSession(session_id="s1", workflow_id="w1")
    for i, executor_run in enumerate(executor_runs):
        session.upsert_run(WorkflowRunOutput(run_id=f"wf-run-{i}", step_executor_runs=[executor_run]))
    return session


def _session_with_runs(n: int) -> WorkflowSession:
    """Build a WorkflowSession with n completed workflow runs (input/output pairs)."""
    session = WorkflowSession(session_id="s1", workflow_id="w1")
    for i in range(n):
        session.upsert_run(
            WorkflowRunOutput(run_id=f"r{i}", status=RunStatus.completed, input=f"in{i}", content=f"out{i}")
        )
    return session


class TestGetMessagesLimit:
    """get_messages() must not leak the full history at the smallest limits."""

    def test_agent_limit_one_returns_only_system_message(self):
        """With a system message, limit=1 returns just the system message."""
        session = _session_with(_make_agent_run(_messages(with_system=True)))

        result = session.get_messages(agent_id="agent-1", limit=1)

        assert len(result) == 1
        assert result[0].role == "system"

    def test_agent_limit_zero_returns_empty_without_system(self):
        """Without a system message, limit=0 returns no messages."""
        session = _session_with(_make_agent_run(_messages(with_system=False)))

        assert session.get_messages(agent_id="agent-1", limit=0) == []

    def test_team_limit_one_returns_only_system_message(self):
        """With a system message, limit=1 returns just the system message."""
        session = _session_with(_make_team_run(_messages(with_system=True)))

        result = session.get_messages(team_id="team-1", limit=1)

        assert len(result) == 1
        assert result[0].role == "system"

    def test_team_limit_zero_returns_empty_without_system(self):
        """Without a system message, limit=0 returns no messages."""
        session = _session_with(_make_team_run(_messages(with_system=False)))

        assert session.get_messages(team_id="team-1", limit=0) == []


class TestGetMessagesLastNRuns:
    """last_n_runs must be honored even when a message limit is set."""

    def test_agent_last_n_runs_honored_with_limit(self):
        """last_n_runs restricts which runs contribute even when limit is set."""
        runs = [
            _make_agent_run(
                [Message(role="user", content=f"u{i}"), Message(role="assistant", content=f"a{i}")],
                run_id=f"r{i}",
            )
            for i in range(3)
        ]
        session = _session_with(*runs)

        result = session.get_messages(agent_id="agent-1", last_n_runs=1, limit=100)

        assert [m.content for m in result] == ["u2", "a2"]

    def test_agent_last_n_runs_zero_returns_empty(self):
        """last_n_runs=0 returns no messages rather than the whole history."""
        session = _session_with(_make_agent_run([Message(role="user", content="u0")], run_id="r0"))

        assert session.get_messages(agent_id="agent-1", last_n_runs=0, limit=100) == []

    def test_team_last_n_runs_honored_with_limit(self):
        """last_n_runs restricts which runs contribute even when limit is set."""
        runs = [
            _make_team_run(
                [Message(role="user", content=f"u{i}"), Message(role="assistant", content=f"a{i}")],
                run_id=f"r{i}",
            )
            for i in range(3)
        ]
        session = _session_with(*runs)

        result = session.get_messages(team_id="team-1", last_n_runs=1, limit=100)

        assert [m.content for m in result] == ["u2", "a2"]


class TestHistoryZeroCount:
    """Zero/negative run counts must return empty, not the whole history."""

    def test_get_workflow_history_zero_returns_empty(self):
        """num_runs=0 returns no history rather than all runs."""
        assert _session_with_runs(3).get_workflow_history(num_runs=0) == []

    def test_get_workflow_history_positive_is_limited(self):
        """A positive num_runs returns that many recent runs."""
        assert len(_session_with_runs(3).get_workflow_history(num_runs=2)) == 2

    def test_get_chat_history_zero_returns_empty(self):
        """last_n_runs=0 returns no history rather than all runs."""
        assert _session_with_runs(3).get_chat_history(last_n_runs=0) == []

    def test_get_chat_history_positive_is_limited(self):
        """A positive last_n_runs returns that many recent runs."""
        assert len(_session_with_runs(3).get_chat_history(last_n_runs=1)) == 1


class TestGetMessagesFromTeamRunsMemberFlag:
    """get_messages_from_team_runs must handle skip_member_messages=False."""

    def test_skip_member_messages_false_does_not_crash(self):
        """skip_member_messages=False must not raise (session_runs stays bound)."""
        run = TeamRunOutput(
            run_id="x",
            team_id="tm",
            status=RunStatus.completed,
            messages=[Message(role="user", content="hi"), Message(role="assistant", content="yo")],
        )
        session = WorkflowSession(session_id="s2", workflow_id="w2")

        result = session.get_messages_from_team_runs(team_id="tm", runs=[run], skip_member_messages=False)

        assert [m.content for m in result] == ["hi", "yo"]
