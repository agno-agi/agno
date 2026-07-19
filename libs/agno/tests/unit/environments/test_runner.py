"""Unit tests for run_rollouts / arun_rollouts, hermetic overrides, and results."""

import asyncio
import json

import pytest

from agno.db.in_memory import InMemoryDb
from agno.environments import Env, EnvRunResult, EnvTask, StopReason, TaskResult, arun_rollouts, run_rollouts
from agno.environments._engine import AttemptResult
from agno.models.openai import OpenAIChat
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.scorer import CodeScorer, EnvMismatchError, Score


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


class StubRolloutAgent:
    """Duck-typed agent for Env factories. Mirrors the streaming contract; records a
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
        self.user_id = None
        self.session_state = {"seed": 1}
        self.instructions = "Answer tersely."
        self.update_memory_on_run = True
        self.enable_user_memories = True
        self.enable_agentic_memory = True
        self.update_knowledge = True

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
                "user_id": self.user_id,
                "update_memory_on_run": self.update_memory_on_run,
                "enable_user_memories": self.enable_user_memories,
                "enable_agentic_memory": self.enable_agentic_memory,
                "update_knowledge": self.update_knowledge,
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


def _stub_env(recorder=None, *, tasks=None, scorer=None, timeout_seconds=120, **agent_kwargs) -> Env:
    recorder = recorder if recorder is not None else Recorder()
    return Env(
        name="stub-env",
        tasks=tasks if tasks is not None else (EnvTask(input="one", expected="echo:one"),),
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
    # deep_copy shares a LearningMachine by reference and it resolves against its own
    # db: left attached, a "hermetic" run would write learning updates to the
    # caller's real store.
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


async def test_hermetic_identical_start():
    # Each attempt's first-call payload, with session/user ids masked, is identical.
    recorder = Recorder()
    env = _stub_env(recorder)

    await arun_rollouts(env, k=4, concurrency=4)

    masked = [
        {
            "input": run_input,
            "session_state": snapshot["session_state"],
            "instructions": snapshot["instructions"],
            "db_type": type(snapshot["db"]).__name__,
        }
        for run_input, snapshot in zip(recorder.run_inputs, recorder.snapshots)
    ]
    assert all(payload == masked[0] for payload in masked)
    # The ids themselves are fresh per attempt.
    assert len(set(recorder.session_ids)) == 4
    assert len({snapshot["user_id"] for snapshot in recorder.snapshots}) == 4
    assert all(snapshot["user_id"] for snapshot in recorder.snapshots)


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
    return TaskResult(task=EnvTask(input="q", id="t1"), attempts=tuple(attempts))


def test_learning_zone_rule():
    # Needs two scored attempts; isclose on the extremes -- no epsilon invented.
    assert _task_result_with_values([0.7, 0.7000000001]).in_learning_zone is False
    assert _task_result_with_values([0.8, 0.9, 1.0]).in_learning_zone is True
    assert _task_result_with_values([1.0]).in_learning_zone is False  # k=1 degenerate
    assert _task_result_with_values([], unscored=2).in_learning_zone is False
    assert _task_result_with_values([0.0, 1.0]).in_learning_zone is True


async def test_expected_reaches_scorer_through_env():
    env = _stub_env(
        tasks=(
            EnvTask(input="one", expected="echo:one"),
            EnvTask(input="two", expected="echo:two"),
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
    from agno.environments.env import policy_fingerprint_of

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
        EnvTask(input="one", expected="echo:one"),
        EnvTask(input="two", expected="echo:two"),
        EnvTask(input="three", expected="echo:three"),
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
        await arun_rollouts(env, k=1, tasks=[EnvTask(input="two")])


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
    # A uniform misconfiguration is not data about the agent: first `concurrency`
    # completions all errored with one exception type -> stop scheduling, drain, and
    # return the partial result.
    env = _stub_env(tasks=(EnvTask(input="one"), EnvTask(input="two")), error=RuntimeError("bad api key"))
    result = await arun_rollouts(env, k=4, concurrency=2)

    assert result.stopped_early == "error-storm"
    assert result.n_attempts == 2  # the unscheduled attempts are absent
    assert result.summary()["stopped_early"] == "error-storm"


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
        tasks=(EnvTask(input="one", expected="echo:one"), EnvTask(input="two", expected="echo:two")),
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
    env = _stub_env(tasks=(EnvTask(input="one", expected="echo:one"), EnvTask(input="two", expected="wrong")))
    result = await arun_rollouts(env, k=2, concurrency=2)
    path = tmp_path / "baseline.json"

    result.save(path)
    assert json.loads(path.read_text(encoding="utf-8"))["format_version"] == 1

    loaded = EnvRunResult.load(path)
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
        task_results.append(TaskResult(task=EnvTask(input=task_id, id=task_id), attempts=tuple(attempts)))
    return EnvRunResult(
        env_name="arithmetic",
        k=8,
        env_fingerprint=env_fingerprint,
        policy_fingerprint=policy_fingerprint,
        task_results=tuple(task_results),
        duration_seconds=1.0,
    )


def test_diff_refuses_mismatched_env():
    current = _result_with("aaa", "p1", {"t1": (8, 0)})
    with pytest.raises(EnvMismatchError, match="env_fingerprint"):
        current.diff(_result_with("bbb", "p1", {"t1": (8, 0)}))
    # None never matches -- a plain == would pass trivially when both are None.
    nameless = _result_with(None, "p1", {"t1": (8, 0)})
    with pytest.raises(EnvMismatchError):
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
