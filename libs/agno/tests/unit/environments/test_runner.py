"""Unit tests for run_rollouts / arun_rollouts, hermetic overrides, and results."""

import asyncio
import json
from uuid import uuid4

import pytest

from agno.agent import Agent
from agno.agent._utils import SHARED_BY_REFERENCE_FIELDS
from agno.db.in_memory import InMemoryDb
from agno.environments import Env, EnvRunResult, EnvTask, StopReason, TaskResult, arun_rollouts, run_rollouts
from agno.environments._engine import AttemptResult
from agno.environments.runner import _HERMETIC_FIELD_ACTIONS
from agno.models.base import Model
from agno.models.message import Message
from agno.models.openai import OpenAIChat
from agno.models.response import ModelResponse
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


class StubManager:
    """Attribute-bearing manager stand-in: the hermetic rebind copies managers and
    touches their db/model slots, so a plain object() cannot model one."""

    def __init__(self, db=None, model=None):
        self.db = db
        self.model = model


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


def _live_env(live_agent) -> Env:
    """An Env whose agent is a LIVE duck-typed stub, to drive the runner's deep_copy
    branch offline. Env's front door correctly rejects a non-Agent live value, so the
    stub is installed past validation -- the branch under test is the runner's, and a
    real Agent cannot run without a live model."""
    env = Env(
        name="live-env",
        tasks=(EnvTask(input="one", expected="echo:one"),),
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
    # read-only copy, memory nulled, secondary-model caches disabled on copies --
    # and the caller's instance untouched afterwards. The REAL-Agent twin below
    # covers the fields this stub cannot model.
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
        assert snapshot["memory_manager"] is None
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
    from agno.environments.env import _policy_fingerprint_of as policy_fingerprint_of

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


# ---------------------------------------------------------------------------
# Review fixes: factory lifecycle, culture/memory hermeticity, storm resilience
# ---------------------------------------------------------------------------


async def test_hermetic_factory_culture_rebound_and_memory_nulled():
    # The factory branch gets the same override set as the live branch: memory
    # nulled, culture rebound to a read-only copy so reads survive.
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
        assert snapshot["memory_manager"] is None
        assert snapshot["update_cultural_knowledge"] is False
        assert snapshot["enable_agentic_culture"] is False


async def test_factory_preflight_error_names_the_factory():
    # A factory broken at time zero raises at call time -- like the other preflight
    # rejections -- with a message naming where it happened, not a bare traceback.
    def broken():
        raise KeyError("no such config")

    env = Env(
        name="broken",
        tasks=(EnvTask(input="x"),),
        scorer=CodeScorer(echo_scorer),
        agent=broken,
    )
    with pytest.raises(RuntimeError, match="run-start construction"):
        await arun_rollouts(env, k=2)


async def test_factory_returning_non_agent_rejected_at_run_start():
    env = Env(
        name="bypass",
        tasks=(EnvTask(input="x"),),
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

    env = _stub_env(tasks=(EnvTask(input="one"), EnvTask(input="two")), error=RuntimeError("bad api key"))
    result = await arun_rollouts(env, k=4, concurrency=2)

    assert result.stopped_early == "error-storm"
    assert result.n_attempts == 2


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

    env = Env(
        name="storm",
        tasks=(EnvTask(input="one"), EnvTask(input="two")),
        scorer=CodeScorer(echo_scorer),
        agent=varying_error_factory,
    )
    result = await arun_rollouts(env, k=4, concurrency=2)
    assert result.stopped_early == "error-storm"


async def test_timeout_unscored_at_runner_level():
    # The runner threads Env.timeout_seconds into the engine: a timed-out attempt is
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

    task = EnvTask(input="x", expected=Weird(), id="t1")
    result = EnvRunResult(
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
    return Env(
        name="real-env",
        tasks=tasks if tasks is not None else (EnvTask(input="hello"),),
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
        tasks=(EnvTask(input="one"), EnvTask(input="two")),
    )
    result = await arun_rollouts(env, k=4, concurrency=2)

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
        assert attempt_agent.session_summary_manager is None
        assert attempt_agent.enable_session_summaries is False
        assert attempt_agent.memory_manager is None
        assert attempt_agent.add_memories_to_context is False
        assert attempt_agent.add_session_summary_to_context is False
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
    # Exactly one provider call per attempt on the main model, none anywhere else:
    # no summary call, no reasoning call, no memory call rode along.
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
    # are resolved IN PLACE on the caller's first run: without the override forcing
    # them off, an already-run caller handed its attempts a memory boilerplate
    # block that a never-run caller's attempts did not get -- two prompts for the
    # same Env and task.
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
    assert "retain memories" not in "\n".join(ran_prompts)


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

    env = Env(name="mcp-factory", tasks=(EnvTask(input="one"),), scorer=CodeScorer(lambda r, e: True), agent=factory)
    result = await arun_rollouts(env, k=1, concurrency=1)
    assert result.n_attempts == 1


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

    env = Env(
        name="mcp-nested-factory",
        tasks=(EnvTask(input="one"),),
        scorer=CodeScorer(lambda r, e: True),
        agent=factory,
    )
    result = await arun_rollouts(env, k=1, concurrency=1)
    assert result.n_attempts == 1


async def test_positional_task_id_collision_rejected_at_run_start():
    # An explicit "t2" colliding with the second task's auto-id only exists after
    # resolution; diff() keyed on the duplicate would pair rows with the wrong task.
    env = _stub_env(tasks=(EnvTask(input="a", id="t2"), EnvTask(input="b")))
    with pytest.raises(ValueError, match="duplicate resolved task id"):
        await arun_rollouts(env, k=1)


async def test_model_less_duck_subject_degrades_policy_fingerprint():
    # A duck-typed factory product with NO model attribute degrades the policy
    # fingerprint to None like a model-less Agent -- it must not crash preflight.
    class ModelLessDuck:
        async def arun(self, *, input, stream, stream_events, yield_run_output, session_id):
            yield _output(content=f"echo:{input}")

    env = Env(
        name="duck",
        tasks=(EnvTask(input="one"),),
        scorer=CodeScorer(lambda run, expected: True),
        agent=lambda: ModelLessDuck(),
    )
    result = await arun_rollouts(env, k=1, concurrency=1)
    assert result.policy_fingerprint is None
    assert result.pass_rate == 1.0


def test_every_shared_field_has_a_hermetic_action():
    # The drift alarm: a field added to deep_copy's shared-by-reference tuple
    # without a mapped hermetic action fails here before it ships.
    missing = set(SHARED_BY_REFERENCE_FIELDS) - set(_HERMETIC_FIELD_ACTIONS)
    assert not missing, f"unmapped shared-by-reference fields: {sorted(missing)}"


async def test_asave_aload_roundtrip(tmp_path):
    result = await arun_rollouts(_stub_env(), k=2, concurrency=2)
    target = tmp_path / "async-roundtrip.json"
    await result.asave(target)
    loaded = await EnvRunResult.aload(target)
    assert loaded.summary() == result.summary()
