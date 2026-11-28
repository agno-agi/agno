"""A turn of Super Agent that a killed server cut leaves the person's message stored, and the next
turn is told what was cut. A turn that ends is stored as it always was."""

import asyncio
from types import SimpleNamespace

import pytest

from agno.db.base import SessionType
from agno.db.schemas.scheduler import FINISHED_WORK_REPORT_METADATA_KEY
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, OSManager
from agno.os.manager.finished_work import FINISHED_WORK_LABEL
from agno.os.manager.interrupted_turn import INTERRUPTED_REPLY, InterruptedTurns, _cut_turns
from agno.os.manager.linked_work import LINKED_WORK_KEY
from agno.os.manager.person import Person, TurnContext
from agno.run import RunContext
from agno.run.authorization import authorization_scope
from agno.run.base import RunStatus
from agno.run.cancel import cleanup_run, register_run
from agno.run.concurrency import mark_worker_managed, unmark_worker_managed
from agno.run.team import TeamRunInput, TeamRunOutput
from agno.session.team import TeamSession
from agno.team import Team
from tests.unit.os.test_company_decision_tools import (
    chat,  # noqa: F401
    person,
)
from tests.unit.os.test_super_agent_linked_work import ADD, Scripted

pytestmark = pytest.mark.usefixtures("unavailable_manager_docs")

CUT = "from the person that got no reply (from AgentOS, not written by the person)"
MODES = ["sync", "async", "sync stream", "async stream"]


@pytest.fixture(autouse=True)
def scripted_models_are_sent_the_note(monkeypatch):
    from agno.os.manager import linked_work

    monkeypatch.setattr(linked_work, "_delivers", lambda model: not getattr(model, "unlisted", False))


class Killed(BaseException):
    """The server process is killed: no handler of the run stores anything."""


class KilledAfter(Scripted):
    """Calls the scripted tools, then the process is killed while the model is asked again."""

    def invoke(self, messages, tools=None, **kwargs):
        if sum(1 for message in messages if message.role == "tool" and not message.from_history) >= len(self.script):
            raise Killed()
        return super().invoke(messages, tools, **kwargs)


def turn(team, message, mode, session="chat", **options):
    with authorization_scope(lambda: person(None)):
        if mode == "sync":
            return team.run(message, user_id="alice", session_id=session, **options)
        if mode == "async":
            return asyncio.run(team.arun(message, user_id="alice", session_id=session, **options))
        if mode == "sync stream":
            return list(team.run(message, user_id="alice", session_id=session, stream=True, **options))

        async def consume():
            return [event async for event in team.arun(message, user_id="alice", session_id=session, stream=True)]

        return asyncio.run(consume())


def cut(chat, message, mode, calls=(), session="chat"):  # noqa: F811
    chat.os.manager.model = KilledAfter(calls)
    with pytest.raises(Killed):
        turn(chat.os.manager, message, mode, session)


def stored(chat, session="chat"):  # noqa: F811
    """The conversation's own turns as the database holds them, oldest first."""
    found = chat.db.get_session(session_id=session, session_type=SessionType.TEAM)
    return [run for run in (found.runs if found is not None else None) or [] if run.parent_run_id is None]


def say(chat, message, mode, session="chat", model=None):  # noqa: F811
    """One turn that ends: the run, and the note about a cut turn the model was sent ('' for none)."""
    model = model or Scripted()
    chat.os.manager.model = model
    turn(chat.os.manager, message, mode, session)
    notes = []
    for request in model.requests:
        fresh = [str(content) for role, content, old in request if role == "user" and not old]
        # One context message right before the person's own, which is sent as they wrote it.
        assert len(fresh) == 2 and fresh[-1] == message
        notes.append(fresh[0])
    assert len(set(notes)) == 1, notes
    return notes[0] if CUT in notes[0] else ""


# ----------------------------------------------------------------- what a killed turn leaves


@pytest.mark.parametrize("mode", MODES)
def test_a_turn_killed_while_it_runs_leaves_the_message_stored_as_running(chat, mode):  # noqa: F811
    cut(chat, "Research the reminder rules and wait", mode)
    (run,) = stored(chat)
    assert run.status == RunStatus.running
    assert run.input.input_content == "Research the reminder rules and wait"
    assert not run.messages and run.content is None


# A Task is added in an asynchronous run only.
@pytest.mark.parametrize("mode", ["async", "async stream"])
def test_the_work_a_killed_turn_added_is_kept_in_the_conversation_state(chat, mode):  # noqa: F811
    cut(chat, "Add the Task, then research", mode, calls=[("add_company_task", {**ADD, "start": False})])
    (run,) = stored(chat)
    (entry,) = chat.os.manager.get_session_state(session_id="chat")[LINKED_WORK_KEY]
    assert entry["kind"] == "task" and entry["receipt_in"] == run.run_id
    assert run.status == RunStatus.running


def test_a_team_that_does_not_ask_stores_nothing_before_a_run_ends(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "team.db"))
    team = Team(id="plain", members=[], model=KilledAfter(), db=db)
    with pytest.raises(Killed):
        team.run("Hello", session_id="chat")
    found = db.get_session(session_id="chat", session_type=SessionType.TEAM)
    assert found is None or not found.runs
    db.close()


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_run_the_queue_owns_is_not_stored_in_flight(chat, mode, monkeypatch):  # noqa: F811
    from agno.team import _run

    written = []
    monkeypatch.setattr(_run, "_persist_team_run_in_session", lambda *a, **k: written.append(a))

    async def apersist(*a, **k):
        written.append(a)

    monkeypatch.setattr(_run, "_apersist_team_run_in_session", apersist)
    team = chat.os.manager
    session = TeamSession(session_id="chat", runs=[])
    run = TeamRunOutput(run_id="queued-run", session_id="chat", team_id=team.id)
    mark_worker_managed("queued-run")
    try:
        if mode == "sync":
            _run.store_team_run_in_flight(team, run, session)
        else:
            asyncio.run(_run.astore_team_run_in_flight(team, run, session))
    finally:
        unmark_worker_managed("queued-run")
    assert written == []
    run.run_id = "inline-run"
    if mode == "sync":
        _run.store_team_run_in_flight(team, run, session)
    else:
        asyncio.run(_run.astore_team_run_in_flight(team, run, session))
    assert len(written) == 1


# ----------------------------------------------------------------- a turn that ends is stored as before


def conversation(chat, mode):  # noqa: F811
    """Two turns that end, the first adding a Task: what is stored, and what the model was sent."""
    first = Scripted([("add_company_task", {**ADD, "start": False})])
    chat.os.manager.model = first
    turn(chat.os.manager, "Add the Task", mode)
    second = Scripted()
    chat.os.manager.model = second
    turn(chat.os.manager, "Thanks", mode)
    runs = [
        (
            run.status,
            run.input.input_content,
            [(message.role, message.from_history) for message in run.messages],
            [(tool.tool_name, tool.tool_call_error) for tool in run.tools or []],
            run.session_state,
            sorted(key for key, value in run.to_dict().items() if value not in (None, [], {})),
        )
        for run in stored(chat)
    ]
    sent = [[(role, old) for role, _, old in request] for request in first.requests + second.requests]
    data = chat.db.get_session(session_id="chat", session_type=SessionType.TEAM).session_data
    state = data["session_state"]
    session = (sorted(data), sorted(state), [sorted(entry) for entry in state.get(LINKED_WORK_KEY, [])])
    return runs, sent, session


@pytest.mark.parametrize("mode", MODES)
def test_turns_that_end_are_stored_and_sent_history_as_without_the_early_write(chat, mode, tmp_path):  # noqa: F811
    from tests.unit.os.test_mini_agent_tasks import System

    with_it = conversation(chat, mode)
    other = System(tmp_path / "other")
    other.os.manager._store_run_in_flight = False
    try:
        without = conversation(other, mode)
    finally:
        other.db.close()
    assert with_it == without
    assert [status for status, *_ in with_it[0]] == [RunStatus.completed, RunStatus.completed]


@pytest.mark.parametrize("mode", MODES)
def test_the_run_that_has_not_ended_takes_no_place_in_the_history_window(chat, mode):  # noqa: F811
    chat.os.manager.num_history_runs = 1
    say(chat, "First message", mode)
    model = Scripted()
    say(chat, "Second message", mode, model=model)
    history = [str(content) for role, content, old in model.requests[0] if old and role == "user"]
    assert "First message" in history


@pytest.mark.parametrize("mode", MODES)
def test_a_tool_still_reads_the_ids_of_its_run_in_the_session_state(tmp_path, mode):
    # Saving a session takes the run's ids out of the session state, and the early write saves it
    # while the run's tools still have to read them.
    seen = {}

    def whoami(run_context: RunContext) -> str:
        """Say who is asking."""
        seen.update({key: value for key, value in run_context.session_state.items() if key.startswith("current_")})
        return "ok"

    db = SqliteDb(db_file=str(tmp_path / "ids.db"))
    try:
        agent_os = AgentOS(db=db, manager=OSManager(model=Scripted(), tools=[whoami]), telemetry=False)
        agent_os.get_app()
        assert agent_os.manager._store_run_in_flight
        agent_os.manager.model = Scripted([("whoami", {})])
        turn(agent_os.manager, "Who am I?", mode)
        (run,) = [run for run in db.get_session(session_id="chat", session_type=SessionType.TEAM).runs]
        assert seen == {"current_user_id": "alice", "current_session_id": "chat", "current_run_id": run.run_id}
        # They are the run's own, and are not stored with the conversation.
        assert not set(seen) & set(agent_os.manager.get_session_state(session_id="chat"))
    finally:
        db.close()


# ----------------------------------------------------------------- the next turn


@pytest.mark.parametrize("mode", MODES)
def test_the_next_turn_is_told_what_was_cut_and_the_cut_turn_is_stored_as_failed(chat, mode):  # noqa: F811
    cut(chat, 'Research the "reminder" rules\nand wait', mode)
    note = say(chat, "Did that go through?", mode)
    assert "A message " + CUT in note
    # One line, and the person's text cannot close the quotes around it.
    assert "\"Research the 'reminder' rules and wait\"" in note
    assert "No Task or background run is recorded as added, started or read by it." in note
    assert "Nothing was run again." in note and "Do not ask them what it was." in note
    first, second = stored(chat)
    assert (first.status, first.content) == (RunStatus.error, INTERRUPTED_REPLY)
    assert first.input.input_content == 'Research the "reminder" rules\nand wait'
    assert second.status == RunStatus.completed
    # The note is sent and never stored: the stored turn holds the person's message as they wrote it.
    assert [m.content for m in second.messages if m.role == "user"] == ["Did that go through?"]


@pytest.mark.parametrize("mode", ["async", "async stream"])
def test_the_note_names_the_task_the_cut_turn_added(chat, mode):  # noqa: F811
    cut(chat, "Add the Task, then research", mode, calls=[("add_company_task", {**ADD, "start": False})])
    (task,), _ = chat.db.get_tasks(limit=10)
    note = say(chat, "Did that go through?", mode)
    assert f"Recorded as added, started or read by it before it was cut: Task {task['id']}." in note
    # The work block under it gives the Task's state now.
    assert f'- Task "Draft the notes" (id {task["id"]}' in note
    assert chat.db.get_tasks(limit=10)[1] == 1


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_once_a_later_turn_ends_the_cut_turn_is_not_named_again(chat, mode):  # noqa: F811
    cut(chat, "Research and wait", mode)
    assert say(chat, "Did that go through?", mode)
    assert say(chat, "Thanks", mode) == ""
    assert [run.status for run in stored(chat)] == [RunStatus.error, RunStatus.completed, RunStatus.completed]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_two_turns_cut_in_a_row_are_both_named_newest_first(chat, mode):  # noqa: F811
    cut(chat, "First request", mode)
    cut(chat, "Second request", mode)
    note = say(chat, "What happened?", mode)
    assert "Messages " + CUT in note
    assert note.index('"Second request"') < note.index('"First request"')
    assert [run.status for run in stored(chat)][:2] == [RunStatus.error, RunStatus.error]


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_model_that_is_not_sent_the_note_still_has_the_cut_turn_stored_as_failed(chat, mode):  # noqa: F811
    cut(chat, "Research and wait", mode)
    model = Scripted()
    model.unlisted = True
    chat.os.manager.model = model
    turn(chat.os.manager, "Did that go through?", mode)
    assert all(CUT not in str(content) for request in model.requests for _, content, _ in request)
    assert [run.status for run in stored(chat)] == [RunStatus.error, RunStatus.completed]


# ----------------------------------------------------------------- which stored runs count as cut


def a_run(run_id, status, text="Hello", **fields):
    return TeamRunOutput(
        run_id=run_id, team_id="superagent", status=status, input=TeamRunInput(input_content=text), **fields
    )


def cut_ids(runs, active=(), current="now"):
    session = SimpleNamespace(runs=runs)
    found = _cut_turns(session, RunContext(run_id=current, session_id="chat"), "superagent", set(active))
    return [(run.run_id, running) for run, running in found]


def test_a_turn_still_executing_in_this_process_is_not_cut():
    assert cut_ids([a_run("a", RunStatus.running)], active={"a"}) == []
    assert cut_ids([a_run("a", RunStatus.running)]) == [("a", True)]


def test_the_run_being_built_is_not_its_own_cut_turn():
    assert cut_ids([a_run("now", RunStatus.running)]) == []


def test_a_run_the_durable_queue_holds_is_left_to_the_queue():
    runs = [a_run("queued", RunStatus.pending, queue_attempt=0), a_run("claimed", RunStatus.running, queue_attempt=1)]
    assert cut_ids(runs) == []


def test_a_finished_work_report_and_a_members_run_are_not_the_persons_turns():
    runs = [
        a_run("report", RunStatus.running, text=FINISHED_WORK_LABEL + ". Work ended."),
        a_run("marked", RunStatus.running, metadata={FINISHED_WORK_REPORT_METADATA_KEY: {"kind": "task"}}),
        a_run("member", RunStatus.running, parent_run_id="a"),
        TeamRunOutput(run_id="other-team", team_id="crew", status=RunStatus.running),
    ]
    assert cut_ids(runs) == []


def test_the_walk_stops_at_the_newest_turn_that_ended_another_way():
    runs = [
        a_run("old", RunStatus.running),
        a_run("answered", RunStatus.completed),
        a_run("stored", RunStatus.error, content=INTERRUPTED_REPLY),
        a_run("report", RunStatus.completed, text=FINISHED_WORK_LABEL + ". Work ended."),
        a_run("new", RunStatus.running),
    ]
    assert cut_ids(runs) == [("new", True), ("stored", False)]
    # A turn that failed for its own reason ends the walk like one that was answered.
    assert cut_ids([a_run("old", RunStatus.running), a_run("failed", RunStatus.error, content="boom")]) == []


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_finished_work_report_neither_stores_nor_tells(mode):
    team = SimpleNamespace(id="superagent")
    session = SimpleNamespace(runs=[a_run("a", RunStatus.running)], session_id="chat", user_id="alice")
    report = RunContext(run_id="now", session_id="chat", metadata={FINISHED_WORK_REPORT_METADATA_KEY: True})
    turns = InterruptedTurns(lambda: team)
    note = turns.read(report, session) if mode == "sync" else asyncio.run(turns.aread(report, session))
    assert note is None and session.runs[0].status == RunStatus.running


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_registered_run_is_read_as_executing(chat, mode):  # noqa: F811
    cut(chat, "Research and wait", mode)
    (run,) = stored(chat)
    register_run(run.run_id)
    try:
        assert say(chat, "Hello again", mode) == ""
    finally:
        cleanup_run(run.run_id)
    assert stored(chat)[0].status == RunStatus.running


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_a_turn_that_ended_after_the_conversation_was_loaded_keeps_its_reply(chat, mode):  # noqa: F811
    # A second message loads the conversation while the first turn is executing, and looks for cut
    # turns after the first one ended: it holds the turn as running, and nothing executes it.
    cut(chat, "First message", mode)
    loaded = chat.db.get_session(session_id="chat", session_type=SessionType.TEAM)
    (ended,) = stored(chat)
    ended.status, ended.content = RunStatus.completed, "The answer"
    chat.db.upsert_run(run=ended, session_id="chat", user_id="alice", run_index=0)
    turns = InterruptedTurns(lambda: chat.os.manager)
    second = RunContext(run_id="second", session_id="chat", user_id="alice")
    note = turns.read(second, loaded) if mode == "sync" else asyncio.run(turns.aread(second, loaded))
    assert note is None
    (run,) = stored(chat)
    assert (run.status, run.content) == (RunStatus.completed, "The answer")


@pytest.mark.parametrize("mode", ["sync", "async"])
def test_the_note_sits_between_who_the_person_is_and_the_work(mode):
    class Part:
        def __init__(self, text):
            self.text = text

        def read(self, run_context, session=None):
            return self.text

        async def aread(self, run_context, session=None):
            return self.text

    context = TurnContext(Person(), Part("WORK"), interrupted=Part("CUT"))
    run_context = RunContext(run_id="r", session_id="s", user_id="jonah")
    text = context.read(run_context) if mode == "sync" else asyncio.run(context.aread(run_context))
    head, middle, tail = text.split("\n\n")
    assert head.startswith("Who you are talking to") and (middle, tail) == ("CUT", "WORK")
