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
    messages = _transcript(runs=2)
    c = Compaction(compact_at_runs=1, keep_last_runs=99)
    assert c.boundary_for(messages) == 0


# --- applying ------------------------------------------------------------


def test_apply_record_replaces_head_with_summary():
    messages = _transcript(runs=3)
    record = CompactionRecord(messages_compacted=4, summary="Earlier: discussed 0 and 1.", boundary=4)
    c = Compaction(compact_at_runs=2)
    out = c.apply_record(messages, record)

    assert out[0].role == "system"
    assert "Earlier: discussed 0 and 1." in out[0].content
    assert out[1:] == messages[4:]


def test_summary_message_is_not_persisted():
    """Sent to the model, never written to the session.

    add_to_agent_memory is what the run actually filters on; temporary alone
    is only honoured by some providers. Persisting the summary would mean the
    next compaction summarizes a summary, compounding the loss each time.
    """
    c = Compaction(compact_at_runs=2)
    record = CompactionRecord(messages_compacted=2, summary="s", boundary=2)
    summary_message = c.apply_record(_transcript(), record)[0]

    assert summary_message.add_to_agent_memory is False
    assert summary_message.temporary is True


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

    kept = c.apply_record(messages, CompactionRecord(messages_compacted=2, summary="s", boundary=2))

    tail = kept[1:]
    assert all("response_id" not in (m.provider_data or {}) for m in tail)
    # Unrelated provider_data is preserved.
    assert tail[-1].provider_data == {"other": "keep"}
    # The stored history itself is untouched.
    assert messages[3].provider_data["response_id"] == "resp_123"


def test_summary_points_at_the_archive_when_there_is_one():
    c = Compaction(compact_at_runs=2)
    with_archive = c.apply_record(
        _transcript(), CompactionRecord(messages_compacted=2, summary="s", boundary=2, archive_path="0001.md")
    )[0]
    without = c.apply_record(_transcript(), CompactionRecord(messages_compacted=2, summary="s", boundary=2))[0]

    assert "0001.md" in with_archive.content
    assert "0001.md" not in without.content


def test_record_roundtrips_through_dict():
    record = CompactionRecord(messages_compacted=4, summary="s", boundary=4, archive_path="0001.md", tokens_before=100)
    assert CompactionRecord.from_dict(record.to_dict()) == record


def test_second_compaction_only_covers_what_is_new():
    """A span already compacted is not archived or summarized twice.

    The stored boundary is an absolute index into the full history, so a later
    compaction starts where the previous one stopped. Getting this wrong makes
    the boundary crawl forward one message per run, so the context never
    actually shrinks and every subsequent run compacts again.
    """
    messages = _transcript(runs=4)
    # min_chars_to_reclaim=0: this exercises the boundary, not the size floor.
    c = Compaction(compact_at_runs=2, keep_last_runs=1, min_chars_to_reclaim=0, model=_StubModel())
    previous = CompactionRecord(messages_compacted=2, summary="earlier", boundary=2)

    record = c.compact(messages, session_id="s", db=None, previous=previous)

    assert record is not None
    assert record.boundary > previous.boundary
    # Only the messages after the previous boundary were sent to the summarizer.
    assert "question 0" not in c.model.seen
    assert "question 2" in c.model.seen


def test_no_new_span_does_not_recompact():
    messages = _transcript(runs=2)
    c = Compaction(compact_at_runs=2, keep_last_runs=1)
    boundary = c.boundary_for(messages)
    previous = CompactionRecord(messages_compacted=boundary, summary="s", boundary=boundary)

    assert c.compact(messages, session_id="s", db=None, previous=previous) is None


def test_skips_compaction_that_would_not_free_anything():
    """A summary costs more than a handful of short turns is worth.

    Compacting anyway leaves the context bigger than it started and throws
    away the prompt-cache prefix to do it.
    """
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(compact_at_runs=2, keep_last_messages=0, model=_StubModel())

    assert c.compact(tiny, session_id="s", db=None) is None


def test_reclaim_floor_can_be_disabled():
    tiny = [Message(role="user", content="hi"), Message(role="assistant", content="hello")]
    c = Compaction(compact_at_runs=2, keep_last_messages=0, min_chars_to_reclaim=0, model=_StubModel())

    assert c.compact(tiny, session_id="s", db=None) is not None


def test_large_span_clears_the_floor():
    big = [Message(role="user", content="x" * 5_000), Message(role="assistant", content="y" * 5_000)]
    c = Compaction(compact_at_runs=2, keep_last_messages=0, model=_StubModel())

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
    big = [Message(role="user", content="x" * 5_000), Message(role="assistant", content="y" * 5_000)]
    c = Compaction(compact_at_runs=2, keep_last_messages=0, model=_StubModel())

    boundary = c.plan(big)
    record = c.compact(big, session_id="s", db=None)

    assert boundary is not None
    assert record is not None
    assert record.boundary == boundary


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
