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
