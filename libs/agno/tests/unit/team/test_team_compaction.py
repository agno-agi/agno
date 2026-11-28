"""Conversation compaction on a Team: the team leader's history is folded the way an Agent's is."""

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from agno.agent import Agent
from agno.compaction import Compaction, CompactionStatus
from agno.compaction.archive import CompactionArchive
from agno.compaction.prompts import SUMMARY_PREFIX
from agno.db.sqlite import SqliteDb
from agno.metrics import MessageMetrics
from agno.models.message import Message
from agno.models.response import ModelResponse
from agno.run.team import TeamRunOutput
from agno.session import AgentSession, TeamSession
from agno.team import Team
from agno.team import _compaction as team_compaction
from agno.team.mode import TeamMode
from tests.unit.compaction.test_compaction import (
    _RecordingModel,
    _StubModel,
    pause_after_a_refused_request,
    refusing_model,
    sends_the_summary_not_the_folded_turns,
)

MODES = ["run", "stream", "arun", "astream"]
PAD = "pad " * 300


class _Summarizer(_StubModel):
    """A summarizer for sync and async runs that keeps everything it was asked to summarize."""

    def __init__(self):
        self.asked = []

    def response(self, messages, **kwargs):
        self.asked.append(messages[-1].content)
        return ModelResponse(content="SUMMARY OF THE EARLIER TURNS")

    async def aresponse(self, messages, **kwargs):
        return self.response(messages)


def _db():
    return SqliteDb(db_file=str(Path(tempfile.mkdtemp()) / "team.db"))


def _leader(delegate=False, overflow_on=None):
    """The team leader's model. It records each request and the tools it was offered.

    ``delegate`` makes every run hand one task to the member before it answers. ``overflow_on``
    names the request, counted from 1, that is refused as too long.
    """
    from agno.exceptions import ContextWindowExceededError

    model = _RecordingModel.build()
    model.offered = []
    model.calls = 0

    def reply(messages):
        fresh = [m for m in messages if not m.from_history]
        if delegate and not any(m.role == "tool" for m in fresh):
            arguments = json.dumps({"member_id": "m1", "task": "look it up"})
            call = {"id": f"call-{model.calls}", "type": "function"}
            call["function"] = {"name": "delegate_task_to_member", "arguments": arguments}
            return ModelResponse(role="assistant", tool_calls=[call], response_usage=MessageMetrics())
        return ModelResponse(role="assistant", content="leader answer", response_usage=MessageMetrics())

    def invoke(*args, **kwargs):
        model.calls += 1
        messages = list(kwargs.get("messages") or [])
        model.requests.append(messages)
        model.offered.append({tool["function"]["name"] for tool in kwargs.get("tools") or []})
        if overflow_on == model.calls:
            raise ContextWindowExceededError("prompt is too long")
        return reply(messages)

    async def ainvoke(*args, **kwargs):
        return invoke(*args, **kwargs)

    def invoke_stream(*args, **kwargs):
        yield invoke(*args, **kwargs)

    async def ainvoke_stream(*args, **kwargs):
        yield invoke(*args, **kwargs)

    model.invoke, model.ainvoke = invoke, ainvoke
    model.invoke_stream, model.ainvoke_stream = invoke_stream, ainvoke_stream
    model._parse_provider_response = lambda response, **kwargs: response
    model._parse_provider_response_delta = lambda response: response
    return model


def _searching_leader(overflow_on, pattern):
    """A leader whose request ``overflow_on`` is refused as too long, and that searches the compacted
    history for ``pattern`` in the request sent again. ``found`` holds what the search returned."""
    model = _leader(overflow_on=overflow_on)
    model.found = []
    answer = model.invoke

    def invoke(*args, **kwargs):
        response = answer(*args, **kwargs)
        results = [str(m.content) for m in kwargs.get("messages") or [] if m.role == "tool" and not m.from_history]
        if model.calls == overflow_on + 1 and not results:
            call = {"id": "call-search", "type": "function"}
            call["function"] = {"name": "search_compacted_history", "arguments": json.dumps({"pattern": pattern})}
            return ModelResponse(role="assistant", tool_calls=[call], response_usage=MessageMetrics())
        model.found += results
        return response

    async def ainvoke(*args, **kwargs):
        return invoke(*args, **kwargs)

    model.invoke, model.ainvoke = invoke, ainvoke
    return model


def _folding(**settings):
    settings.setdefault("compact_at_tokens", 2_000)
    settings.setdefault("uncompacted_runs", 2)
    settings.setdefault("model", _Summarizer())
    return Compaction(**settings)


def _team(model=None, db=None, **settings):
    settings.setdefault("members", [Agent(id="m1", name="M1", model=_RecordingModel.build())])
    return Team(
        id="t",
        model=model or _leader(),
        db=db or _db(),
        session_id="s",
        add_history_to_context=True,
        **settings,
    )


def _say(team, text, mode="run"):
    """One turn in the given mode. Returns the events a streamed turn yielded."""
    if mode == "run":
        team.run(text)
        return []
    if mode == "stream":
        return list(team.run(text, stream=True, stream_events=True))
    if mode == "arun":
        asyncio.run(team.arun(text))
        return []

    async def stream():
        return [event async for event in team.arun(text, stream=True, stream_events=True)]

    return asyncio.run(stream())


def _talk(team, turns, mode="run", start=0):
    events = []
    for i in range(start, start + turns):
        events += _say(team, f"question {i} {PAD}", mode)
    return events


def _rows(team):
    return team.db.get_compactions_for_session("s")


def _texts(request):
    return [str(m.content) for m in request]


def _summaries(request):
    return [m for m in request if m.role == "user" and str(m.content).startswith(SUMMARY_PREFIX)]


# ----------------------------------------------------------------- off by default


def test_compaction_is_off_by_default_and_nothing_changes():
    """A Team that does not ask for compaction replays num_history_runs, folds nothing, stores no
    record and offers no search tool."""
    team = _team(num_history_runs=3)
    assert team.compaction is None

    _talk(team, 8)

    last = team.model.requests[-1]
    assert [m.role for m in last] == ["system"] + ["user", "assistant"] * 3 + ["user"]
    assert _summaries(last) == []
    assert _rows(team) == []
    assert all("search_compacted_history" not in offered for offered in team.model.offered)


def test_without_compaction_the_history_read_is_the_one_a_team_always_made():
    team = _team(num_history_runs=2, num_history_messages=None)
    _talk(team, 5)
    session = team.get_session(session_id="s")

    history, record, replay_ids = team_compaction.history_for_run(team, session, None)

    assert [m.id for m in history] == [m.id for m in session.get_messages(last_n_runs=2, skip_roles=["system"])]
    assert record is None and replay_ids is None


def test_compaction_false_is_off():
    team = _team(compaction=False)
    _talk(team, 2)
    assert team.compaction is None


def test_true_folds_only_on_overflow_and_does_not_widen_the_replay():
    team = _team(compaction=True, num_history_runs=3)
    _talk(team, 8)

    assert team.compaction.compact_at_tokens is None and team.compaction.on_context_overflow is True
    assert [m.role for m in team.model.requests[-1]] == ["system"] + ["user", "assistant"] * 3 + ["user"]
    assert _rows(team) == []


def test_the_summary_model_defaults_to_the_teams():
    team = _team(compaction=Compaction(compact_at_tokens=3_000))
    _talk(team, 1)
    assert team.compaction.model is team.model


def test_a_database_that_stores_no_records_turns_compaction_off():
    from agno.db.in_memory import InMemoryDb

    team = _team(db=InMemoryDb(), compaction=_folding())
    assert team.compaction is None


def test_a_copy_of_the_team_keeps_its_compaction():
    team = _team(compaction=_folding())
    copy = team.deep_copy()
    assert isinstance(copy.compaction, Compaction)
    assert copy.compaction.compact_at_tokens == 2_000


# ----------------------------------------------------------------- the fold


@pytest.mark.parametrize("mode", MODES)
def test_a_long_conversation_is_folded_into_a_summary_and_the_originals_are_stored(mode):
    team = _team(compaction=_folding())
    _talk(team, 8, mode)

    rows = _rows(team)
    assert rows, "the leader's history crossed the threshold and was never folded"
    last = team.model.requests[-1]
    assert len(_summaries(last)) == 1
    assert "SUMMARY OF THE EARLIER TURNS" in _summaries(last)[0].content
    # The summary stands where the old turns were: right after the system message.
    assert last[1] is _summaries(last)[0]
    sent = "\n".join(_texts(last))
    assert "question 0 " not in sent and "question 7 " in sent
    # Nothing is lost: the folded turns are stored as they were.
    archived = "\n".join(row["archived_messages"] or "" for row in rows)
    assert "question 0 " in archived
    assert all(row["run_id"] for row in rows)


@pytest.mark.parametrize("mode", MODES)
def test_the_stored_conversation_is_never_changed(mode):
    team = _team(compaction=_folding())
    _talk(team, 8, mode)

    stored = team.get_session(session_id="s").get_messages()
    assert [m.content for m in stored if m.role == "user"] == [f"question {i} {PAD}" for i in range(8)]
    assert not any(str(m.content).startswith(SUMMARY_PREFIX) for m in stored)


def test_a_fold_is_replayed_and_not_paid_for_again():
    team = _team(compaction=_folding())
    _talk(team, 8)
    summarizer = team.compaction.model
    made = len(_rows(team))
    assert made >= 1
    calls = len(summarizer.asked)

    # A fresh Team over the same database, as another server process would build it.
    again = _team(db=team.db, compaction=_folding(compact_at_tokens=1_000_000, model=summarizer))
    _say(again, "one more")

    assert len(summarizer.asked) == calls and len(_rows(again)) == made
    assert len(_summaries(again.model.requests[-1])) == 1


def test_a_threshold_owns_the_window_so_turns_past_num_history_runs_are_still_sent():
    """With compact_at_tokens the threshold is the limit: every turn since the last fold is sent."""
    team = _team(compaction=_folding(compact_at_tokens=1_000_000), num_history_runs=2)
    _talk(team, 6)

    sent = "\n".join(_texts(team.model.requests[-1]))
    assert all(f"question {i} " in sent for i in range(6))
    assert _rows(team) == []


def test_the_next_fold_carries_the_previous_summary_forward():
    team = _team(compaction=_folding())
    _talk(team, 12)

    assert len(_rows(team)) >= 2
    assert (
        "Summary of the conversation before this point:\nSUMMARY OF THE EARLIER TURNS"
        in team.compaction.model.asked[-1]
    )


def test_the_run_reports_its_compaction_and_keeps_it_when_stored():
    team = _team(compaction=_folding())
    _talk(team, 8)
    runs = [run for run in team.get_session(session_id="s").runs if run.compaction is not None]

    assert runs, "no run reports the fold it made"
    record = runs[-1].compaction
    assert record.messages_compacted > 0 and record.archived is True
    assert record.tokens_after < record.tokens_before
    restored = TeamRunOutput.from_dict(runs[-1].to_dict())
    assert restored.compaction.id == record.id and restored.compaction.summary == record.summary


@pytest.mark.parametrize("mode", ["stream", "astream"])
def test_a_streamed_run_announces_its_compaction(mode):
    team = _team(compaction=_folding())
    events = [event for event in _talk(team, 8, mode) if "Compaction" in event.event]

    assert [event.event for event in events[:2]] == ["TeamCompactionStarted", "TeamCompactionCompleted"]
    completed = events[1]
    assert completed.team_id == "t" and completed.messages_compacted > 0
    assert completed.tokens_after < completed.tokens_before and completed.archived is True


def test_a_continued_run_replays_the_fold_and_makes_no_new_one():
    from agno.team._run import _build_continue_run_messages

    team = _team(compaction=_folding())
    _talk(team, 8)
    made = len(_rows(team))
    session = team.get_session(session_id="s")

    built = _build_continue_run_messages(team, [Message(role="user", content="go on")], session, True)

    assert len(_summaries(built.messages)) == 1 and built.messages[-1].content == "go on"
    assert "question 0 " not in "\n".join(_texts(built.messages))
    assert len(_rows(team)) == made


def _leader_runs(team):
    return [run for run in team.get_session(session_id="s").runs if run.parent_run_id is None]


def test_a_regenerated_run_replays_the_fold_its_source_run_inherited():
    """Most runs make no fold and inherit an earlier one. Regenerating such a run sends the
    summary it was sent, not the whole conversation from the first turn."""
    team = _team(compaction=_folding())
    _talk(team, 8)
    last = _leader_runs(team)[-1]
    assert _rows(team) and all(row["run_id"] != last.run_id for row in _rows(team))
    original = team.model.requests[-1]
    assert len(_summaries(original)) == 1

    team.continue_run(run_id=last.run_id, session_id="s", regenerate=True)

    regenerated = team.model.requests[-1]
    assert len(_summaries(regenerated)) == 1
    assert _texts(regenerated) == _texts(original)


def test_a_run_before_the_first_fold_is_regenerated_without_the_summary():
    """The fold a run saw is never one made after it: that summarizes turns it never had."""
    team = _team(compaction=_folding())
    _talk(team, 2)
    early = _leader_runs(team)[-1]
    _talk(team, 6, start=2)
    assert _rows(team)

    team.continue_run(run_id=early.run_id, session_id="s", regenerate=True, replace_original=False)

    assert _summaries(team.model.requests[-1]) == []


def test_the_fold_a_run_saw_is_the_newest_made_at_or_before_it():
    def row(compaction_id, run_id, created_at):
        return {
            "compaction_id": compaction_id,
            "session_id": "s",
            "run_id": run_id,
            "user_id": None,
            "first_kept_message_id": "m",
            "summary": compaction_id,
            "archived_messages": None,
            "messages_compacted": 2,
            "tokens_before": 900,
            "tokens_after": 100,
            "created_at": created_at,
        }

    db = _db()
    for record in [row("by-run-2", "run-2", 200), row("manual", None, 350), row("by-run-5", "run-5", 500)]:
        db.upsert_compaction(record)
    archive = CompactionArchive(db, "s")

    assert archive.latest()["compaction_id"] == "by-run-5"
    # Run 3 made no fold: it saw the one run 2 made.
    assert archive.latest("run-3", ["run-1", "run-2"], 300)["compaction_id"] == "by-run-2"
    # A manual fold has no run, so the time it was made places it: before run 4 began.
    assert archive.latest("run-4", ["run-1", "run-2", "run-3"], 400)["compaction_id"] == "manual"
    assert archive.latest("run-5", ["run-1", "run-2", "run-3", "run-4"], 500)["compaction_id"] == "by-run-5"
    assert archive.latest("run-1", [], 100) is None
    # A run that is not in the session resolves only its own fold, as before.
    assert archive.latest("run-2")["compaction_id"] == "by-run-2"
    assert archive.latest("run-3") is None


# ----------------------------------------------------------------- the search tool


@pytest.mark.parametrize("mode", ["run", "arun"])
def test_the_search_tool_finds_what_the_summary_dropped(mode):
    team = _team(compaction=_folding())
    _say(team, f"The build hash is 9f3c2ab and the port is 5532. {PAD}", mode)

    _talk(team, 8, mode)
    assert _rows(team)
    assert "search_compacted_history" in team.model.offered[-1]

    (search,) = team_compaction.search_tools(team, team.get_session(session_id="s"), TeamRunOutput(run_id="later"))
    found = search("build hash")
    assert "9f3c2ab" in found and "5532" in found
    assert search("no such thing anywhere").startswith("No compacted history matches")


@pytest.mark.parametrize("mode", MODES)
def test_the_run_that_makes_the_first_fold_can_search_it(mode):
    """A run's tools are built before the run folds. The summary says to search what was folded,
    so the request that first carries a summary must carry the search tool too."""
    team = _team(compaction=_folding())
    _talk(team, 8, mode)

    first = next(i for i, request in enumerate(team.model.requests) if _summaries(request))
    assert "is stored and searchable" in _summaries(team.model.requests[first])[0].content
    assert "search_compacted_history" in team.model.offered[first]


@pytest.mark.parametrize("mode", ["run", "arun"])
def test_the_retry_after_a_refused_request_can_search_what_it_folded(mode):
    model = _leader(overflow_on=7)
    team = _team(model=model, compaction=Compaction(on_context_overflow=True, model=_Summarizer()), num_history_runs=6)
    _talk(team, 7, mode)

    assert len(_summaries(model.requests[7])) == 1
    assert "search_compacted_history" in model.offered[7]


@pytest.mark.parametrize("mode", ["run", "arun"])
def test_the_run_that_folds_after_a_refused_request_finds_that_fold(mode):
    """compaction=True folds only after a refused request, and that fold is often anchored on the
    run's own question, which the session does not hold until the run is stored. The request sent
    again carries a summary that says to search, so the search has to find the fold just made."""
    model = _searching_leader(overflow_on=4, pattern="9f3c2ab")
    team = _team(model=model, compaction=Compaction(on_context_overflow=True, model=_Summarizer()))
    _say(team, f"The build hash is 9f3c2ab. {PAD}", mode)
    _talk(team, 2, mode)

    _say(team, "Here is a long document. " + PAD * 12, mode)

    (row,) = _rows(team)
    question = [m for m in model.requests[4] if m.role == "user" and not m.from_history][-1]
    assert row["first_kept_message_id"] == question.id
    (found,) = model.found
    assert "9f3c2ab" in found and not found.startswith("No compacted history matches")


def test_search_can_be_switched_off():
    team = _team(compaction=_folding(search_compacted_messages=False))
    _talk(team, 8)

    assert _rows(team)
    assert all("search_compacted_history" not in offered for offered in team.model.offered)


# ----------------------------------------------------------------- the leader and its members


def test_only_the_leaders_conversation_is_compacted():
    """A member's answer is folded as the result of the delegation call. The member's own run is
    not: it is never summarized, never archived, and the member is never sent a summary."""
    member_model = _RecordingModel.build()
    member = Agent(id="m1", name="M1", model=member_model)
    team = _team(model=_leader(delegate=True), members=[member], compaction=_folding())
    _talk(team, 8)

    rows = _rows(team)
    assert rows
    archived = "\n".join(row["archived_messages"] or "" for row in rows)
    assert "## tool (delegate_task_to_member)" in archived
    leader_ids = {m.id for m in team.get_session(session_id="s").get_messages()}
    assert all(row["first_kept_message_id"] in leader_ids for row in rows)
    assert member_model.requests and not any(_summaries(request) for request in member_model.requests)


def _foreign_row(
    db, summary="A MEMBER'S SUMMARY", archived="## user\n\nthe member's private text", anchor="a-member-message"
):
    """A fold another conversation of the same session stored: a member's, anchored on its own message."""
    import time

    db.upsert_compaction(
        {
            "compaction_id": "member-fold",
            "session_id": "s",
            "run_id": "member-run",
            "user_id": None,
            "first_kept_message_id": anchor,
            "summary": summary,
            "archived_messages": archived,
            "messages_compacted": 4,
            "tokens_before": 900,
            "tokens_after": 100,
            "created_at": int(time.time()) + 3_600,
        }
    )


@pytest.mark.parametrize("mode", ["run", "arun"])
def test_the_leader_does_not_read_a_fold_a_member_stored_in_the_same_session(mode):
    """Records are stored by session, and a Team and its members share one. The newest record of
    the session can be a member's: the leader must keep replaying its own."""
    team = _team(compaction=_folding())
    _talk(team, 8, mode)
    own = len(_rows(team))
    assert own >= 1
    _foreign_row(team.db)

    _talk(team, 8, mode, start=8)

    last = team.model.requests[-1]
    assert len(_summaries(last)) == 1 and "A MEMBER'S SUMMARY" not in "\n".join(_texts(last))
    assert not any("A MEMBER'S SUMMARY" in asked for asked in team.compaction.model.asked)
    # The leader went on folding from where it was, and did not start again from the first turn.
    newest = [row for row in _rows(team) if row["compaction_id"] != "member-fold"][0]
    assert "question 0 " not in (newest["archived_messages"] or "")
    (search,) = team_compaction.search_tools(team, team.get_session(session_id="s"), TeamRunOutput(run_id="later"))
    assert search("private text").startswith("No compacted history matches")


class _LeaderSummarizer(_Summarizer):
    def response(self, messages, **kwargs):
        super().response(messages)
        return ModelResponse(content="THE LEADER'S SUMMARY")


def _team_whose_member_folds(leader_compaction):
    """A team whose leader delegates every turn to a member with compaction of its own. The member's
    fifth request is refused as too long, so the member folds its own conversation once."""
    db = _db()
    member = Agent(
        id="m1",
        name="M1",
        model=_leader(overflow_on=5),
        db=db,
        add_history_to_context=True,
        num_history_runs=6,
        compaction=Compaction(on_context_overflow=True, model=_Summarizer()),
    )
    team = _team(model=_leader(delegate=True), db=db, members=[member], compaction=leader_compaction)
    _say(team, f"The build hash is 9f3c2ab. {PAD}")
    _talk(team, 8)
    return team, member


def _member_search(member):
    """The search tool a later run of the member is given. A member's run holds a session with no
    runs: its runs are stored in the team's session."""
    from agno.agent._tools import get_tools
    from agno.run import RunContext
    from agno.run.agent import RunOutput

    session = AgentSession(session_id="s", agent_id=member.id)
    tools = get_tools(
        member, RunOutput(run_id="later", session_id="s"), RunContext(run_id="later", session_id="s"), session
    )
    (search,) = [tool for tool in tools if getattr(tool, "__name__", None) == "search_compacted_history"]
    return search


def test_a_member_does_not_read_the_leaders_fold():
    """A member folding its own messages after a refused request must not take the leader's summary
    as the summary it continues from."""
    team, member = _team_whose_member_folds(_folding(model=_LeaderSummarizer()))

    summaries = [row["summary"] for row in _rows(team)]
    assert "THE LEADER'S SUMMARY" in summaries and "SUMMARY OF THE EARLIER TURNS" in summaries
    (asked,) = member.compaction.model.asked
    assert "THE LEADER'S SUMMARY" not in asked


def test_a_member_searches_its_own_folds_and_never_the_leaders():
    """A member with compaction of its own runs in the leader's session. Its search tool reads the
    folds the member made, on later runs too, and what the leader was told stays with the leader."""
    team, member = _team_whose_member_folds(_folding())
    assert "9f3c2ab" in "\n".join(row["archived_messages"] or "" for row in _rows(team))
    assert all("search_compacted_history" in offered for offered in member.model.offered)

    search = _member_search(member)

    assert "look it up" in search("look it up")
    assert search("build hash").startswith("No compacted history matches")


def test_a_member_without_a_fold_finds_nothing_in_the_leaders():
    team = _team(model=_leader(delegate=True), compaction=_folding())
    _say(team, f"The build hash is 9f3c2ab. {PAD}")
    _talk(team, 8)
    member = Agent(id="m1", name="M1", model=_RecordingModel.build(), db=team.db, compaction=_folding())
    member.team_id = "t"
    member.initialize_agent()

    assert _member_search(member)("build hash").startswith("No compacted history matches")


def test_a_nested_team_searches_its_own_folds():
    """A team that is a member runs with a session that holds no runs, like a member agent."""
    db = _db()
    nested = Team(
        id="m1",
        name="Nested",
        model=_leader(overflow_on=5),
        db=db,
        add_history_to_context=True,
        num_history_runs=6,
        members=[Agent(id="leaf", name="Leaf", model=_RecordingModel.build())],
        compaction=Compaction(on_context_overflow=True, model=_Summarizer()),
    )
    team = _team(model=_leader(delegate=True), db=db, members=[nested])
    _talk(team, 8)
    assert len(_rows(team)) == 1

    session = TeamSession(session_id="s", team_id="m1")
    (search,) = team_compaction.search_tools(nested, session, TeamRunOutput(run_id="later"))

    assert "look it up" in search("look it up")


def test_the_archive_reads_only_the_records_anchored_on_the_named_messages():
    db = _db()
    _foreign_row(db)

    assert CompactionArchive(db, "s").latest()["compaction_id"] == "member-fold"
    assert CompactionArchive(db, "s", message_ids={"a-member-message"}).latest()["compaction_id"] == "member-fold"
    assert CompactionArchive(db, "s", message_ids={"another"}).latest() is None
    assert len(CompactionArchive(db, "s", message_ids={"a-member-message"}).search("private")) == 1
    assert CompactionArchive(db, "s", message_ids=set()).search("private") == []


def test_the_archive_also_reads_the_records_its_own_run_made():
    """A fold a run makes is anchored on a message the session does not hold until the run is
    stored. An archive held for that run, as a search tool's is, reads it by its run id."""
    db = _db()
    _foreign_row(db)

    assert len(CompactionArchive(db, "s", message_ids=set(), run_id="member-run").search("private")) == 1
    assert CompactionArchive(db, "s", message_ids=set(), run_id="another-run").search("private") == []
    # Without the ids of a conversation every record of the session is read, whatever the run.
    assert len(CompactionArchive(db, "s", run_id="another-run").search("private")) == 1


def test_the_archive_reads_its_message_ids_each_time_when_given_a_function():
    db = _db()
    _foreign_row(db)
    stored = set()
    archive = CompactionArchive(db, "s", message_ids=lambda: stored)

    assert archive.latest() is None
    stored.add("a-member-message")
    assert archive.latest()["compaction_id"] == "member-fold"


# ----------------------------------------------------------------- overflow


class _Note:
    """Stands in for the context a Team adds to a run and does not store."""

    TEXT = "Work this conversation started: nothing is running."

    def read(self, run_context, session):
        return self.TEXT

    async def aread(self, run_context, session):
        return self.TEXT


@pytest.mark.parametrize("mode", MODES)
def test_a_request_refused_as_too_long_is_folded_and_sent_again(mode):
    # Six turns, then the seventh turn's request is refused once.
    model = _leader(overflow_on=7)
    team = _team(model=model, compaction=Compaction(on_context_overflow=True, model=_Summarizer()), num_history_runs=6)
    team._message_context = _Note()
    _talk(team, 7, mode)

    refused, retried = model.requests[6], model.requests[7]
    assert len(model.requests) == 8
    assert len(_summaries(retried)) == 1 and len(retried) < len(refused) + 1
    assert "question 0 " not in "\n".join(_texts(retried))
    (row,) = _rows(team)
    assert row["run_id"] and "question 0 " in row["archived_messages"]
    # The unstored context stays with the person's message, and is not folded or stored.
    assert [m.content for m in retried[-2:]] == [_Note.TEXT, f"question 6 {PAD}"]
    assert _Note.TEXT not in row["archived_messages"]
    assert _Note.TEXT not in team.compaction.model.asked[-1]
    # The turn that was refused is stored like any other.
    stored = team.get_session(session_id="s").get_messages()
    assert [m.content for m in stored if m.role == "user"][-1] == f"question 6 {PAD}"


@pytest.mark.parametrize("mode", MODES)
def test_a_refused_request_is_not_folded_in_tasks_mode(mode):
    """A tasks run adds a user message with the task state on every iteration, which a fold would
    take for the start of the current exchange. So a refused request is not folded and sent again:
    the run ends as it would without compaction, and nothing is stored as folded."""
    model = _leader(overflow_on=7)
    team = _team(
        model=model,
        compaction=Compaction(on_context_overflow=True, model=_Summarizer()),
        num_history_runs=6,
        mode=TeamMode.tasks,
        max_iterations=1,
    )
    _talk(team, 7, mode)

    assert len(model.requests) == 7
    assert _rows(team) == []
    assert team.compaction.model.asked == []


def test_the_unstored_context_is_kept_out_of_an_overflow_fold_that_reaches_the_newest_turn():
    """With one run kept, the cut lands on the person's newest message, right behind the context."""

    class _RunMessages:
        def __init__(self, messages):
            self.messages = messages

    messages = [Message(role="system", content="sys")]
    for i in range(6):
        messages += [Message(role="user", content=f"q{i} {PAD}"), Message(role="assistant", content=f"a{i} {PAD}")]
    note = Message(role="user", content=_Note.TEXT, add_to_agent_memory=False)
    messages += [note, Message(role="user", content="the newest question")]
    team = _team(
        compaction=Compaction(
            on_context_overflow=True, uncompacted_runs=1, store_compacted_messages=False, model=_Summarizer()
        )
    )
    team.initialize_team()
    run_messages = _RunMessages(messages)

    assert team_compaction.recompact_after_overflow(team, TeamSession(session_id="s", runs=[]), run_messages) is True
    assert run_messages.messages is messages
    assert [m.content for m in messages[-2:]] == [_Note.TEXT, "the newest question"] and messages[-2] is note
    assert _Note.TEXT not in team.compaction.model.asked[-1]


@pytest.mark.parametrize("use_async", [False, True])
def test_a_run_folded_on_its_own_question_continues_and_regenerates(use_async):
    """The Team twin of the Agent test: a leader run paused after a fold anchored on its own
    question is continued from the db and regenerated with the summary, not the folded turns."""
    from agno.run.base import RunStatus
    from agno.tools import tool

    @tool(requires_confirmation=True)
    def delete() -> str:
        """Delete it."""
        return "deleted"

    team = _team(
        model=refusing_model(2000, "delete"),
        tools=[delete],
        num_history_runs=6,
        compaction=Compaction(on_context_overflow=True, uncompacted_runs=1, model=_Summarizer()),
    )
    paused = pause_after_a_refused_request(team)

    kwargs = dict(run_id=paused.run_id, requirements=paused.requirements, session_id="s")
    continued = asyncio.run(team.acontinue_run(**kwargs)) if use_async else team.continue_run(**kwargs)
    assert continued.status == RunStatus.completed, continued.content
    assert sends_the_summary_not_the_folded_turns(team.model.requests[-1])

    kwargs = dict(run_id=paused.run_id, session_id="s", regenerate=True)
    regenerated = asyncio.run(team.acontinue_run(**kwargs)) if use_async else team.continue_run(**kwargs)
    assert regenerated.status == RunStatus.completed, regenerated.content
    assert sends_the_summary_not_the_folded_turns(team.model.requests[-1])


def test_overflow_recovery_does_nothing_without_compaction():
    class _RunMessages:
        messages = [Message(role="user", content="q")]

    team = _team()
    assert team_compaction.recompact_after_overflow(team, None, _RunMessages()) is False
    assert asyncio.run(team_compaction.arecompact_after_overflow(team, None, _RunMessages())) is False


# ----------------------------------------------------------------- compact() and acompact()


def _compact(team, use_async, **kwargs):
    if use_async:
        return asyncio.run(team.acompact(session_id="s", **kwargs))
    return team.compact(session_id="s", **kwargs)


@pytest.mark.parametrize("use_async", [False, True])
def test_compact_folds_now_without_waiting_for_the_threshold(use_async):
    team = _team(compaction=_folding(compact_at_tokens=None, uncompacted_runs=1))
    _talk(team, 4)
    assert _rows(team) == []

    result = _compact(team, use_async)

    assert result.compacted and result.status == CompactionStatus.COMPACTED
    assert result.record.messages_compacted == 6 and result.record.archived
    _say(team, "and now?")
    last = team.model.requests[-1]
    assert len(_summaries(last)) == 1 and "question 0 " not in "\n".join(_texts(last))


@pytest.mark.parametrize("use_async", [False, True])
def test_compact_works_on_a_team_that_has_not_run_yet(use_async):
    """compaction=True is resolved when the team is initialized. A server that restarts and
    compacts a stored session has not run the team first."""
    earlier = _team()
    _talk(earlier, 8)

    team = _team(db=earlier.db, compaction=True)
    result = _compact(team, use_async)

    assert result.compacted, result.message
    assert len(_rows(team)) == 1


@pytest.mark.parametrize("use_async", [False, True])
def test_compact_reports_why_it_did_nothing(use_async):
    off = _team()
    _talk(off, 2)
    result = _compact(off, use_async)
    assert result.status == CompactionStatus.NOT_ENABLED and "team" in result.message

    team = _team(compaction=_folding(compact_at_tokens=None, uncompacted_runs=5))
    assert _compact(team, use_async).status == CompactionStatus.NO_HISTORY
    _talk(team, 2)
    assert _compact(team, use_async).status == CompactionStatus.NOTHING_TO_FOLD


@pytest.mark.parametrize("use_async", [False, True])
def test_a_manual_compactions_usage_is_added_to_the_leaders_latest_run_and_the_session(use_async):
    summarizer = _RecordingModel.build()
    team = _team(
        model=_leader(delegate=True),
        compaction=_folding(compact_at_tokens=None, uncompacted_runs=1, model=summarizer),
    )
    _talk(team, 4)
    assert "compaction_model" not in (team.get_session_metrics(session_id="s").details or {})

    result = _compact(team, use_async)

    assert result.compacted and result.metrics is not None
    session = team.get_session(session_id="s")
    leader_runs = [run for run in session.runs if run.parent_run_id is None]
    member_runs = [run for run in session.runs if run.parent_run_id is not None]
    assert "compaction_model" in (leader_runs[-1].metrics.details or {})
    assert all("compaction_model" not in (run.metrics.details or {}) for run in leader_runs[:-1])
    # The session's newest run is the leader's, but a member's run in it is never the one.
    assert member_runs and all("compaction_model" not in (run.metrics.details or {}) for run in member_runs)
    assert "compaction_model" in (team.get_session_metrics(session_id="s").details or {})
