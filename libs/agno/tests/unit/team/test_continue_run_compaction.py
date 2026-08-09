from agno.compression.context import CompactionState
from agno.models.message import Message
from agno.run.base import RunStatus
from agno.run.team import TeamRunOutput
from agno.session.team import TeamSession
from agno.team._run import _get_continue_run_messages
from agno.team.team import Team


def _team_run(
    run_id: str,
    compaction_state=None,
    forked_from_run_id=None,
) -> TeamRunOutput:
    return TeamRunOutput(
        run_id=run_id,
        team_id="team-001",
        status=RunStatus.completed,
        compaction_state=compaction_state,
        forked_from_run_id=forked_from_run_id,
        messages=[
            Message(role="user", content=f"message for {run_id}", id=f"user-{run_id}"),
            Message(role="assistant", content=f"reply for {run_id}", id=f"assistant-{run_id}"),
        ],
    )


def _message_contents(run_messages) -> list[str]:
    return [str(m.content) for m in run_messages.messages if m.content]


def test_continue_run_uses_run_response_compaction_state_directly():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    state = CompactionState(summary="Mid-loop summary", compacted_message_ids={"user-r1", "assistant-r1"})
    run1 = _team_run("r1")
    session.upsert_run(run1)
    run_response = _team_run("r2", compaction_state=state)

    run_messages = _get_continue_run_messages(
        team,
        input=run_response.messages,
        session=session,
        run_response=run_response,
        add_history_to_context=True,
    )

    contents = _message_contents(run_messages)
    assert any("Mid-loop summary" in c for c in contents)

    history_ids = {m.id for m in run_messages.messages if getattr(m, "from_history", False)}
    assert "user-r1" not in history_ids
    assert "assistant-r1" not in history_ids


def test_continue_run_point_in_time_lookup_via_forked_from_run_id():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    run1 = _team_run("r1")
    session.upsert_run(run1)

    old_state = CompactionState(summary="v3 summary", compacted_message_ids={"user-r1", "assistant-r1"})
    run3 = _team_run("r3", compaction_state=old_state)
    session.upsert_run(run3)

    run4 = _team_run("r4")
    session.upsert_run(run4)

    new_state = CompactionState(
        summary="v6 summary",
        compacted_message_ids={"user-r1", "assistant-r1", "user-r3", "assistant-r3", "user-r4", "assistant-r4"},
    )
    run6 = _team_run("r6", compaction_state=new_state)
    session.upsert_run(run6)

    # Continuing a fork taken at run3, before run6's compaction ever happened —
    # must use run3's point-in-time state, not the session's latest (run6).
    forked_run = _team_run("r3-fork", forked_from_run_id="r3")

    run_messages = _get_continue_run_messages(
        team,
        input=forked_run.messages,
        session=session,
        run_response=forked_run,
        add_history_to_context=True,
    )

    contents = _message_contents(run_messages)
    assert any("v3 summary" in c for c in contents)
    assert not any("v6 summary" in c for c in contents)

    all_ids = {m.id for m in run_messages.messages}
    assert "user-r1" not in all_ids
    assert "assistant-r1" not in all_ids
    # run3/run4's own messages were not compacted as of run3 and must survive.
    assert "user-r3" in all_ids
    assert "user-r4" in all_ids


def test_continue_run_without_compaction_state_unaffected():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    run1 = _team_run("r1")
    session.upsert_run(run1)
    run_response = _team_run("r2")

    run_messages = _get_continue_run_messages(
        team,
        input=run_response.messages,
        session=session,
        run_response=run_response,
        add_history_to_context=True,
    )

    all_ids = {m.id for m in run_messages.messages}
    assert "user-r1" in all_ids
    assert "assistant-r1" in all_ids


def test_continue_run_without_run_response_backward_compatible():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    state = CompactionState(summary="Should not be used", compacted_message_ids={"user-r1"})
    run1 = _team_run("r1", compaction_state=state)
    session.upsert_run(run1)

    run_messages = _get_continue_run_messages(
        team,
        input=[Message(role="user", content="new input", id="user-new")],
        session=session,
        add_history_to_context=True,
    )

    contents = _message_contents(run_messages)
    assert not any("Should not be used" in c for c in contents)


# ============================================================================
# Area 3: Continue-run seeding fix (team/_run.py:5350-5355)
# These test the fix where compaction_state is seeded from session when
# run_response.compaction_state is None (e.g., reconstructed in-flight object)
# ============================================================================


def test_continue_run_seeds_compaction_state_from_session():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    # r1 provides history
    session.upsert_run(_team_run("r1"))

    # r2 was persisted WITH compaction state
    persisted = CompactionState(
        summary="Persisted before pause", compacted_message_ids={"user-r1"}, total_compactions=1
    )
    session.upsert_run(_team_run("r2", compaction_state=persisted))

    # Continuation run_response reconstructed without in-memory state
    rr = _team_run("r2")
    rr.compaction_state = None

    _get_continue_run_messages(
        team,
        input=rr.messages,
        session=session,
        run_response=rr,
        add_history_to_context=True,
    )

    assert rr.compaction_state is not None
    assert rr.compaction_state.summary == "Persisted before pause"


def test_continue_run_seeded_state_is_deep_copy():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    persisted = CompactionState(summary="P", compacted_message_ids={"user-r1"})
    session.upsert_run(_team_run("r2", compaction_state=persisted))
    rr = _team_run("r2")
    rr.compaction_state = None

    _get_continue_run_messages(
        team,
        input=rr.messages,
        session=session,
        run_response=rr,
        add_history_to_context=True,
    )

    # Must be a different object
    assert rr.compaction_state is not persisted
    # Mutating seeded state must not touch persisted state
    rr.compaction_state.compacted_message_ids.add("user-extra")
    assert "user-extra" not in persisted.compacted_message_ids


def test_continue_run_existing_state_not_overwritten():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    session.upsert_run(_team_run("r2", compaction_state=CompactionState(summary="stale persisted")))
    in_memory = CompactionState(summary="fresh in-memory")
    rr = _team_run("r2", compaction_state=in_memory)

    _get_continue_run_messages(
        team,
        input=rr.messages,
        session=session,
        run_response=rr,
        add_history_to_context=True,
    )

    # In-memory state wins, not replaced by session lookup
    assert rr.compaction_state is in_memory


def test_continue_run_no_state_anywhere_stays_none():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    session.upsert_run(_team_run("r1"))
    rr = _team_run("r2")
    rr.compaction_state = None

    _get_continue_run_messages(
        team,
        input=rr.messages,
        session=session,
        run_response=rr,
        add_history_to_context=True,
    )

    assert rr.compaction_state is None


def test_continue_run_seeding_walks_back_to_earlier_run():
    team = Team(name="Test Team", members=[])
    session = TeamSession(session_id="s1")
    session.runs = []

    # r1 has compaction state, r2 does not
    session.upsert_run(_team_run("r1", compaction_state=CompactionState(summary="from r1")))
    session.upsert_run(_team_run("r2"))

    # Continuing r2 which has no state of its own -> walk-back seeds r1's state
    rr = _team_run("r2")
    rr.compaction_state = None

    _get_continue_run_messages(
        team,
        input=rr.messages,
        session=session,
        run_response=rr,
        add_history_to_context=True,
    )

    assert rr.compaction_state is not None
    assert rr.compaction_state.summary == "from r1"
