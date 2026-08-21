import pytest

from agno.compression.context import SUMMARY_PREFIX, CompactionState
from agno.models.message import Message
from agno.run import RunContext
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._messages import _aget_run_messages, _get_run_messages
from agno.team.team import Team


def _team_run(run_id: str, compaction_state=None, parent_run_id=None) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=run_id,
        team_id="team-001",
        status=RunStatus.completed,
        compaction_state=compaction_state,
        parent_run_id=parent_run_id,
        messages=[
            Message(role="user", content=f"message for {run_id}", id=f"user-{run_id}"),
            Message(role="assistant", content=f"reply for {run_id}", id=f"assistant-{run_id}"),
        ],
    )


def _member_run(run_id: str, parent_run_id: str, compaction_state=None) -> RunOutput:
    return RunOutput(
        run_id=run_id,
        agent_id="member-001",
        status=RunStatus.completed,
        parent_run_id=parent_run_id,
        compaction_state=compaction_state,
        messages=[
            Message(role="user", content=f"member msg {run_id}", id=f"member-user-{run_id}"),
            Message(role="assistant", content=f"member reply {run_id}", id=f"member-assistant-{run_id}"),
        ],
    )


def _fresh_team() -> Team:
    return Team(name="Test Team", members=[], system_message="You are a test team.")


def _run_context() -> RunContext:
    return RunContext(run_id="rc-1", session_id="s1")


# ============================================================================
# Area 1: TeamSession.get_compaction_state() (session/team.py:106-133)
# ============================================================================


class TestGetCompactionState:
    def test_empty_session_returns_none(self):
        s = TeamSession(session_id="s1")
        assert s.get_compaction_state() is None
        s.runs = []
        assert s.get_compaction_state() is None

    def test_returns_latest_state(self):
        s = TeamSession(session_id="s1")
        s.runs = []
        s.upsert_run(_team_run("r1", CompactionState(summary="first")))
        s.upsert_run(_team_run("r2", CompactionState(summary="second")))
        st = s.get_compaction_state()
        assert st is not None and st.summary == "second"

    def test_walks_back_past_stateless_run(self):
        s = TeamSession(session_id="s1")
        s.runs = []
        s.upsert_run(_team_run("r1", CompactionState(summary="only state")))
        s.upsert_run(_team_run("r2"))
        st = s.get_compaction_state()
        assert st is not None and st.summary == "only state"

    def test_ignores_member_runs(self):
        s = TeamSession(session_id="s1")
        s.runs = []
        s.upsert_run(_team_run("r1", CompactionState(summary="team state")))
        # Member run stored AFTER team run, with its own compaction state
        s.upsert_run(_member_run("m1", parent_run_id="r1", compaction_state=CompactionState(summary="member state")))
        st = s.get_compaction_state()
        assert st.summary == "team state"

    def test_member_only_session_returns_none(self):
        s = TeamSession(session_id="s1")
        s.runs = []
        s.upsert_run(_member_run("m1", parent_run_id="rX", compaction_state=CompactionState(summary="member state")))
        assert s.get_compaction_state() is None

    def test_point_in_time_via_run_id(self):
        s = TeamSession(session_id="s1")
        s.runs = []
        s.upsert_run(_team_run("r1", CompactionState(summary="v1")))
        s.upsert_run(_team_run("r2"))
        s.upsert_run(_team_run("r3", CompactionState(summary="v3")))
        st = s.get_compaction_state(run_id="r2")
        assert st.summary == "v1"
        st3 = s.get_compaction_state(run_id="r3")
        assert st3.summary == "v3"

    def test_unknown_run_id_returns_none(self):
        s = TeamSession(session_id="s1")
        s.runs = []
        s.upsert_run(_team_run("r1", CompactionState(summary="v1")))
        assert s.get_compaction_state(run_id="nope") is None

    def test_member_run_id_lookup_returns_none(self):
        # Member runs are filtered out before index lookup, so member run_id -> None
        s = TeamSession(session_id="s1")
        s.runs = []
        s.upsert_run(_team_run("r1", CompactionState(summary="v1")))
        s.upsert_run(_member_run("m1", parent_run_id="r1", compaction_state=CompactionState(summary="member")))
        assert s.get_compaction_state(run_id="m1") is None


# ============================================================================
# Area 2: Fresh run message building (_get_run_messages, team/_messages.py)
# ============================================================================


class TestFreshRunMessageBuilding:
    def test_injects_summary_when_compaction_state_exists(self):
        team = _fresh_team()
        session = TeamSession(session_id="s1")
        session.runs = []
        session.upsert_run(
            _team_run("r1", CompactionState(summary="Prior work summary", compacted_message_ids={"user-r1"}))
        )
        rr = TeamRunOutput(run_id="r2", team_id="team-001")

        rm = _get_run_messages(
            team,
            run_response=rr,
            run_context=_run_context(),
            session=session,
            input_message="next question",
            add_history_to_context=True,
        )
        contents = [str(m.content) for m in rm.messages if m.content]
        assert any(SUMMARY_PREFIX in c and "Prior work summary" in c for c in contents)
        # Ordering: system first, then summary
        assert rm.messages[0].role == "system"
        assert SUMMARY_PREFIX in str(rm.messages[1].content)

    def test_seeds_run_response_with_deep_copy(self):
        team = _fresh_team()
        session = TeamSession(session_id="s1")
        session.runs = []
        state = CompactionState(summary="S", compacted_message_ids={"user-r1"}, total_compactions=2)
        session.upsert_run(_team_run("r1", state))
        rr = TeamRunOutput(run_id="r2", team_id="team-001")

        _get_run_messages(
            team,
            run_response=rr,
            run_context=_run_context(),
            session=session,
            input_message="q",
            add_history_to_context=True,
        )
        assert rr.compaction_state is not None
        assert rr.compaction_state.summary == "S"
        assert rr.compaction_state.total_compactions == 2
        # Deep copy: mutating seeded state must not touch session-stored state
        rr.compaction_state.compacted_message_ids.add("user-r2")
        assert "user-r2" not in state.compacted_message_ids

    def test_filters_compacted_history(self):
        team = _fresh_team()
        session = TeamSession(session_id="s1")
        session.runs = []
        session.upsert_run(_team_run("r1"))
        session.upsert_run(
            _team_run("r2", CompactionState(summary="S", compacted_message_ids={"user-r1", "assistant-r1"}))
        )
        rr = TeamRunOutput(run_id="r3", team_id="team-001")

        rm = _get_run_messages(
            team,
            run_response=rr,
            run_context=_run_context(),
            session=session,
            input_message="q",
            add_history_to_context=True,
        )
        ids = {m.id for m in rm.messages if m.id}
        assert "user-r1" not in ids and "assistant-r1" not in ids
        assert "user-r2" in ids and "assistant-r2" in ids

    def test_no_prior_compaction_no_effect(self):
        team = _fresh_team()
        session = TeamSession(session_id="s1")
        session.runs = []
        session.upsert_run(_team_run("r1"))
        rr = TeamRunOutput(run_id="r2", team_id="team-001")

        rm = _get_run_messages(
            team,
            run_response=rr,
            run_context=_run_context(),
            session=session,
            input_message="q",
            add_history_to_context=True,
        )
        contents = [str(m.content) for m in rm.messages if m.content]
        assert not any(SUMMARY_PREFIX in c for c in contents)
        assert rr.compaction_state is None
        ids = {m.id for m in rm.messages if m.id}
        assert "user-r1" in ids and "assistant-r1" in ids

    def test_member_state_not_injected(self):
        team = _fresh_team()
        session = TeamSession(session_id="s1")
        session.runs = []
        session.upsert_run(_team_run("r1"))
        session.upsert_run(
            _member_run("m1", parent_run_id="r1", compaction_state=CompactionState(summary="member secret"))
        )
        rr = TeamRunOutput(run_id="r2", team_id="team-001")

        rm = _get_run_messages(
            team,
            run_response=rr,
            run_context=_run_context(),
            session=session,
            input_message="q",
            add_history_to_context=True,
        )
        contents = [str(m.content) for m in rm.messages if m.content]
        assert not any("member secret" in c for c in contents)
        assert rr.compaction_state is None

    @pytest.mark.asyncio
    async def test_async_injects_summary_and_filters_history(self):
        team = _fresh_team()
        session = TeamSession(session_id="s1")
        session.runs = []
        state = CompactionState(summary="Async summary", compacted_message_ids={"user-r1", "assistant-r1"})
        session.upsert_run(_team_run("r1"))
        session.upsert_run(_team_run("r2", state))
        rr = TeamRunOutput(run_id="r3", team_id="team-001")

        rm = await _aget_run_messages(
            team,
            run_response=rr,
            run_context=_run_context(),
            session=session,
            input_message="q",
            add_history_to_context=True,
        )
        contents = [str(m.content) for m in rm.messages if m.content]
        assert any("Async summary" in c for c in contents)
        ids = {m.id for m in rm.messages if m.id}
        assert "user-r1" not in ids
        assert rr.compaction_state is not None and rr.compaction_state.summary == "Async summary"
