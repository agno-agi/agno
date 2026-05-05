"""Integration tests for AsyncClickhouseDb against a real ClickHouse server.

Mirrors the sync tests in ``test_traces.py`` for the async adapter — same
fixtures, same assertions, just awaited. Skips automatically if ClickHouse
isn't reachable.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import AsyncIterator, List
from uuid import uuid4

import pytest
import pytest_asyncio

from agno.db.clickhouse import AsyncClickhouseDb
from agno.tracing.schemas import Span, create_trace_from_spans

CLICKHOUSE_HOST = "localhost"
CLICKHOUSE_PORT = 8123
CLICKHOUSE_USER = "ai"
CLICKHOUSE_PASSWORD = "ai"


def _server_available() -> bool:
    try:
        import clickhouse_connect

        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
        )
        client.command("SELECT 1")
        client.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _server_available(),
    reason="ClickHouse server not reachable on localhost:8123 (run ./cookbook/scripts/run_clickhouse.sh)",
)


@pytest_asyncio.fixture
async def clickhouse_db() -> AsyncIterator[AsyncClickhouseDb]:
    db_name = f"agno_traces_async_test_{uuid4().hex[:8]}"
    db = AsyncClickhouseDb(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=db_name,
    )
    try:
        yield db
    finally:
        try:
            client = await db._client_()
            await client.command(f"DROP DATABASE IF EXISTS {db_name}")
        finally:
            await db.close()


def _make_spans(trace_id: str, count: int = 3, agent_id: str = "agent-1") -> List[Span]:
    now = datetime.now(timezone.utc)
    spans: List[Span] = []
    for i in range(count):
        spans.append(
            Span(
                span_id=f"span-{trace_id}-{i:016x}",
                trace_id=trace_id,
                parent_span_id=None if i == 0 else f"span-{trace_id}-{(i - 1):016x}",
                name=f"step-{i}",
                span_kind="INTERNAL",
                status_code="ERROR" if i == count - 1 and count > 1 else "OK",
                status_message=None,
                start_time=now + timedelta(milliseconds=i * 5),
                end_time=now + timedelta(milliseconds=i * 5 + 4),
                duration_ms=4,
                attributes=(
                    {
                        "agno.agent.id": agent_id,
                        "agno.session.id": "sess-1",
                        "agno.run.id": "run-1",
                    }
                    if i == 0
                    else {"step": i}
                ),
                created_at=now,
            )
        )
    return spans


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #


async def test_async_trace_round_trip(clickhouse_db: AsyncClickhouseDb):
    spans = _make_spans("trace-async-rt", count=3)
    await clickhouse_db.upsert_trace(create_trace_from_spans(spans))
    await clickhouse_db.create_spans(spans)

    fetched = await clickhouse_db.get_trace(trace_id="trace-async-rt")
    assert fetched is not None
    assert fetched.trace_id == "trace-async-rt"
    assert fetched.total_spans == 3
    assert fetched.error_count == 1


async def test_async_reads_against_empty_db_return_empty(clickhouse_db: AsyncClickhouseDb):
    assert await clickhouse_db.get_trace(trace_id="missing") is None
    assert await clickhouse_db.get_traces() == ([], 0)
    assert await clickhouse_db.get_trace_stats() == ([], 0)
    assert await clickhouse_db.get_spans(trace_id="missing") == []


# --------------------------------------------------------------------------- #
# Filtering
# --------------------------------------------------------------------------- #


async def test_async_get_traces_with_filter_expr_trace_id(clickhouse_db: AsyncClickhouseDb):
    for i in range(3):
        spans = _make_spans(f"trace-async-fe-{i}", count=1)
        await clickhouse_db.upsert_trace(create_trace_from_spans(spans))
        await clickhouse_db.create_spans(spans)

    matched, total = await clickhouse_db.get_traces(
        filter_expr={"op": "EQ", "key": "trace_id", "value": "trace-async-fe-1"}
    )
    assert total == 1
    assert matched[0].trace_id == "trace-async-fe-1"

    miss, total = await clickhouse_db.get_traces(
        filter_expr={"op": "EQ", "key": "trace_id", "value": "does-not-exist"}
    )
    assert (miss, total) == ([], 0)


async def test_async_get_traces_accepts_iso_datetime_strings(clickhouse_db: AsyncClickhouseDb):
    """FE sends ISO strings like '2026-05-05T16:30:00+05:30' for the async DB too."""
    spans = _make_spans("trace-async-iso", count=1)
    await clickhouse_db.upsert_trace(create_trace_from_spans(spans))
    await clickhouse_db.create_spans(spans)

    now = datetime.now(timezone.utc)
    ist = timezone(timedelta(hours=5, minutes=30))
    fe_start = (now - timedelta(hours=1)).astimezone(ist).isoformat()
    fe_end = (now + timedelta(hours=1)).astimezone(ist).isoformat()

    traces, total = await clickhouse_db.get_traces(start_time=fe_start, end_time=fe_end)
    assert total == 1
    assert traces[0].trace_id == "trace-async-iso"

    stats, total = await clickhouse_db.get_trace_stats(start_time=fe_start, end_time=fe_end)
    assert total == 1


async def test_async_get_traces_excludes_traces_outside_time_range(
    clickhouse_db: AsyncClickhouseDb,
):
    """Regression: a trace outside the requested time range must not leak through."""
    spans = _make_spans("trace-async-out-of-range", count=1)
    await clickhouse_db.upsert_trace(create_trace_from_spans(spans))
    await clickhouse_db.create_spans(spans)

    ist = timezone(timedelta(hours=5, minutes=30))
    past_start = (datetime.now(timezone.utc) - timedelta(days=60)).astimezone(ist).isoformat()
    past_end = (datetime.now(timezone.utc) - timedelta(days=30)).astimezone(ist).isoformat()

    traces, total = await clickhouse_db.get_traces(start_time=past_start, end_time=past_end)
    assert (traces, total) == ([], 0)

    stats, total = await clickhouse_db.get_trace_stats(start_time=past_start, end_time=past_end)
    assert (stats, total) == ([], 0)


async def test_async_get_traces_concurrent_writes_share_schema(clickhouse_db: AsyncClickhouseDb):
    """Concurrent first-time writes must not race on schema creation.

    With the per-table cache + lazy create-if-not-exists, a burst of trace
    exports against a fresh DB should all succeed and end up in the same
    underlying table — covering the BatchSpanProcessor scenario.
    """

    async def write_one(i: int) -> None:
        spans = _make_spans(f"trace-async-concurrent-{i}", count=1)
        await clickhouse_db.upsert_trace(create_trace_from_spans(spans))
        await clickhouse_db.create_spans(spans)

    await asyncio.gather(*(write_one(i) for i in range(8)))

    _, total = await clickhouse_db.get_traces(limit=20)
    assert total == 8


# --------------------------------------------------------------------------- #
# Schema versioning
# --------------------------------------------------------------------------- #


async def test_async_schema_version_round_trip(clickhouse_db: AsyncClickhouseDb):
    await clickhouse_db.upsert_schema_version("agno_traces", "1.0.0")
    assert await clickhouse_db.get_latest_schema_version("agno_traces") == "1.0.0"

    await clickhouse_db.upsert_schema_version("agno_traces", "1.1.0")
    assert await clickhouse_db.get_latest_schema_version("agno_traces") == "1.1.0"
