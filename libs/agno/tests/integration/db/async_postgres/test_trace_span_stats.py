"""Integration tests for component-grouped trace stats, span stats and lazy metrics on AsyncPostgresDb.

Each test gets its own AsyncPostgresDb with a dedicated schema and engine, so it
is immune to the shared test_schema teardown ordering issues.
"""

import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from agno.db.postgres import AsyncPostgresDb
from agno.session.agent import AgentSession
from agno.tracing.schemas import Span, Trace


@pytest_asyncio.fixture
async def stats_db():
    schema = f"agentos_stats_{uuid.uuid4().hex[:8]}"
    engine = create_async_engine("postgresql+psycopg_async://ai:ai@localhost:5532/ai")
    db = AsyncPostgresDb(db_engine=engine, db_schema=schema)
    yield db
    async with engine.begin() as conn:
        await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    await engine.dispose()


def _make_trace(
    agent_id: Optional[str] = None,
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
        team_id=None,
        workflow_id=None,
        created_at=start,
    )


def _make_span(
    trace_id: str,
    name: str = "my_tool",
    span_type: Optional[str] = "TOOL",
    duration_ms: int = 100,
    status_code: str = "OK",
) -> Span:
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
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


@pytest.mark.asyncio
async def test_get_trace_stats_group_by_agent(stats_db: AsyncPostgresDb):
    await stats_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1", duration_ms=100))
    await stats_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s2", duration_ms=300, status="ERROR"))
    await stats_db.upsert_trace(_make_trace(session_id=None, user_id=None))

    rows, total = await stats_db.get_trace_stats(group_by="agent")

    assert total == 1
    top = rows[0]
    assert top["agent_id"] == "agent-1"
    assert top["total_traces"] == 2
    assert top["avg_duration_ms"] == 200.0
    assert top["p95_duration_ms"] == 290.0
    assert top["error_traces"] == 1


@pytest.mark.asyncio
async def test_get_trace_stats_group_by_endpoint(stats_db: AsyncPostgresDb):
    await stats_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="s1"))
    await stats_db.upsert_trace(_make_trace(session_id=None, user_id=None, name="tools/call run_agent"))

    rows, total = await stats_db.get_trace_stats(group_by="endpoint")

    assert total == 1
    assert rows[0]["name"] == "tools/call run_agent"
    assert rows[0]["total_traces"] == 1


@pytest.mark.asyncio
async def test_get_trace_stats_default_shape_unchanged(stats_db: AsyncPostgresDb):
    await stats_db.upsert_trace(_make_trace(agent_id="agent-1", session_id="session-1"))

    rows, total = await stats_db.get_trace_stats()

    assert total == 1
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
    assert set(rows[0].keys()) == expected_keys


@pytest.mark.asyncio
async def test_get_span_stats(stats_db: AsyncPostgresDb):
    trace = _make_trace(agent_id="agent-1", session_id="s1")
    await stats_db.upsert_trace(trace)
    await stats_db.create_spans(
        [
            _make_span(trace.trace_id, name="slow_tool", duration_ms=900),
            _make_span(trace.trace_id, name="slow_tool", duration_ms=1100),
            _make_span(trace.trace_id, name="Model.invoke", span_type="LLM", duration_ms=500),
        ]
    )

    rows, total = await stats_db.get_span_stats(span_type="TOOL")

    assert total == 1
    assert rows[0]["name"] == "slow_tool"
    assert rows[0]["total_calls"] == 2
    assert rows[0]["avg_duration_ms"] == 1000.0
    assert rows[0]["p95_duration_ms"] == 1090.0
    assert "attributes" not in rows[0]


@pytest.mark.asyncio
async def test_get_span_stats_paging_with_tied_name_groups_is_lossless(stats_db: AsyncPostgresDb):
    trace = _make_trace(agent_id="agent-1", session_id="s1")
    await stats_db.upsert_trace(trace)
    # 8 groups sharing one name, all tied on every aggregate: only the
    # (name, span_type) ORDER BY tiebreak makes paging deterministic
    await stats_db.create_spans([_make_span(trace.trace_id, name="dup", span_type=f"KIND{i:02d}") for i in range(20)])

    seen = []
    total = 0
    for page in range(1, 24):
        rows, total = await stats_db.get_span_stats(limit=3, page=page)
        if not rows:
            break
        seen.extend((row["name"], row["span_type"]) for row in rows)

    assert total == 20
    assert len(seen) == 20
    assert len(set(seen)) == 20


@pytest.mark.asyncio
async def test_get_metrics_refreshes_lazily_and_throttles(stats_db: AsyncPostgresDb):
    async def seed_session(user_id: str) -> None:
        now = int(time.time())
        await stats_db.upsert_session(
            AgentSession(
                session_id=str(uuid.uuid4()), agent_id="agent-1", user_id=user_id, created_at=now, updated_at=now
            )
        )

    await seed_session("user-1")

    # No calculate_metrics call: get_metrics must refresh on its own
    rows, _ = await stats_db.get_metrics()
    assert len(rows) == 1
    assert rows[0]["agent_sessions_count"] == 1

    # A second read within the throttle window must not recompute
    await seed_session("user-2")
    rows, _ = await stats_db.get_metrics()
    assert rows[0]["agent_sessions_count"] == 1

    # Expiring the throttle picks the new session up
    stats_db._metrics_refreshed_at = 0.0
    rows, _ = await stats_db.get_metrics()
    assert rows[0]["agent_sessions_count"] == 2
