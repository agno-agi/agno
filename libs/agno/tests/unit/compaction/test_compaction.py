import tempfile
from pathlib import Path

import pytest

from agno.compaction import Compaction, CompactionRecord
from agno.compaction.archive import namespace_for, render_messages
from agno.models.message import Message


def _transcript(runs: int = 3) -> list:
    """A transcript of ``runs`` user/assistant exchanges, one with a tool batch."""
    messages = []
    for i in range(runs):
        messages.append(Message(role="user", content=f"question {i}"))
        if i == 1:
            messages.append(
                Message(
                    role="assistant",
                    content=None,
                    tool_calls=[{"id": f"call_{i}", "function": {"name": "search", "arguments": "{}"}}],
                )
            )
            messages.append(Message(role="tool", tool_call_id=f"call_{i}", tool_name="search", content="data"))
        messages.append(Message(role="assistant", content=f"answer {i}"))
    return messages


class _StubModel:
    """A summarizer that records what it was asked to summarize."""

    id = "stub"
    seen = ""

    def response(self, messages, **kwargs):
        from agno.models.response import ModelResponse

        self.seen = messages[-1].content
        return ModelResponse(content="SUMMARY")


def _record(messages, boundary_index, summary="s", **kwargs):
    """A record anchored on messages[boundary_index] - the first message kept verbatim."""
    return CompactionRecord(
        messages_compacted=boundary_index,
        summary=summary,
        first_kept_message_id=messages[boundary_index].id if boundary_index < len(messages) else None,
        **kwargs,
    )


def _db():
    return __import__("agno.db.sqlite", fromlist=["SqliteDb"]).SqliteDb(
        db_file=str(Path(tempfile.mkdtemp()) / "test.db")
    )


# --- configuration -------------------------------------------------------


def test_requires_at_least_one_threshold():
    with pytest.raises(ValueError, match="at least one threshold"):
        Compaction(compact_at_runs=None)


def test_rejects_non_positive_threshold():
    with pytest.raises(ValueError, match="compact_at_tokens"):
        Compaction(compact_at_tokens=0)


def test_keep_last_messages_wins_over_runs():
    c = Compaction(compact_at_runs=5, keep_last_runs=3, keep_last_messages=10)
    assert c.keep_last_runs is None
    assert c.keep_last_messages == 10


# --- triggers ------------------------------------------------------------


def test_triggers_on_runs_in_context():
    """Runs are counted in the live context, not in the session.

    A session count only grows, so it would stay tripped forever and
    recompact on every run after the first.
    """
    c = Compaction(compact_at_runs=3)
    assert c.should_compact(_transcript(runs=3)) is True
    assert c.should_compact(_transcript(runs=2)) is False


def test_triggers_on_message_count():
    c = Compaction(compact_at_runs=None, compact_at_messages=5)
    assert c.should_compact(_transcript(runs=3)) is True
    assert c.should_compact(_transcript(runs=1)) is False


def test_prefers_reported_tokens_over_counting():
    """The provider's own number is used when available, with no model call."""
    c = Compaction(compact_at_runs=None, compact_at_tokens=1000)
    assert c.should_compact(_transcript(), last_input_tokens=2000, model=None) is True
    assert c.should_compact(_transcript(), last_input_tokens=500, model=None) is False


def test_no_threshold_met_without_signal():
    """A token threshold with nothing to measure must not fire."""
    c = Compaction(compact_at_runs=None, compact_at_tokens=1000)
    assert c.should_compact(_transcript(), last_input_tokens=None, model=None) is False


# --- boundary safety -----------------------------------------------------


def test_boundary_never_splits_a_tool_batch():
    """The kept tail must never begin with an unanswered tool result."""
    messages = _transcript(runs=3)
    for keep in range(len(messages) + 1):
        c = Compaction(compact_at_runs=2, keep_last_messages=keep)
        boundary = c.boundary_for(messages)
        tail = messages[boundary:]
        if tail:
            assert tail[0].role != "tool", f"orphaned tool result at keep={keep}"
        # every call kept in the compacted half is answered in that half
        answered = {m.tool_call_id for m in messages[:boundary] if m.role == "tool"}
        for message in messages[:boundary]:
            for call in message.tool_calls or []:
                assert call["id"] in answered, f"unanswered call at keep={keep}"


def test_boundary_keeps_requested_runs():
    messages = _transcript(runs=3)
    c = Compaction(compact_at_runs=2, keep_last_runs=1)
    tail = messages[c.boundary_for(messages) :]
    assert tail[0].role == "user"
    assert tail[0].content == "question 2"


def test_keeping_everything_compacts_nothing():
    """No safe cut is None, not 0: there is nothing to fold, so the pass aborts."""
    messages = _transcript(runs=2)
    c = Compaction(compact_at_runs=1, keep_last_runs=99)
    assert c.boundary_for(messages) is None


# --- applying ------------------------------------------------------------


def test_apply_record_replaces_head_with_summary():
    messages = _transcript(runs=3)
    record = _record(messages, 4, summary="Earlier: discussed 0 and 1.")
    c = Compaction(compact_at_runs=2)
    from agno.compaction.prompts import SUMMARY_PREFIX

    out = c.apply_record(messages, record)

    assert out[0].content.startswith(SUMMARY_PREFIX)
    assert "Earlier: discussed 0 and 1." in out[0].content
    assert [m.id for m in out[1:]] == [m.id for m in messages[4:]]


def test_summary_is_injected_into_the_view_only():
    """The summary exists in the derived view, never in the stored transcript.

    Views are rebuilt per call and discarded, so there is nothing to persist and
    no way for a later compaction to end up summarizing its own summary.
    """
    from agno.compaction.prompts import SUMMARY_PREFIX

    messages = _transcript()
    original = list(messages)
    c = Compaction(compact_at_runs=2)

    view = c.apply_record(messages, _record(messages, 3, summary="earlier turns"))

    injected = next(m for m in view if isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX))
    assert "earlier turns" in injected.content
    assert injected.from_history is True
    # The canonical list is untouched: same objects, same order, no summary in it.
    assert messages == original
    assert not any(isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX) for m in messages)


def test_kept_messages_lose_provider_side_conversation_state():
    """Compaction must not leave a provider able to replay the dropped turns.

    OpenAI Responses chains on previous_response_id from an assistant
    message's provider_data, and the server then replays the whole prior
    conversation - so the context looks compacted locally while the model
    still sees everything. The saving would be imaginary.
    """
    messages = [
        Message(role="user", content="q0"),
        Message(role="assistant", content="a0"),
        Message(role="user", content="q1"),
        Message(role="assistant", content="a1", provider_data={"response_id": "resp_123", "other": "keep"}),
    ]
    c = Compaction(compact_at_runs=2)

    kept = c.apply_record(messages, _record(messages, 2, summary="s"))

    tail = kept[1:]
    assert all("response_id" not in (m.provider_data or {}) for m in tail)
    # Unrelated provider_data is preserved.
    assert tail[-1].provider_data == {"other": "keep"}
    # The stored history itself is untouched.
    assert messages[3].provider_data["response_id"] == "resp_123"


def test_only_the_chaining_key_is_stripped_not_the_exchange():
    """Reasoning payload and tool exchanges survive; only response_id goes.

    Dropping the whole exchange would be the blunt fix. The precise one is to
    remove only the chaining key: a function_call still needs its paired
    reasoning item, which lives elsewhere in provider_data.
    """
    messages = [
        Message(role="user", content="q0"),
        Message(role="assistant", content="a0"),
        Message(role="user", content="q1"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
            provider_data={"response_id": "resp_123"},
        ),
        Message(role="tool", tool_call_id="call_1", tool_name="search", content="data"),
        Message(role="assistant", content="a1"),
    ]

    tail = Compaction(compact_at_runs=2).apply_record(messages, _record(messages, 2, summary="s"))[1:]

    # The exchange survives intact - only the chaining key is gone.
    assert any(m.role == "tool" for m in tail)
    assert any(m.tool_calls for m in tail)
    assert all("response_id" not in (m.provider_data or {}) for m in tail)
    # The canonical message keeps its provider_data.
    assert messages[3].provider_data["response_id"] == "resp_123"


def test_tool_exchanges_survive_when_there_is_no_server_state():
    """Nothing is dropped for providers that send history in the request."""
    messages = [
        Message(role="user", content="q0"),
        Message(role="assistant", content="a0"),
        Message(role="user", content="q1"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "call_1", "function": {"name": "search", "arguments": "{}"}}],
        ),
        Message(role="tool", tool_call_id="call_1", tool_name="search", content="data"),
    ]

    tail = Compaction(compact_at_runs=2).apply_record(messages, _record(messages, 2, summary="s"))[1:]

    assert any(m.role == "tool" for m in tail)
    assert any(m.tool_calls for m in tail)


def test_summary_points_at_the_archive_only_when_the_agent_can_read_it():
    """The lookup instruction is promised only when the tools exist.

    Without searchable the archive is for a developer, not the model. Telling
    it to read a file it cannot open invites a refusal or an invented answer.
    """
    messages = _transcript()
    archived = _record(messages, 3, summary="s", archive_path="0001.md")

    searchable = Compaction(compact_at_runs=2, searchable=True).apply_record(messages, archived)[0]
    not_searchable = Compaction(compact_at_runs=2).apply_record(messages, archived)[0]
    no_archive = Compaction(compact_at_runs=2, searchable=True).apply_record(
        messages, _record(messages, 3, summary="s")
    )[0]

    assert "0001.md" in searchable.content
    assert "read or search that file" in searchable.content
    assert "0001.md" not in not_searchable.content
    assert "0001.md" not in no_archive.content


def test_summarizer_is_told_to_flag_gaps_only_when_archived():
    """A summary should declare what it dropped only if that is recoverable."""
    c = Compaction(compact_at_runs=2)

    archived = c._summary_messages(_transcript(), None, archived=True)[0].content
    plain = c._summary_messages(_transcript(), None, archived=False)[0].content

    assert "Not covered here:" in archived
    assert "Not covered here:" not in plain


def test_record_roundtrips_through_dict():
    record = CompactionRecord(
        messages_compacted=4, summary="s", first_kept_message_id="m-4", archive_path="0001.md", tokens_before=100
    )
    assert CompactionRecord.from_dict(record.to_dict()) == record


def test_second_compaction_only_covers_what_is_new():
    """A span already compacted is not archived or summarized twice.

    The stored boundary is an absolute index into the full history, so a later
    compaction starts where the previous one stopped. Getting this wrong makes
    the boundary crawl forward one message per run, so the context never
    actually shrinks and every subsequent run compacts again.
    """
    messages = _transcript(runs=4)
    # min_fold_ratio=0: this exercises the boundary, not the size floor.
    c = Compaction(compact_at_runs=2, keep_last_runs=1, min_fold_ratio=0, model=_StubModel())
    previous = _record(messages, 2, summary="earlier")

    record = c.compact(messages, session_id="s", db=None, previous=previous)

    assert record is not None
    # The new anchor sits strictly after the previous one.
    ids = [m.id for m in messages]
    assert ids.index(record.first_kept_message_id) > ids.index(previous.first_kept_message_id)
    # Only the messages after the previous boundary were sent to the summarizer.
    assert "question 0" not in c.model.seen
    assert "question 2" in c.model.seen


def test_no_new_span_does_not_recompact():
    messages = _transcript(runs=2)
    c = Compaction(compact_at_runs=2, keep_last_runs=1)
    boundary = c.boundary_for(messages)
    previous = _record(messages, boundary, summary="s")

    assert c.compact(messages, session_id="s", db=None, previous=previous) is None


def test_skips_a_fold_that_cannot_pay_for_its_summary():
    """Folding barely more than is kept leaves the context bigger, not smaller."""
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(compact_at_runs=2, keep_last_messages=1, model=_StubModel())

    assert c.compact(tiny, session_id="s", db=None) is None


def test_fold_ratio_can_be_disabled():
    messages = [
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
        Message(role="user", content="more"),
    ]
    c = Compaction(compact_at_runs=2, keep_last_messages=1, min_fold_ratio=0, model=_StubModel())

    assert c.compact(messages, session_id="s", db=None) is not None


def test_large_fold_against_a_small_tail_clears_the_ratio():
    big = [
        Message(role="user", content="x" * 5_000),
        Message(role="assistant", content="y" * 5_000),
        Message(role="user", content="tiny"),
    ]
    c = Compaction(compact_at_runs=2, keep_last_messages=1, model=_StubModel())

    assert c.compact(big, session_id="s", db=None) is not None


def test_plan_refuses_what_compact_would_refuse():
    """plan() is what callers announce on, so it must agree with compact().

    should_compact() alone cannot see the pair-safe boundary or the size
    floor, so announcing on it logs "Auto-compacting" and emits
    CompactionStarted for compactions that then never happen.
    """
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(compact_at_runs=2, keep_last_messages=0, model=_StubModel())

    assert c.plan(tiny) is None
    assert c.compact(tiny, session_id="s", db=None) is None


def test_plan_agrees_with_compact_when_worthwhile():
    big = [
        Message(role="user", content="x" * 5_000),
        Message(role="assistant", content="y" * 5_000),
        Message(role="user", content="tiny"),
    ]
    c = Compaction(compact_at_runs=2, keep_last_messages=1, model=_StubModel())

    boundary = c.plan(big)
    record = c.compact(big, session_id="s", db=None)

    assert boundary is not None
    assert record is not None
    assert record.first_kept_message_id == big[boundary].id


def test_run_output_carries_the_compaction_record():
    """`run.compaction` is the documented way to inspect what happened."""
    from agno.run.agent import RunOutput

    record = CompactionRecord(
        messages_compacted=6,
        summary="s",
        first_kept_message_id="m-6",
        archive_path="0001.md",
        tokens_before=100,
        tokens_after=40,
    )
    run = RunOutput(run_id="r", session_id="s", compaction=record)

    restored = RunOutput.from_dict(run.to_dict())
    assert restored.compaction == record


def test_run_output_without_compaction_serializes_cleanly():
    from agno.run.agent import RunOutput

    assert "compaction" not in RunOutput(run_id="r", session_id="s").to_dict()
    assert RunOutput.from_dict({"run_id": "r", "session_id": "s"}).compaction is None


def test_unresolvable_anchor_fails_open():
    """A record whose anchor is not in this list must not cut anything.

    History is rebuilt from stored runs every run. An anchor that no longer
    resolves means the record does not describe this list - sending the full
    list is always valid, silently cutting at the wrong place is not.
    """
    from agno.compaction.prompts import SUMMARY_PREFIX

    messages = _transcript()
    stale = CompactionRecord(messages_compacted=4, summary="s", first_kept_message_id="not-in-this-list")

    view = Compaction(compact_at_runs=2).apply_record(messages, stale)

    assert [m.id for m in view] == [m.id for m in messages]
    assert not any(isinstance(m.content, str) and m.content.startswith(SUMMARY_PREFIX) for m in view)


def test_tool_results_before_the_watermark_are_elided():
    """Elision reclaims bulk tool output without paying a summarizer for it."""
    from agno.compaction.prompts import ELISION_PLACEHOLDER

    messages = [
        Message(role="user", content="q0"),
        Message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "c1", "function": {"name": "dump", "arguments": "{}"}}],
        ),
        Message(role="tool", tool_call_id="c1", tool_name="dump", content="x" * 5_000),
        Message(role="user", content="q1"),
    ]
    record = CompactionRecord(messages_compacted=0, summary="", elision_watermark_message_id=messages[3].id)

    view = Compaction(compact_at_runs=2).apply_record(messages, record)

    elided = next(m for m in view if m.role == "tool")
    assert elided.content == ELISION_PLACEHOLDER.format(n_chars=5_000)
    # The transcript keeps the real payload.
    assert messages[2].content == "x" * 5_000


def test_boundary_never_anchors_on_a_message_that_will_not_persist():
    """A temporary message is gone by the next run; anchoring there would break."""
    messages = [
        Message(role="user", content="q0" * 400),
        Message(role="assistant", content="a0" * 400),
        Message(role="user", content="temp", temporary=True),
        Message(role="assistant", content="a1" * 400),
        Message(role="user", content="q2"),
    ]

    boundary = Compaction(compact_at_runs=2, keep_last_messages=2).boundary_for(messages)

    assert boundary is None or not messages[boundary].temporary


# --- events --------------------------------------------------------------


def test_compaction_events_are_registered():
    """Both events must round-trip through the run-event registry."""
    from agno.run.agent import RUN_EVENT_TYPE_REGISTRY, RunEvent

    assert RUN_EVENT_TYPE_REGISTRY[RunEvent.compaction_started.value].__name__ == "CompactionStartedEvent"
    assert RUN_EVENT_TYPE_REGISTRY[RunEvent.compaction_completed.value].__name__ == "CompactionCompletedEvent"


def test_completed_event_carries_what_happened():
    from agno.run.agent import RunOutput
    from agno.utils.events import create_compaction_completed_event

    event = create_compaction_completed_event(
        from_run_response=RunOutput(run_id="r1", session_id="s1"),
        messages_compacted=6,
        tokens_before=1000,
        tokens_after=200,
        archive_path="0001.md",
    )

    assert event.messages_compacted == 6
    assert event.tokens_before == 1000
    assert event.tokens_after == 200
    assert event.archive_path == "0001.md"


# --- archive -------------------------------------------------------------


def test_archive_roundtrip_and_numbering():
    c = Compaction(compact_at_runs=2)
    archive = c.archive_for("session-a", _db())
    messages = [Message(role="assistant", content="policy KR-9912 applies")]

    first = archive.write(messages)
    assert first == "0001.md"
    assert "KR-9912" in archive.read(first)
    assert archive.write(messages) == "0002.md"


def test_archive_is_isolated_per_session():
    """One session must never be able to read another's history."""
    db = _db()
    c = Compaction(compact_at_runs=2)
    c.archive_for("session-a", db).write([Message(role="assistant", content="secret KR-9912")])

    assert c.resolve_fs("session-a", db).search("KR-9912")
    assert not c.resolve_fs("session-b", db).search("KR-9912")


def test_namespaces_do_not_collide_on_case():
    assert namespace_for("Session-A") != namespace_for("session-a")


def test_archive_degrades_when_db_cannot_back_it():
    """A db AgentFS cannot use loses the archive, not the run."""

    class UnsupportedDb:
        pass

    assert Compaction(compact_at_runs=2).archive_for("s", UnsupportedDb()) is None
    assert Compaction(compact_at_runs=2).archive_for("s", None) is None


def test_archive_off_returns_no_store():
    assert Compaction(compact_at_runs=2, archive=False).archive_for("s", _db()) is None


def test_render_includes_roles_and_tool_names():
    rendered = render_messages(_transcript(runs=2))
    assert "## user" in rendered
    assert "## tool (search)" in rendered
    assert "question 0" in rendered


def test_render_clips_huge_tool_results():
    """One enormous result must not be able to exhaust the archive quota."""
    from agno.compaction.archive import MAX_ARCHIVED_TOOL_RESULT_CHARS

    rendered = render_messages([Message(role="tool", tool_name="dump", content="x" * 60_000)])
    assert "clipped" in rendered
    assert len(rendered) < MAX_ARCHIVED_TOOL_RESULT_CHARS + 1000


# --- searchable tools ----------------------------------------------------


def test_searchable_exposes_read_only_tools():
    """Once something is archived, the read-only surface is attached."""
    c = Compaction(compact_at_runs=2, searchable=True)
    db = _db()
    c.archive_for("s", db).write([Message(role="user", content="something to find")])

    toolkit = c.tools_for("s", db)

    assert sorted(f.name for f in toolkit.functions.values()) == [
        "list_files",
        "read_file",
        "search_content",
    ]


def test_no_tools_until_something_is_archived():
    """An empty archive offers nothing - there is no history to search yet.

    Attaching the tools on turn one only invites a pointless lookup before
    any compaction has happened.
    """
    assert Compaction(compact_at_runs=2, searchable=True).tools_for("s", _db()) is None


def test_searchable_tools_reach_the_agent():
    """The toolkit must actually be registered, not merely constructible.

    tools_for() existing is not enough - without it being wired into tool
    resolution the agent has no way to read its own archive, and the feature
    silently does nothing.
    """
    from agno.agent import Agent
    from agno.agent._tools import get_tools
    from agno.models.openai import OpenAIResponses
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session import AgentSession

    db = _db()
    compaction = Compaction(compact_at_runs=2, searchable=True)
    compaction.archive_for("s", db).write([Message(role="user", content="archived")])
    agent = Agent(model=OpenAIResponses(id="gpt-4o-mini"), db=db, compaction=compaction)
    tools = get_tools(
        agent,
        run_response=RunOutput(run_id="r", session_id="s"),
        run_context=RunContext(run_id="r", session_id="s"),
        session=AgentSession(session_id="s"),
    )

    names = [name for tool in tools for name in (getattr(tool, "functions", None) or {})]
    assert "search_content" in names
    assert "read_file" in names


def test_archive_tools_absent_when_not_searchable():
    from agno.agent import Agent
    from agno.agent._tools import get_tools
    from agno.models.openai import OpenAIResponses
    from agno.run import RunContext
    from agno.run.agent import RunOutput
    from agno.session import AgentSession

    agent = Agent(
        model=OpenAIResponses(id="gpt-4o-mini"),
        db=_db(),
        compaction=Compaction(compact_at_runs=2),
    )
    tools = get_tools(
        agent,
        run_response=RunOutput(run_id="r", session_id="s"),
        run_context=RunContext(run_id="r", session_id="s"),
        session=AgentSession(session_id="s"),
    )

    names = [name for tool in tools for name in (getattr(tool, "functions", None) or {})]
    assert "search_content" not in names


def test_not_searchable_by_default():
    assert Compaction(compact_at_runs=2).tools_for("s", _db()) is None
