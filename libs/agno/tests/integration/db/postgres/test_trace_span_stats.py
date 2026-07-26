"""Integration tests for component-grouped trace stats, span stats and lazy metrics on PostgresDb"""

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from agno.db.postgres.postgres import PostgresDb
from agno.session.agent import AgentSession
from agno.tracing.schemas import Span, Trace


def _make_trace(
    agent_id: Optional[str] = None,
    team_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    session_id: Optional[str] = "session-1",
    user_id: Optional[str] = "user-1",
    duration_ms: int = 100,
    status: str = "OK",
    minutes_ago: int = 5,
) -> Trace:
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return Trace(
        trace_id=str(uuid.uuid4()),
        name="Agent.run",
        status=status,
        start_time=start,
        end_time=start + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        total_spans=0,
        error_count=1 if status == "ERROR" else 0,
        run_id=None,
        session_id=session_id,
        user_id=user_id,
        agent_id=agent_id,
        team_id=team_id,
        workflow_id=workflow_id,
        created_at=start,
    )


def _make_span(
    trace_id: str,
    name: str = "my_tool",
    span_type: Optional[str] = "TOOL",
    duration_ms: int = 100,
    status_code: str = "OK",
    minutes_ago: int = 5,
) -> Span:
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    attributes: Dict[str, Any] = {"openinference.span.kind": span_type} if span_type else {}
    return Span(
        span_id=str(uuid.uuid4()),
        trace_id=trace_id,
        parent_span_id=None,
        name=name,
        span_kind="INTERNAL",
        status_code=status_code,
        status_message=None,
        start_time=start,
        end_time=start + timedelta(milliseconds=duration_ms),
        duration_ms=duration_ms,
        attributes=attributes,
        created_at=start,
    )


def test_get_trace_stats_default_shape_unchanged(postgres_db_real: PostgresDb):
    postgres_db_real.upsert_trace(_make_trace(agent_id="agent-1", session_id="session-1"))
    postgres_db_real.upsert_trace(_make_trace(agent_id="agent-2", session_id="session-2"))

    rows, total = postgres_db_real.get_trace_stats()

    assert total == 2
    expected_keys = {
        "session_id",
        "user_id",
        "agent_id",
        "team_id",
        "workflow_id",
        "total_traces",
        "first_trace_at",
        "last_trace_at",
    }
    for row in rows:
        assert set(row.keys()) == expected_keys
        assert isinstance(row["first_trace_at"], datetime)


def test_get_trace_stats_group_by_agent(postgres_db_real: PostgresDb):
    postgres_db_real.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", duration_ms=100))
    postgres_db_real.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2", duration_ms=300, status="ERROR"))
    postgres_db_real.upsert_trace(_make_trace(agent_id="agent-2", session_id="s3", duration_ms=50))
    postgres_db_real.upsert_trace(_make_trace(session_id=None, user_id=None))  # endpoint-level, excluded

    rows, total = postgres_db_real.get_trace_stats(group_by="agent")

    assert total == 2
    top = rows[0]
    assert top["agent_id"] == "agent-1"
    assert top["total_traces"] == 2
    assert top["total_sessions"] == 2
    assert top["avg_duration_ms"] == 200.0
    # percentile_cont(0.95) over [100, 300] interpolates to 290
    assert top["p95_duration_ms"] == 290.0
    assert top["max_duration_ms"] == 300
    assert top["error_traces"] == 1


def test_get_trace_stats_group_by_team_and_workflow(postgres_db_real: PostgresDb):
    postgres_db_real.upsert_trace(_make_trace(team_id="team-1", session_id="s1"))
    postgres_db_real.upsert_trace(_make_trace(workflow_id="wf-1", session_id="s2"))

    team_rows, team_total = postgres_db_real.get_trace_stats(group_by="team")
    workflow_rows, workflow_total = postgres_db_real.get_trace_stats(group_by="workflow")

    assert team_total == 1
    assert team_rows[0]["team_id"] == "team-1"
    assert workflow_total == 1
    assert workflow_rows[0]["workflow_id"] == "wf-1"


def test_get_span_stats_aggregates_and_extracts_span_type(postgres_db_real: PostgresDb):
    trace = _make_trace(agent_id="agent-1", session_id="s1")
    postgres_db_real.upsert_trace(trace)
    postgres_db_real.create_spans(
        [
            _make_span(trace.trace_id, name="slow_tool", duration_ms=900),
            _make_span(trace.trace_id, name="slow_tool", duration_ms=1100),
            _make_span(trace.trace_id, name="fast_tool", duration_ms=10, status_code="ERROR"),
            _make_span(trace.trace_id, name="Model.invoke", span_type="LLM", duration_ms=500),
        ]
    )

    rows, total = postgres_db_real.get_span_stats()

    assert total == 3
    by_name = {row["name"]: row for row in rows}
    assert by_name["slow_tool"]["total_calls"] == 2
    assert by_name["slow_tool"]["avg_duration_ms"] == 1000.0
    # percentile_cont(0.95) over [900, 1100] interpolates to 1090
    assert by_name["slow_tool"]["p95_duration_ms"] == 1090.0
    assert by_name["slow_tool"]["span_type"] == "TOOL"
    assert by_name["fast_tool"]["error_count"] == 1
    assert by_name["Model.invoke"]["span_type"] == "LLM"
    for row in rows:
        assert "attributes" not in row


def test_get_span_stats_filters_and_sorting(postgres_db_real: PostgresDb):
    trace = _make_trace(agent_id="agent-1", session_id="s1")
    other = _make_trace(agent_id="agent-2", session_id="s2")
    postgres_db_real.upsert_trace(trace)
    postgres_db_real.upsert_trace(other)
    postgres_db_real.create_spans(
        [
            _make_span(trace.trace_id, name="tool_a", duration_ms=1000),
            _make_span(trace.trace_id, name="tool_b", duration_ms=10),
            _make_span(other.trace_id, name="tool_c", duration_ms=10),
            _make_span(trace.trace_id, name="Model.invoke", span_type="LLM", duration_ms=500),
        ]
    )

    tool_rows, tool_total = postgres_db_real.get_span_stats(span_type="TOOL", sort_by="p95_duration_ms")
    assert tool_total == 3
    assert tool_rows[0]["name"] == "tool_a"

    agent_rows, agent_total = postgres_db_real.get_span_stats(agent_id="agent-1")
    assert agent_total == 3
    assert "tool_c" not in {row["name"] for row in agent_rows}

    start_time = datetime.now(timezone.utc) - timedelta(minutes=60)
    windowed_rows, _ = postgres_db_real.get_span_stats(start_time=start_time)
    assert {row["name"] for row in windowed_rows} == {"tool_a", "tool_b", "tool_c", "Model.invoke"}


def test_get_metrics_refreshes_lazily(postgres_db_real: PostgresDb):
    now = int(time.time())
    session = AgentSession(
        session_id=str(uuid.uuid4()),
        agent_id="agent-1",
        user_id="user-1",
        created_at=now,
        updated_at=now,
    )
    postgres_db_real.upsert_session(session)

    # No calculate_metrics call: get_metrics must refresh on its own
    rows, _ = postgres_db_real.get_metrics()

    assert len(rows) == 1
    assert rows[0]["agent_sessions_count"] == 1
