"""Tests for TeamSession.get_messages deduplication (issue #7341).

When a member agent's run is stored both as a standalone run in session.runs
and inside a team run's member_responses, get_messages(member_ids=...) should
return each message exactly once.
"""

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession


def _make_member_run(run_id: str, agent_id: str, messages: list[Message]) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id=agent_id,
        parent_run_id="team-run-1",
        messages=messages,
        status=RunStatus.completed,
    )


def _make_team_run(run_id: str, team_id: str, member_responses: list[RunOutput]) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=run_id,
        team_id=team_id,
        parent_run_id=None,
        messages=[Message(role="user", content="hello")],
        member_responses=member_responses,
        status=RunStatus.completed,
    )


def test_duplicate_member_run_is_deduplicated():
    """The core bug: same member run appears as standalone AND inside member_responses."""
    member_messages = [
        Message(role="user", content="search for X"),
        Message(role="assistant", content="Here are results", tool_calls=[{"id": "fc_abc123"}]),
        Message(role="tool", content="tool result", tool_call_id="fc_abc123"),
    ]

    # The member's standalone run
    member_run = _make_member_run("member-run-1", "agent-exa", member_messages)

    # The team run that also contains a copy of the member run in member_responses
    member_run_copy = _make_member_run("member-run-1", "agent-exa", member_messages)
    team_run = _make_team_run("team-run-1", "team-coordinator", [member_run_copy])

    session = TeamSession(
        session_id="sess-1",
        runs=[member_run, team_run],
    )

    messages = session.get_messages(member_ids=["agent-exa"])

    # Each message should appear exactly once (3 messages, not 6)
    assert len(messages) == 3
    # Verify content
    contents = [m.content for m in messages]
    assert contents == ["search for X", "Here are results", "tool result"]


def test_no_duplicates_when_only_standalone_run():
    """When there's only a standalone member run, no duplication."""
    member_messages = [
        Message(role="user", content="query"),
        Message(role="assistant", content="response"),
    ]
    member_run = _make_member_run("run-1", "agent-a", member_messages)

    session = TeamSession(
        session_id="sess-1",
        runs=[member_run],
    )

    messages = session.get_messages(member_ids=["agent-a"])
    assert len(messages) == 2


def test_no_duplicates_when_only_in_member_responses():
    """When the member run only exists inside member_responses."""
    member_messages = [
        Message(role="assistant", content="done"),
    ]
    member_run = _make_member_run("run-1", "agent-a", member_messages)
    team_run = _make_team_run("team-run-1", "team-1", [member_run])

    session = TeamSession(
        session_id="sess-1",
        runs=[team_run],
    )

    messages = session.get_messages(member_ids=["agent-a"])
    assert len(messages) == 1
    assert messages[0].content == "done"


def test_multiple_different_member_runs_preserved():
    """Different member runs (different run_ids) should all be preserved."""
    run1 = _make_member_run("run-1", "agent-a", [Message(role="assistant", content="first")])
    run2 = _make_member_run("run-2", "agent-a", [Message(role="assistant", content="second")])

    team_run = _make_team_run("team-run-1", "team-1", [run1])

    session = TeamSession(
        session_id="sess-1",
        runs=[run2, team_run],
    )

    messages = session.get_messages(member_ids=["agent-a"])
    assert len(messages) == 2
    contents = [m.content for m in messages]
    assert "first" in contents
    assert "second" in contents


def test_empty_session_returns_no_messages():
    """Empty session should return empty list."""
    session = TeamSession(session_id="sess-1", runs=[])
    messages = session.get_messages(member_ids=["agent-a"])
    assert messages == []


def test_empty_runs_none_returns_no_messages():
    """Session with runs=None should return empty list."""
    session = TeamSession(session_id="sess-1", runs=None)
    messages = session.get_messages(member_ids=["agent-a"])
    assert messages == []


def test_dedup_preserves_message_ordering():
    """The standalone run appears first, so its messages should be kept (not the copy)."""
    msgs = [
        Message(role="user", content="q1"),
        Message(role="assistant", content="a1"),
    ]
    standalone = _make_member_run("run-1", "agent-a", msgs)

    copy_in_team = _make_member_run("run-1", "agent-a", msgs)
    team_run = _make_team_run("team-run-1", "team-1", [copy_in_team])

    session = TeamSession(
        session_id="sess-1",
        runs=[standalone, team_run],
    )

    messages = session.get_messages(member_ids=["agent-a"])
    assert len(messages) == 2
    assert messages[0].content == "q1"
    assert messages[1].content == "a1"


def test_multiple_members_deduplicated_independently():
    """Two different members, each duplicated, should both be deduplicated."""
    run_a = _make_member_run("run-a", "agent-a", [Message(role="assistant", content="from A")])
    run_b = _make_member_run("run-b", "agent-b", [Message(role="assistant", content="from B")])

    run_a_copy = _make_member_run("run-a", "agent-a", [Message(role="assistant", content="from A")])
    run_b_copy = _make_member_run("run-b", "agent-b", [Message(role="assistant", content="from B")])
    team_run = _make_team_run("team-run-1", "team-1", [run_a_copy, run_b_copy])

    session = TeamSession(
        session_id="sess-1",
        runs=[run_a, run_b, team_run],
    )

    messages = session.get_messages(member_ids=["agent-a", "agent-b"])
    assert len(messages) == 2
    contents = [m.content for m in messages]
    assert "from A" in contents
    assert "from B" in contents
