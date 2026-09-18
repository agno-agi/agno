"""Integration tests for the setup and main methods of the AsyncOracleDb class"""

import time
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from agno.db.oracle import AsyncOracleDb


@pytest.mark.asyncio
async def test_init_with_db_url():
    """Test initialization with actual database URL format"""
    db_url = "oracle+oracledb_async://ai:ai@localhost:1521/?service_name=FREEPDB1"

    db = AsyncOracleDb(db_url=db_url, session_table="test_async_oracle_sessions")
    assert db.db_url == db_url
    assert db.session_table_name == "test_async_oracle_sessions"

    # Test connection
    async with db.async_session_factory() as sess:
        result = await sess.execute(text("SELECT 1 FROM dual"))
        assert result.scalar() == 1

    await db.db_engine.dispose()


@pytest.mark.asyncio
async def test_create_session_table_integration(async_oracle_db_real):
    """Test actual session table creation with Oracle"""
    await async_oracle_db_real._create_table("test_async_oracle_sessions", "sessions")

    # Oracle stores unquoted identifiers uppercase in the data dictionary
    async with async_oracle_db_real.async_session_factory() as sess:
        result = await sess.execute(
            text("SELECT table_name FROM user_tables WHERE table_name = 'TEST_ASYNC_ORACLE_SESSIONS'")
        )
        assert result.scalar() == "TEST_ASYNC_ORACLE_SESSIONS"

    assert await async_oracle_db_real.table_exists("test_async_oracle_sessions")


@pytest.mark.asyncio
async def test_create_metrics_table_with_constraints(async_oracle_db_real):
    """Test creating metrics table with unique constraints"""
    await async_oracle_db_real._create_table("test_metrics", "metrics")

    # Verify unique constraint exists (named f"{table_name}_{constraint_name}" by _create_table)
    async with async_oracle_db_real.async_session_factory() as sess:
        result = await sess.execute(
            text(
                "SELECT constraint_name FROM user_constraints "
                "WHERE table_name = 'TEST_METRICS' AND constraint_type = 'U'"
            )
        )
        constraints = [row[0] for row in result.fetchall()]
        assert any("UQ_METRICS_DATE_PERIOD" in c for c in constraints)


@pytest.mark.asyncio
async def test_create_table_with_indexes(async_oracle_db_real):
    """Test that indexes are created correctly"""
    await async_oracle_db_real._create_table("test_memories", "memories")

    # Verify indexes exist (named idx_{table_name}_{col} by _create_table, uppercased by Oracle)
    async with async_oracle_db_real.async_session_factory() as sess:
        result = await sess.execute(text("SELECT index_name FROM user_indexes WHERE table_name = 'TEST_MEMORIES'"))
        indexes = [row[0] for row in result.fetchall()]

        # Should have indexes on user_id and updated_at
        assert any("USER_ID" in idx for idx in indexes)
        assert any("UPDATED_AT" in idx for idx in indexes)


@pytest.mark.asyncio
async def test_get_or_create_existing_table(async_oracle_db_real):
    """Test getting an existing table"""
    # First create the table
    await async_oracle_db_real._create_table("test_async_oracle_sessions", "sessions")

    # Clear the cached table attribute
    if hasattr(async_oracle_db_real, "session_table"):
        delattr(async_oracle_db_real, "session_table")

    # Now get it again - should not recreate
    with patch.object(async_oracle_db_real, "_create_table", new=AsyncMock()) as mock_create:
        table = await async_oracle_db_real._get_or_create_table(
            table_name="test_async_oracle_sessions", table_type="sessions", create_table_if_not_found=True
        )

        # Should not call create since table exists
        mock_create.assert_not_called()

    assert table.name == "test_async_oracle_sessions"


@pytest.mark.asyncio
async def test_full_workflow(async_oracle_db_real):
    """Test a complete workflow of creating and using tables"""
    # Get tables (will create them)
    session_table = await async_oracle_db_real._get_table("sessions", create_table_if_not_found=True)
    await async_oracle_db_real._get_table("memories", create_table_if_not_found=True)

    # Verify tables are cached
    assert hasattr(async_oracle_db_real, "session_table")
    assert hasattr(async_oracle_db_real, "memory_table")

    # Verify we can insert data (basic smoke test)
    async with async_oracle_db_real.async_session_factory() as sess:
        # Insert a test session
        await sess.execute(
            session_table.insert().values(
                session_id="test-session-123",
                session_type="agent",
                created_at=int(datetime.now(timezone.utc).timestamp() * 1000),
                session_data={"test": "data"},
            )
        )
        await sess.commit()

        # Query it back
        result = await sess.execute(session_table.select().where(session_table.c.session_id == "test-session-123"))
        row = result.fetchone()

        assert row is not None
        assert row.session_type == "agent"


# -- Oracle-specific extra cases --


@pytest.mark.asyncio
async def test_json_column_round_trips_payload_over_4000_bytes(async_oracle_db_real):
    """Round-trip a JSON payload bigger than Oracle's classic VARCHAR2(4000) limit.

    Confirms the CLOB-backed OracleJSON column type used across oracle/schemas.py
    does not truncate/reject large documents.
    """
    from agno.session import AgentSession

    large_value = "x" * 4500
    assert len(large_value.encode("utf-8")) > 4000

    session = AgentSession(
        session_id="test-large-json-session",
        agent_id="test-agent",
        user_id="test-user",
        session_data={"large_field": large_value, "nested": {"more_data": large_value}},
        created_at=int(time.time()),
    )

    result = await async_oracle_db_real.upsert_session(session)
    assert result is not None

    retrieved = await async_oracle_db_real.get_session(session_id="test-large-json-session", session_type=None)
    assert retrieved is not None
    assert retrieved.session_data["large_field"] == large_value
    assert retrieved.session_data["nested"]["more_data"] == large_value


@pytest.mark.asyncio
async def test_upsert_schema_version_merge_is_idempotent(async_oracle_db_real):
    """MERGE-based upsert_schema_version must not create duplicate rows on a second call.

    Uses a unique `table_name` key so this test is independent from other tests/suites
    that share the (un-prefixed, not test-table-scoped) `agno_schema_versions` table.
    """
    await async_oracle_db_real._get_table("versions", create_table_if_not_found=True)
    version_key = f"test_merge_idempotent_{uuid.uuid4().hex[:8]}"

    await async_oracle_db_real.upsert_schema_version(table_name=version_key, version="2.0.0")
    await async_oracle_db_real.upsert_schema_version(table_name=version_key, version="2.1.0")

    versions_table_name = async_oracle_db_real.versions_table_name
    async with async_oracle_db_real.async_session_factory() as sess:
        result = (
            await sess.execute(
                text(f"SELECT version, COUNT(*) FROM {versions_table_name} WHERE table_name = :t GROUP BY version"),
                {"t": version_key},
            )
        ).fetchall()

    # A single row for the table_name key, holding the latest version written
    assert len(result) == 1
    assert result[0][0] == "2.1.0"
    assert result[0][1] == 1


@pytest.mark.asyncio
async def test_get_trace_aggregates_span_counts(async_oracle_engine):
    """get_trace/get_traces must aggregate span counts once spans exist.

    Grouping the trace-span join by trace_id alone raises ORA-00979 on Oracle,
    so the provider aggregates spans in a derived subquery instead.
    """
    from agno.tracing.schemas import Span, Trace

    db = AsyncOracleDb(db_engine=async_oracle_engine, traces_table="test_traces_agg", spans_table="test_spans_agg")
    now = datetime.now(timezone.utc)
    await db.upsert_trace(
        Trace(
            trace_id="test-agg-trace",
            name="agent.run",
            status="OK",
            start_time=now,
            end_time=now,
            duration_ms=10,
            total_spans=0,
            error_count=0,
            run_id=None,
            session_id=None,
            user_id=None,
            agent_id="agent-1",
            team_id=None,
            workflow_id=None,
            created_at=now,
        )
    )
    for span_id, status_code in (("test-agg-span-ok", "OK"), ("test-agg-span-err", "ERROR")):
        await db.create_span(
            Span(
                span_id=span_id,
                trace_id="test-agg-trace",
                parent_span_id=None,
                name="step",
                span_kind="INTERNAL",
                status_code=status_code,
                status_message=None,
                start_time=now,
                end_time=now,
                duration_ms=10,
                attributes={},
                created_at=now,
            )
        )

    trace = await db.get_trace(trace_id="test-agg-trace")
    assert trace is not None
    assert trace.total_spans == 2
    assert trace.error_count == 1

    traces, total = await db.get_traces()
    assert total >= 1
    assert any(t.trace_id == "test-agg-trace" for t in traces)


@pytest.mark.asyncio
async def test_concurrent_upsert_trace_retries_on_unique_violation(async_oracle_engine):
    """The losing MERGE of two concurrent inserts of a brand-new trace_id must retry.

    Both writers pass the FOR UPDATE read (no row to lock yet) and take the insert
    branch; the loser hits ORA-00001 and, without the retry, its trace data would be
    silently dropped.
    """
    import asyncio

    from sqlalchemy import create_engine

    from agno.tracing.schemas import Trace

    db = AsyncOracleDb(db_engine=async_oracle_engine, traces_table="test_traces_race")
    now = datetime.now(timezone.utc)

    def make_trace(trace_id: str, agent_id: str) -> Trace:
        return Trace(
            trace_id=trace_id,
            name="agent.run",
            status="OK",
            start_time=now,
            end_time=now,
            duration_ms=10,
            total_spans=0,
            error_count=0,
            run_id=None,
            session_id=None,
            user_id=None,
            agent_id=agent_id,
            team_id=None,
            workflow_id=None,
            created_at=now,
        )

    # Create the table outside the race window
    await db.upsert_trace(make_trace("test-race-warmup", "warmup-agent"))

    # Writer A (a plain sync connection): uncommitted insert of the contended trace_id
    sync_url = async_oracle_engine.url.render_as_string(hide_password=False).replace("+oracledb_async", "+oracledb")
    sync_engine = create_engine(sync_url)
    blocker = sync_engine.connect()
    tx = blocker.begin()
    blocker.execute(text("SELECT * FROM test_traces_race WHERE trace_id = 'test-race-1' FOR UPDATE"))
    blocker.execute(
        text(
            "INSERT INTO test_traces_race (trace_id, name, status, start_time, end_time, duration_ms, created_at) "
            "VALUES ('test-race-1', 'agent.run', 'OK', '2026-01-01T00:00:00+00:00', "
            "'2026-01-01T00:00:01+00:00', 1000, '2026-01-01T00:00:00+00:00')"
        )
    )

    # Writer B: blocks on writer A's uncommitted unique index entry, then loses
    loser = asyncio.create_task(db.upsert_trace(make_trace("test-race-1", "loser-agent")))
    await asyncio.sleep(2)
    tx.commit()
    await asyncio.wait_for(loser, timeout=30)
    blocker.close()

    async with async_oracle_engine.connect() as conn:
        result = await conn.execute(text("SELECT agent_id FROM test_traces_race WHERE trace_id = 'test-race-1'"))
        agent_id = result.scalar()
    sync_engine.dispose()
    assert agent_id == "loser-agent"
