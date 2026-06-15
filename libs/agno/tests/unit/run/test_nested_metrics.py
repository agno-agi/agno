"""Unit tests for the nested-run metrics sink machinery (no API calls)."""

import pytest

from agno.metrics import (
    ModelMetrics,
    RunMetrics,
    get_nested_run_metrics_sink,
    report_metrics_to_sink,
    swap_nested_run_metrics_sink,
)
from agno.run._nested_metrics import (
    arun_stream_with_metrics_scope,
    has_token_metrics,
    metrics_collection_sink,
    report_run_to_parent,
    run_stream_with_metrics_scope,
    shielded_metrics_sink,
    total_run_metrics,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus


@pytest.fixture(autouse=True)
def _reset_sink():
    """Isolate from sink leaks of unrelated tests sharing this context."""
    swap_nested_run_metrics_sink(None)
    yield
    swap_nested_run_metrics_sink(None)


def _metrics(total: int, duration: float = 1.0) -> RunMetrics:
    return RunMetrics(
        input_tokens=total // 2,
        output_tokens=total - total // 2,
        total_tokens=total,
        duration=duration,
        details={"model": [ModelMetrics(id="m1", provider="p", total_tokens=total)]},
    )


def test_report_merges_tokens_but_not_timing():
    parent = RunMetrics(total_tokens=15, duration=1.0)
    child = _metrics(150, duration=99.0)
    child.cost = 0.5
    report_metrics_to_sink(parent, child)
    assert parent.total_tokens == 165
    assert parent.duration == 1.0
    assert parent.cost == 0.5
    assert parent.details["model"][0].total_tokens == 150


def test_report_to_self_is_a_noop():
    metrics = _metrics(10)
    report_metrics_to_sink(metrics, metrics)
    assert metrics.total_tokens == 10


def test_sink_swap_and_shield():
    parent = RunMetrics()
    previous = swap_nested_run_metrics_sink(parent)
    assert previous is None
    try:
        with shielded_metrics_sink():
            assert get_nested_run_metrics_sink() is None
        assert get_nested_run_metrics_sink() is parent
    finally:
        swap_nested_run_metrics_sink(None)


def test_collection_sink_collects_reports():
    with metrics_collection_sink() as collected:
        report_metrics_to_sink(get_nested_run_metrics_sink(), _metrics(150))
    assert collected.total_tokens == 150
    assert has_token_metrics(collected)
    assert get_nested_run_metrics_sink() is None


def test_paused_runs_do_not_report():
    run_output = RunOutput(run_id="r1", metrics=_metrics(42))
    run_output.status = RunStatus.paused
    sink = RunMetrics()
    report_run_to_parent(sink, run_output)
    assert sink.total_tokens == 0
    run_output.status = RunStatus.completed
    report_run_to_parent(sink, run_output)
    assert sink.total_tokens == 42


def test_total_run_metrics_includes_members():
    class FakeOutput:
        pass

    team_output = FakeOutput()
    team_output.metrics = _metrics(10, duration=2.5)
    member = FakeOutput()
    member.metrics = _metrics(20)
    member.member_responses = None
    team_output.member_responses = [member]

    total = total_run_metrics(team_output)
    assert total.total_tokens == 30
    assert total.duration == 2.5


def test_stream_scope_reports_once_and_restores_sink():
    run_output = RunOutput(run_id="r2", metrics=_metrics(7))
    outer = RunMetrics()

    def stream():
        yield "a"
        run_output.status = RunStatus.completed
        yield "b"

    swap_nested_run_metrics_sink(outer)
    try:
        events = []
        for event in run_stream_with_metrics_scope(stream(), run_output, sink=run_output.metrics):
            events.append(event)
            # The sink never leaks into the consumer context between yields
            assert get_nested_run_metrics_sink() is outer
    finally:
        swap_nested_run_metrics_sink(None)

    assert events == ["a", "b"]
    assert outer.total_tokens == 7


def test_stream_scope_reports_on_early_break():
    run_output = RunOutput(run_id="r3", metrics=_metrics(9))
    outer = RunMetrics()

    def stream():
        run_output.status = RunStatus.completed
        yield "completed-event"
        yield "never-consumed"

    swap_nested_run_metrics_sink(outer)
    try:
        for _ in run_stream_with_metrics_scope(stream(), run_output, sink=run_output.metrics):
            break
    finally:
        swap_nested_run_metrics_sink(None)

    assert outer.total_tokens == 9


def test_stream_scope_picks_up_resolved_run_output():
    """A run continued by run_id starts with no run_output; the wrapper picks up
    the resolved output from the stream and reports it on completion."""
    resolved = RunOutput(run_id="r6", metrics=_metrics(13))
    outer = RunMetrics()

    def stream():
        yield "event"
        resolved.status = RunStatus.completed
        yield resolved

    swap_nested_run_metrics_sink(outer)
    try:
        for _ in run_stream_with_metrics_scope(stream(), None, sink=None, run_id="r6"):
            pass
    finally:
        swap_nested_run_metrics_sink(None)

    assert outer.total_tokens == 13


def test_stream_scope_reports_own_completed_event_without_run_output():
    """Without yield_run_output the resolved output is never yielded — the
    wrapper falls back to the run's own completed event."""
    from agno.run.agent import RunCompletedEvent

    outer = RunMetrics()

    def stream():
        yield "event"
        yield RunCompletedEvent(run_id="r7", metrics=_metrics(17))

    swap_nested_run_metrics_sink(outer)
    try:
        for _ in run_stream_with_metrics_scope(stream(), None, sink=None, run_id="r7"):
            pass
    finally:
        swap_nested_run_metrics_sink(None)

    assert outer.total_tokens == 17


def test_stream_scope_ignores_foreign_outputs_and_events():
    """Member or nested-run outputs and completed events flowing through a
    by-run_id continue stream must not be adopted as this run's output."""
    from agno.run.agent import RunCompletedEvent

    outer = RunMetrics()
    foreign_output = RunOutput(run_id="member-1", metrics=_metrics(100))
    foreign_output.status = RunStatus.completed

    def stream():
        yield RunCompletedEvent(run_id="member-1", metrics=_metrics(100))
        yield foreign_output
        yield RunCompletedEvent(run_id="r8", metrics=_metrics(21))

    swap_nested_run_metrics_sink(outer)
    try:
        for _ in run_stream_with_metrics_scope(stream(), None, sink=None, run_id="r8"):
            pass
    finally:
        swap_nested_run_metrics_sink(None)

    # Only the run's own completed event is reported — never the member's
    assert outer.total_tokens == 21


def test_stream_scope_preserves_inner_sink_replacement():
    """A continued run installs its own sink mid-stream; the per-resume swap keeps it."""
    resolved_metrics = RunMetrics()
    run_output = RunOutput(run_id="r4", metrics=resolved_metrics)
    outer = RunMetrics()

    def stream():
        # Mimic a continued run resolving its stored run and installing its sink
        swap_nested_run_metrics_sink(resolved_metrics)
        yield "a"
        # Nested run reporting inside the run's frames lands on the resolved sink
        report_metrics_to_sink(get_nested_run_metrics_sink(), _metrics(5))
        run_output.status = RunStatus.completed
        yield "b"

    swap_nested_run_metrics_sink(outer)
    try:
        for _ in run_stream_with_metrics_scope(stream(), run_output, sink=None):
            assert get_nested_run_metrics_sink() is outer
    finally:
        swap_nested_run_metrics_sink(None)

    assert resolved_metrics.total_tokens == 5
    # The run reported its (resolved) metrics to the outer sink on completion
    assert outer.total_tokens == 5


def test_collection_sink_close_in_foreign_context_does_not_clobber():
    """Closing a generator holding a collection sink from a consumer context must
    not overwrite the consumer's own sink."""

    def gen():
        with metrics_collection_sink():
            yield "a"
            yield "b"

    iterator = gen()
    next(iterator)  # enter the with block; the collector leaks into this context
    consumer_sink = RunMetrics()
    swap_nested_run_metrics_sink(consumer_sink)
    try:
        iterator.close()  # finalized while the consumer's sink is installed
        assert get_nested_run_metrics_sink() is consumer_sink
    finally:
        swap_nested_run_metrics_sink(None)


@pytest.mark.asyncio
async def test_async_stream_scope_reports_once():
    run_output = RunOutput(run_id="r5", metrics=_metrics(11))
    outer = RunMetrics()

    async def astream():
        yield "a"
        run_output.status = RunStatus.completed
        yield "b"

    swap_nested_run_metrics_sink(outer)
    try:
        async for _ in arun_stream_with_metrics_scope(astream(), run_output, sink=run_output.metrics):
            assert get_nested_run_metrics_sink() is outer
    finally:
        swap_nested_run_metrics_sink(None)

    assert outer.total_tokens == 11
