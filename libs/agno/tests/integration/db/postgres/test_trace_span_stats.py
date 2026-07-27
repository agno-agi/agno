"""Integration tests for component-grouped trace stats, span stats and lazy metrics on PostgresDb.

Each test gets its own PostgresDb with a dedicated schema and engine, so it is
immune to the shared test_schema teardown ordering issues.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest
from sqlalchemy import create_engine, text

from agno.db.postgres.postgres import PostgresDb
from agno.session.agent import AgentSession
from agno.tracing.schemas import Span, Trace


@pytest.fixture
def stats_db():
    schema = f"agentos_stats_{uuid.uuid4().hex[:8]}"
    engine = create_engine("postgresql+psycopg://ai:ai@localhost:5532/ai")
    db = PostgresDb(db_engine=engine, db_schema=schema)
    yield db
    with engine.connect() as conn:
        conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        conn.commit()
    engine.dispose()


def _make_trace(
    agent_id: Optional[str] = None,
    team_id: Optional[str] = None,
    workflow_id: Optional[str] = None,
    session_id: Optional[str] = "session-1",
    user_id: Optional[str] = "user-1",
    duration_ms: int = 100,
    status: str = "OK",
    minutes_ago: int = 5,
    name: str = "Agent.run",
) -> Trace:
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return Trace(
        trace_id=str(uuid.uuid4()),
        name=name,
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


def test_get_trace_stats_default_shape_unchanged(stats_db: PostgresDb):
    stats_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="session-1"))
    stats_db.upsert_trace(_make_trace(agent_id="agent-2", session_id="session-2"))

    rows, total = stats_db.get_trace_stats()

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


def test_get_trace_stats_group_by_agent(stats_db: PostgresDb):
    stats_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", duration_ms=100))
    stats_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2", duration_ms=300, status="ERROR"))
    stats_db.upsert_trace(_make_trace(agent_id="agent-2", session_id="s3", duration_ms=50))
    stats_db.upsert_trace(_make_trace(session_id=None, user_id=None))  # endpoint-level, excluded

    rows, total = stats_db.get_trace_stats(group_by="agent")

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


def test_get_trace_stats_group_by_team_workflow_endpoint(stats_db: PostgresDb):
    stats_db.upsert_trace(_make_trace(team_id="team-1", session_id="s1"))
    stats_db.upsert_trace(_make_trace(workflow_id="wf-1", session_id="s2"))
    stats_db.upsert_trace(_make_trace(session_id=None, user_id=None, name="tools/call run_agent"))

    team_rows, team_total = stats_db.get_trace_stats(group_by="team")
    workflow_rows, workflow_total = stats_db.get_trace_stats(group_by="workflow")
    endpoint_rows, endpoint_total = stats_db.get_trace_stats(group_by="endpoint")

    assert team_total == 1
    assert team_rows[0]["team_id"] == "team-1"
    assert workflow_total == 1
    assert workflow_rows[0]["workflow_id"] == "wf-1"
    assert endpoint_total == 1
    assert endpoint_rows[0]["name"] == "tools/call run_agent"
    assert endpoint_rows[0]["total_traces"] == 1


def test_get_span_stats_aggregates_and_extracts_span_type(stats_db: PostgresDb):
    trace = _make_trace(agent_id="agent-1", session_id="s1")
    stats_db.upsert_trace(trace)
    stats_db.create_spans(
        [
            _make_span(trace.trace_id, name="slow_tool", duration_ms=900),
            _make_span(trace.trace_id, name="slow_tool", duration_ms=1100),
            _make_span(trace.trace_id, name="fast_tool", duration_ms=10, status_code="ERROR"),
            _make_span(trace.trace_id, name="Model.invoke", span_type="LLM", duration_ms=500),
        ]
    )

    rows, total = stats_db.get_span_stats()

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


def test_get_span_stats_filters_and_sorting(stats_db: PostgresDb):
    trace = _make_trace(agent_id="agent-1", session_id="s1")
    other = _make_trace(agent_id="agent-2", session_id="s2")
    stats_db.upsert_trace(trace)
    stats_db.upsert_trace(other)
    stats_db.create_spans(
        [
            _make_span(trace.trace_id, name="tool_a", duration_ms=1000),
            _make_span(trace.trace_id, name="tool_b", duration_ms=10),
            _make_span(other.trace_id, name="tool_c", duration_ms=10),
            _make_span(trace.trace_id, name="old_tool", minutes_ago=120),
            _make_span(trace.trace_id, name="Model.invoke", span_type="LLM", duration_ms=500),
        ]
    )

    tool_rows, tool_total = stats_db.get_span_stats(span_type="TOOL", sort_by="p95_duration_ms")
    assert tool_total == 4
    assert tool_rows[0]["name"] == "tool_a"

    agent_rows, agent_total = stats_db.get_span_stats(agent_id="agent-1")
    assert agent_total == 4
    assert "tool_c" not in {row["name"] for row in agent_rows}

    # The span 120 minutes old must fall outside a 60-minute window
    start_time = datetime.now(timezone.utc) - timedelta(minutes=60)
    windowed_rows, _ = stats_db.get_span_stats(start_time=start_time)
    windowed_names = {row["name"] for row in windowed_rows}
    assert "old_tool" not in windowed_names
    assert windowed_names == {"tool_a", "tool_b", "tool_c", "Model.invoke"}

    # And only it survives an end_time cap before the recent spans
    end_time = datetime.now(timezone.utc) - timedelta(minutes=60)
    capped_rows, _ = stats_db.get_span_stats(end_time=end_time)
    assert {row["name"] for row in capped_rows} == {"old_tool"}


def test_get_span_stats_paging_with_tied_name_groups_is_lossless(stats_db: PostgresDb):
    trace = _make_trace(agent_id="agent-1", session_id="s1")
    stats_db.upsert_trace(trace)
    # 8 groups sharing one name, all tied on every aggregate: only the
    # (name, span_type) ORDER BY tiebreak makes paging deterministic
    stats_db.create_spans([_make_span(trace.trace_id, name="dup", span_type=f"KIND{i:02d}") for i in range(20)])

    seen = []
    total = 0
    for page in range(1, 24):
        rows, total = stats_db.get_span_stats(limit=3, page=page)
        if not rows:
            break
        seen.extend((row["name"], row["span_type"]) for row in rows)

    assert total == 20
    assert len(seen) == 20
    assert len(set(seen)) == 20


def test_get_metrics_refreshes_lazily_and_throttles(stats_db: PostgresDb):
    def seed_session(user_id: str) -> None:
        now = int(time.time())
        stats_db.upsert_session(
            AgentSession(
                session_id=str(uuid.uuid4()), agent_id="agent-1", user_id=user_id, created_at=now, updated_at=now
            )
        )

    seed_session("user-1")

    # No calculate_metrics call: get_metrics must refresh on its own
    rows, _ = stats_db.get_metrics()
    assert len(rows) == 1
    assert rows[0]["agent_sessions_count"] == 1

    # A second read within the throttle window must not recompute
    seed_session("user-2")
    rows, _ = stats_db.get_metrics()
    assert rows[0]["agent_sessions_count"] == 1

    # Expiring the throttle picks the new session up
    stats_db._metrics_refreshed_at = 0.0
    rows, _ = stats_db.get_metrics()
    assert rows[0]["agent_sessions_count"] == 2
