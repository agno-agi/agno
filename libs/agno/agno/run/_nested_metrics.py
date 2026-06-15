"""Plumbing for propagating nested-run metrics to the enclosing run.

When an agent/team/workflow run is started from inside user code that belongs
to another run — a custom tool, a tool hook, a pre/post hook or a custom
workflow step function — its token metrics must roll up into the enclosing
run so session metrics and AgentOS reflect the real cost of the run. The
channel is a ContextVar in agno.metrics holding the enclosing run's RunMetrics
collector (the "sink").

The helpers here wrap run execution so the run's own sink is installed while
its frames execute (restored per-resume for generators, so the sink never
leaks into consumer contexts between yields) and the run's total metrics are
reported to the enclosing sink exactly once, when the run reaches a terminal
status or its stream is exhausted or closed. Paused runs do not report — the
continued run reports the full metrics when it finishes. Framework-managed
child runs (team members, workflow steps) are already aggregated through
member_responses / step metrics, so those call sites shield the sink to avoid
double counting.
"""

from contextlib import contextmanager
from typing import Any, AsyncIterator, Coroutine, Iterator, List, Optional, TypeVar

from agno.metrics import (
    RunMetrics,
    accumulate_run_metrics,
    get_nested_run_metrics_sink,
    report_metrics_to_sink,
    swap_nested_run_metrics_sink,
)
from agno.run.agent import RunCompletedEvent, RunOutput
from agno.run.base import RunStatus
from agno.run.team import RunCompletedEvent as TeamRunCompletedEvent
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowCompletedEvent, WorkflowRunOutput

T = TypeVar("T")

_TERMINAL_STATUSES = (RunStatus.completed, RunStatus.error, RunStatus.cancelled)

_RUN_OUTPUT_TYPES = (RunOutput, TeamRunOutput, WorkflowRunOutput)

_COMPLETED_EVENT_TYPES = (RunCompletedEvent, TeamRunCompletedEvent, WorkflowCompletedEvent)


def total_run_metrics(run_output: Any) -> Optional[RunMetrics]:
    """Compute the total metrics a completed run should report to its parent.

    - Workflow runs carry WorkflowMetrics: sum the per-step RunMetrics.
    - Team runs: leader metrics plus all member responses, recursively.
    - Agent runs: the run metrics as-is.
    """
    metrics = getattr(run_output, "metrics", None)

    # WorkflowMetrics — aggregate the per-step breakdown
    if metrics is not None and hasattr(metrics, "steps"):
        # Workflow-agent runs already roll the executed steps up into the
        # agent's own run metrics, so those are the full totals
        workflow_agent_run = getattr(run_output, "workflow_agent_run", None)
        if workflow_agent_run is not None and workflow_agent_run.metrics is not None:
            return workflow_agent_run.metrics
        total = RunMetrics()
        for step_metrics in (metrics.steps or {}).values():
            if step_metrics.metrics is not None:
                accumulate_run_metrics(total, step_metrics.metrics)
        return total

    member_responses = getattr(run_output, "member_responses", None)
    if member_responses:
        total = RunMetrics()
        if metrics is not None:
            accumulate_run_metrics(total, metrics)
            # Keep the team leader's timing — member runs happen within it
            total.duration = metrics.duration
            total.time_to_first_token = metrics.time_to_first_token
        _accumulate_member_metrics(total, member_responses)
        return total

    return metrics


def _accumulate_member_metrics(total: RunMetrics, member_responses: List[Any]) -> None:
    for member_response in member_responses:
        member_metrics = getattr(member_response, "metrics", None)
        if member_metrics is not None:
            accumulate_run_metrics(total, member_metrics)
        nested_members = getattr(member_response, "member_responses", None)
        if nested_members:
            _accumulate_member_metrics(total, nested_members)


def report_run_to_parent(parent_sink: Optional[RunMetrics], run_output: Any) -> None:
    """Report a finished run's total metrics to the enclosing run's sink."""
    if parent_sink is None or run_output is None:
        return
    # Paused runs report nothing — the continued run reports the full metrics.
    if getattr(run_output, "status", None) == RunStatus.paused:
        return
    report_metrics_to_sink(parent_sink, total_run_metrics(run_output))


def run_stream_with_metrics_scope(
    stream: Iterator[T],
    run_output: Any,
    sink: Optional[RunMetrics],
    run_id: Optional[str] = None,
    swallow_run_output: bool = False,
) -> Iterator[T]:
    """Wrap a run's event stream so nested-run metrics propagate correctly.

    The sink is installed only while the inner generator's frames execute and
    restored before each event is yielded out. The run reports to the parent
    sink as soon as it reaches a terminal status, so metrics survive consumers
    that stop iterating after the completed event.

    A run continued by run_id resolves the stored run inside its own frames, so
    run_output is None at wrap time; pass run_id so the wrapper can adopt the
    resolved output (or its completed event) from the stream without mistaking
    a member's or nested run's output for this run's. Continue dispatchers force
    yield_run_output so the resolved output reaches the wrapper, and set
    swallow_run_output when the caller did not ask for it.
    """
    reported = False
    parent_sink: Optional[RunMetrics] = None
    completed_event: Any = None
    # The run's frames may replace their own sink (e.g. a continued run installs
    # its metrics once the stored run is resolved) — capture what they leave
    # installed on each resume so it is re-installed on the next one.
    current_sink = sink
    try:
        while True:
            parent_sink = swap_nested_run_metrics_sink(current_sink)
            try:
                item = next(stream)
            except StopIteration:
                if not reported:
                    reported = True
                    report_run_to_parent(parent_sink, run_output if run_output is not None else completed_event)
                return
            finally:
                current_sink = swap_nested_run_metrics_sink(parent_sink)
            if run_output is None and getattr(item, "run_id", None) == run_id and run_id is not None:
                if isinstance(item, _RUN_OUTPUT_TYPES):
                    run_output = item
                elif isinstance(item, _COMPLETED_EVENT_TYPES):
                    # The resolved output is only yielded when yield_run_output is
                    # set — keep the completed event as a fallback to report from
                    completed_event = item
            if not reported and getattr(run_output, "status", None) in _TERMINAL_STATUSES:
                reported = True
                report_run_to_parent(parent_sink, run_output)
            if swallow_run_output and isinstance(item, _RUN_OUTPUT_TYPES) and item.run_id == run_id:
                continue
            yield item
    finally:
        if not reported:
            report_run_to_parent(parent_sink, run_output if run_output is not None else completed_event)


async def arun_stream_with_metrics_scope(
    stream: AsyncIterator[T],
    run_output: Any,
    sink: Optional[RunMetrics],
    run_id: Optional[str] = None,
    swallow_run_output: bool = False,
) -> AsyncIterator[T]:
    """Async variant of run_stream_with_metrics_scope."""
    reported = False
    parent_sink: Optional[RunMetrics] = None
    completed_event: Any = None
    current_sink = sink
    try:
        while True:
            parent_sink = swap_nested_run_metrics_sink(current_sink)
            try:
                item = await stream.__anext__()
            except StopAsyncIteration:
                if not reported:
                    reported = True
                    report_run_to_parent(parent_sink, run_output if run_output is not None else completed_event)
                return
            finally:
                current_sink = swap_nested_run_metrics_sink(parent_sink)
            if run_output is None and getattr(item, "run_id", None) == run_id and run_id is not None:
                if isinstance(item, _RUN_OUTPUT_TYPES):
                    run_output = item
                elif isinstance(item, _COMPLETED_EVENT_TYPES):
                    # The resolved output is only yielded when yield_run_output is
                    # set — keep the completed event as a fallback to report from
                    completed_event = item
            if not reported and getattr(run_output, "status", None) in _TERMINAL_STATUSES:
                reported = True
                report_run_to_parent(parent_sink, run_output)
            if swallow_run_output and isinstance(item, _RUN_OUTPUT_TYPES) and item.run_id == run_id:
                continue
            yield item
    finally:
        if not reported:
            report_run_to_parent(parent_sink, run_output if run_output is not None else completed_event)


async def arun_with_metrics_scope(coro: Coroutine[Any, Any, T], run_output: Any, sink: Optional[RunMetrics]) -> T:
    """Await a non-streaming run with its metrics sink installed.

    Reports the returned output (which may be a different object than
    run_output, e.g. on cancellation) to the enclosing sink on the way out.
    """
    parent_sink = swap_nested_run_metrics_sink(sink)
    result = None
    try:
        result = await coro
        return result
    finally:
        swap_nested_run_metrics_sink(parent_sink)
        report_run_to_parent(parent_sink, result if result is not None else run_output)


def shielded_stream(stream: Iterator[T]) -> Iterator[T]:
    """Consume a framework-managed child run's stream with the sink shielded.

    Used where the parent already aggregates the child's metrics through its
    own bookkeeping (team member responses), so the child must not also report
    to the ambient sink.
    """
    while True:
        parent_sink = swap_nested_run_metrics_sink(None)
        try:
            item = next(stream)
        except StopIteration:
            return
        finally:
            swap_nested_run_metrics_sink(parent_sink)
        yield item


async def ashielded_stream(stream: AsyncIterator[T]) -> AsyncIterator[T]:
    """Async variant of shielded_stream."""
    while True:
        parent_sink = swap_nested_run_metrics_sink(None)
        try:
            item = await stream.__anext__()
        except StopAsyncIteration:
            return
        finally:
            swap_nested_run_metrics_sink(parent_sink)
        yield item


@contextmanager
def shielded_metrics_sink():
    """Hide the ambient metrics sink.

    Used around framework-managed child runs whose metrics are aggregated
    through other means (member responses, workflow step metrics).
    """
    parent_sink = swap_nested_run_metrics_sink(None)
    try:
        yield
    finally:
        # Restore only if our shield is still installed — a generator holding
        # this context manager may be closed from a foreign context (e.g. an
        # abandoned stream finalized in its consumer's context), where swapping
        # would clobber that context's own sink.
        if get_nested_run_metrics_sink() is None:
            swap_nested_run_metrics_sink(parent_sink)


@contextmanager
def metrics_collection_sink():
    """Install a fresh collection sink and yield it.

    Used around custom workflow step functions: nested runs started inside the
    function report into the yielded collector, which is then attached to the
    step output.
    """
    collected = RunMetrics()
    parent_sink = swap_nested_run_metrics_sink(collected)
    try:
        yield collected
    finally:
        # Restore only if our collector is still installed — a generator holding
        # this context manager may be closed from a foreign context (e.g. an
        # abandoned stream finalized in its consumer's context), where swapping
        # would clobber that context's own sink.
        if get_nested_run_metrics_sink() is collected:
            swap_nested_run_metrics_sink(parent_sink)


def has_token_metrics(metrics: Optional[RunMetrics]) -> bool:
    """Whether a collector accumulated anything worth attaching."""
    if metrics is None:
        return False
    return metrics.total_tokens > 0 or metrics.input_tokens > 0 or metrics.output_tokens > 0 or bool(metrics.details)
