"""The private rollout engine: run a subject K times per input, isolated, and collect results.

Private means async-only (the sync door is `run_rollouts`) and this interface may change
without deprecation. The result types (`AttemptResult`, `StopReason`) are public,
re-exported from `agno.environments`, because they appear on every `TaskResult`.

There is no single-run door: `Agent.run` already is one, and scoring one run is
`scorer.score(agent.run(x), expected)`.
"""

import asyncio
import copy
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

from agno.run.agent import RunErrorEvent, RunOutput
from agno.run.base import RunStatus
from agno.run.team import RunErrorEvent as TeamRunErrorEvent
from agno.run.team import TeamRunOutput
from agno.scorer import AnyRunOutput, Score, Scorer
from agno.utils.log import log_warning

_RUN_ERROR_EVENTS = (RunErrorEvent, TeamRunErrorEvent)

_STATUS_TO_STOP = {
    RunStatus.paused: "paused",
    RunStatus.cancelled: "cancelled",
    RunStatus.error: "error",
}


class StopReason(str, Enum):
    """Why an attempt stopped. Values are lowercase and equal to their names, so
    natural string comparison works; not interchangeable with RunStatus values,
    which use a different casing."""

    completed = "completed"  # run finished; the only state a scorer sees
    error = "error"  # run raised or yielded an error event
    timeout = "timeout"  # exceeded timeout_seconds; whatever was captured is kept
    cancelled = "cancelled"  # run was cancelled
    paused = "paused"  # HITL pause; content is placeholder boilerplate, never scored


@dataclass
class AttemptResult:
    """One attempt, complete: failures are data here, not exceptions."""

    run: Optional[AnyRunOutput]  # whatever was captured before failure; None only if nothing arrived
    score: Optional[Score]  # None = unscored (non-completed run, no scorer, or scorer crash)
    stop_reason: StopReason
    duration_seconds: float
    error: Optional[str] = None
    # A fact, not a policy: tool_call_limit refuses further calls but the run still
    # completes, so exhaustion is invisible to a status check. The attempt is still
    # scored; downstream consumers filter on the flag.
    tool_call_limit_hit: bool = False
    # The exception class name when one is known (raise path, or an error event that
    # carried error_type); None when only a typeless error event was seen. Structured
    # so the error-storm check does not have to parse it back out of `error`.
    error_type: Optional[str] = None


@dataclass
class _AttemptState:
    run: Optional[AnyRunOutput] = None
    score: Optional[Score] = None
    errors: List[str] = field(default_factory=list)
    errored: bool = False
    error_type: Optional[str] = None  # first known exception class, if any


def _materialize(subject: Any) -> Any:
    """One isolation rule, applied per attempt.

    A factory is called once per attempt: nothing is shared because nothing is copied.
    A live subject is deep-copied once per attempt -- `deep_copy` shares model, db,
    knowledge and learning by reference, and silently shares any tool whose deepcopy
    raises, so its residuals are real; share expensive components deliberately through
    a factory closure instead.

    `cache_response` is disabled unconditionally on the effective model: the response
    cache is a shared disk cache keyed by messages, so a cached attempt is a replay,
    not a sample -- K identical attempts, zero variance, a silently degenerate
    environment. On both branches the model is `copy.copy`'d first (shallow, so the
    HTTP client underneath stays shared) and the flag set on the copy, never on the
    incoming instance: a factory product usually carries a fresh model, but a factory
    closure may share one model object across calls, and flipping the flag in place
    would mutate the caller's instance.
    """
    if callable(subject):
        agent = subject()
    else:
        agent = subject.deep_copy()
    model = getattr(agent, "model", None)
    if model is not None:
        model_copy = copy.copy(model)
        model_copy.cache_response = False
        agent.model = model_copy
    return agent


def _tool_call_limit_hit(run: Optional[AnyRunOutput]) -> bool:
    """Set difference: message-side tool_call_error ids with no matching execution.

    A refused call never produces a `ToolExecution`, only an error message; an errored
    execution produces both, with the same id, and is excluded by the difference.
    """
    if run is None or not run.messages:
        return False
    execution_ids = {t.tool_call_id for t in (run.tools or []) if t.tool_call_id}
    for message in run.messages:
        if getattr(message, "tool_call_error", None) and getattr(message, "tool_call_id", None):
            if message.tool_call_id not in execution_ids:
                return True
    return False


def _stop_reason_for(state: _AttemptState) -> StopReason:
    """Pure derivation -- called both for the scoring gate and the final result."""
    if state.errored:
        return StopReason.error
    if state.run is None:
        return StopReason.error
    status = state.run.status
    if status == RunStatus.completed:
        return StopReason.completed
    mapped = _STATUS_TO_STOP.get(status)
    return StopReason(mapped) if mapped is not None else StopReason.error


async def _attempt_body(
    agent: Any,
    input_value: str,
    expected_value: Any,
    scorer: Optional[Scorer],
    session_id: str,
    state: _AttemptState,
) -> None:
    """Stream the run, committing the final RunOutput the moment it arrives in-stream.

    The streaming form is a requirement, not a style choice: the stream can stall after
    the final output, and a timeout then must not discard what the run produced. A
    plain awaited `arun` under `wait_for` is cancelled whole and leaves nothing to keep.
    """
    try:
        async for event in agent.arun(
            input=input_value,
            stream=True,
            stream_events=True,
            yield_run_output=True,
            session_id=session_id,
        ):
            if isinstance(event, (RunOutput, TeamRunOutput)):
                state.run = event
                continue
            if isinstance(event, _RUN_ERROR_EVENTS):
                state.errored = True
                error_text = getattr(event, "content", None) or getattr(event, "error", None) or "unknown error"
                error_type = getattr(event, "error_type", None)
                if error_type:
                    error_text = f"{error_type}: {error_text}"
                    if state.error_type is None:
                        state.error_type = str(error_type)
                state.errors.append(str(error_text))
    except Exception as exc:
        state.errored = True
        if state.error_type is None:
            state.error_type = type(exc).__name__
        state.errors.append(f"{type(exc).__name__}: {exc}")
        return

    # Score inside the same timeout window, and only a completed run: everything else
    # stays unscored -- score is None, never 0.0.
    run = state.run
    if scorer is not None and run is not None and _stop_reason_for(state) == StopReason.completed:
        try:
            state.score = await scorer.ascore(run, expected_value)
        except Exception as exc:
            state.errors.append(f"scorer: {type(exc).__name__}: {exc}")


async def _run_attempt(
    subject: Any,
    input_value: str,
    expected_value: Any,
    scorer: Optional[Scorer],
    timeout_seconds: Optional[int],
) -> AttemptResult:
    start = time.perf_counter()
    state = _AttemptState()
    session_id = f"rollout-{uuid4().hex}"

    try:
        agent = _materialize(subject)
    except Exception as exc:
        return AttemptResult(
            run=None,
            score=None,
            stop_reason=StopReason.error,
            duration_seconds=time.perf_counter() - start,
            error=f"{type(exc).__name__}: {exc}",
            error_type=type(exc).__name__,
        )

    timed_out = False
    try:
        await asyncio.wait_for(
            _attempt_body(agent, input_value, expected_value, scorer, session_id, state),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        timed_out = True
        state.errors.append(f"timeout: exceeded {timeout_seconds}s")

    if timed_out:
        stop_reason = StopReason.timeout
    else:
        stop_reason = _stop_reason_for(state)
        if stop_reason != StopReason.completed and not state.errored:
            if state.run is None:
                state.errors.append("no run output recorded")
            else:
                status = state.run.status
                state.errors.append(f"run ended with status {getattr(status, 'value', status)}")
    return AttemptResult(
        run=state.run,
        score=state.score,
        stop_reason=stop_reason,
        duration_seconds=time.perf_counter() - start,
        error="; ".join(state.errors) if state.errors else None,
        tool_call_limit_hit=_tool_call_limit_hit(state.run),
        error_type=state.error_type,
    )


async def arun_batch(
    subject: Any,
    inputs: Sequence[str],
    *,
    k: int = 1,
    concurrency: int = 1,
    scorer: Optional[Scorer] = None,
    expected: Optional[Sequence[Any]] = None,
    timeout_seconds: Optional[int] = None,
    on_attempt_end: Optional[Callable[[int, int, AttemptResult], None]] = None,
    should_stop: Optional[Callable[[], bool]] = None,
) -> Tuple[Tuple[AttemptResult, ...], ...]:
    """Run `subject` k times per input, isolated, with optional scoring.

    `subject` is an `Agent` (deep-copied per attempt) or a zero-arg factory (called per
    attempt). `expected` is zipped to `inputs` -- the expectations handed to the scorer;
    lengths must match. The per-attempt timeout wraps run plus scoring. Returns one
    inner tuple per input, in input order, attempts in attempt order, regardless of
    completion order; every attempt yields an `AttemptResult`, never an exception.

    `on_attempt_end` and `should_stop` are seams for the rollouts runner (live grid,
    error-storm stop): when `should_stop()` turns true, not-yet-started attempts are
    skipped -- their slots are simply absent from the inner tuples -- while in-flight
    attempts drain normally.
    """
    if k < 1:
        raise ValueError(f"k must be >= 1, got {k}")
    if concurrency < 1:
        # Semaphore(0) would make every attempt block forever instead of raising.
        raise ValueError(f"concurrency must be >= 1, got {concurrency}")
    if isinstance(inputs, str):
        raise TypeError("inputs must be a sequence of input strings, not a bare string")
    if isinstance(expected, str):
        raise TypeError("expected must be a sequence zipped to inputs, not a bare string")
    if expected is not None and len(expected) != len(inputs):
        raise ValueError(f"expected has length {len(expected)} but inputs has length {len(inputs)}; they are zipped")

    semaphore = asyncio.Semaphore(concurrency)
    results: Dict[Tuple[int, int], AttemptResult] = {}
    # A broken callback must not read as a batch failure: disable it after the first
    # raise instead of destroying the completed AttemptResults.
    callback_enabled = [True]

    async def _bounded(input_index: int, attempt_index: int) -> None:
        async with semaphore:
            if should_stop is not None and should_stop():
                return
            expected_value = expected[input_index] if expected is not None else None
            result = await _run_attempt(subject, inputs[input_index], expected_value, scorer, timeout_seconds)
            results[(input_index, attempt_index)] = result
            if on_attempt_end is not None and callback_enabled[0]:
                try:
                    on_attempt_end(input_index, attempt_index, result)
                except Exception as exc:
                    callback_enabled[0] = False
                    log_warning(
                        f"on_attempt_end raised {type(exc).__name__}: {exc}; disabled for the rest of the batch"
                    )

    tasks = [
        asyncio.ensure_future(_bounded(input_index, attempt_index))
        for input_index in range(len(inputs))
        for attempt_index in range(k)
    ]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()

    return tuple(
        tuple(
            results[(input_index, attempt_index)]
            for attempt_index in range(k)
            if (input_index, attempt_index) in results
        )
        for input_index in range(len(inputs))
    )
