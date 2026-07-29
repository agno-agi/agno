"""Unit tests for team member visibility via AG-UI Activity snapshots.

Verifies that member chunks are surfaced as ACTIVITY_SNAPSHOT events (not folded
into the leader's text message), while the team leader keeps using TEXT_MESSAGE_*.
"""

import pytest

pytest.importorskip("ag_ui", reason="ag_ui not installed")

from ag_ui.core import EventType

from agno.os.interfaces.agui.handlers import process_event
from agno.os.interfaces.agui.state import StreamState
from agno.run.agent import RunContentCompletedEvent as AgentRunContentCompletedEvent
from agno.run.agent import RunContentEvent as AgentRunContentEvent
from agno.run.agent import ToolCallCompletedEvent, ToolCallStartedEvent
from agno.run.team import RunContentEvent as TeamRunContentEvent


def _state() -> StreamState:
    return StreamState(thread_id="thread-1", run_id="run-1")


def _member_chunk(text: str, run_id: str = "member-run-1", agent_id: str = "research-agent") -> AgentRunContentEvent:
    return AgentRunContentEvent(
        content=text,
        agent_id=agent_id,
        agent_name="Research Agent",
        run_id=run_id,
        parent_run_id="run-1",  # set by team delegation -> marks this as a member chunk
    )


def _leader_chunk(text: str) -> TeamRunContentEvent:
    return TeamRunContentEvent(content=text, team_id="team-1", team_name="Team", run_id="run-1")


def test_member_chunk_emits_activity_snapshot_not_text_message():
    state = _state()
    events = process_event(_member_chunk("searching..."), state)

    types = [e.type for e in events]
    assert EventType.ACTIVITY_SNAPSHOT in types
    assert EventType.TEXT_MESSAGE_START not in types
    assert EventType.TEXT_MESSAGE_CONTENT not in types

    snapshot = next(e for e in events if e.type == EventType.ACTIVITY_SNAPSHOT)
    assert snapshot.activity_type == "agno.team_member"
    assert snapshot.content["agentId"] == "research-agent"
    assert snapshot.content["agentName"] == "Research Agent"
    assert snapshot.content["parentRunId"] == "run-1"
    assert snapshot.content["status"] == "running"
    assert "searching..." in snapshot.content["text"]


def test_member_chunks_reuse_message_id_and_accumulate_text():
    state = _state()
    e1 = process_event(_member_chunk("hello "), state)
    e2 = process_event(_member_chunk("world"), state)

    snap1 = next(e for e in e1 if e.type == EventType.ACTIVITY_SNAPSHOT)
    snap2 = next(e for e in e2 if e.type == EventType.ACTIVITY_SNAPSHOT)

    assert snap1.message_id == snap2.message_id
    assert snap2.content["text"] == "hello world"


def test_distinct_members_get_distinct_message_ids():
    state = _state()
    e1 = process_event(_member_chunk("a", run_id="member-run-1", agent_id="agent-a"), state)
    e2 = process_event(_member_chunk("b", run_id="member-run-2", agent_id="agent-b"), state)

    snap1 = next(e for e in e1 if e.type == EventType.ACTIVITY_SNAPSHOT)
    snap2 = next(e for e in e2 if e.type == EventType.ACTIVITY_SNAPSHOT)

    assert snap1.message_id != snap2.message_id
    assert snap1.content["agentId"] == "agent-a"
    assert snap2.content["agentId"] == "agent-b"


def test_leader_chunk_uses_text_message_only():
    state = _state()
    events = process_event(_leader_chunk("final answer"), state)

    types = [e.type for e in events]
    assert EventType.TEXT_MESSAGE_START in types
    assert EventType.TEXT_MESSAGE_CONTENT in types
    assert EventType.ACTIVITY_SNAPSHOT not in types

    content = next(e for e in events if e.type == EventType.TEXT_MESSAGE_CONTENT)
    assert content.delta == "final answer"


def test_member_tool_call_updates_activity_status():
    state = _state()

    started = ToolCallStartedEvent(
        agent_id="research-agent",
        agent_name="Research Agent",
        run_id="member-run-1",
        parent_run_id="run-1",
    )
    started.tool = type("T", (), {"tool_call_id": "tc-1", "tool_name": "web_search", "tool_args": {}})()

    events = process_event(started, state)
    snapshot = next(e for e in events if e.type == EventType.ACTIVITY_SNAPSHOT)
    assert snapshot.content["status"] == "tool_calling"
    assert snapshot.content["currentTool"] == "web_search"

    completed = ToolCallCompletedEvent(
        agent_id="research-agent",
        agent_name="Research Agent",
        run_id="member-run-1",
        parent_run_id="run-1",
    )
    completed.tool = type("T", (), {"tool_call_id": "tc-1", "tool_name": "web_search", "result": "ok"})()

    events = process_event(completed, state)
    snapshot = next(e for e in events if e.type == EventType.ACTIVITY_SNAPSHOT)
    assert snapshot.content["status"] == "running"
    assert snapshot.content["currentTool"] is None


def test_member_content_completed_marks_completed():
    state = _state()
    process_event(_member_chunk("done"), state)

    done = AgentRunContentCompletedEvent(
        agent_id="research-agent",
        agent_name="Research Agent",
        run_id="member-run-1",
        parent_run_id="run-1",
    )
    events = process_event(done, state)
    snapshot = next(e for e in events if e.type == EventType.ACTIVITY_SNAPSHOT)
    assert snapshot.content["status"] == "completed"
    assert snapshot.content["currentTool"] is None


def test_single_agent_chunk_without_parent_is_not_member():
    # A plain agent run (no team) has parent_run_id=None, so it must NOT be
    # treated as a member — it stays on the normal TEXT_MESSAGE_* path.
    state = _state()
    chunk = AgentRunContentEvent(content="hi", agent_id="solo", agent_name="Solo", run_id="run-1")
    events = process_event(chunk, state)

    types = [e.type for e in events]
    assert EventType.TEXT_MESSAGE_CONTENT in types
    assert EventType.ACTIVITY_SNAPSHOT not in types
