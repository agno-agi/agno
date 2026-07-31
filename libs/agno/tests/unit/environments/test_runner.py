"""Unit tests for run_rollouts / arun_rollouts, hermetic overrides, and results."""

import asyncio
import json
from uuid import uuid4

import pytest

from agno.agent import Agent
from agno.agent._utils import SHARED_BY_REFERENCE_FIELDS
from agno.db.in_memory import InMemoryDb
from agno.environments import (
    Environment,
    EnvironmentRunResult,
    StopReason,
    Task,
    TaskResult,
    arun_rollouts,
    run_rollouts,
)
from agno.environments._engine import AttemptResult
from agno.environments.runner import _ISOLATE_FIELD_ACTIONS, _isolate_attempt
from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.scorer import CodeScorer, MismatchError, Score


def _output(**kwargs):
    kwargs.setdefault("status", RunStatus.completed)
    return RunOutput(**kwargs)


def echo_scorer(run, expected):
    return run.content == expected


class Recorder:
    """Shared across attempt agents: one entry per attempt at run time."""

    def __init__(self):
        self.snapshots = []
        self.session_ids = []
        self.run_inputs = []


class StubModel:
    def __init__(self, cache_response=False, id="stub-model"):
        self.cache_response = cache_response
        self.id = id


class StubManager:
    """Attribute-bearing manager stand-in: the hermetic rebind copies managers and
    touches their db/model slots, so a plain object() cannot model one."""

    def __init__(self, db=None, model=None):
        self.db = db
        self.model = model


class StubRolloutAgent:
    """Duck-typed agent for Environment factories. Mirrors the streaming contract; records a
    hermetic-relevant snapshot of itself at run time."""

    def __init__(
        self,
        recorder=None,
        *,
        respond=None,
        error=None,
        error_on_calls=(),
        paused_on_calls=(),
        delay=0.0,
        model=None,
        db=None,
        knowledge=None,
        learning=None,
        culture_manager=None,
        memory_manager=None,
        reasoning_model=None,
        parser_model=None,
        output_model=None,
    ):
        self.recorder = recorder if recorder is not None else Recorder()
        self._respond = respond if respond is not None else (lambda value: _output(content=f"echo:{value}"))
        self._error = error
        self._error_on_calls = set(error_on_calls)
        self._paused_on_calls = set(paused_on_calls)
        self._delay = delay
        self.model = model
        self.db = db
        self.knowledge = knowledge
        self.learning = learning
        self.culture_manager = culture_manager
        self.memory_manager = memory_manager
        self.reasoning_model = reasoning_model
        self.parser_model = parser_model
        self.output_model = output_model
        self.user_id = None
        self.session_state = {"seed": 1}
        self.instructions = "Answer tersely."
        self.update_memory_on_run = True
        self.enable_user_memories = True
        self.enable_agentic_memory = True
        self.update_knowledge = True
        self.update_cultural_knowledge = True
        self.enable_agentic_culture = True

    def deep_copy(self):
        # Mirrors Agent.deep_copy's sharing rule for what matters here: db, models,
        # managers, knowledge and learning stay shared by reference on the copy.
        import copy

        return copy.copy(self)

    async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
        call_index = len(self.recorder.snapshots)
        self.recorder.session_ids.append(session_id)
        self.recorder.run_inputs.append(input)
        self.recorder.snapshots.append(
            {
                "agent": self,
                "db": self.db,
                "model": self.model,
                "model_cache": self.model.cache_response if self.model is not None else None,
                "knowledge": self.knowledge,
                "learning": self.learning,
                "culture_manager": self.culture_manager,
                "memory_manager": self.memory_manager,
                "reasoning_model": self.reasoning_model,
                "parser_model": self.parser_model,
                "output_model": self.output_model,
                "user_id": self.user_id,
                "update_memory_on_run": self.update_memory_on_run,
                "enable_user_memories": self.enable_user_memories,
                "enable_agentic_memory": self.enable_agentic_memory,
                "update_knowledge": self.update_knowledge,
                "update_cultural_knowledge": self.update_cultural_knowledge,
                "enable_agentic_culture": self.enable_agentic_culture,
                "session_state": dict(self.session_state or {}),
                "instructions": self.instructions,
            }
        )
        if self._error is not None or call_index in self._error_on_calls:
            raise self._error or RuntimeError("attempt exploded")
        if self._delay:
            await asyncio.sleep(self._delay)
        if call_index in self._paused_on_calls:
            yield _output(content="hitl boilerplate", status=RunStatus.paused)
            return
        yield self._respond(input)


def _stub_env(recorder=None, *, tasks=None, scorer=None, timeout_seconds=120, **agent_kwargs) -> Environment:
    recorder = recorder if recorder is not None else Recorder()
    return Environment(
        name="stub-env",
        tasks=tasks if tasks is not None else (Task(input="one", expected="echo:one"),),
        scorer=scorer if scorer is not None else CodeScorer(echo_scorer),
        agent=lambda: StubRolloutAgent(recorder, **agent_kwargs),
        timeout_seconds=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# Hermetic overrides
# ---------------------------------------------------------------------------


async def test_hermetic_no_db_writes():
    recorder = Recorder()
    caller_db = object()  # stands in for the caller's real database
    env = _stub_env(recorder, db=caller_db)

    await arun_rollouts(env, k=3, concurrency=3)

    dbs = [snapshot["db"] for snapshot in recorder.snapshots]
    assert all(isinstance(db, InMemoryDb) for db in dbs)
    assert caller_db not in dbs
    assert len({id(db) for db in dbs}) == 3  # fresh per attempt


async def test_hermetic_no_knowledge_writes():
    recorder = Recorder()
    env = _stub_env(recorder)

    await arun_rollouts(env, k=2, concurrency=2)

    assert all(snapshot["update_knowledge"] is False for snapshot in recorder.snapshots)


async def test_hermetic_no_memory_capture():
    recorder = Recorder()
    env = _stub_env(recorder)

    await arun_rollouts(env, k=2, concurrency=2)

    for snapshot in recorder.snapshots:
        assert snapshot["update_memory_on_run"] is False
        assert snapshot["enable_user_memories"] is False
        assert snapshot["enable_agentic_memory"] is False


async def test_hermetic_no_learning_writes():
    # deep_copy shares the learning value by reference: a real LearningMachine gets
    # a read-only rebind (pinned by test_learning_reads_survive_hermetic_attempts);
    # anything else truthy -- learning=True, duck-typed stand-ins like this one --
    # is nulled, never left attached to write into the caller's store.
    recorder = Recorder()
    caller_learning = object()
    env = _stub_env(recorder, learning=caller_learning)

    await arun_rollouts(env, k=2, concurrency=2)

    assert all(snapshot["learning"] is None for snapshot in recorder.snapshots)


async def test_hermetic_knowledge_reads_still_work():
    # The test that stops "disable knowledge" from being implemented as "null the
    # knowledge object" and silently zeroing every RAG agent: retrieval goes through
    # knowledge.vector_db, not agent.db, so the shared reference must survive.
    recorder = Recorder()
    shared_knowledge = object()
    env = _stub_env(recorder, knowledge=shared_knowledge)

    await arun_rollouts(env, k=2, concurrency=2)

    assert all(snapshot["knowledge"] is shared_knowledge for snapshot in recorder.snapshots)


def _live_env(live_agent) -> Environment:
    """An Environment whose agent is a LIVE duck-typed stub, to drive the runner's deep_copy
    branch offline. Environment's front door correctly rejects a non-Agent live value, so the
    stub is installed past validation -- the branch under test is the runner's, and a
    real Agent cannot run without a live model."""
    env = Environment(
        name="live-env",
        tasks=(Task(input="one", expected="echo:one"),),
        scorer=CodeScorer(echo_scorer),
        agent=lambda: None,
    )
    object.__setattr__(env, "agent", live_agent)
    return env


def _masked_start(run_input, snapshot):
    """The full first-call payload with per-attempt identities masked to their shape:
    ids are fresh by design, everything else must be identical across attempts."""
    return {
        "input": run_input,
        "session_state": snapshot["session_state"],
        "instructions": snapshot["instructions"],
        "db_type": type(snapshot["db"]).__name__,
        "model": None if snapshot["model"] is None else (snapshot["model"].id, snapshot["model"].cache_response),
        "knowledge": snapshot["knowledge"],
        "learning": snapshot["learning"],
        "culture_manager": snapshot["culture_manager"],
        "memory_manager": snapshot["memory_manager"],
        "update_memory_on_run": snapshot["update_memory_on_run"],
        "enable_user_memories": snapshot["enable_user_memories"],
        "enable_agentic_memory": snapshot["enable_agentic_memory"],
        "update_knowledge": snapshot["update_knowledge"],
        "update_cultural_knowledge": snapshot["update_cultural_knowledge"],
        "enable_agentic_culture": snapshot["enable_agentic_culture"],
    }


async def test_hermetic_identical_start():
    # Each attempt's first-call payload, ids masked, is identical -- on the LIVE
    # subject path (deep_copy), where cross-attempt contamination is possible at all.
    recorder = Recorder()
    live = StubRolloutAgent(recorder, model=StubModel(cache_response=True), db=object(), learning=object())
    env = _live_env(live)

    await arun_rollouts(env, k=4, concurrency=4)

    masked = [
        _masked_start(run_input, snapshot) for run_input, snapshot in zip(recorder.run_inputs, recorder.snapshots)
    ]
    assert len(masked) == 4
    assert all(payload == masked[0] for payload in masked)
    # No attempt ran on the caller's instance, and the ids are fresh per attempt.
    assert all(snapshot["agent"] is not live for snapshot in recorder.snapshots)
    assert len(set(recorder.session_ids)) == 4
    assert len({snapshot["user_id"] for snapshot in recorder.snapshots}) == 4
    assert all(snapshot["user_id"] for snapshot in recorder.snapshots)


async def test_hermetic_live_agent_full_override_set():
    # The live-agent branch on STUB agents: db-bound state cut, culture rebound to a
    # read-only copy, memory rebound to the attempt's fresh db, secondary-model
    # caches disabled on copies -- and the caller's instance untouched afterwards.
    # The REAL-Agent twin below covers the fields this stub cannot model.
    recorder = Recorder()
    caller_db = object()
    culture_manager = StubManager(db=object())
    memory_manager = StubManager()
    live = StubRolloutAgent(
        recorder,
        model=StubModel(cache_response=True),
        db=caller_db,
        learning=object(),
        culture_manager=culture_manager,
        memory_manager=memory_manager,
        reasoning_model=StubModel(cache_response=True, id="reasoning"),
        parser_model=StubModel(cache_response=True, id="parser"),
        output_model=StubModel(cache_response=True, id="output"),
    )
    env = _live_env(live)

    result = await arun_rollouts(env, k=3, concurrency=3)

    assert result.pass_rate == 1.0
    assert len(recorder.snapshots) == 3  # non-vacuous: every attempt actually ran
    for snapshot in recorder.snapshots:
        assert snapshot["agent"] is not live
        assert isinstance(snapshot["db"], InMemoryDb)
        assert snapshot["learning"] is None
        # Culture READS survive: a manager copy, never the caller's object.
        assert snapshot["culture_manager"] is not None
        assert snapshot["culture_manager"] is not culture_manager
        assert snapshot["culture_manager"].db is culture_manager.db
        # Memory is per-user state: the manager copy reads the attempt's fresh db.
        assert snapshot["memory_manager"] is not None
        assert snapshot["memory_manager"] is not memory_manager
        assert snapshot["memory_manager"].db is snapshot["db"]
        assert snapshot["update_cultural_knowledge"] is False
        assert snapshot["enable_agentic_culture"] is False
        assert snapshot["model_cache"] is False
        for secondary_name in ("reasoning_model", "parser_model", "output_model"):
            secondary = snapshot[secondary_name]
            assert secondary.cache_response is False
            assert secondary is not getattr(live, secondary_name)
    # The caller's live agent keeps its configuration.
    assert live.db is caller_db
    assert live.culture_manager is culture_manager
    assert live.memory_manager is memory_manager
    assert live.model.cache_response is True
    assert live.reasoning_model.cache_response is True
    assert live.update_cultural_knowledge is True


# ---------------------------------------------------------------------------
# Statistics and the learning zone
# ---------------------------------------------------------------------------


async def test_unscored_excluded_from_stats():
    # 8 attempts, 2 paused (unscored): scored count 6, pass_rate over 6 -- a paused
    # or timed-out attempt is never counted as 0.0.
    recorder = Recorder()
    env = _stub_env(recorder, paused_on_calls={0, 1})

    result = await arun_rollouts(env, k=8, concurrency=1)

    assert result.n_scored == 6
    assert result.n_unscored == 2
    assert result.pass_rate == 1.0
    assert result.summary()["n_unscored"] == 2


def _task_result_with_values(values, unscored=0):
    attempts = [
        AttemptResult(
            run=_output(content="x"),
            score=Score(value=value, passed=value >= 0.5),
            stop_reason=StopReason.completed,
            duration_seconds=0.1,
        )
        for value in values
    ]
    attempts += [
        AttemptResult(run=None, score=None, stop_reason=StopReason.timeout, duration_seconds=0.1)
        for _ in range(unscored)
    ]
    return TaskResult(task=Task(input="q", id="t1"), attempts=tuple(attempts))


def test_learning_zone_rule():
    # Pass rate strictly between 0 and 1; the helper scores value >= 0.5 as passed.
    assert _task_result_with_values([0.0, 1.0]).in_learning_zone is True  # binary mixed
    assert _task_result_with_values([1.0, 1.0]).in_learning_zone is False  # binary saturated
    assert _task_result_with_values([0.0, 0.0]).in_learning_zone is False  # binary hopeless
    assert _task_result_with_values([0.4, 0.9]).in_learning_zone is True  # numeric mixed
    assert _task_result_with_values([0.6, 0.8, 1.0]).in_learning_zone is False  # all passed, scores vary
    assert _task_result_with_values([0.1, 0.3]).in_learning_zone is False  # all failed, scores vary
    assert _task_result_with_values([1.0]).in_learning_zone is False  # k=1 degenerate
    assert _task_result_with_values([0.0]).in_learning_zone is False
    assert _task_result_with_values([], unscored=2).in_learning_zone is False
    assert _task_result_with_values([0.4, 0.9], unscored=3).in_learning_zone is True  # unscored never blocks
    assert _task_result_with_values([1.0], unscored=4).in_learning_zone is False  # unscored are not failures


def test_learning_zone_filter_keeps_only_tasks_with_failures():
    # The invariant to_sft_jsonl's only_passed default builds on: every task
    # learning_zone() returns has at least one FAILED scored attempt.
    result = EnvironmentRunResult(
        env_name="zone",
        k=4,
        env_fingerprint="aaa",
        policy_fingerprint="p1",
        task_results=(
            _task_result_with_values([0.6, 0.8, 1.0]),  # all passed, scores vary
            _task_result_with_values([0.1, 0.3]),  # all failed, scores vary
            _task_result_with_values([0.4, 0.9]),  # mixed
            _task_result_with_values([0.0, 1.0], unscored=2),  # mixed with unscored
            _task_result_with_values([1.0]),  # single scored attempt
            _task_result_with_values([], unscored=3),  # unscored only
        ),
        duration_seconds=1.0,
    )
    zone = result.learning_zone()
    assert len(zone.task_results) == 2  # exactly the two mixed tasks
    for task_result in zone.task_results:
        assert any(attempt.score is not None and not attempt.score.passed for attempt in task_result.attempts), (
            "learning_zone() returned a task with no failed scored attempt"
        )


async def test_expected_reaches_scorer_through_env():
    env = _stub_env(
        tasks=(
            Task(input="one", expected="echo:one"),
            Task(input="two", expected="echo:two"),
        )
    )
    result = await arun_rollouts(env, k=3, concurrency=3)
    assert result.pass_rate == 1.0


# ---------------------------------------------------------------------------
# The model= override
# ---------------------------------------------------------------------------


async def test_model_override_flips_policy_only():
    env = _stub_env()
    base = await arun_rollouts(env, k=1)
    swapped = await arun_rollouts(env, k=1, model=OpenAIChat(id="gpt-5"))

    assert base.env_fingerprint == swapped.env_fingerprint
    assert base.policy_fingerprint != swapped.policy_fingerprint

    with pytest.raises(TypeError, match="string"):
        await arun_rollouts(env, k=1, model="gpt-5.5")


async def test_model_override_stamps_effective_fingerprint():
    from agno.environments.environment import _policy_fingerprint_of as policy_fingerprint_of

    override = OpenAIChat(id="gpt-5")
    env = _stub_env(model=StubModel(id="declared-model"))

    result = await arun_rollouts(env, k=1, model=override)

    assert result.policy_fingerprint == policy_fingerprint_of(override)


async def test_model_override_disables_cache():
    # Pins the override-before-cache ordering: an override model with caching on
    # would otherwise replay a shared disk cache across all K attempts -- the one
    # silent failure on the checkpoint-comparison path.
    recorder = Recorder()
    override = OpenAIChat(id="gpt-5")
    override.cache_response = True
    env = _stub_env(recorder)

    await arun_rollouts(env, k=3, concurrency=3, model=override)

    assert override.cache_response is True  # caller's instance untouched
    assert len(recorder.snapshots) == 3
    assert all(snapshot["model_cache"] is False for snapshot in recorder.snapshots)
    assert len({id(snapshot["model"]) for snapshot in recorder.snapshots}) == 3
    assert all(snapshot["model"] is not override for snapshot in recorder.snapshots)


# ---------------------------------------------------------------------------
# Selection, errors, and the sync door
# ---------------------------------------------------------------------------


async def test_tasks_subset_selection():
    tasks = (
        Task(input="one", expected="echo:one"),
        Task(input="two", expected="echo:two"),
        Task(input="three", expected="echo:three"),
    )
    env = _stub_env(tasks=tasks)
    full = await arun_rollouts(env, k=1)
    subset = await arun_rollouts(env, k=1, tasks=[task for task in env.tasks if task.input == "two"])

    assert [task_result.task.input for task_result in subset.task_results] == ["two"]
    # Selection keeps env identity: the fingerprint does not flip, and the id keeps
    # its env position.
    assert subset.env_fingerprint == full.env_fingerprint
    assert subset.task_results[0].task.id == "t2"

    with pytest.raises(ValueError, match="env.tasks"):
        await arun_rollouts(env, k=1, tasks=[Task(input="two")])


async def test_scorer_exception_captured():
    def broken(run, expected):
        raise RuntimeError("scorer bug")

    env = _stub_env(scorer=CodeScorer(broken))
    result = await arun_rollouts(env, k=2, concurrency=2)

    for task_result in result.task_results:
        for attempt in task_result.attempts:
            assert attempt.score is None
            assert "scorer: RuntimeError: scorer bug" in attempt.error


async def test_error_storm_stops_early():
    # A uniform misconfiguration is not data about the agent: a single-task run whose
    # opening completions (past a small sample floor) all errored with one exception
    # type stops scheduling, drains, and returns the partial result. Single-task only:
    # a multi-task run never globally aborts (test_error_storm_ignores_multi_task_runs).
    env = _stub_env(tasks=(Task(input="one"),), error=RuntimeError("bad api key"))
    result = await arun_rollouts(env, k=8, concurrency=2)

    assert result.stopped_early == "error-storm"
    assert result.n_attempts < 8  # the unscheduled attempts are absent
    assert result.summary()["stopped_early"] == "error-storm"


async def test_error_storm_ignores_multi_task_runs():
    # A multi-task run must never globally abort. Scheduling is input-major, so a
    # front-loaded failing task would otherwise skip healthy tasks and make
    # completeness depend on task order. Even a uniformly failing multi-task env runs
    # every attempt rather than aborting.
    env = _stub_env(tasks=(Task(input="one"), Task(input="two")), error=RuntimeError("bad api key"))
    result = await arun_rollouts(env, k=4, concurrency=2)

    assert result.stopped_early is None
    assert result.n_attempts == 8  # all attempts ran; no global abort


async def test_error_storm_needs_sample_floor():
    # A single error must not trip the storm: below the floor there is not yet enough
    # signal that the failure is uniform rather than a flaky first sample.
    recorder = Recorder()
    env = _stub_env(recorder, tasks=(Task(input="one"),), error_on_calls={0})
    result = await arun_rollouts(env, k=8, concurrency=1)

    assert result.stopped_early is None
    assert result.n_attempts == 8  # one early error does not abort the run


async def test_error_storm_disarmed_at_small_k():
    # At k <= max(concurrency, floor) every attempt has run or started by the time
    # uniform failure could be established, so there is nothing to save by stopping:
    # even uniform failures complete the full plan with no stopped-early stamp.
    env = _stub_env(tasks=(Task(input="one"),), error=RuntimeError("bad api key"))
    for k in (1, 2, 3, 4):
        result = await arun_rollouts(env, k=k, concurrency=1)
        assert result.stopped_early is None, f"k={k}"
        assert result.n_attempts == k, f"k={k}"


async def test_error_storm_trips_across_concurrency_levels():
    # Above the evidence window the storm still trips on uniform failures and the
    # unscheduled tail is skipped, at small and window-sized concurrency alike.
    for concurrency in (1, 4):
        env = _stub_env(tasks=(Task(input="one"),), error=RuntimeError("bad api key"))
        result = await arun_rollouts(env, k=8, concurrency=concurrency)
        assert result.stopped_early == "error-storm", f"concurrency={concurrency}"
        assert result.n_attempts < 8, f"concurrency={concurrency}"


async def test_storm_trip_after_full_plan_not_stamped():
    # k just above the evidence window with concurrency at the window: the storm can
    # trip only after the fifth attempt has already passed the scheduling gate, so the
    # full plan runs and nothing is skipped. A complete run must not be stamped
    # stopped-early -- the completeness guard's own case, reachable by no other test.
    # The event forces the order: attempt 0 errors instantly, freeing a slot for
    # attempt 4 while only one error is in (no trip yet); attempts 1-3 hold their
    # errors until attempt 4 has started, so the trip always lands after full entry.
    starts = []
    fifth_started = asyncio.Event()

    class GatedErrorAgent:
        async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
            index = len(starts)
            starts.append(session_id)
            if index >= 4:
                fifth_started.set()
            elif index > 0:
                await fifth_started.wait()
            raise RuntimeError("bad api key")
            yield  # pragma: no cover

    env = Environment(
        name="late-trip",
        tasks=(Task(input="one"),),
        scorer=CodeScorer(lambda r, e: True),
        agent=lambda: GatedErrorAgent(),
    )
    result = await arun_rollouts(env, k=5, concurrency=4)

    assert len(starts) == 5  # the fifth attempt entered before the trip
    assert result.n_attempts == 5
    assert result.stopped_early is None


async def test_error_order_does_not_change_completeness():
    # A leading error and a trailing error cost the run the same: nothing. Below the
    # evidence window the storm is disarmed, so [BAD, GOOD] and [GOOD, BAD] both
    # complete every attempt.
    for error_call in (0, 1):
        env = _stub_env(tasks=(Task(input="one"),), error_on_calls={error_call})
        result = await arun_rollouts(env, k=2, concurrency=1)
        assert result.stopped_early is None, f"error on call {error_call}"
        assert result.n_attempts == 2, f"error on call {error_call}"
        assert result.n_unscored == 1, f"error on call {error_call}"


async def test_partial_errors_do_not_stop():
    recorder = Recorder()
    env = _stub_env(recorder, error_on_calls={0})
    result = await arun_rollouts(env, k=8, concurrency=2)

    assert result.stopped_early is None
    assert result.n_attempts == 8
    assert result.n_unscored == 1  # only the single errored attempt


async def test_errors_grouped_by_task():
    # One errored attempt on t1 only: the grouping must be non-empty, keyed by the
    # errored task's id, and absent for the clean task.
    recorder = Recorder()
    env = _stub_env(
        recorder,
        tasks=(Task(input="one", expected="echo:one"), Task(input="two", expected="echo:two")),
        error_on_calls={0},
    )
    result = await arun_rollouts(env, k=2, concurrency=2)

    grouped = result.errors()
    assert list(grouped) == ["t1"]
    assert len(grouped["t1"]) == 1
    assert "RuntimeError: attempt exploded" in grouped["t1"][0]
    assert result.stopped_early is None  # mixed first completions are not a storm


async def test_run_rollouts_raises_in_running_loop():
    env = _stub_env()
    with pytest.raises(RuntimeError, match="arun_rollouts"):
        run_rollouts(env, k=1)


def test_run_rollouts_sync_door():
    env = _stub_env()
    result = run_rollouts(env, k=2, concurrency=2)
    assert result.pass_rate == 1.0


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------


async def test_grid_skipped_when_not_tty(monkeypatch):
    # Non-TTY stdout (CI, notebooks, pipes) skips live rendering automatically;
    # summary() stays the programmatic contract. This is why no quiet= exists.
    import agno.environments.runner as runner_module

    class ExplodingLiveGrid:
        def __init__(self, *args, **kwargs):
            raise AssertionError("LiveGrid must not be constructed off-TTY")

    monkeypatch.setattr(runner_module, "LiveGrid", ExplodingLiveGrid)
    monkeypatch.setattr("rich.console.Console.is_terminal", property(lambda self: False))

    result = await arun_rollouts(_stub_env(), k=1)
    assert result.pass_rate == 1.0


async def test_grid_cost_segment_absent_when_cost_none():
    # agno carries cost only when the provider reports it; no price table, ever.
    result = await arun_rollouts(_stub_env(), k=2, concurrency=2)
    assert "$" not in str(result)


async def test_grid_renders_statically():
    result = await arun_rollouts(_stub_env(), k=2, concurrency=2)
    text = str(result)
    assert "stub-env" in text
    assert "k=2" in text
    assert "t1" in text
    assert "██" in text


# ---------------------------------------------------------------------------
# summary(), save/load, diff
# ---------------------------------------------------------------------------


async def test_summary_shape():
    result = await arun_rollouts(_stub_env(), k=2, concurrency=2)
    summary = result.summary()
    assert list(summary.keys()) == [
        "env",
        "k",
        "n_tasks",
        "n_attempts",
        "n_scored",
        "n_unscored",
        "pass_rate",
        "mean_value",
        "env_fingerprint",
        "policy_fingerprint",
        "stopped_early",
        "tasks",
    ]
    assert list(summary["tasks"][0].keys()) == ["id", "pass_rate", "mean_value", "n_unscored", "learning_zone"]
    json.dumps(summary)


async def test_save_load_roundtrip(tmp_path):
    env = _stub_env(tasks=(Task(input="one", expected="echo:one"), Task(input="two", expected="wrong")))
    result = await arun_rollouts(env, k=2, concurrency=2)
    path = tmp_path / "baseline.json"

    result.save(path)
    assert json.loads(path.read_text(encoding="utf-8"))["format_version"] == 1

    loaded = EnvironmentRunResult.load(path)
    assert loaded.summary() == result.summary()
    diff = result.diff(loaded)
    assert all(row["delta"] == 0.0 for row in diff.rows)
    assert diff.improved == ()
    assert diff.regressed == ()


def _result_with(env_fingerprint, policy_fingerprint, rates_by_id):
    task_results = []
    for task_id, (passed, failed) in rates_by_id.items():
        attempts = [
            AttemptResult(
                run=_output(content="x"),
                score=Score(value=1.0 if is_pass else 0.0, passed=is_pass),
                stop_reason=StopReason.completed,
                duration_seconds=0.1,
            )
            for is_pass in [True] * passed + [False] * failed
        ]
        task_results.append(TaskResult(task=Task(input=task_id, id=task_id), attempts=tuple(attempts)))
    return EnvironmentRunResult(
        env_name="arithmetic",
        k=8,
        env_fingerprint=env_fingerprint,
        policy_fingerprint=policy_fingerprint,
        task_results=tuple(task_results),
        duration_seconds=1.0,
    )


def test_diff_refuses_mismatched_env():
    current = _result_with("aaa", "p1", {"t1": (8, 0)})
    with pytest.raises(MismatchError, match="env_fingerprint"):
        current.diff(_result_with("bbb", "p1", {"t1": (8, 0)}))
    # None never matches -- a plain == would pass trivially when both are None.
    nameless = _result_with(None, "p1", {"t1": (8, 0)})
    with pytest.raises(MismatchError):
        nameless.diff(_result_with(None, "p1", {"t1": (8, 0)}))


def test_diff_per_task_delta():
    baseline = _result_with("aaa", "p1", {"t1": (8, 0), "t2": (3, 5)})
    current = _result_with("aaa", "p2", {"t1": (8, 0), "t2": (6, 2)})

    diff = current.diff(baseline)
    rows = {row["id"]: row for row in diff.rows}
    assert rows["t1"]["delta"] == 0.0
    assert rows["t1"]["status"] == ""
    assert rows["t2"]["delta"] == pytest.approx(0.375)
    assert rows["t2"]["status"] == "improved"
    assert diff.policy_changed is True
    assert "improved" in str(diff)


def test_diff_flags_regressions():
    baseline = _result_with("aaa", "p1", {"t1": (7, 1)})
    current = _result_with("aaa", "p2", {"t1": (4, 4)})

    diff = current.diff(baseline)
    assert diff.regressed == ("t1",)
    assert diff.improved == ()
    assert "regressed" in str(diff)


# ---------------------------------------------------------------------------
# Review fixes: factory lifecycle, culture/memory hermeticity, storm resilience
# ---------------------------------------------------------------------------


async def test_hermetic_factory_culture_and_memory_rebound():
    # The factory branch gets the same override set as the live branch: culture
    # rebound to a read-only copy so global reads survive, memory rebound to the
    # attempt's fresh db so per-user reads are empty.
    recorder = Recorder()
    culture_manager = StubManager(db=object())
    memory_manager = StubManager()
    env = _stub_env(recorder, culture_manager=culture_manager, memory_manager=memory_manager)

    result = await arun_rollouts(env, k=2, concurrency=2)

    assert result.pass_rate == 1.0
    assert len(recorder.snapshots) == 2  # non-vacuous: the old assertions passed on zero snapshots
    for snapshot in recorder.snapshots:
        assert snapshot["culture_manager"] is not None
        assert snapshot["culture_manager"] is not culture_manager
        assert snapshot["culture_manager"].db is culture_manager.db
        assert snapshot["memory_manager"] is not None
        assert snapshot["memory_manager"] is not memory_manager
        assert snapshot["memory_manager"].db is snapshot["db"]
        assert snapshot["update_cultural_knowledge"] is False
        assert snapshot["enable_agentic_culture"] is False


async def test_factory_preflight_error_names_the_factory():
    # A factory broken at time zero raises at call time -- like the other preflight
    # rejections -- with a message naming where it happened, not a bare traceback.
    def broken():
        raise KeyError("no such config")

    env = Environment(
        name="broken",
        tasks=(Task(input="x"),),
        scorer=CodeScorer(echo_scorer),
        agent=broken,
    )
    with pytest.raises(RuntimeError, match="run-start construction"):
        await arun_rollouts(env, k=2)


async def test_factory_returning_non_agent_rejected_at_run_start():
    env = Environment(
        name="bypass",
        tasks=(Task(input="x"),),
        scorer=CodeScorer(echo_scorer),
        agent=lambda: "not an agent",
    )
    with pytest.raises(TypeError, match="must return an Agent"):
        await arun_rollouts(env, k=1)


def test_default_model_resolved_for_fingerprint():
    # A model-less Agent runs on the installed default, so the fingerprint resolves
    # that same default -- on a copy, never mutating the caller's agent.
    from agno.agent import Agent
    from agno.environments.runner import _default_model_for

    agent = Agent()
    resolved = _default_model_for(agent)
    assert resolved is not None
    assert resolved.id == "gpt-5.4"
    assert agent.model is None
    # Duck-typed subjects degrade to None (and the fingerprint warns), not crash.
    assert _default_model_for(StubRolloutAgent(Recorder())) is None


async def test_error_storm_survives_grid_failure(monkeypatch):
    # The storm check and the grid share the engine callback; a rendering bug must
    # not take storm detection down with it.
    import agno.environments.runner as runner_module

    class RenderBugGrid:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def on_attempt(self, *args):
            raise ValueError("render bug")

    monkeypatch.setattr(runner_module, "LiveGrid", RenderBugGrid)
    monkeypatch.setattr("rich.console.Console.is_terminal", property(lambda self: True))

    env = _stub_env(tasks=(Task(input="one"),), error=RuntimeError("bad api key"))
    result = await arun_rollouts(env, k=8, concurrency=2)

    assert result.stopped_early == "error-storm"
    assert result.n_attempts < 8


async def test_error_storm_uses_structured_error_type(monkeypatch):
    # Two attempts failing with the same exception class but different message text
    # before the first colon still count as one storm kind.
    class WeirdError(RuntimeError):
        pass

    recorder = Recorder()
    calls = {"n": 0}

    def varying_error_factory():
        calls["n"] += 1
        return StubRolloutAgent(recorder, error=WeirdError(f"request {calls['n']} failed; retry later"))

    env = Environment(
        name="storm",
        tasks=(Task(input="one"),),
        scorer=CodeScorer(echo_scorer),
        agent=varying_error_factory,
    )
    result = await arun_rollouts(env, k=8, concurrency=2)
    assert result.stopped_early == "error-storm"


async def test_timeout_unscored_at_runner_level():
    # The runner threads Environment.timeout_seconds into the engine: a timed-out attempt is
    # unscored and excluded from statistics, never counted as 0.0.
    recorder = Recorder()
    env = _stub_env(recorder, delay=1.5, timeout_seconds=1)

    result = await arun_rollouts(env, k=2, concurrency=2)

    assert result.n_scored == 0
    assert result.n_unscored == 2
    assert result.pass_rate is None
    attempts = result.task_results[0].attempts
    assert all(attempt.stop_reason == StopReason.timeout for attempt in attempts)


def test_save_failure_names_task_and_preserves_existing_file(tmp_path):
    # A non-JSON expected is a legal run-time state (fingerprint degrades with a
    # warning), so save() must fail cleanly: serialize before truncating, and name
    # the task and field instead of a bare json TypeError.
    class Weird:
        pass

    task = Task(input="x", expected=Weird(), id="t1")
    result = EnvironmentRunResult(
        env_name="e",
        k=1,
        env_fingerprint=None,
        policy_fingerprint=None,
        task_results=(
            TaskResult(
                task=task,
                attempts=(AttemptResult(run=None, score=None, stop_reason=StopReason.error, duration_seconds=0.0),),
            ),
        ),
        duration_seconds=0.1,
    )
    target = tmp_path / "baseline.json"
    target.write_text("precious baseline", encoding="utf-8")

    with pytest.raises(TypeError, match=r"'t1'.*'expected'"):
        result.save(target)
    assert target.read_text(encoding="utf-8") == "precious baseline"


def test_diff_names_unmatched_tasks():
    # Same fingerprint, different task subset (learning_zone(), tasks=) is legal, so
    # unmatched tasks must be visible in the diff, never silently dropped.
    current = _result_with("aaa", "p1", {"t1": (8, 0), "t2": (6, 2)})
    baseline = _result_with("aaa", "p1", {"t1": (8, 0), "t3": (5, 3)})

    diff = current.diff(baseline)

    assert [row["id"] for row in diff.rows] == ["t1"]
    assert diff.unmatched_current == ("t2",)
    assert diff.unmatched_baseline == ("t3",)
    assert "not compared" in str(diff)
    assert diff.to_dict()["unmatched_current"] == ["t2"]


# ---------------------------------------------------------------------------
# Hermetic overrides on a REAL Agent (deep_copy path, end-to-end)
#
# The stub tests above mirror the override rules; these run the real Agent code so
# a field the stubs do not model (session summaries, compression, reasoning_agent,
# save_response_to_file, followup/fallback models) cannot pass vacuously.
# ---------------------------------------------------------------------------


class RecordingFakeModel(Model):
    """Real Model subclass: completes, counts provider calls, records the message
    list each call received. The runner's per-attempt copy.copy shares the mutable
    records, so the caller-side lists see attempt traffic."""

    def __init__(self, tag="fake", calls=None, seen_messages=None, seen_tools=None):
        super().__init__(id=f"fake-{tag}", name=f"fake-{tag}", provider="test")
        self.calls = calls if calls is not None else []
        self.seen_messages = seen_messages if seen_messages is not None else []
        self.seen_tools = seen_tools if seen_tools is not None else []

    def __deepcopy__(self, memo):
        # Fallback resolution deepcopies models; keep sharing the records and the
        # cache flag so tests can observe both across the copy.
        clone = type(self)(
            tag=self.id.removeprefix("fake-"),
            calls=self.calls,
            seen_messages=self.seen_messages,
            seen_tools=self.seen_tools,
        )
        clone.cache_response = self.cache_response
        return clone

    def _record(self, kind, args, kwargs):
        self.calls.append((self.id, kind, id(self), self.cache_response))
        for value in list(args) + list(kwargs.values()):
            if isinstance(value, list) and value and all(isinstance(m, Message) for m in value):
                self.seen_messages.append(list(value))
                break
        for tool in kwargs.get("tools") or []:
            if isinstance(tool, dict):
                name = tool.get("function", {}).get("name") or tool.get("name")
                if name:
                    self.seen_tools.append(name)
        return ModelResponse(role="assistant", content="The answer is 42.")

    def invoke(self, *args, **kwargs):
        return self._record("invoke", args, kwargs)

    async def ainvoke(self, *args, **kwargs):
        return self._record("ainvoke", args, kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self._record("invoke_stream", args, kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self._record("ainvoke_stream", args, kwargs)

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


class VaryingErrorModel(Model):
    """Raises RuntimeError with a colon-free, per-call-varying message: the storm
    fallback's first-colon prefix is never stable, so only the structured
    error_type path can detect the storm."""

    def __init__(self):
        super().__init__(id="varying-error", name="varying-error", provider="test")

    def _boom(self):
        raise RuntimeError(f"boom {uuid4().hex}")

    def invoke(self, *args, **kwargs):
        self._boom()

    async def ainvoke(self, *args, **kwargs):
        self._boom()

    def invoke_stream(self, *args, **kwargs):
        self._boom()
        yield  # pragma: no cover

    async def ainvoke_stream(self, *args, **kwargs):
        self._boom()
        yield  # pragma: no cover

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def _real_env(agent, *, tasks=None):
    return Environment(
        name="real-env",
        tasks=tasks if tasks is not None else (Task(input="hello"),),
        scorer=CodeScorer(lambda run, expected: True),
        agent=agent,
    )


def _spy_deep_copy(agent, sink):
    original = agent.deep_copy

    def spy(**kwargs):
        attempt_copy = original(**kwargs)
        sink.append(attempt_copy)
        return attempt_copy

    agent.deep_copy = spy
    return agent


async def test_error_storm_detected_by_error_type_on_real_agent():
    # A real Agent swallows model exceptions into error events; before the
    # error_type sweep those events were typeless and this exact run finished all
    # 8 attempts with stopped_early=None.
    env = _real_env(
        Agent(model=VaryingErrorModel(), telemetry=False),
        tasks=(Task(input="one"),),
    )
    result = await arun_rollouts(env, k=8, concurrency=2)

    assert result.stopped_early == "error-storm"
    attempts = [attempt for task_result in result.task_results for attempt in task_result.attempts]
    assert attempts
    assert all(attempt.error_type == "RuntimeError" for attempt in attempts)


async def test_hermetic_real_agent_full_override_set(tmp_path):
    from agno.compression.manager import CompressionManager
    from agno.culture.manager import CultureManager
    from agno.session import SessionSummaryManager
    from agno.skills.agent_skills import Skills

    calls = []
    main_model = RecordingFakeModel("main", calls=calls)
    main_model.cache_response = True
    reasoning_model = RecordingFakeModel("reasoning")
    reasoning_model.cache_response = True
    followup_model = RecordingFakeModel("followup")
    followup_model.cache_response = True
    fallback_model = RecordingFakeModel("fallback")
    fallback_model.cache_response = True
    sub_model = RecordingFakeModel("sub")
    caller_db = InMemoryDb()
    reasoning_db = InMemoryDb()
    summary_manager = SessionSummaryManager()
    compression_manager = CompressionManager()
    culture_manager = CultureManager(db=InMemoryDb())
    skills = Skills(loaders=[])
    save_path = tmp_path / "response.txt"
    caller = Agent(
        model=main_model,
        db=caller_db,
        reasoning_model=reasoning_model,
        followup_model=followup_model,
        fallback_models=[fallback_model],
        session_summary_manager=summary_manager,
        compression_manager=compression_manager,
        culture_manager=culture_manager,
        skills=skills,
        reasoning_agent=Agent(model=sub_model, db=reasoning_db, telemetry=False),
        save_response_to_file=str(save_path),
        telemetry=False,
    )
    attempt_agents = []
    _spy_deep_copy(caller, attempt_agents)

    result = await arun_rollouts(_real_env(caller), k=2, concurrency=2)

    assert result.pass_rate == 1.0
    assert len(attempt_agents) == 2
    for attempt_agent in attempt_agents:
        assert isinstance(attempt_agent.db, InMemoryDb) and attempt_agent.db is not caller_db
        assert attempt_agent.model is not main_model and attempt_agent.model.cache_response is False
        assert attempt_agent.reasoning_model is not reasoning_model
        assert attempt_agent.reasoning_model.cache_response is False
        assert attempt_agent.followup_model is not followup_model
        assert attempt_agent.followup_model.cache_response is False
        assert attempt_agent.fallback_config is not caller.fallback_config
        assert all(entry.cache_response is False for entry in attempt_agent.fallback_config.on_error)
        # The summary manager survives as an attempt-local copy: production's
        # resolver binds the attempt model on it, the read flag resolves True (a
        # fresh session has no summary to render), and only the WRITE is severed.
        assert attempt_agent.session_summary_manager is not None
        assert attempt_agent.session_summary_manager is not summary_manager
        assert attempt_agent.session_summary_manager.model is not main_model
        assert attempt_agent.session_summary_manager.model.id == "fake-main"
        assert attempt_agent.session_summary_manager.model.cache_response is False
        assert attempt_agent.enable_session_summaries is False
        assert attempt_agent.memory_manager is None
        # No memory signal on this caller, so production's resolver leaves the
        # read flag unresolved -- exactly what a fresh production run would see.
        assert attempt_agent.add_memories_to_context is None
        assert attempt_agent.add_session_summary_to_context is True
        assert attempt_agent.add_culture_to_context is True
        assert attempt_agent.compression_manager is not compression_manager
        assert attempt_agent.compression_manager.stats == {}
        assert attempt_agent.compression_manager.stats is not compression_manager.stats
        assert attempt_agent.culture_manager is not culture_manager
        assert attempt_agent.culture_manager.db is culture_manager.db
        assert attempt_agent.reasoning_agent is not caller.reasoning_agent
        assert isinstance(attempt_agent.reasoning_agent.db, InMemoryDb)
        assert attempt_agent.reasoning_agent.db is not reasoning_db
        assert attempt_agent.reasoning_agent.model is not sub_model
        assert attempt_agent.reasoning_agent.model.cache_response is False
        assert attempt_agent.save_response_to_file is None
        assert attempt_agent.skills is skills  # read-only definitions stay shared
    # The caller is untouched, in objects and in side effects.
    assert caller.db is caller_db
    assert caller.model is main_model and main_model.cache_response is True
    assert caller.add_memories_to_context is None
    assert caller.add_session_summary_to_context is None
    assert summary_manager.model is None  # attempt init never wrote its model here
    assert caller.fallback_config.on_error[0].cache_response is True
    assert not save_path.exists()
    # Exactly one provider call per attempt on the main model, none anywhere
    # else: no summary or memory call rode along. (Reasoning is not enabled on
    # this caller, so the reasoning slots are exercised as bindings only.)
    assert [call[0] for call in calls] == ["fake-main", "fake-main"]


async def test_culture_reads_survive_hermetic_attempts():
    # Regression pin: nulling the culture manager silently swapped the caller's
    # culture for the empty-culture boilerplate inside every attempt.
    from agno.culture.manager import CultureManager
    from agno.db.schemas.culture import CulturalKnowledge

    seen_messages = []
    recording_model = RecordingFakeModel("culture", seen_messages=seen_messages)
    caller_db = InMemoryDb()
    CultureManager(db=caller_db).add_cultural_knowledge(
        CulturalKnowledge(name="Golden Rule", content="CULTURE-MARKER-XYZZY")
    )
    caller = Agent(model=recording_model, db=caller_db, add_culture_to_context=True, telemetry=False)

    result = await arun_rollouts(_real_env(caller), k=1, concurrency=1)

    assert result.pass_rate == 1.0
    prompt_text = "\n".join(
        str(message.content) for messages in seen_messages for message in messages if message.content
    )
    assert "CULTURE-MARKER-XYZZY" in prompt_text
    assert "no cultural knowledge is currently available" not in prompt_text


class FakeLearnedKnowledge:
    """Duck-typed knowledge store holding one GLOBAL learned item, recording reads
    and any write reaching it."""

    def __init__(self):
        self.search_calls = []
        self.writes = []
        self.items = [
            {"content": '{"title": "Deploy rule", "learning": "LEARNING-MARKER-XYZZY", "namespace": "global"}'}
        ]

    def search(self, query, max_results=5, filters=None, **kwargs):
        self.search_calls.append(query)
        return list(self.items)

    def __getattr__(self, name):
        if name.startswith(("add", "upsert", "insert", "save", "delete")):

            def _write(*args, **kwargs):
                self.writes.append((name, args, kwargs))

            return _write
        raise AttributeError(name)


async def test_learning_reads_survive_hermetic_attempts():
    # Regression pin: nulling agent.learning severed global learned-knowledge READS
    # -- the <learning_system> block, the search_learnings tool, the store read
    # path -- when only the writes must go. Learned knowledge is global state like
    # culture, so attempts read it exactly as production does.
    from agno.learn import LearningMachine
    from agno.learn.config import LearnedKnowledgeConfig

    seen_messages = []
    seen_tools = []
    recording_model = RecordingFakeModel("learning", seen_messages=seen_messages, seen_tools=seen_tools)
    knowledge = FakeLearnedKnowledge()
    machine = LearningMachine(learned_knowledge=LearnedKnowledgeConfig(knowledge=knowledge))
    caller = Agent(model=recording_model, db=InMemoryDb(), learning=machine, telemetry=False)

    result = await arun_rollouts(_real_env(caller), k=1, concurrency=1)

    assert result.pass_rate == 1.0
    prompt_text = "\n".join(
        str(message.content) for messages in seen_messages for message in messages if message.content
    )
    assert "<learning_system>" in prompt_text
    assert "search_learnings" in seen_tools  # the read tool survives
    assert "save_learning" not in seen_tools  # the write tool does not
    assert knowledge.writes == []
    # The caller's machine is untouched and still writable in production.
    assert caller.learning is machine
    assert machine.learned_knowledge.agent_can_save is True


async def test_hermetic_learning_extraction_never_fires():
    # An ALWAYS-mode store extracts after every run via an extra model call; inside
    # an attempt that call must not ride along and nothing may land in the caller's
    # store -- while the read surfaces stay up.
    from agno.learn import LearningMachine
    from agno.learn.config import LearnedKnowledgeConfig, LearningMode

    calls = []
    recording_model = RecordingFakeModel("main", calls=calls)
    knowledge = FakeLearnedKnowledge()
    machine = LearningMachine(
        learned_knowledge=LearnedKnowledgeConfig(knowledge=knowledge, mode=LearningMode.ALWAYS),
    )
    caller = Agent(model=recording_model, db=InMemoryDb(), learning=machine, telemetry=False)

    result = await arun_rollouts(_real_env(caller), k=2, concurrency=2)

    assert result.pass_rate == 1.0
    assert [call[0] for call in calls] == ["fake-main", "fake-main"]  # no extraction call rode along
    assert knowledge.writes == []
    assert machine.learned_knowledge.mode is LearningMode.ALWAYS  # caller config untouched


async def test_attempt_prompt_same_whether_caller_ran_before_handover():
    # add_memories_to_context / add_session_summary_to_context default to None and
    # are resolved IN PLACE on the caller's first run. The override runs
    # production's resolver against the swapped inputs, so a never-run caller's
    # attempts resolve the same flags an already-run caller carries -- one prompt
    # for the same Environment and task, and it is production's fresh-user prompt: the
    # memory empty-state paragraph is IN it, not severed with the block.
    from agno.memory import MemoryManager

    def build_caller(tag, seen_messages):
        return Agent(
            model=RecordingFakeModel(tag, seen_messages=seen_messages),
            db=InMemoryDb(),
            memory_manager=MemoryManager(),
            telemetry=False,
        )

    seen_fresh = []
    fresh_caller = build_caller("fresh", seen_fresh)

    seen_ran = []
    ran_caller = build_caller("ran", seen_ran)
    await ran_caller.arun(input="warmup")  # resolves the context flags on the caller
    seen_ran.clear()

    await arun_rollouts(_real_env(fresh_caller), k=1, concurrency=1)
    await arun_rollouts(_real_env(ran_caller), k=1, concurrency=1)

    fresh_prompts = ["\n".join(str(m.content) for m in messages) for messages in seen_fresh]
    ran_prompts = ["\n".join(str(m.content) for m in messages) for messages in seen_ran]
    assert fresh_prompts and fresh_prompts == ran_prompts
    assert "retain memories" in "\n".join(ran_prompts)


class MCPTools:
    """Named exactly like the real class: the run-start guard matches on MRO class
    names, mirroring the run path's own MCP detection -- so this stand-in triggers
    it without a server."""


async def test_live_agent_with_mcp_tools_rejected_at_run_start():
    caller = Agent(model=RecordingFakeModel("mcp"), tools=[MCPTools()], telemetry=False)
    with pytest.raises(RuntimeError, match="factory"):
        await arun_rollouts(_real_env(caller), k=1)


async def test_factory_env_with_mcp_tools_not_rejected():
    # A factory constructs fresh MCP tools per attempt -- the documented workaround
    # -- so the guard must not fire on the factory path.
    recorder = Recorder()

    def factory():
        stub = StubRolloutAgent(recorder)
        stub.tools = [MCPTools()]
        return stub

    env = Environment(
        name="mcp-factory", tasks=(Task(input="one"),), scorer=CodeScorer(lambda r, e: True), agent=factory
    )
    result = await arun_rollouts(env, k=1, concurrency=1)
    assert result.n_attempts == 1


async def test_live_agent_with_callable_tools_factory_mcp_rejected():
    # A callable tools-factory hides MCP from a top-level list check; the guard resolves
    # it and rejects, so a rollout can never silently green a toolless run (the factory
    # tools resolve per attempt into run_context and the unconnected MCP is dropped).
    shared = MCPTools()
    caller = Agent(model=RecordingFakeModel("mcp"), tools=lambda: [shared], telemetry=False)
    with pytest.raises(RuntimeError, match="MCPTools"):
        await arun_rollouts(_real_env(caller), k=1)


async def test_factory_env_with_callable_tools_factory_mcp_rejected():
    # Even a factory env must not hide MCP behind a callable tools factory -- concrete
    # tools=[MCPTools()] is the supported pattern, a callable is not.
    recorder = Recorder()
    shared = MCPTools()

    def factory():
        stub = StubRolloutAgent(recorder)
        stub.tools = lambda: [shared]
        return stub

    env = Environment(
        name="mcp-callable", tasks=(Task(input="one"),), scorer=CodeScorer(lambda r, e: True), agent=factory
    )
    with pytest.raises(RuntimeError, match="MCPTools"):
        await arun_rollouts(env, k=1, concurrency=1)


async def test_injected_arg_tools_factory_fails_closed():
    # Production supports tools factories with injected parameters (agent, run_context,
    # session_state); the run-start guard can only call a factory with no arguments, so
    # an injected-arg factory raises there and its tools are never inspected. Tools the
    # guard never saw cannot be certified MCP-free: the run refuses to start, before
    # any attempt reaches the model.
    calls = []

    def tools_factory(agent, run_context):
        return []

    caller = Agent(model=RecordingFakeModel("injected", calls=calls), tools=tools_factory, telemetry=False)
    with pytest.raises(RuntimeError, match="tools factory"):
        await arun_rollouts(_real_env(caller), k=2)
    assert calls == []  # no attempt ever ran


async def test_injected_arg_tools_factory_fails_closed_on_factory_env():
    recorder = Recorder()

    def factory():
        stub = StubRolloutAgent(recorder)
        stub.tools = lambda agent, run_context: []
        return stub

    env = Environment(
        name="injected-factory", tasks=(Task(input="one"),), scorer=CodeScorer(lambda r, e: True), agent=factory
    )
    with pytest.raises(RuntimeError, match="tools factory"):
        await arun_rollouts(env, k=1, concurrency=1)
    assert recorder.snapshots == []  # no attempt ever ran


async def test_async_tools_factory_fails_closed():
    # Calling a coroutine function raises nothing -- it returns a coroutine object --
    # so without an awaitable check an async factory would slip past the guard as
    # "no tools" and green a run whose MCP was never connected. Async factories are
    # a supported production pattern, so this is a real front door, and it must
    # fail closed like the injected-arg case.
    calls = []

    async def tools_factory():
        return []

    caller = Agent(model=RecordingFakeModel("async-tools", calls=calls), tools=tools_factory, telemetry=False)
    with pytest.raises(RuntimeError, match="async"):
        await arun_rollouts(_real_env(caller), k=2)
    assert calls == []  # no attempt ever ran


async def test_async_tools_factory_hiding_mcp_fails_closed_on_factory_env():
    recorder = Recorder()

    async def tools_factory():
        return [MCPTools()]

    def factory():
        stub = StubRolloutAgent(recorder)
        stub.tools = tools_factory
        return stub

    env = Environment(name="async-mcp", tasks=(Task(input="one"),), scorer=CodeScorer(lambda r, e: True), agent=factory)
    with pytest.raises(RuntimeError, match="async"):
        await arun_rollouts(env, k=1, concurrency=1)
    assert recorder.snapshots == []  # no attempt ever ran


async def test_zero_arg_tools_factory_without_mcp_still_runs():
    # A zero-arg factory the guard can resolve to ordinary tools passes; only
    # unresolvable factories fail closed.
    def tools_factory():
        return []

    caller = Agent(model=RecordingFakeModel("zero-arg-tools"), tools=tools_factory, telemetry=False)
    result = await arun_rollouts(_real_env(caller), k=1, concurrency=1)
    assert result.pass_rate == 1.0


async def test_live_agent_with_composed_mcp_tools_rejected():
    # MCP held by composition (a toolkit wrapping MCPTools) evades a top-level type
    # check; one level of container composition is walked so it is still caught.
    class WrapperToolkit:
        def __init__(self):
            self.tools = [MCPTools()]

    caller = Agent(model=RecordingFakeModel("mcp"), tools=[WrapperToolkit()], telemetry=False)
    with pytest.raises(RuntimeError, match="MCPTools"):
        await arun_rollouts(_real_env(caller), k=1)


async def test_opaque_learning_store_in_standard_slot_dropped():
    # An opaque store in a standard slot satisfies the LearningStore protocol but
    # carries no .config, so isolation cannot strip its write tools -- it must be
    # dropped loudly, not shallow-copied with its writes (and caller state) intact.
    from agno.environments.runner import _read_only_learning_machine
    from agno.learn import LearningMachine

    class OpaqueStore:
        def get_tools(self, **kwargs):
            return [lambda value: None]

    machine = LearningMachine()
    machine.user_profile = OpaqueStore()
    isolated = _read_only_learning_machine(machine, source_db=InMemoryDb())
    assert isolated.user_profile is False


async def test_live_agent_with_nested_mcp_tools_rejected_at_run_start():
    # deep_copy shares a reasoning agent's tools by reference exactly like
    # top-level ones: the guard must see MCPTools anywhere the hermetic walk goes.
    caller = Agent(
        model=RecordingFakeModel("mcp-outer"),
        reasoning_agent=Agent(model=RecordingFakeModel("mcp-inner"), tools=[MCPTools()], telemetry=False),
        telemetry=False,
    )
    with pytest.raises(RuntimeError, match="factory"):
        await arun_rollouts(_real_env(caller), k=1)


async def test_factory_env_with_nested_mcp_tools_not_rejected():
    recorder = Recorder()

    def factory():
        stub = StubRolloutAgent(recorder)
        nested = StubRolloutAgent(recorder)
        nested.tools = [MCPTools()]
        stub.reasoning_agent = nested
        return stub

    env = Environment(
        name="mcp-nested-factory",
        tasks=(Task(input="one"),),
        scorer=CodeScorer(lambda r, e: True),
        agent=factory,
    )
    result = await arun_rollouts(env, k=1, concurrency=1)
    assert result.n_attempts == 1


async def test_positional_task_id_collision_rejected_at_run_start():
    # An explicit "t2" colliding with the second task's auto-id only exists after
    # resolution; diff() keyed on the duplicate would pair rows with the wrong task.
    env = _stub_env(tasks=(Task(input="a", id="t2"), Task(input="b")))
    with pytest.raises(ValueError, match="duplicate resolved task id"):
        await arun_rollouts(env, k=1)


async def test_model_less_duck_subject_degrades_policy_fingerprint():
    # A duck-typed factory product with NO model attribute degrades the policy
    # fingerprint to None like a model-less Agent -- it must not crash preflight.
    class ModelLessDuck:
        async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
            yield _output(content=f"echo:{input}")

    env = Environment(
        name="duck",
        tasks=(Task(input="one"),),
        scorer=CodeScorer(lambda run, expected: True),
        agent=lambda: ModelLessDuck(),
    )
    result = await arun_rollouts(env, k=1, concurrency=1)
    assert result.policy_fingerprint is None
    assert result.pass_rate == 1.0


def test_every_shared_field_has_a_hermetic_action():
    # The drift alarm: a field added to deep_copy's shared-by-reference tuple
    # without a mapped hermetic action fails here before it ships.
    missing = set(SHARED_BY_REFERENCE_FIELDS) - set(_ISOLATE_FIELD_ACTIONS)
    assert not missing, f"unmapped shared-by-reference fields: {sorted(missing)}"


# ---------------------------------------------------------------------------
# Read parity: for every context-shaping feature, the attempt system prompt is
# byte-identical to the prompt a fresh production user gets from the same world.
# The attempt runs FIRST, so equality also proves the attempt left the world
# unchanged for the production run that follows.
# ---------------------------------------------------------------------------


def _system_text(seen_messages):
    first_call = seen_messages[0]
    return "\n".join(str(m.content) for m in first_call if getattr(m, "role", None) == "system")


async def _parity_prompts(build_agent):
    """build_agent(model) -> an Agent over a shared world. Returns the attempt
    system prompt and the fresh-user production system prompt, in that order."""
    attempt_seen = []
    attempt_env = _real_env(build_agent(RecordingFakeModel("parity", seen_messages=attempt_seen)))
    result = await arun_rollouts(attempt_env, k=1, concurrency=1)
    assert result.pass_rate == 1.0  # non-vacuous: the attempt actually completed

    production_seen = []
    production_agent = build_agent(RecordingFakeModel("parity", seen_messages=production_seen))
    try:
        await production_agent.arun(
            input="hello",
            user_id=f"fresh-user-{uuid4().hex}",
            session_id=f"fresh-session-{uuid4().hex}",
        )
    except Exception:
        # Post-run write engines may choke on the fake model's canned response;
        # the system prompt was captured at request time.
        pass
    assert production_seen, "production run never reached the model"
    return _system_text(attempt_seen), _system_text(production_seen)


async def test_read_parity_memory():
    world_db = InMemoryDb()

    def build(model):
        return Agent(model=model, db=world_db, update_memory_on_run=True, telemetry=False)

    attempt_prompt, production_prompt = await _parity_prompts(build)
    assert "retain memories" in attempt_prompt  # the fresh-user empty state renders
    assert attempt_prompt == production_prompt


async def test_read_parity_culture():
    from agno.culture.manager import CultureManager
    from agno.db.schemas.culture import CulturalKnowledge

    world_db = InMemoryDb()
    CultureManager(db=world_db).add_cultural_knowledge(
        CulturalKnowledge(name="Golden Rule", content="CULTURE-MARKER-XYZZY")
    )

    def build(model):
        return Agent(model=model, db=world_db, add_culture_to_context=True, telemetry=False)

    attempt_prompt, production_prompt = await _parity_prompts(build)
    assert "CULTURE-MARKER-XYZZY" in attempt_prompt  # global culture reads survive
    assert attempt_prompt == production_prompt


async def test_read_parity_culture_write_flag_only_no_db():
    # The gate's path 5a: a caller with only a culture WRITE flag and no db.
    # Production resolves add_culture_to_context=True and renders the culture
    # empty state; severing the write flag before resolution used to lose the
    # whole block. Resolution now runs first, against the attempt's fresh db.
    def build(model):
        return Agent(model=model, update_cultural_knowledge=True, telemetry=False)

    attempt_prompt, production_prompt = await _parity_prompts(build)
    assert "no cultural knowledge is currently available" in attempt_prompt
    assert attempt_prompt == production_prompt


async def test_read_parity_learning():
    from agno.learn import LearningMachine
    from agno.learn.config import LearnedKnowledgeConfig

    world_db = InMemoryDb()
    knowledge = FakeLearnedKnowledge()

    def build(model):
        return Agent(
            model=model,
            db=world_db,
            learning=LearningMachine(learned_knowledge=LearnedKnowledgeConfig(knowledge=knowledge)),
            telemetry=False,
        )

    attempt_prompt, production_prompt = await _parity_prompts(build)
    assert "<learning_system>" in attempt_prompt  # global learned knowledge renders
    assert attempt_prompt == production_prompt


async def test_read_parity_learning_true_default():
    # learning=True is materialized into an explicit default machine so severing
    # survives re-initialization; the prompt must still be what production's own
    # learning=True renders for a fresh user.
    world_db = InMemoryDb()

    def build(model):
        # The description keeps the system prompt non-empty, so equality is not
        # a vacuous ""-vs-"" comparison.
        return Agent(model=model, db=world_db, learning=True, description="Parity probe.", telemetry=False)

    attempt_prompt, production_prompt = await _parity_prompts(build)
    assert "Parity probe." in attempt_prompt
    assert attempt_prompt == production_prompt


async def test_read_parity_session_summary():
    world_db = InMemoryDb()

    def build(model):
        # The description keeps the system prompt non-empty, so equality is not
        # a vacuous ""-vs-"" comparison.
        return Agent(
            model=model, db=world_db, enable_session_summaries=True, description="Parity probe.", telemetry=False
        )

    attempt_prompt, production_prompt = await _parity_prompts(build)
    assert "Parity probe." in attempt_prompt
    assert "summary_of_previous_interactions" not in attempt_prompt  # fresh session: nothing to render
    assert attempt_prompt == production_prompt


class StubKnowledge:
    """Duck-typed knowledge: enough surface for context building and the search
    tool registration, with a marker the parity assertions can look for."""

    def build_context(self, enable_agentic_filters=False):
        return "<knowledge_instructions>KNOWLEDGE-MARKER-XYZZY</knowledge_instructions>"


async def test_read_parity_knowledge():
    world_db = InMemoryDb()
    knowledge = StubKnowledge()

    def build(model):
        return Agent(model=model, db=world_db, knowledge=knowledge, telemetry=False)

    attempt_prompt, production_prompt = await _parity_prompts(build)
    assert "KNOWLEDGE-MARKER-XYZZY" in attempt_prompt  # shared knowledge reads survive
    assert attempt_prompt == production_prompt


class StubSkills:
    """Duck-typed skills: the two methods the run path calls."""

    def get_system_prompt_snippet(self):
        return "SKILLS-MARKER-XYZZY"

    def get_tools(self):
        return []


async def test_read_parity_skills():
    world_db = InMemoryDb()
    skills = StubSkills()

    def build(model):
        return Agent(model=model, db=world_db, skills=skills, telemetry=False)

    attempt_prompt, production_prompt = await _parity_prompts(build)
    assert "SKILLS-MARKER-XYZZY" in attempt_prompt  # shared skill definitions survive
    assert attempt_prompt == production_prompt


# ---------------------------------------------------------------------------
# Write isolation: the deep-freeze check. Concurrent attempts on a maxed-out
# caller must leave the caller's reachable object graph byte-identical.
# ---------------------------------------------------------------------------

# Test-double observation sinks that grow on deliberate READS; everything else
# in the caller graph must be frozen.
_SNAPSHOT_SINK_NAMES = {"calls", "seen_messages", "seen_tools", "search_calls"}


def _graph_paths(root, keepalive):
    """Flatten an object graph into {path: value-or-id} for before/after diffing.
    `keepalive` pins visited objects so ids cannot be reused across snapshots."""
    paths = {}

    def record(path, value, depth, on_path_ids):
        if isinstance(value, (str, int, float, bool, type(None))):
            paths[path] = repr(value)
            return
        if id(value) in on_path_ids:
            paths[path] = "<cycle>"
            return
        keepalive.append(value)
        branch_ids = on_path_ids | {id(value)}
        if isinstance(value, (list, tuple)):
            paths[path + ".len"] = len(value)
            if depth > 0:
                for index, item in enumerate(value):
                    record(f"{path}[{index}]", item, depth - 1, branch_ids)
            return
        if isinstance(value, (set, frozenset)):
            paths[path + ".len"] = len(value)
            if depth > 0:
                for index, item in enumerate(sorted(value, key=repr)):
                    record(f"{path}{{{index}}}", item, depth - 1, branch_ids)
            return
        if isinstance(value, dict):
            paths[path + ".len"] = len(value)
            if depth > 0:
                for key in sorted(value, key=repr):
                    record(f"{path}[{key!r}]", value[key], depth - 1, branch_ids)
            return
        paths[path + ".id"] = id(value)
        if depth > 0 and hasattr(value, "__dict__"):
            for name in sorted(vars(value)):
                if name in _SNAPSHOT_SINK_NAMES or name.startswith("__"):
                    continue
                record(f"{path}.{name}", vars(value)[name], depth - 1, branch_ids)

    record("caller", root, 6, frozenset())
    return paths


async def _drain_background_tasks():
    current = asyncio.current_task()
    pending = [task for task in asyncio.all_tasks() if task is not current]
    if pending:
        await asyncio.gather(*pending, return_exceptions=True)


async def test_write_isolation_deep_freeze(tmp_path):
    # k=3 concurrent attempts on a maxed-out caller -- every manager, seeded db,
    # learning machine over a shared store, reasoning agent, fallback models,
    # warm caches, save file. Snapshot the caller's reachable graph before and
    # after; zero caller-side mutations, no save file, no cache replay.
    from agno.compression.manager import CompressionManager
    from agno.culture.manager import CultureManager
    from agno.db.schemas.culture import CulturalKnowledge
    from agno.learn import LearningMachine
    from agno.learn.config import LearnedKnowledgeConfig, LearningMode
    from agno.memory import MemoryManager
    from agno.session import SessionSummaryManager

    calls = []
    main_model = RecordingFakeModel("main", calls=calls)
    main_model.cache_response = True
    reasoning_model = RecordingFakeModel("reasoning", calls=calls)
    reasoning_model.cache_response = True
    fallback_model = RecordingFakeModel("fallback", calls=calls)
    fallback_model.cache_response = True
    sub_model = RecordingFakeModel("sub", calls=calls)
    sub_model.cache_response = True

    world_db = InMemoryDb()
    culture_db = InMemoryDb()
    CultureManager(db=culture_db).add_cultural_knowledge(
        CulturalKnowledge(name="Golden Rule", content="CULTURE-MARKER-XYZZY")
    )
    learned_store = FakeLearnedKnowledge()
    save_path = tmp_path / "response.txt"

    caller = Agent(
        model=main_model,
        db=world_db,
        reasoning_model=reasoning_model,
        fallback_models=[fallback_model],
        memory_manager=MemoryManager(),
        session_summary_manager=SessionSummaryManager(),
        culture_manager=CultureManager(db=culture_db),
        compression_manager=CompressionManager(),
        learning=LearningMachine(
            learned_knowledge=LearnedKnowledgeConfig(knowledge=learned_store, mode=LearningMode.ALWAYS)
        ),
        update_memory_on_run=True,
        enable_agentic_memory=True,
        enable_session_summaries=True,
        update_knowledge=True,
        update_cultural_knowledge=True,
        enable_agentic_culture=True,
        reasoning_agent=Agent(model=sub_model, db=InMemoryDb(), telemetry=False),
        save_response_to_file=str(save_path),
        skills=StubSkills(),
        telemetry=False,
    )

    # Warm the caller: resolve flags in place, run lazy initializers, write the
    # production rows the attempts must then never touch.
    try:
        await caller.arun(input="warmup", user_id="prod-user")
    except Exception:
        pass  # write engines may choke on the fake model's canned response
    await _drain_background_tasks()
    save_path.unlink(missing_ok=True)  # written by the warm run, legitimately
    calls.clear()

    keepalive = []
    before = _graph_paths(caller, keepalive)
    assert len(before) >= 200  # the freeze is only meaningful over a broad graph

    result = await arun_rollouts(_real_env(caller), k=3, concurrency=3)
    await _drain_background_tasks()

    assert result.n_attempts == 3
    after = _graph_paths(caller, keepalive)
    diffs = {
        path: (before.get(path), after.get(path))
        for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    }
    assert not diffs, f"caller-side mutations after attempts: {dict(sorted(diffs.items())[:10])}"
    assert not save_path.exists()
    assert learned_store.writes == []
    # No cross-attempt cache replay: every provider call the attempts made ran
    # with the response cache off, on every model slot.
    assert calls, "attempts made no provider calls"
    assert all(call[3] is False for call in calls)


# ---------------------------------------------------------------------------
# Callable-instance hooks through the engine
# ---------------------------------------------------------------------------


class RecordingCallableHook:
    """A hook with no __name__: only the type name identifies it."""

    def __init__(self, sink):
        self.sink = sink

    def __call__(self, **kwargs):
        self.sink.append(type(self).__name__)


async def test_callable_instance_hooks_survive_attempts():
    # The engine always streams with stream_events=True, and the hook-event
    # builders read the hook's name on every path -- a callable instance used to
    # fail 100% of attempts with AttributeError before get_hook_name.
    fired = []
    pre_hook = RecordingCallableHook(fired)
    post_hook = RecordingCallableHook(fired)

    env = Environment(
        name="callable-hooks",
        tasks=(Task(input="hello"),),
        scorer=CodeScorer(lambda run, expected: True),
        agent=lambda: Agent(
            model=RecordingFakeModel("hooks"),
            pre_hooks=[pre_hook],
            post_hooks=[post_hook],
            telemetry=False,
        ),
    )
    result = await arun_rollouts(env, k=2, concurrency=2)

    assert result.pass_rate == 1.0
    attempts = [attempt for task_result in result.task_results for attempt in task_result.attempts]
    assert all(attempt.stop_reason == StopReason.completed for attempt in attempts)
    assert all(attempt.error is None for attempt in attempts)
    assert fired.count("RecordingCallableHook") == 4  # pre and post, both attempts


async def test_asave_aload_roundtrip(tmp_path):
    result = await arun_rollouts(_stub_env(), k=2, concurrency=2)
    target = tmp_path / "async-roundtrip.json"
    await result.asave(target)
    loaded = await EnvironmentRunResult.aload(target)
    assert loaded.summary() == result.summary()


async def test_subclass_custom_manager_and_model_are_isolated():
    # Agent is @dataclass(init=False): a subclass's own instance attributes are not
    # dataclass fields, so before the union in _field_names_of they were invisible to
    # the unknown-manager null and the cache-off walk -- a custom manager stayed bound
    # to the caller's db and a write through it landed in the caller's store.
    caller_db = InMemoryDb()

    class _CustomManager:
        def __init__(self, db):
            self.db = db

    # An EXPLICIT signature on purpose: a **kwargs subclass loses every field under
    # deep_copy (a separate defect, guarded by the wrong-policy check), which would make
    # this test vacuous by dropping the very attributes it asserts on.
    class _SubAgent(Agent):
        def __init__(self, model=None, db=None, telemetry=False):
            super().__init__(model=model, db=db, telemetry=telemetry)
            self.custom_manager = _CustomManager(db=caller_db)
            self.critic_model = RecordingFakeModel("critic")
            self.critic_model.cache_response = True

    caller = _SubAgent(model=RecordingFakeModel("main"), db=caller_db, telemetry=False)
    # Non-vacuity: the copy really does carry the subclass attributes, re-bound to the
    # caller's db, before isolation runs.
    precheck = caller.deep_copy()
    assert precheck.custom_manager.db is caller_db
    assert precheck.critic_model.cache_response is True
    isolated = caller.deep_copy()
    _isolate_attempt(isolated)

    # The unknown manager is nulled loudly rather than shared, and the subclass's own
    # model has its response cache disabled like any other.
    assert getattr(isolated, "custom_manager", None) is None
    assert getattr(isolated, "critic_model").cache_response is False


async def test_factory_returning_shared_mcp_instance_rejected():
    # A factory that closes over ONE MCP hands every attempt the same session -- the
    # anti-pattern the run-start guard rejects on the live path. Identity across calls
    # is what catches it here.
    recorder = Recorder()
    shared = MCPTools()

    def factory():
        stub = StubRolloutAgent(recorder)
        stub.tools = [shared]  # same instance every call
        return stub

    env = Environment(
        name="mcp-shared", tasks=(Task(input="one"),), scorer=CodeScorer(lambda r, e: True), agent=factory
    )
    with pytest.raises(RuntimeError, match="SAME"):
        await arun_rollouts(env, k=2, concurrency=1)


async def test_model_less_agent_does_not_trip_policy_guard(monkeypatch):
    # The wrong-policy guard reads the attempt's model AFTER _isolate_attempt, because
    # initialize_agent() installs the default there. A model-less agent must resolve
    # to the same default the run was fingerprinted against, not fire the guard: a
    # misfire is captured as attempt-error data, which is exactly what the completed/
    # no-error assertions below rule out. The default installer is patched to an
    # offline recording model -- every consumer imports it from agno.agent._init at
    # call time -- so the test never constructs the real provider default and can
    # never make a live call.
    import agno.agent._init as agent_init
    from agno.environments.environment import _policy_fingerprint_of

    calls = []
    fake_default = RecordingFakeModel("default", calls=calls)

    def install_fake_default(agent):
        if agent.model is None:
            agent.model = fake_default

    monkeypatch.setattr(agent_init, "set_default_model", install_fake_default)

    # Computed before the run, like the runner's own stamp: the fingerprint sweeps
    # unknown model attributes, which for this recording model includes the call
    # sinks the attempt fills.
    expected_fingerprint = _policy_fingerprint_of(fake_default)

    caller = Agent(telemetry=False)
    result = await arun_rollouts(_real_env(caller), k=1, concurrency=1)

    assert caller.model is None  # the caller stays model-less; only copies get the default
    assert [call[0] for call in calls] == ["fake-default"]  # the fake default served the attempt
    attempt = result.task_results[0].attempts[0]
    assert attempt.stop_reason == StopReason.completed
    assert attempt.error is None  # the guard did not fire (guard failures land here)
    assert result.policy_fingerprint == expected_fingerprint
