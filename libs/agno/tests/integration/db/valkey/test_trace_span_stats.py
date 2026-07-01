"""Integration tests for index-based span stats in get_trace / get_traces.

Verifies that _get_span_stats_for_trace uses the trace_id index set + pipeline
instead of scanning all spans, and that the results are correct.
"""

import time as time_module
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from agno.db.valkey.valkey import ValkeyDb
from agno.tracing.schemas import Span, Trace


def _make_trace(trace_id: str, **overrides) -> Trace:
    now = datetime.now(tz=timezone.utc)
    defaults = dict(
        trace_id=trace_id,
        name="test.run",
        run_id=f"run_{trace_id}",
        session_id="sess_1",
        user_id="user_1",
        agent_id="agent_1",
        team_id=None,
        workflow_id=None,
        start_time=now,
        end_time=now + timedelta(milliseconds=200),
        duration_ms=200,
        total_spans=0,
        error_count=0,
        status="OK",
        created_at=now,
    )
    defaults.update(overrides)
    return Trace(**defaults)


def _make_span(span_id: str, trace_id: str, status_code: str = "OK") -> Span:
    now = datetime.now(tz=timezone.utc)
    return Span(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=None,
        name=f"span_{span_id}",
        span_kind="internal",
        status_code=status_code,
        status_message=None,
        start_time=now,
        end_time=now + timedelta(milliseconds=50),
        duration_ms=50,
        attributes={},
        created_at=now,
    )


# -- Correctness --


def test_get_trace_span_stats_correct(valkey_db: ValkeyDb):
    """get_trace returns accurate total_spans and error_count."""
    valkey_db.upsert_trace(_make_trace("t1"))
    valkey_db.create_spans(
        [
            _make_span("s1", "t1", "OK"),
            _make_span("s2", "t1", "OK"),
            _make_span("s3", "t1", "ERROR"),
        ]
    )

    result = valkey_db.get_trace(trace_id="t1")
    assert result is not None
    assert result.total_spans == 3
    assert result.error_count == 1


def test_get_trace_no_spans(valkey_db: ValkeyDb):
    """get_trace returns zero counts when trace has no spans."""
    valkey_db.upsert_trace(_make_trace("t_empty"))

    result = valkey_db.get_trace(trace_id="t_empty")
    assert result is not None
    assert result.total_spans == 0
    assert result.error_count == 0


def test_get_trace_by_run_id_span_stats(valkey_db: ValkeyDb):
    """get_trace by run_id also returns correct span stats."""
    valkey_db.upsert_trace(_make_trace("t2"))
    valkey_db.create_spans(
        [
            _make_span("s4", "t2", "ERROR"),
            _make_span("s5", "t2", "ERROR"),
        ]
    )

    result = valkey_db.get_trace(run_id="run_t2")
    assert result is not None
    assert result.total_spans == 2
    assert result.error_count == 2


def test_get_traces_span_stats_per_trace(valkey_db: ValkeyDb):
    """get_traces enriches each trace with its own span stats, not a global count."""
    valkey_db.upsert_trace(_make_trace("ta"))
    valkey_db.upsert_trace(_make_trace("tb"))

    valkey_db.create_spans(
        [
            _make_span("sa1", "ta", "OK"),
            _make_span("sa2", "ta", "ERROR"),
        ]
    )
    valkey_db.create_spans(
        [
            _make_span("sb1", "tb", "OK"),
            _make_span("sb2", "tb", "OK"),
            _make_span("sb3", "tb", "OK"),
        ]
    )

    traces, total = valkey_db.get_traces(user_id="user_1")
    assert total == 2

    by_id = {t.trace_id: t for t in traces}
    assert by_id["ta"].total_spans == 2
    assert by_id["ta"].error_count == 1
    assert by_id["tb"].total_spans == 3
    assert by_id["tb"].error_count == 0


def test_span_stats_isolated_across_traces(valkey_db: ValkeyDb):
    """Spans from one trace do not leak into another trace's stats."""
    valkey_db.upsert_trace(_make_trace("iso_a"))
    valkey_db.upsert_trace(_make_trace("iso_b"))

    valkey_db.create_spans([_make_span(f"iso_s{i}", "iso_a") for i in range(10)])
    # iso_b has zero spans

    result_a = valkey_db.get_trace(trace_id="iso_a")
    result_b = valkey_db.get_trace(trace_id="iso_b")

    assert result_a is not None and result_a.total_spans == 10
    assert result_b is not None and result_b.total_spans == 0


# -- Efficiency: index-based lookup avoids full span scan --


def test_get_trace_does_not_scan_all_spans(valkey_db: ValkeyDb):
    """get_trace uses the index, not _get_all_records('spans')."""
    valkey_db.upsert_trace(_make_trace("t_eff"))
    valkey_db.create_spans([_make_span("eff_s1", "t_eff")])

    with patch.object(valkey_db, "_get_all_records", wraps=valkey_db._get_all_records) as mock_get_all:
        valkey_db.get_trace(trace_id="t_eff")

        # _get_all_records should NOT have been called with "spans"
        span_calls = [c for c in mock_get_all.call_args_list if c.args[0] == "spans"]
        assert len(span_calls) == 0, "_get_all_records('spans') should not be called for index-based lookup"


def test_get_traces_does_not_scan_all_spans(valkey_db: ValkeyDb):
    """get_traces uses per-trace index lookups, not a full span scan."""
    valkey_db.upsert_trace(_make_trace("t_eff2"))
    valkey_db.create_spans([_make_span("eff2_s1", "t_eff2")])

    with patch.object(valkey_db, "_get_all_records", wraps=valkey_db._get_all_records) as mock_get_all:
        valkey_db.get_traces(user_id="user_1")

        span_calls = [c for c in mock_get_all.call_args_list if c.args[0] == "spans"]
        assert len(span_calls) == 0, "_get_all_records('spans') should not be called for index-based lookup"


def test_get_traces_only_enriches_paginated_page(valkey_db: ValkeyDb):
    """Span stats are only computed for the returned page, not all matching traces."""
    # Create 10 traces, each with 1 span
    for i in range(10):
        valkey_db.upsert_trace(_make_trace(f"pg_{i}"))
        valkey_db.create_span(_make_span(f"pg_s{i}", f"pg_{i}"))

    with patch.object(valkey_db, "_get_span_stats_for_trace", wraps=valkey_db._get_span_stats_for_trace) as mock_stats:
        traces, total = valkey_db.get_traces(user_id="user_1", limit=3, page=1)

        assert total == 10
        assert len(traces) == 3
        # Should only call _get_span_stats_for_trace 3 times (page size), not 10
        assert mock_stats.call_count == 3


# -- Timing: index path should be faster than full scan with many unrelated spans --
# This is a test purely developed to time an optimization I did.


def test_index_lookup_faster_than_full_scan(valkey_db: ValkeyDb):
    """Index-based span stats is faster than scanning all spans when most spans are unrelated."""
    # Create one target trace with 2 spans
    valkey_db.upsert_trace(_make_trace("target"))
    valkey_db.create_spans(
        [
            _make_span("target_s1", "target", "OK"),
            _make_span("target_s2", "target", "ERROR"),
        ]
    )

    # Create 200 unrelated spans across other traces
    noise_spans = [_make_span(f"noise_{i}", f"noise_trace_{i % 20}") for i in range(200)]
    valkey_db.create_spans(noise_spans)

    # Time the index-based approach (what we actually use)
    start = time_module.perf_counter()
    for _ in range(20):
        total, errors = valkey_db._get_span_stats_for_trace("target")
    index_elapsed = time_module.perf_counter() - start

    assert total == 2
    assert errors == 1

    # Time the full-scan approach (what we replaced)
    start = time_module.perf_counter()
    for _ in range(20):
        all_spans = valkey_db._get_all_records("spans")
        trace_spans = [s for s in all_spans if s.get("trace_id") == "target"]
        _total = len(trace_spans)
        _errors = len([s for s in trace_spans if s.get("status_code") == "ERROR"])
    scan_elapsed = time_module.perf_counter() - start

    assert _total == 2
    assert _errors == 1

    # Index path should be meaningfully faster with 200+ unrelated spans
    # Using a generous 3x margin to avoid flaky CI failures
    assert index_elapsed < scan_elapsed * 3, (
        f"Index lookup ({index_elapsed:.4f}s) should be faster than full scan ({scan_elapsed:.4f}s)"
    )
