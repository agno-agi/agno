"""Unit tests for the private rollout engine (agno.environments._engine)."""

import ast
import asyncio
import copy
import os
import pathlib
import time

import pytest

from agno.environments._engine import arun_batch
from agno.models.message import Message
from agno.models.response import ToolExecution
from agno.run.agent import RunErrorEvent, RunOutput
from agno.run.base import RunStatus
from agno.scorer import CodeScorer


def _output(**kwargs):
    kwargs.setdefault("status", RunStatus.completed)
    return RunOutput(**kwargs)


class Tracker:
    """Shared across an agent and its per-attempt copies, so tests see every attempt."""

    def __init__(self):
        self.agents = []
        self.toolkits = []
        self.session_ids = []
        self.model_snapshots = []  # (id(model), cache_response) at invocation time


class StubModel:
    def __init__(self, cache_response=False):
        self.cache_response = cache_response


class StubToolkit:
    def __init__(self):
        self.calls = 0


class StubAgent:
    """Mirrors the real streaming contract: in-run failures yield a RunErrorEvent and
    end without the final RunOutput; a raising `error` models pre-stream failures.
    deep_copy shares the model by reference (like Agent.deep_copy) and rebuilds the
    toolkit (like the tools deepcopy)."""

    def __init__(
        self,
        tracker=None,
        *,
        respond=None,
        events=(),
        error=None,
        fail_inputs=(),
        delay=0.0,
        tail_delay=0.0,
        emit_output=True,
        model=None,
        delay_by_input=None,
    ):
        self.tracker = tracker if tracker is not None else Tracker()
        self._respond = respond if respond is not None else lambda value: _output(content=f"echo:{value}")
        self._events = list(events)
        self._error = error
        self._fail_inputs = set(fail_inputs)
        self._delay = delay
        self._tail_delay = tail_delay
        self._emit_output = emit_output
        self.model = model
        self._delay_by_input = delay_by_input or {}
        self.toolkit = StubToolkit()

    def deep_copy(self):
        clone = copy.copy(self)
        clone.toolkit = StubToolkit()
        return clone

    async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
        self.tracker.agents.append(self)
        self.tracker.toolkits.append(self.toolkit)
        self.tracker.session_ids.append(session_id)
        if self.model is not None:
            self.tracker.model_snapshots.append((id(self.model), self.model.cache_response))
        self.toolkit.calls += 1
        if self._error is not None:
            raise self._error
        delay = self._delay_by_input.get(input, self._delay)
        if delay:
            await asyncio.sleep(delay)
        for event in self._events:
            yield event
        if input in self._fail_inputs:
            yield RunErrorEvent(content=f"boom on {input}")
            return
        if self._emit_output:
            yield self._respond(input)
        if self._tail_delay:
            await asyncio.sleep(self._tail_delay)


# ---------------------------------------------------------------------------
# Batch shape and failure capture
# ---------------------------------------------------------------------------


async def test_batch_preserves_input_order():
    # Completion order is scrambled by per-input delays; the result is still grouped
    # by input in input order, attempts in attempt order.
    agent = StubAgent(delay_by_input={"a": 0.05, "b": 0.0, "c": 0.02})
    results = await arun_batch(agent, ["a", "b", "c"], k=2, concurrency=6)

    assert len(results) == 3
    assert all(len(attempts) == 2 for attempts in results)
    for value, attempts in zip(["a", "b", "c"], results):
        for attempt in attempts:
            assert attempt.stop_reason == "completed"
            assert attempt.run.content == f"echo:{value}"


async def test_batch_preserves_attempt_order():
    # The inner tuple is in attempt order even when later attempts finish first.
    # Each factory product stamps its construction index into the content and sleeps
    # inversely to it, so completion order is the reverse of attempt order.
    counter = {"n": 0}

    def factory():
        index = counter["n"]
        counter["n"] += 1
        return StubAgent(respond=lambda value, i=index: _output(content=f"attempt:{i}"), tail_delay=0.05 * (3 - index))

    results = await arun_batch(factory, ["a"], k=3, concurrency=3)
    assert [attempt.run.content for attempt in results[0]] == ["attempt:0", "attempt:1", "attempt:2"]


async def test_batch_captures_failures():
    # One failing attempt out of ten yields ten results, not an exception.
    inputs = [f"q{i}" for i in range(9)] + ["fail-me"]
    agent = StubAgent(fail_inputs={"fail-me"})
    results = await arun_batch(agent, inputs, k=1, concurrency=4)

    flat = [attempt for attempts in results for attempt in attempts]
    assert len(flat) == 10
    failed = flat[-1]
    assert failed.stop_reason == "error"
    assert failed.run is None
    assert "boom on fail-me" in failed.error
    assert all(attempt.stop_reason == "completed" for attempt in flat[:-1])


async def test_expected_reaches_scorer():
    # The end-to-end expectation plumbing: without it every scorer receives
    # expected=None and the flagship's pass rates are silently 0.0 everywhere.
    def compare_to_expected(run, expected):
        return run.content == expected

    inputs = ["one", "two", "three"]
    expectations = [f"echo:{value}" for value in inputs]
    results = await arun_batch(StubAgent(), inputs, k=2, scorer=CodeScorer(compare_to_expected), expected=expectations)

    scores = [attempt.score for attempts in results for attempt in attempts]
    assert all(score is not None and score.passed for score in scores)
    assert sum(score.value for score in scores) / len(scores) == 1.0


async def test_expected_length_mismatch_raises():
    with pytest.raises(ValueError) as excinfo:
        await arun_batch(StubAgent(), ["a", "b", "c"], expected=[1, 2])
    assert "2" in str(excinfo.value)
    assert "3" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Import direction
# ---------------------------------------------------------------------------


def _direct_imports(package_dir: pathlib.Path):
    """Yield (file, lineno, target) for every import statement in the package."""
    for path in sorted(package_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    yield path, node.lineno, alias.name
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                yield path, node.lineno, node.module


def _imports_of(package_dir: pathlib.Path, prefix: str):
    return [
        f"{path.name}:{lineno}: {target}"
        for path, lineno, target in _direct_imports(package_dir)
        if target == prefix or target.startswith(prefix + ".")
    ]


def test_dependency_direction():
    # scorer imports neither eval nor environments; the engine imports scorer; eval
    # imports scorer; nothing imports backwards. (The nothing-imports-environments
    # half is completed in R5, when the public package exists.)
    import agno

    agno_root = pathlib.Path(agno.__file__).parent
    scorer_dir = agno_root / "scorer"
    environments_dir = agno_root / "environments"
    eval_dir = agno_root / "eval"

    assert _imports_of(scorer_dir, "agno.eval") == []
    assert _imports_of(scorer_dir, "agno.environments") == []
    assert _imports_of(environments_dir, "agno.scorer") != []
    assert _imports_of(environments_dir, "agno.eval") == []
    assert _imports_of(eval_dir, "agno.scorer") != []
    assert _imports_of(eval_dir, "agno.environments") == []

    # Nothing outside the environments package imports it.
    outside = [
        f"{path}:{lineno}"
        for path, lineno, target in _direct_imports(agno_root)
        if (target == "agno.environments" or target.startswith("agno.environments."))
        and environments_dir not in path.parents
    ]
    assert outside == []


# ---------------------------------------------------------------------------
# The StopReason partition
# ---------------------------------------------------------------------------


async def test_scorer_runs_only_on_completed():
    calls = []

    def counting(run, expected):
        calls.append(run)
        return True

    scorer = CodeScorer(counting)

    errored = await arun_batch(StubAgent(fail_inputs={"q"}), ["q"], scorer=scorer)
    paused = await arun_batch(
        StubAgent(respond=lambda value: _output(content="hitl boilerplate", status=RunStatus.paused)),
        ["q"],
        scorer=scorer,
    )
    cancelled = await arun_batch(
        StubAgent(respond=lambda value: _output(content="cancelled", status=RunStatus.cancelled)),
        ["q"],
        scorer=scorer,
    )
    timed_out = await arun_batch(StubAgent(delay=5.0), ["q"], scorer=scorer, timeout_seconds=1)

    for results, reason in ((errored, "error"), (paused, "paused"), (cancelled, "cancelled"), (timed_out, "timeout")):
        attempt = results[0][0]
        assert attempt.stop_reason == reason
        assert attempt.score is None  # unscored, never coerced to 0.0
    assert calls == []

    completed = await arun_batch(StubAgent(), ["q"], scorer=scorer)
    assert completed[0][0].score is not None
    assert len(calls) == 1


async def test_timeout_keeps_partial_run():
    # The stream can stall after the final output; the timeout must not discard what
    # the run produced. This is why the engine consumes the stream internally.
    agent = StubAgent(tail_delay=5.0)
    results = await arun_batch(agent, ["q"], timeout_seconds=1)

    attempt = results[0][0]
    assert attempt.stop_reason == "timeout"
    assert attempt.run is not None
    assert attempt.run.content == "echo:q"


async def test_scorer_exception_is_captured_as_unscored():
    def broken(run, expected):
        raise RuntimeError("scorer bug")

    results = await arun_batch(StubAgent(), ["q"], scorer=CodeScorer(broken))
    attempt = results[0][0]
    assert attempt.stop_reason == "completed"
    assert attempt.score is None
    assert "scorer: RuntimeError: scorer bug" in attempt.error


# ---------------------------------------------------------------------------
# Isolation and the response cache
# ---------------------------------------------------------------------------


async def test_live_agent_does_not_mutate_caller_model():
    model = StubModel(cache_response=True)
    tracker = Tracker()
    agent = StubAgent(tracker, model=model)

    await arun_batch(agent, ["q"], k=3, concurrency=3)

    # The caller's model keeps its setting; every attempt ran on a distinct copy with
    # the cache off, so K attempts were K distinct model invocations, not replays.
    assert model.cache_response is True
    assert len(tracker.model_snapshots) == 3
    assert all(cache is False for _, cache in tracker.model_snapshots)
    assert len({model_id for model_id, _ in tracker.model_snapshots}) == 3
    assert id(model) not in {model_id for model_id, _ in tracker.model_snapshots}


async def test_factory_path_disables_response_cache():
    tracker = Tracker()

    def make_agent():
        return StubAgent(tracker, model=StubModel(cache_response=True))

    await arun_batch(make_agent, ["q"], k=3, concurrency=3)

    assert len(tracker.model_snapshots) == 3
    assert all(cache is False for _, cache in tracker.model_snapshots)
    assert len({model_id for model_id, _ in tracker.model_snapshots}) == 3


async def test_factory_closure_shared_model_not_mutated():
    # A factory closure may hand the same model object to every product; the cache
    # flag must be flipped on a per-attempt copy, never on the shared instance.
    shared_model = StubModel(cache_response=True)
    tracker = Tracker()

    await arun_batch(lambda: StubAgent(tracker, model=shared_model), ["q"], k=3, concurrency=3)

    assert shared_model.cache_response is True
    assert all(cache is False for _, cache in tracker.model_snapshots)
    assert id(shared_model) not in {model_id for model_id, _ in tracker.model_snapshots}


async def test_live_agent_attempt_isolation():
    tracker = Tracker()
    agent = StubAgent(tracker, model=StubModel())

    await arun_batch(agent, ["q"], k=3, concurrency=3)

    # Three attempts: three distinct agent copies (never the caller's instance),
    # three distinct toolkits each called exactly once, three fresh session ids.
    assert len(tracker.agents) == 3
    assert agent not in tracker.agents
    assert len({id(a) for a in tracker.agents}) == 3
    assert len({id(t) for t in tracker.toolkits}) == 3
    assert all(toolkit.calls == 1 for toolkit in tracker.toolkits)
    assert len(set(tracker.session_ids)) == 3


async def test_factory_attempt_isolation():
    tracker = Tracker()
    built = []

    def make_agent():
        agent = StubAgent(tracker, model=StubModel())
        built.append(agent)
        return agent

    await arun_batch(make_agent, ["q"], k=3, concurrency=3)

    assert len(built) == 3  # the factory ran once per attempt
    assert len({id(a) for a in tracker.agents}) == 3
    assert len({id(t) for t in tracker.toolkits}) == 3
    assert all(toolkit.calls == 1 for toolkit in tracker.toolkits)
    assert len(set(tracker.session_ids)) == 3


# ---------------------------------------------------------------------------
# tool_call_limit_hit
# ---------------------------------------------------------------------------


async def test_tool_call_limit_hit_flag():
    # A refused call exists only as a message-side tool_call_error with no matching
    # execution id: the set difference flags it, and the attempt is still scored.
    refused = _output(
        content="done under duress",
        messages=[
            Message(role="tool", content="limit reached", tool_call_id="c9", tool_name="x", tool_call_error=True)
        ],
        tools=[],
    )
    # An errored execution appears on BOTH sides with the same id: no flag.
    errored_execution = _output(
        content="done",
        messages=[Message(role="tool", content="tool blew up", tool_call_id="c1", tool_name="x", tool_call_error=True)],
        tools=[ToolExecution(tool_call_id="c1", tool_name="x", tool_call_error=True)],
    )

    scorer = CodeScorer(lambda run, expected: True)
    flagged = await arun_batch(StubAgent(respond=lambda value: refused), ["q"], scorer=scorer)
    unflagged = await arun_batch(StubAgent(respond=lambda value: errored_execution), ["q"], scorer=scorer)

    assert flagged[0][0].tool_call_limit_hit is True
    assert flagged[0][0].score is not None  # the run completed; its answer is real
    assert unflagged[0][0].tool_call_limit_hit is False


# ---------------------------------------------------------------------------
# Construction-cost benchmark (does not gate R2)
# ---------------------------------------------------------------------------


def bench_agent_construction_share():
    """Per-attempt construction must be cheap against a model round-trip.

    Fixture: a 250ms simulated attempt latency. Threshold: median construction under
    5% of the attempt wall time. This is the measurement backing per-attempt
    construction as the default; if it fails with the fixture present, the default
    is wrong.
    """
    try:
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
    except ImportError:
        pytest.skip("fixture unavailable offline: openai not installed")

    simulated_attempt_seconds = 0.25
    samples = []
    for _ in range(20):
        start = time.perf_counter()
        Agent(model=OpenAIChat(id="gpt-5.5"))
        samples.append(time.perf_counter() - start)
    samples.sort()
    median = samples[len(samples) // 2]
    assert median < 0.05 * simulated_attempt_seconds, (
        f"agent construction took {median * 1000:.1f}ms, over 5% of a {simulated_attempt_seconds * 1000:.0f}ms attempt"
    )


@pytest.mark.skipif(
    not os.environ.get("AGNO_RUN_BENCH"),
    reason="benchmark, not a gate (plan R2): a wall-clock threshold must not fail CI on a loaded runner; set AGNO_RUN_BENCH=1 to run",
)
def test_bench_agent_construction_share():
    # pytest only collects test_*; this wrapper runs the named bench.
    bench_agent_construction_share()


# ---------------------------------------------------------------------------
# Engine hardening (review-round fixes)
# ---------------------------------------------------------------------------


async def test_callback_error_does_not_destroy_batch():
    # A broken on_attempt_end must not cost the batch: it is disabled after the
    # first raise and every AttemptResult still comes back.
    def broken_callback(input_index, attempt_index, attempt):
        raise RuntimeError("renderer bug")

    results = await arun_batch(StubAgent(), ["a", "b"], k=2, concurrency=2, on_attempt_end=broken_callback)

    flat = [attempt for attempts in results for attempt in attempts]
    assert len(flat) == 4
    assert all(attempt.stop_reason == "completed" for attempt in flat)


async def test_engine_validates_bounds():
    with pytest.raises(ValueError, match="k must be"):
        await arun_batch(StubAgent(), ["a"], k=0)
    # concurrency=0 would hang forever on Semaphore(0), not raise.
    with pytest.raises(ValueError, match="concurrency must be"):
        await arun_batch(StubAgent(), ["a"], concurrency=0)
    # Bare strings satisfy Sequence but zip per character.
    with pytest.raises(TypeError, match="bare string"):
        await arun_batch(StubAgent(), "abc")
    with pytest.raises(TypeError, match="bare string"):
        await arun_batch(StubAgent(), ["abc"], expected="x")


async def test_error_type_is_structured():
    # The raise path knows the exception class; a typeless error event leaves the
    # field None (the storm check then falls back to its string heuristic).
    raising = StubAgent(error=RuntimeError("boom"))
    results = await arun_batch(raising, ["a"], k=1)
    assert results[0][0].error_type == "RuntimeError"

    event_only = StubAgent(fail_inputs=("a",))
    results = await arun_batch(event_only, ["a"], k=1)
    attempt = results[0][0]
    assert attempt.stop_reason == "error"
    assert attempt.error_type is None
