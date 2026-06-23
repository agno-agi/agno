"""
Regression test for the post-hook agent session_id override bug.

When a post-hook on an outer agent invokes a *second* agent (the "post-hook agent")
with its own session_id, OpenTelemetry exports both agents' spans under the same
trace_id (because the inner agent's spans are children of the outer agent's span).
Each export batch triggers `create_trace_from_spans` followed by `upsert_trace`.

There were two bugs that combined to override the outer trace's session_id:

1. `create_trace_from_spans` fell back to `spans[0]` when no true root span was
   present in the batch, then read `session_id`/`agent_id`/etc. from that
   non-root span. So a batch containing only the post-hook agent's child spans
   produced a Trace dict tagged with the post-hook agent's session_id.

2. `upsert_trace`'s ON CONFLICT clause used
       COALESCE(insert_stmt.excluded.session_id, table.c.session_id)
   which returns the new value whenever it's non-null — the opposite of what
   the comment claimed ("preserve existing"). Whichever export batch landed
   last won the context fields.

This file covers both layers:
- Direct `upsert_trace` calls verify the COALESCE order.
- `create_trace_from_spans` calls with fabricated spans verify the root-span
  guard, mirroring what the OTel exporter sees in the real post-hook flow.
"""

from datetime import datetime, timedelta, timezone

import pytest

from agno.db.sqlite import SqliteDb
from agno.tracing.schemas import Span, Trace, create_trace_from_spans


@pytest.fixture
def db(tmp_path):
    db_file = tmp_path / "trace_context_preservation.db"
    instance = SqliteDb(db_file=str(db_file))
    instance._get_table(table_type="traces", create_table_if_not_found=True)
    yield instance
    if instance.db_engine:
        instance.db_engine.dispose()


def _make_trace(
    *,
    trace_id: str,
    name: str,
    session_id,
    user_id,
    agent_id,
    team_id,
    run_id,
    workflow_id=None,
    start_offset_s: float = 0.0,
) -> Trace:
    base = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    start = base + timedelta(seconds=start_offset_s)
    end = start + timedelta(milliseconds=100)
    return Trace(
        trace_id=trace_id,
        name=name,
        status="OK",
        start_time=start,
        end_time=end,
        duration_ms=100,
        total_spans=1,
        error_count=0,
        run_id=run_id,
        session_id=session_id,
        user_id=user_id,
        agent_id=agent_id,
        team_id=team_id,
        workflow_id=workflow_id,
        created_at=start,
    )


def _read_trace(db: SqliteDb, trace_id: str) -> dict:
    from sqlalchemy import select

    table = db._get_table(table_type="traces", create_table_if_not_found=True)
    with db.Session() as sess:
        row = sess.execute(select(table).where(table.c.trace_id == trace_id)).mappings().one()
        return dict(row)


def test_upsert_trace_preserves_session_id_when_inner_context_arrives_after(db):
    """Outer team's correct session_id must survive a follow-up upsert tagged
    with the post-hook (rating) agent's session_id."""
    trace_id = "trace-outer-then-inner"

    db.upsert_trace(
        _make_trace(
            trace_id=trace_id,
            name="customer_support_team.run",
            session_id="mobile_session_chris@example.com",
            user_id="chris@example.com",
            agent_id=None,
            team_id="customer_support_team",
            run_id="run-outer-1",
            start_offset_s=0.0,
        )
    )

    db.upsert_trace(
        _make_trace(
            trace_id=trace_id,
            name="Rating.run",
            session_id="ratings_mobile_session_chris@example.com",
            user_id="chris@example.com",
            agent_id="rating",
            team_id=None,
            run_id="run-inner-1",
            start_offset_s=0.05,
        )
    )

    row = _read_trace(db, trace_id)
    assert row["session_id"] == "mobile_session_chris@example.com"
    assert row["team_id"] == "customer_support_team"
    assert row["run_id"] == "run-outer-1"
    assert row["agent_id"] == "rating"


def _make_span(
    *,
    span_id: str,
    parent_span_id,
    trace_id: str,
    name: str,
    session_id=None,
    agent_id=None,
    team_id=None,
    run_id=None,
    user_id=None,
    start_offset_s: float = 0.0,
) -> Span:
    base = datetime(2026, 5, 4, 12, 0, 0, tzinfo=timezone.utc)
    start = base + timedelta(seconds=start_offset_s)
    end = start + timedelta(milliseconds=100)
    attrs: dict = {}
    if session_id is not None:
        attrs["session.id"] = session_id
    if agent_id is not None:
        attrs["agno.agent.id"] = agent_id
    if team_id is not None:
        attrs["agno.team.id"] = team_id
    if run_id is not None:
        attrs["agno.run.id"] = run_id
    if user_id is not None:
        attrs["user.id"] = user_id
    return Span(
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        name=name,
        span_kind="INTERNAL",
        status_code="OK",
        status_message=None,
        start_time=start,
        end_time=end,
        duration_ms=100,
        attributes=attrs,
        created_at=start,
    )


def test_create_trace_from_spans_skips_context_when_no_root_in_batch():
    """A child-only batch (post-hook agent's spans exporting before the parent
    span ends) must not produce a Trace tagged with the child's session_id.
    Context fields stay None so the upsert COALESCE preserves whatever the
    root-span batch wrote."""
    trace_id = "trace-child-only"

    inner_run = _make_span(
        span_id="inner-run",
        parent_span_id="outer-run",
        trace_id=trace_id,
        name="Rating.run",
        session_id="ratings_mobile_session_chris@example.com",
        agent_id="rating",
        run_id="run-inner-1",
    )
    inner_llm = _make_span(
        span_id="inner-llm",
        parent_span_id="inner-run",
        trace_id=trace_id,
        name="OpenAIResponses.invoke",
        start_offset_s=0.05,
    )

    trace = create_trace_from_spans([inner_run, inner_llm])

    assert trace is not None
    assert trace.session_id is None
    assert trace.agent_id is None
    assert trace.run_id is None


def test_create_trace_from_spans_uses_root_when_present():
    """When the batch DOES contain the root span, its context should be used —
    even if a child span with a different session_id is also in the batch."""
    trace_id = "trace-root-and-child"

    outer_run = _make_span(
        span_id="outer-run",
        parent_span_id=None,
        trace_id=trace_id,
        name="customer_support_team.run",
        session_id="mobile_session_chris@example.com",
        team_id="customer_support_team",
        run_id="run-outer-1",
    )
    inner_run = _make_span(
        span_id="inner-run",
        parent_span_id="outer-run",
        trace_id=trace_id,
        name="Rating.run",
        session_id="ratings_mobile_session_chris@example.com",
        agent_id="rating",
        run_id="run-inner-1",
        start_offset_s=0.05,
    )

    trace = create_trace_from_spans([outer_run, inner_run])

    assert trace is not None
    assert trace.session_id == "mobile_session_chris@example.com"
    assert trace.team_id == "customer_support_team"
    assert trace.run_id == "run-outer-1"


def test_pipeline_inner_batch_first_then_root_batch(db):
    """Full pipeline: inner span batch lands first (matches the real OTel
    export ordering, since inner runs end before the outer parent span),
    followed by the root span batch. Final trace row must carry the OUTER
    session_id."""
    trace_id = "trace-pipeline-inner-first"

    inner_run = _make_span(
        span_id="inner-run",
        parent_span_id="outer-run",
        trace_id=trace_id,
        name="Rating.run",
        session_id="ratings_mobile_session_chris@example.com",
        agent_id="rating",
        run_id="run-inner-1",
        start_offset_s=0.05,
    )
    db.upsert_trace(create_trace_from_spans([inner_run]))

    outer_run = _make_span(
        span_id="outer-run",
        parent_span_id=None,
        trace_id=trace_id,
        name="customer_support_team.run",
        session_id="mobile_session_chris@example.com",
        team_id="customer_support_team",
        run_id="run-outer-1",
    )
    db.upsert_trace(create_trace_from_spans([outer_run]))

    row = _read_trace(db, trace_id)
    assert row["session_id"] == "mobile_session_chris@example.com"
    assert row["team_id"] == "customer_support_team"
    assert row["run_id"] == "run-outer-1"
    assert row["name"] == "customer_support_team.run"


def test_pipeline_root_batch_first_then_inner_batch(db):
    """Full pipeline: root batch lands first, then a child-only batch from a
    post-hook agent. The trace's outer context must survive."""
    trace_id = "trace-pipeline-root-first"

    outer_run = _make_span(
        span_id="outer-run",
        parent_span_id=None,
        trace_id=trace_id,
        name="customer_support_team.run",
        session_id="mobile_session_chris@example.com",
        team_id="customer_support_team",
        run_id="run-outer-1",
    )
    db.upsert_trace(create_trace_from_spans([outer_run]))

    inner_run = _make_span(
        span_id="inner-run",
        parent_span_id="outer-run",
        trace_id=trace_id,
        name="Rating.run",
        session_id="ratings_mobile_session_chris@example.com",
        agent_id="rating",
        run_id="run-inner-1",
        start_offset_s=0.05,
    )
    db.upsert_trace(create_trace_from_spans([inner_run]))

    row = _read_trace(db, trace_id)
    assert row["session_id"] == "mobile_session_chris@example.com"
    assert row["team_id"] == "customer_support_team"
    assert row["run_id"] == "run-outer-1"
