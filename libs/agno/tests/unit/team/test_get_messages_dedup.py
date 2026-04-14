"""Unit tests for TeamSession.get_messages() deduplication of member runs.

Verifies fix for GitHub issue #7341: member runs stored both as standalone
runs and inside member_responses should only appear once in get_messages output.
"""

from agno.models.message import Message
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession


def _make_member_run(agent_id: str, run_id: str) -> RunOutput:
    """Create a member RunOutput with tool call messages."""
    return RunOutput(
        run_id=run_id,
        agent_id=agent_id,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Search for AI news"),
            Message(
                role="assistant",
                content="Let me search.",
                tool_calls=[
                    {
                        "id": f"tc_{run_id}",
                        "type": "function",
                        "function": {"name": "web_search", "arguments": "{}"},
                    }
                ],
            ),
            Message(role="tool", content="Results here.", tool_call_id=f"tc_{run_id}"),
            Message(role="assistant", content="Here are the results."),
        ],
    )


def _make_team_run(team_id: str, run_id: str, member_runs: list[RunOutput]) -> TeamRunOutput:
    """Create a TeamRunOutput containing member_responses."""
    return TeamRunOutput(
        run_id=run_id,
        team_id=team_id,
        status=RunStatus.completed,
        messages=[
            Message(role="user", content="Find AI news"),
            Message(role="assistant", content="Delegating to search agent."),
        ],
        member_responses=member_runs,
    )


def _build_dual_storage_session(member_agent_id: str = "agent-001") -> TeamSession:
    """Build a session that has the dual-storage pattern: member run exists both
    as a standalone run AND inside the team run's member_responses."""
    member_run = _make_member_run(member_agent_id, "run-member-001")
    team_run = _make_team_run("team-001", "run-team-001", [member_run])

    session = TeamSession(session_id="test-session")
    session.runs = []
    session.upsert_run(member_run)
    session.upsert_run(team_run)
    return session


class TestGetMessagesMemberDedup:
    """Tests for deduplication when member runs appear in multiple locations."""

    def test_no_duplicate_messages_from_dual_storage(self):
        """Core bug: same member run in standalone + member_responses should not produce duplicates."""
        session = _build_dual_storage_session()

        messages = session.get_messages(member_ids=["agent-001"], skip_member_messages=False)

        # Should get 4 messages from the single member run, not 8
        assert len(messages) == 4
        contents = [m.content for m in messages]
        assert contents == [
            "Search for AI news",
            "Let me search.",
            "Results here.",
            "Here are the results.",
        ]

    def test_no_duplicate_tool_call_ids(self):
        """The actual API failure: duplicate tool call IDs cause 400 errors."""
        session = _build_dual_storage_session()

        messages = session.get_messages(member_ids=["agent-001"], skip_member_messages=False)

        tool_call_ids = []
        for msg in messages:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id:
                        tool_call_ids.append(tc_id)

        # Each tool call ID should appear exactly once
        assert len(tool_call_ids) == len(set(tool_call_ids)), f"Duplicate tool call IDs: {tool_call_ids}"

    def test_multiple_members_deduped_independently(self):
        """Two different members, each stored in both locations, should each appear once."""
        member_a = _make_member_run("agent-a", "run-a")
        member_b = _make_member_run("agent-b", "run-b")
        team_run = _make_team_run("team-001", "run-team-001", [member_a, member_b])

        session = TeamSession(session_id="test-session")
        session.runs = []
        session.upsert_run(member_a)
        session.upsert_run(member_b)
        session.upsert_run(team_run)

        # Filter for both members
        messages = session.get_messages(member_ids=["agent-a", "agent-b"], skip_member_messages=False)

        # 4 messages per member * 2 members = 8 total
        assert len(messages) == 8

    def test_single_member_filtered_from_multi_member_team(self):
        """Filtering for one member should not return the other member's messages."""
        member_a = _make_member_run("agent-a", "run-a")
        member_b = _make_member_run("agent-b", "run-b")
        team_run = _make_team_run("team-001", "run-team-001", [member_a, member_b])

        session = TeamSession(session_id="test-session")
        session.runs = []
        session.upsert_run(member_a)
        session.upsert_run(member_b)
        session.upsert_run(team_run)

        messages = session.get_messages(member_ids=["agent-a"], skip_member_messages=False)
        assert len(messages) == 4

    def test_run_without_run_id_still_included(self):
        """Runs without a run_id should not be dropped by dedup logic."""
        run = RunOutput(
            run_id=None,
            agent_id="agent-001",
            status=RunStatus.completed,
            messages=[Message(role="assistant", content="hello")],
        )

        session = TeamSession(session_id="test-session")
        session.runs = [run]  # type: ignore

        messages = session.get_messages(member_ids=["agent-001"], skip_member_messages=False)
        assert len(messages) == 1
        assert messages[0].content == "hello"

    def test_standalone_only_no_regression(self):
        """Member run only in standalone (no member_responses) should still work."""
        member_run = _make_member_run("agent-001", "run-member-001")
        team_run = TeamRunOutput(
            run_id="run-team-001",
            team_id="team-001",
            status=RunStatus.completed,
            messages=[Message(role="user", content="hi")],
            member_responses=[],  # empty
        )

        session = TeamSession(session_id="test-session")
        session.runs = []
        session.upsert_run(member_run)
        session.upsert_run(team_run)

        messages = session.get_messages(member_ids=["agent-001"], skip_member_messages=False)
        assert len(messages) == 4

    def test_member_responses_only_no_regression(self):
        """Member run only in member_responses (no standalone) should still work."""
        member_run = _make_member_run("agent-001", "run-member-001")
        team_run = _make_team_run("team-001", "run-team-001", [member_run])

        session = TeamSession(session_id="test-session")
        # Only the team run, no standalone member run
        session.runs = [team_run]  # type: ignore

        messages = session.get_messages(member_ids=["agent-001"], skip_member_messages=False)
        assert len(messages) == 4

    def test_multiple_delegation_turns_deduped(self):
        """Simulate two delegation turns to the same member: each turn should appear once."""
        member_run_1 = _make_member_run("agent-001", "run-member-001")
        member_run_2 = _make_member_run("agent-001", "run-member-002")
        team_run = _make_team_run("team-001", "run-team-001", [member_run_1, member_run_2])

        session = TeamSession(session_id="test-session")
        session.runs = []
        session.upsert_run(member_run_1)
        session.upsert_run(member_run_2)
        session.upsert_run(team_run)

        messages = session.get_messages(member_ids=["agent-001"], skip_member_messages=False)

        # 4 messages per turn * 2 turns = 8
        assert len(messages) == 8

        # Verify no duplicate tool call IDs
        tc_ids = []
        for msg in messages:
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    tc_id = tc.get("id") if isinstance(tc, dict) else getattr(tc, "id", None)
                    if tc_id:
                        tc_ids.append(tc_id)
        assert len(tc_ids) == len(set(tc_ids))

    def test_dedup_prefers_standalone_run(self):
        """When deduping, the standalone run (seen first) should be kept."""
        member_run = _make_member_run("agent-001", "run-member-001")
        team_run = _make_team_run("team-001", "run-team-001", [member_run])

        session = TeamSession(session_id="test-session")
        session.runs = []
        session.upsert_run(member_run)  # standalone added first
        session.upsert_run(team_run)

        messages = session.get_messages(member_ids=["agent-001"], skip_member_messages=False)

        # Verify we got exactly one copy
        assert len(messages) == 4
