"""Integration tests for ClickhouseDb against a real ClickHouse server.

These tests require a live ClickHouse on ``localhost:8123`` (HTTP) with
credentials ``ai/ai`` — exactly what ``./cookbook/scripts/run_clickhouse.sh``
provides. Each test creates and tears down its own database so runs are
isolated.

Run with::

    pytest libs/agno/tests/integration/db/clickhouse -v

Skips automatically if ClickHouse isn't reachable.
"""

from datetime import datetime, timedelta, timezone
from typing import Iterator, List
from uuid import uuid4

import pytest

from agno.db.clickhouse import ClickhouseDb
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


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def clickhouse_db() -> Iterator[ClickhouseDb]:
    """A ClickhouseDb pointing at a unique database, dropped on teardown."""
    db_name = f"agno_traces_test_{uuid4().hex[:8]}"
    db = ClickhouseDb(
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
            db._client.command(f"DROP DATABASE IF EXISTS {db_name}")
        finally:
            db.close()


def _make_spans(trace_id: str, count: int = 3, agent_id: str = "agent-1") -> List[Span]:
    """Build a small chain of spans sharing a trace_id."""
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
# Schema bootstrap
# --------------------------------------------------------------------------- #


def test_schema_is_created_on_first_write(clickhouse_db: ClickhouseDb):
    """Tables don't exist until the first write — then they're cached."""
    assert clickhouse_db.table_exists(clickhouse_db.trace_table_name) is False
    assert clickhouse_db.table_exists(clickhouse_db.span_table_name) is False

    spans = _make_spans("trace-bootstrap")
    clickhouse_db.upsert_trace(create_trace_from_spans(spans))
    clickhouse_db.create_spans(spans)

    assert clickhouse_db.table_exists(clickhouse_db.trace_table_name) is True
    assert clickhouse_db.table_exists(clickhouse_db.span_table_name) is True


def test_reads_against_empty_db_return_empty(clickhouse_db: ClickhouseDb):
    """Read paths must not provision tables — and must not raise."""
    assert clickhouse_db.get_trace(trace_id="missing") is None
    assert clickhouse_db.get_traces() == ([], 0)
    assert clickhouse_db.get_trace_stats() == ([], 0)
    assert clickhouse_db.get_spans(trace_id="missing") == []


# --------------------------------------------------------------------------- #
# Trace round-trip
# --------------------------------------------------------------------------- #


def test_trace_round_trip(clickhouse_db: ClickhouseDb):
    spans = _make_spans("trace-rt", count=3)
    trace = create_trace_from_spans(spans)
    clickhouse_db.upsert_trace(trace)
    clickhouse_db.create_spans(spans)

    fetched = clickhouse_db.get_trace(trace_id="trace-rt")
    assert fetched is not None
    assert fetched.trace_id == "trace-rt"
    assert fetched.total_spans == 3
    assert fetched.error_count == 1  # last span was ERROR
    assert fetched.agent_id == "agent-1"


def test_get_traces_with_filter_expr_trace_id(clickhouse_db: ClickhouseDb):
    """The FE filters by trace_id via FilterExpr; previously this was ignored
    and returned all traces. Now it should match exactly the requested id."""
    for i in range(3):
        spans = _make_spans(f"trace-fe-{i}", count=1)
        clickhouse_db.upsert_trace(create_trace_from_spans(spans))
        clickhouse_db.create_spans(spans)

    matched, total = clickhouse_db.get_traces(
        filter_expr={"op": "EQ", "key": "trace_id", "value": "trace-fe-1"}
    )
    assert total == 1
    assert matched[0].trace_id == "trace-fe-1"

    miss, total = clickhouse_db.get_traces(
        filter_expr={"op": "EQ", "key": "trace_id", "value": "does-not-exist"}
    )
    assert total == 0
    assert miss == []


def test_get_traces_accepts_iso_datetime_strings(clickhouse_db: ClickhouseDb):
    """The FE sends start_time/end_time as ISO 8601 strings with TZ offsets
    (e.g. '+05:30'). Previously these failed with TYPE_MISMATCH against the
    DateTime64('UTC') column; now they're coerced to UTC datetimes."""
    spans = _make_spans("trace-iso", count=1)
    clickhouse_db.upsert_trace(create_trace_from_spans(spans))
    clickhouse_db.create_spans(spans)

    now = datetime.now(timezone.utc)
    ist = timezone(timedelta(hours=5, minutes=30))
    fe_start = (now - timedelta(hours=1)).astimezone(ist).isoformat()
    fe_end = (now + timedelta(hours=1)).astimezone(ist).isoformat()

    traces, total = clickhouse_db.get_traces(start_time=fe_start, end_time=fe_end)
    assert total == 1
    assert traces[0].trace_id == "trace-iso"

    # get_trace_stats accepts the same format.
    stats, total = clickhouse_db.get_trace_stats(start_time=fe_start, end_time=fe_end)
    assert total == 1


def test_get_traces_excludes_traces_outside_time_range(clickhouse_db: ClickhouseDb):
    """Regression for the FE date-range filter: a trace whose start_time is
    *outside* the requested window must be excluded, not silently returned."""
    spans = _make_spans("trace-out-of-range", count=1)
    clickhouse_db.upsert_trace(create_trace_from_spans(spans))
    clickhouse_db.create_spans(spans)

    # Request a window two months in the past — the trace is "now" so it
    # must not appear.
    ist = timezone(timedelta(hours=5, minutes=30))
    past_start = (datetime.now(timezone.utc) - timedelta(days=60)).astimezone(ist).isoformat()
    past_end = (datetime.now(timezone.utc) - timedelta(days=30)).astimezone(ist).isoformat()

    traces, total = clickhouse_db.get_traces(start_time=past_start, end_time=past_end)
    assert (traces, total) == ([], 0)

    stats, total = clickhouse_db.get_trace_stats(start_time=past_start, end_time=past_end)
    assert (stats, total) == ([], 0)


def test_get_traces_partial_range_filters(clickhouse_db: ClickhouseDb):
    """start_time alone and end_time alone must each apply correctly."""
    spans = _make_spans("trace-partial", count=1)
    clickhouse_db.upsert_trace(create_trace_from_spans(spans))
    clickhouse_db.create_spans(spans)

    now = datetime.now(timezone.utc)

    # Only start_time, in the past → trace is included.
    _, total = clickhouse_db.get_traces(start_time=(now - timedelta(hours=1)).isoformat())
    assert total == 1

    # Only start_time, in the future → trace is excluded.
    _, total = clickhouse_db.get_traces(start_time=(now + timedelta(hours=1)).isoformat())
    assert total == 0

    # Only end_time, in the future → trace is included.
    _, total = clickhouse_db.get_traces(end_time=(now + timedelta(hours=1)).isoformat())
    assert total == 1

    # Only end_time, in the past → trace is excluded.
    _, total = clickhouse_db.get_traces(end_time=(now - timedelta(hours=1)).isoformat())
    assert total == 0


def test_get_traces_filter_expr_datetime_columns(clickhouse_db: ClickhouseDb):
    """FilterExpr targeting datetime columns must coerce string values too."""
    spans = _make_spans("trace-fe-dt", count=1)
    clickhouse_db.upsert_trace(create_trace_from_spans(spans))
    clickhouse_db.create_spans(spans)

    now = datetime.now(timezone.utc)
    iso = (now - timedelta(hours=1)).isoformat()

    matched, total = clickhouse_db.get_traces(
        filter_expr={"op": "GTE", "key": "start_time", "value": iso}
    )
    assert total == 1
    assert matched[0].trace_id == "trace-fe-dt"


def test_get_traces_with_filter_expr_unknown_column_returns_empty(clickhouse_db: ClickhouseDb):
    """Matches PostgresDb semantics: invalid filter is logged + returns empty."""
    spans = _make_spans("trace-bad-filter", count=1)
    clickhouse_db.upsert_trace(create_trace_from_spans(spans))

    out, total = clickhouse_db.get_traces(
        filter_expr={"op": "EQ", "key": "not_a_column", "value": "x"}
    )
    assert (out, total) == ([], 0)


def test_get_traces_paginates_and_filters(clickhouse_db: ClickhouseDb):
    for i in range(5):
        spans = _make_spans(f"trace-page-{i}", count=1, agent_id=f"agent-{i % 2}")
        clickhouse_db.upsert_trace(create_trace_from_spans(spans))
        clickhouse_db.create_spans(spans)

    all_traces, total = clickhouse_db.get_traces(limit=10)
    assert total == 5
    assert len(all_traces) == 5

    filtered, total = clickhouse_db.get_traces(agent_id="agent-0")
    # agent-0 → indexes 0, 2, 4
    assert total == 3
    assert all(t.agent_id == "agent-0" for t in filtered)


def test_get_trace_stats_groups_by_session(clickhouse_db: ClickhouseDb):
    for i in range(3):
        spans = _make_spans(f"trace-stats-{i}", count=1, agent_id="agent-stats")
        clickhouse_db.upsert_trace(create_trace_from_spans(spans))
        clickhouse_db.create_spans(spans)

    stats, total = clickhouse_db.get_trace_stats(agent_id="agent-stats")
    assert total == 1  # all 3 traces share session_id "sess-1"
    assert stats[0]["session_id"] == "sess-1"
    assert stats[0]["total_traces"] == 3
    assert stats[0]["agent_id"] == "agent-stats"


def test_upsert_trace_is_idempotent(clickhouse_db: ClickhouseDb):
    """ReplacingMergeTree should collapse duplicate trace_ids on read with FINAL."""
    spans = _make_spans("trace-dup", count=2)
    trace = create_trace_from_spans(spans)
    for _ in range(3):
        clickhouse_db.upsert_trace(trace)

    _, total = clickhouse_db.get_traces()
    # FINAL collapses the 3 inserts down to one logical row.
    assert total == 1


# --------------------------------------------------------------------------- #
# Spans
# --------------------------------------------------------------------------- #


def test_get_spans_returns_inserted_rows(clickhouse_db: ClickhouseDb):
    spans = _make_spans("trace-spans", count=4)
    clickhouse_db.create_spans(spans)

    fetched = clickhouse_db.get_spans(trace_id="trace-spans")
    assert len(fetched) == 4
    # Attributes are JSON-encoded to String and decoded back to dict.
    assert fetched[0].attributes.get("agno.agent.id") == "agent-1"


def test_get_span_by_id(clickhouse_db: ClickhouseDb):
    spans = _make_spans("trace-by-id", count=1)
    clickhouse_db.create_spans(spans)

    fetched = clickhouse_db.get_span(spans[0].span_id)
    assert fetched is not None
    assert fetched.span_id == spans[0].span_id
    assert fetched.trace_id == "trace-by-id"


# --------------------------------------------------------------------------- #
# Schema versioning
# --------------------------------------------------------------------------- #


def test_schema_version_round_trip(clickhouse_db: ClickhouseDb):
    clickhouse_db.upsert_schema_version("agno_traces", "1.0.0")
    assert clickhouse_db.get_latest_schema_version("agno_traces") == "1.0.0"

    # Updating to a newer version replaces the row via ReplacingMergeTree.
    clickhouse_db.upsert_schema_version("agno_traces", "1.1.0")
    assert clickhouse_db.get_latest_schema_version("agno_traces") == "1.1.0"
