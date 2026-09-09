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

    matched, total = clickhouse_db.get_traces(filter_expr={"op": "EQ", "key": "trace_id", "value": "trace-fe-1"})
    assert total == 1
    assert matched[0].trace_id == "trace-fe-1"

    miss, total = clickhouse_db.get_traces(filter_expr={"op": "EQ", "key": "trace_id", "value": "does-not-exist"})
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

    matched, total = clickhouse_db.get_traces(filter_expr={"op": "GTE", "key": "start_time", "value": iso})
    assert total == 1
    assert matched[0].trace_id == "trace-fe-dt"


def test_get_traces_with_filter_expr_unknown_column_returns_empty(clickhouse_db: ClickhouseDb):
    """Matches PostgresDb semantics: invalid filter is logged + returns empty."""
    spans = _make_spans("trace-bad-filter", count=1)
    clickhouse_db.upsert_trace(create_trace_from_spans(spans))

    out, total = clickhouse_db.get_traces(filter_expr={"op": "EQ", "key": "not_a_column", "value": "x"})
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
    """Re-ingesting an identical trace must collapse to one logical row on read."""
    spans = _make_spans("trace-dup", count=2)
    trace = create_trace_from_spans(spans)
    for _ in range(3):
        clickhouse_db.upsert_trace(trace)

    _, total = clickhouse_db.get_traces()
    # Read-time GROUP BY collapses the 3 inserts down to one logical row.
    assert total == 1


def _root_and_child_partials(trace_id: str):
    """Build the two partial Traces the exporter upserts for one trace_id (root batch, then child-only batch)."""
    base = datetime.now(timezone.utc)
    root = Span(
        span_id=f"span-{trace_id}-root",
        trace_id=trace_id,
        parent_span_id=None,
        name="MyAgent.run",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=base,
        end_time=base + timedelta(seconds=2),
        duration_ms=2000,
        attributes={"agno.agent.id": "agent-merge", "agno.session.id": "sess-merge", "agno.user.id": "user-merge"},
        created_at=base,
    )
    child = Span(
        span_id=f"span-{trace_id}-child",
        trace_id=trace_id,
        parent_span_id=f"span-{trace_id}-root",
        name="OpenAI.invoke",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=base + timedelta(seconds=1),
        end_time=base + timedelta(seconds=2),
        duration_ms=1000,
        attributes={"step": 1},
        created_at=base,
    )
    return create_trace_from_spans([root]), create_trace_from_spans([child]), root, child


@pytest.mark.parametrize("child_first", [False, True], ids=["root_then_child", "child_then_root"])
def test_partial_batches_merge_into_one_trace(clickhouse_db: ClickhouseDb, child_first: bool):
    """Partial upserts for one trace_id reconcile to a single trace whose identity
    comes from the root batch, regardless of arrival order — matching PostgresDb's
    ON CONFLICT merge."""
    root_trace, child_trace, root_span, child_span = _root_and_child_partials("trace-merge")
    order = [child_trace, root_trace] if child_first else [root_trace, child_trace]
    for partial in order:
        clickhouse_db.upsert_trace(partial)
    clickhouse_db.create_spans([root_span, child_span])

    traces, total = clickhouse_db.get_traces()
    assert total == 1  # one logical trace, not one row per batch
    merged = traces[0]
    # Root-batch identity wins; child-only batch must not clobber it.
    assert merged.name == "MyAgent.run"
    assert merged.session_id == "sess-merge"
    assert merged.agent_id == "agent-merge"
    assert merged.user_id == "user-merge"
    # Times span the full trace (earliest start, latest end).
    assert merged.start_time == root_span.start_time
    assert merged.end_time == root_span.end_time

    # get_trace by id returns the same merged row, not a partial.
    fetched = clickhouse_db.get_trace(trace_id="trace-merge")
    assert fetched is not None
    assert fetched.name == "MyAgent.run"
    assert fetched.session_id == "sess-merge"


def test_partial_batches_surface_errors_in_any_batch(clickhouse_db: ClickhouseDb):
    """If any partial batch reports an ERROR span, the merged trace status is ERROR."""
    base = datetime.now(timezone.utc)
    root = Span(
        span_id="span-err-root",
        trace_id="trace-err",
        parent_span_id=None,
        name="MyAgent.run",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=base,
        end_time=base + timedelta(seconds=2),
        duration_ms=2000,
        attributes={"agno.agent.id": "agent-err"},
        created_at=base,
    )
    child = Span(
        span_id="span-err-child",
        trace_id="trace-err",
        parent_span_id="span-err-root",
        name="OpenAI.invoke",
        span_kind="INTERNAL",
        status_code="ERROR",
        status_message="boom",
        start_time=base + timedelta(seconds=1),
        end_time=base + timedelta(seconds=2),
        duration_ms=1000,
        attributes={"step": 1},
        created_at=base,
    )
    clickhouse_db.upsert_trace(create_trace_from_spans([root]))
    clickhouse_db.upsert_trace(create_trace_from_spans([child]))

    fetched = clickhouse_db.get_trace(trace_id="trace-err")
    assert fetched is not None
    assert fetched.status == "ERROR"
    assert fetched.name == "MyAgent.run"


def test_inner_agent_does_not_pollute_outer_team_trace(clickhouse_db: ClickhouseDb):
    """A post-hook inner agent shares the trace_id but has a different agent_id /
    session_id; its child-only batch must not leak into the outer team trace.
    Mirrors the SqliteDb/PostgresDb exporter guarantee."""
    base = datetime.now(timezone.utc)
    team = Span(
        span_id="team",
        trace_id="trace-posthook",
        parent_span_id=None,
        name="customer_support_team.run",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=base,
        end_time=base + timedelta(seconds=3),
        duration_ms=3000,
        attributes={
            "agno.team.id": "customer_support_team",
            "agno.session.id": "team_session_abc",
            "agno.run.id": "run-outer-1",
        },
        created_at=base,
    )
    rating = Span(
        span_id="rating",
        trace_id="trace-posthook",
        parent_span_id="team",
        name="rating.run",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=base + timedelta(seconds=1),
        end_time=base + timedelta(seconds=2),
        duration_ms=1000,
        attributes={"agno.agent.id": "rating", "agno.session.id": "mobile_session_chris"},
        created_at=base,
    )
    # Root (team) batch first, then the inner child-only batch.
    clickhouse_db.upsert_trace(create_trace_from_spans([team]))
    clickhouse_db.upsert_trace(create_trace_from_spans([rating]))

    fetched = clickhouse_db.get_trace(trace_id="trace-posthook")
    assert fetched is not None
    assert fetched.name == "customer_support_team.run"
    assert fetched.team_id == "customer_support_team"
    assert fetched.session_id == "team_session_abc"
    assert fetched.run_id == "run-outer-1"
    assert fetched.agent_id is None  # rating's agent_id must not leak in


def test_independent_traces_do_not_cross_pollute(clickhouse_db: ClickhouseDb):
    """Merging one trace_id must not couple it to an unrelated trace_id."""
    a = _make_spans("trace-iso-a", count=2, agent_id="agent-a")
    b = _make_spans("trace-iso-b", count=2, agent_id="agent-b")
    clickhouse_db.upsert_trace(create_trace_from_spans(a))
    clickhouse_db.upsert_trace(create_trace_from_spans(b))

    ta = clickhouse_db.get_trace(trace_id="trace-iso-a")
    tb = clickhouse_db.get_trace(trace_id="trace-iso-b")
    assert ta.agent_id == "agent-a"
    assert tb.agent_id == "agent-b"


def test_partials_survive_background_merge(clickhouse_db: ClickhouseDb):
    """Partial rows that collide on the sort key (start_time, trace_id) must not be
    dropped when ClickHouse merges parts. A deduplicating engine would discard one
    and lose trace context; the traces table must be a MergeTree."""
    t = datetime.now(timezone.utc)
    # Root and child-only batches share the SAME start_time, so their partial
    # rows collide on the (start_time, trace_id) sort key — the worst case.
    root = Span(
        span_id="span-survive-root",
        trace_id="trace-merge-survive",
        parent_span_id=None,
        name="MyAgent.run",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=t,
        end_time=t,
        duration_ms=0,
        attributes={"agno.agent.id": "agent-1", "agno.session.id": "sess-1", "agno.run.id": "run-1"},
        created_at=t,
    )
    child = Span(
        span_id="span-survive-child",
        trace_id="trace-merge-survive",
        parent_span_id="span-survive-root",
        name="OpenAI.invoke",
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=t,
        end_time=t,
        duration_ms=0,
        attributes={"step": 1},
        created_at=t,
    )
    clickhouse_db.upsert_trace(create_trace_from_spans([root]))
    clickhouse_db.upsert_trace(create_trace_from_spans([child]))

    # Force the background merge ClickHouse would otherwise run on its own schedule.
    clickhouse_db._client.command(f"OPTIMIZE TABLE {clickhouse_db.database}.{clickhouse_db.trace_table_name} FINAL")

    fetched = clickhouse_db.get_trace(trace_id="trace-merge-survive")
    assert fetched is not None
    assert fetched.name == "MyAgent.run"
    assert fetched.agent_id == "agent-1"
    assert fetched.session_id == "sess-1"


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
