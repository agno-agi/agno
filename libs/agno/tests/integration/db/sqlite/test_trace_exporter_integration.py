"""
Integration tests for the trace export pipeline.

These tests exercise the FULL path:
    OTel Tracer.start_span(...)  →  Span.end()
        → SpanProcessor (Simple or Batch)
        → DatabaseSpanExporter.export(...)
        → create_trace_from_spans(...)
        → SqliteDb.upsert_trace(...)

They cover the bug fix from PR #7796:
1. `create_trace_from_spans` must NOT fall back to `spans[0]` when no true root
   is present in the batch (would write a child's session_id to the trace).
2. `SqliteDb.upsert_trace`'s ON CONFLICT clause must preserve existing non-null
   context (COALESCE arg order).

The "post-hook agent" scenario is reproduced by manufacturing two OTel spans:
- An outer "team" root span with `session.id=mobile_session_*`
- A child span inside the team's context with `session.id=ratings_*`

Both end in different orders, in different export batches, exercising the
upsert collision path. The expectation: after the dust settles, the
agno_traces row carries the TEAM's session_id, not the child's.
"""

from typing import Any, Iterator

import pytest
from opentelemetry import trace as trace_api  # type: ignore
from opentelemetry.sdk.trace import TracerProvider  # type: ignore
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor  # type: ignore

from agno.db.sqlite import SqliteDb
from agno.tracing.exporter import DatabaseSpanExporter

TEAM_SESSION = "mobile_session_chris@example.com"
TEAM_ID = "customer_support_team"
RATING_SESSION = "ratings_mobile_session_chris@example.com"
RATING_AGENT_ID = "rating"


@pytest.fixture
def db(tmp_path) -> Iterator[SqliteDb]:
    instance = SqliteDb(db_file=str(tmp_path / "trace_exporter_integration.db"))
    instance._get_table(table_type="traces", create_table_if_not_found=True)
    instance._get_table(table_type="spans", create_table_if_not_found=True)
    yield instance
    if instance.db_engine:
        instance.db_engine.dispose()


def _make_tracer(db: SqliteDb, *, batch: bool) -> tuple[trace_api.Tracer, Any]:
    """Build a fresh TracerProvider wired to our DatabaseSpanExporter.

    Returns (tracer, provider). Caller must `provider.shutdown()` to flush.

    We create a private TracerProvider per test rather than touching the global
    one — keeps tests isolated and avoids leaking state between cases.
    """
    provider = TracerProvider()
    exporter = DatabaseSpanExporter(db=db)
    if batch:
        # max_export_batch_size=1 forces every span to be exported in its own
        # batch — the most adversarial case for the root-span fallback logic.
        provider.add_span_processor(
            BatchSpanProcessor(
                exporter,
                max_queue_size=2048,
                max_export_batch_size=1,
                schedule_delay_millis=10,
            )
        )
    else:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test")
    return tracer, provider


def _read_trace(db: SqliteDb, trace_id: str) -> dict:
    from sqlalchemy import select

    table = db._get_table(table_type="traces", create_table_if_not_found=True)
    with db.Session() as sess:
        row = sess.execute(select(table).where(table.c.trace_id == trace_id)).mappings().one()
        return dict(row)


def _otel_trace_id_hex(span: trace_api.Span) -> str:
    return format(span.get_span_context().trace_id, "032x")


# ---------------------------------------------------------------------------
# 1. SimpleSpanProcessor — exports each span synchronously as it ends.
#    Root span ends LAST (matches real post-hook execution where outer .arun
#    only returns after the post-hook completes). The bug doesn't materialize
#    here on either old or new code because the root batch lands last.
# ---------------------------------------------------------------------------


def test_simple_processor_root_ends_last_keeps_team_session(db):
    """Sanity: SimpleSpanProcessor + root-ends-last is the happy path.
    Should pass on both buggy main and the fix."""
    tracer, provider = _make_tracer(db, batch=False)
    try:
        team_span = tracer.start_span(
            "customer_support_team.run",
            attributes={"session.id": TEAM_SESSION, "agno.team.id": TEAM_ID},
        )
        team_ctx = trace_api.set_span_in_context(team_span)

        rating_span = tracer.start_span(
            "Rating.run",
            context=team_ctx,
            attributes={"session.id": RATING_SESSION, "agno.agent.id": RATING_AGENT_ID},
        )
        rating_span.end()  # child ends first → exports as its own batch
        team_span.end()  # root ends after → exports as its own batch

        trace_id = _otel_trace_id_hex(team_span)
    finally:
        provider.shutdown()

    row = _read_trace(db, trace_id)
    assert row["session_id"] == TEAM_SESSION
    assert row["team_id"] == TEAM_ID
    # Rating's child-only batch is no longer permitted to inject agent_id.
    assert row["agent_id"] is None


# ---------------------------------------------------------------------------
# 2. SimpleSpanProcessor — root ends BEFORE child (race condition where the
#    post-hook's span emission is delayed relative to the team span's
#    instrumentor `finally: span.end()`). This is exactly the scenario where
#    the buggy COALESCE flipped the team's session_id under the rating's.
# ---------------------------------------------------------------------------


def test_simple_processor_root_ends_first_keeps_team_session(db):
    """Adversarial: root ends BEFORE child → without the COALESCE fix, the
    child's later upsert overwrites the team's session_id. With the fix it
    stays correct."""
    tracer, provider = _make_tracer(db, batch=False)
    try:
        team_span = tracer.start_span(
            "customer_support_team.run",
            attributes={"session.id": TEAM_SESSION, "agno.team.id": TEAM_ID},
        )
        team_ctx = trace_api.set_span_in_context(team_span)

        rating_span = tracer.start_span(
            "Rating.run",
            context=team_ctx,
            attributes={"session.id": RATING_SESSION, "agno.agent.id": RATING_AGENT_ID},
        )
        team_span.end()  # root ends first
        rating_span.end()  # child ends after (and exports after)

        trace_id = _otel_trace_id_hex(team_span)
    finally:
        provider.shutdown()

    row = _read_trace(db, trace_id)
    assert row["session_id"] == TEAM_SESSION, "team's session_id was overwritten by rating's"
    assert row["team_id"] == TEAM_ID
    assert row["agent_id"] is None, "team trace must not be tagged with the rating's agent_id"


# ---------------------------------------------------------------------------
# 3. BatchSpanProcessor with max_export_batch_size=1 — every span exports as
#    its own batch. Child-only batches deterministically hit
#    create_trace_from_spans without a root in the batch, exercising the
#    root-span guard.
# ---------------------------------------------------------------------------


def test_batch_processor_size_one_child_only_batches(db):
    """With max_export_batch_size=1, every span is its own batch. The child
    span's batch has no root — without the schemas.py fix it would write the
    child's session_id; with the fix it leaves context NULL so the root's
    later upsert wins."""
    tracer, provider = _make_tracer(db, batch=True)
    try:
        team_span = tracer.start_span(
            "customer_support_team.run",
            attributes={"session.id": TEAM_SESSION, "agno.team.id": TEAM_ID},
        )
        team_ctx = trace_api.set_span_in_context(team_span)

        rating_span = tracer.start_span(
            "Rating.run",
            context=team_ctx,
            attributes={"session.id": RATING_SESSION, "agno.agent.id": RATING_AGENT_ID},
        )
        rating_span.end()
        team_span.end()
        trace_id = _otel_trace_id_hex(team_span)
    finally:
        provider.shutdown()  # forces flush

    row = _read_trace(db, trace_id)
    assert row["session_id"] == TEAM_SESSION
    assert row["team_id"] == TEAM_ID
    assert row["agent_id"] is None


def test_batch_processor_size_one_root_ends_first(db):
    """Adversarial against batch processor: root ends first, child ends later
    in its own batch. The child-only batch must not write context."""
    tracer, provider = _make_tracer(db, batch=True)
    try:
        team_span = tracer.start_span(
            "customer_support_team.run",
            attributes={"session.id": TEAM_SESSION, "agno.team.id": TEAM_ID},
        )
        team_ctx = trace_api.set_span_in_context(team_span)

        rating_span = tracer.start_span(
            "Rating.run",
            context=team_ctx,
            attributes={"session.id": RATING_SESSION, "agno.agent.id": RATING_AGENT_ID},
        )
        team_span.end()
        rating_span.end()
        trace_id = _otel_trace_id_hex(team_span)
    finally:
        provider.shutdown()

    row = _read_trace(db, trace_id)
    assert row["session_id"] == TEAM_SESSION
    assert row["team_id"] == TEAM_ID
    assert row["agent_id"] is None


# ---------------------------------------------------------------------------
# 4. Deep nesting — child of child. Confirms the root-span guard works even
#    when the batch contains a non-root span that has a non-root parent.
# ---------------------------------------------------------------------------


def test_batch_processor_deep_nested_child_only_batch(db):
    """Three-level nesting: team → rating → openai_call. The two inner spans
    arrive in their own batches (no root present). Trace must end up with
    the team's identity."""
    tracer, provider = _make_tracer(db, batch=True)
    try:
        team_span = tracer.start_span(
            "customer_support_team.run",
            attributes={"session.id": TEAM_SESSION, "agno.team.id": TEAM_ID},
        )
        team_ctx = trace_api.set_span_in_context(team_span)

        rating_span = tracer.start_span(
            "Rating.run",
            context=team_ctx,
            attributes={"session.id": RATING_SESSION, "agno.agent.id": RATING_AGENT_ID},
        )
        rating_ctx = trace_api.set_span_in_context(rating_span)

        openai_span = tracer.start_span(
            "OpenAIResponses.invoke",
            context=rating_ctx,
            # No session/agent attrs on the LLM call span — typical case.
        )
        openai_span.end()
        rating_span.end()
        team_span.end()
        trace_id = _otel_trace_id_hex(team_span)
    finally:
        provider.shutdown()

    row = _read_trace(db, trace_id)
    assert row["session_id"] == TEAM_SESSION
    assert row["team_id"] == TEAM_ID
    assert row["agent_id"] is None


# ---------------------------------------------------------------------------
# 5. Multiple concurrent traces (no cross-talk) — sanity that fixing the
#    COALESCE doesn't accidentally couple unrelated trace_ids.
# ---------------------------------------------------------------------------


def test_two_independent_traces_dont_cross_pollute(db):
    """Two team runs with different session_ids. Their traces have different
    trace_ids and must not contaminate each other's rows."""
    tracer, provider = _make_tracer(db, batch=False)
    try:
        team_a = tracer.start_span(
            "customer_support_team.run",
            attributes={"session.id": "session_A", "agno.team.id": TEAM_ID},
        )
        team_b = tracer.start_span(
            "customer_support_team.run",
            attributes={"session.id": "session_B", "agno.team.id": TEAM_ID},
        )

        # End in interleaved order
        team_a.end()
        team_b.end()

        trace_a = _otel_trace_id_hex(team_a)
        trace_b = _otel_trace_id_hex(team_b)
    finally:
        provider.shutdown()

    row_a = _read_trace(db, trace_a)
    row_b = _read_trace(db, trace_b)
    assert row_a["session_id"] == "session_A"
    assert row_b["session_id"] == "session_B"


# ---------------------------------------------------------------------------
# 6. Orphan child batch — root span never arrives (simulates queue overflow
#    or dropped root). Documents the post-fix behavior: trace exists but
#    context fields are NULL rather than mis-attributed to a child.
# ---------------------------------------------------------------------------


def test_orphan_child_batch_yields_null_context(db):
    """If only a child span ever gets exported (root dropped/lost), the trace
    row exists but with NULL context fields — not mis-attributed to the
    child. This is a deliberate behavior change documented in the PR."""
    tracer, provider = _make_tracer(db, batch=True)
    try:
        team_span = tracer.start_span(
            "customer_support_team.run",
            attributes={"session.id": TEAM_SESSION, "agno.team.id": TEAM_ID},
        )
        team_ctx = trace_api.set_span_in_context(team_span)

        rating_span = tracer.start_span(
            "Rating.run",
            context=team_ctx,
            attributes={"session.id": RATING_SESSION, "agno.agent.id": RATING_AGENT_ID},
        )
        rating_span.end()
        trace_id = _otel_trace_id_hex(team_span)
        # NOTE: team_span is intentionally NOT ended → simulates root never
        # making it to the exporter (queue overflow / process crash / etc).
    finally:
        provider.shutdown()

    # Trace row should exist (created when the rating's batch landed) but
    # with NULL context — pre-fix it would have been tagged with the rating's
    # session_id, mis-attributing the orphan trace.
    row = _read_trace(db, trace_id)
    assert row["session_id"] is None, (
        "child-only orphan batch must not write a child's session_id to the "
        "trace; previously this incorrectly tagged the trace with the rating's session"
    )
    assert row["agent_id"] is None
