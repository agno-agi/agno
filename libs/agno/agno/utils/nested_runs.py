"""Runs started inside a tool call of another run.

An agent, team or workflow run started from a tool is linked to the run whose tool started it with
called_from_run_id. A run stored as a row of its own keeps its tokens on that row. A run stored nowhere (no db)
adds its tokens to the run whose tool started it, so every stored total holds each token once.
"""

import contextvars
from contextlib import contextmanager
from typing import AsyncIterator, Awaitable, Iterator, List, Optional, Tuple, TypeVar, Union

from agno.metrics import RunMetrics, merge_background_metrics
from agno.run.agent import RunOutput
from agno.run.base import METRICS_FINAL_STATUSES
from agno.run.team import TeamRunOutput
from agno.run.workflow import WorkflowRunOutput

T = TypeVar("T")

# Use ContextVar instead of threading.local so the runs are collected per coroutine/task, not per thread,
# keeping the runs of concurrent tool calls apart.
_nested_runs: contextvars.ContextVar[Optional["NestedRuns"]] = contextvars.ContextVar("_nested_runs", default=None)


def _nested_run_metrics(run_output: Union[RunOutput, TeamRunOutput, WorkflowRunOutput]) -> RunMetrics:
    """The tokens of a run: its own, its team members' and its workflow steps'."""
    total = RunMetrics()
    if isinstance(run_output, WorkflowRunOutput):
        steps = run_output.metrics.steps if run_output.metrics else {}
        merge_background_metrics(total, [step_metrics.metrics for step_metrics in steps.values()])
        return total
    merge_background_metrics(total, [run_output.metrics])
    member_responses = getattr(run_output, "member_responses", None) or []
    merge_background_metrics(total, [_nested_run_metrics(member_response) for member_response in member_responses])
    return total


class NestedRuns:
    """The runs started inside one tool call of a run."""

    def __init__(self, run_response: Optional[Union[RunOutput, TeamRunOutput]]):
        self.run_response = run_response
        self.runs: List[Tuple[Union[RunOutput, TeamRunOutput, WorkflowRunOutput], bool]] = []

    @contextmanager
    def collect(self) -> Iterator[None]:
        """Collect the runs started while the tool runs."""
        token = _nested_runs.set(self)
        try:
            yield
        finally:
            _nested_runs.reset(token)

    def iterate(self, result: Iterator[T]) -> Iterator[T]:
        """Collect the runs started while a generator tool runs, between the items it yields."""
        try:
            while True:
                with self.collect():
                    try:
                        item = next(result)
                    except StopIteration:
                        return
                yield item
        finally:
            close = getattr(result, "close", None)
            if close is not None:
                close()

    async def acollect(self, coroutine: Awaitable[T]) -> T:
        """Collect the runs started while an async tool runs."""
        with self.collect():
            return await coroutine

    async def aiterate(self, result: AsyncIterator[T]) -> AsyncIterator[T]:
        """Collect the runs started while an async generator tool runs, between the items it yields."""
        try:
            while True:
                with self.collect():
                    try:
                        item = await result.__anext__()
                    except StopAsyncIteration:
                        return
                yield item
        finally:
            aclose = getattr(result, "aclose", None)
            if aclose is not None:
                await aclose()

    def add_to_run(self) -> None:
        """Add the tokens of the finished runs stored nowhere to the run whose tool started them."""
        if self.run_response is None or self.run_response.metrics is None:
            return
        added = []
        for run_output, stored in self.runs:
            if run_output.parent_run_id is not None:
                # A team or workflow owns the run and counts it, so it is not linked to the tool call either
                run_output.called_from_run_id = None
                continue
            if stored:
                continue
            run_output.called_from_run_id = self.run_response.run_id
            if run_output.status in METRICS_FINAL_STATUSES:
                added.append(_nested_run_metrics(run_output))
        merge_background_metrics(self.run_response.metrics, added)


def register_nested_run(
    run_output: Union[RunOutput, TeamRunOutput, WorkflowRunOutput], stored: bool
) -> Optional[NestedRuns]:
    """Link a run started inside a tool call to the run whose tool started it.

    Returns the context the run executes in: a run it starts outside its own tool calls, such as a workflow step
    or a reasoning agent, is counted by it, so it is linked to no run. None for a run no tool call started.
    """
    nested_runs = _nested_runs.get()
    if nested_runs is None or nested_runs.run_response is None:
        return None
    # A run saving its own row needs the link before it saves; a run stored nowhere is linked when the tool call ends
    if stored:
        run_output.called_from_run_id = nested_runs.run_response.run_id
    nested_runs.runs.append((run_output, stored))
    return NestedRuns(None)
