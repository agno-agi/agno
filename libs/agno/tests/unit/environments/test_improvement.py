"""The improvement loop, end to end and offline.

Everything here runs with no GPU, no network and no trainer SDK: a `StubTrainer`
hands back scripted models, and a `CodeScorer` over plain `Task`s decides pass/fail.
"""

import asyncio
import json

import pytest

from agno.agent import Agent
from agno.environments import Environment, ImprovementLoop, Task, run_rollouts
from agno.environments.improvement import RewardHackReport
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.scorer import CodeScorer, FingerprintError

from .stubs import ScriptedModel, StubTrainer

RIGHT = "right"
WRONG = "wrong"


def exact_match(run, expected):
    return run.content == expected


def _env(model=None, *, tasks=None, scorer=None, agent=None, name="haiku"):
    tasks = tasks or (
        Task(input="the sea", expected=RIGHT),
        Task(input="autumn", expected=RIGHT),
    )
    return Environment(
        name=name,
        agent=agent if agent is not None else Agent(model=model),
        tasks=tasks,
        scorer=scorer if scorer is not None else CodeScorer(exact_match),
    )


def _partial_base(tag="base"):
    """Passes every task exactly half the time.

    Within-task variance is the whole point: `learning_zone()` selects tasks with both
    a passing and a failing scored attempt, so a model that answers every attempt of a
    task identically produces an empty zone and trains nothing. At k=2 this alternating
    script gives each task exactly 1/2.
    """
    return ScriptedModel([RIGHT, WRONG], tag=tag)


def _loop(tmp_path, *, base=None, tuned=None, k=2, audit_scorer=None, env=None, trainer=None):
    base = base or _partial_base()
    tuned = tuned or [ScriptedModel(RIGHT, tag="tuned-1")]
    trainer = trainer or StubTrainer(base, tuned)
    return ImprovementLoop(
        env if env is not None else _env(base),
        trainer=trainer,
        k=k,
        audit_scorer=audit_scorer,
        workdir=tmp_path,
    )


# ---------------------------------------------------------------------------
# The release's reason to exist
# ---------------------------------------------------------------------------


def test_full_loop_closes_offline(tmp_path):
    # Six steps in one call: sample the base, export what passed, train on it, sample
    # the tuned checkpoint, re-measure, diff. Green with no network.
    loop = _loop(tmp_path)

    report = loop.step()

    assert report.round == 1
    assert report.converged is False
    assert report.baseline_pass_rate == 0.5
    assert report.tuned_pass_rate == 1.0
    assert report.tuned_pass_rate > report.baseline_pass_rate

    assert report.diff is not None
    assert report.diff.policy_changed is True
    # Task ids resolve positionally to t1..tN when undeclared.
    assert report.diff.improved == ("t1", "t2")
    assert all(row["delta"] > 0 for row in report.diff.rows)

    # Provenance is on the report, not reconstructed by the caller.
    assert report.checkpoint is not None
    assert report.dataset_path and report.dataset_digest
    assert report.train_result is not None and report.train_result.step_metrics
    assert report.export_report.n_written >= 1
    assert report.env_fingerprint and report.baseline_policy_fingerprint
    assert report.tuned_policy_fingerprint != report.baseline_policy_fingerprint


def test_improvement_loop_baseline_uses_base_model(tmp_path):
    # The baseline must be the model about to be trained. Sampling env.agent.model
    # instead would train one model and measure another -- an invalid before/after.
    base = _partial_base()
    env_model = ScriptedModel(RIGHT, tag="env-declared")  # would score 1.0 if used
    loop = _loop(tmp_path, base=base, env=_env(env_model))

    report = loop.step()

    assert report.baseline_pass_rate == 0.5  # the base's rate, not the env model's 1.0
    assert report.baseline_policy_fingerprint != _policy_fp_of(env_model)


def _policy_fp_of(model):
    from agno.environments.environment import _policy_fingerprint_of

    return _policy_fingerprint_of(model)


def test_improvement_loop_empty_export_short_circuits(tmp_path):
    # Nothing to train on is not a failure, but it must not fabricate tuned numbers.
    saturated_trainer = StubTrainer(ScriptedModel(RIGHT, tag="sat"), [ScriptedModel(RIGHT, tag="t1")])
    saturated = ImprovementLoop(_env(), trainer=saturated_trainer, k=2, workdir=tmp_path / "sat")
    report = saturated.step()

    assert report.converged is True
    assert report.converged_reason == "saturated"
    assert report.baseline_pass_rate == 1.0
    for empty in (
        report.tuned_pass_rate,
        report.tuned_policy_fingerprint,
        report.diff,
        report.checkpoint,
        report.train_result,
        report.reward_hack,
        report.dataset_path,
        report.dataset_digest,
    ):
        assert empty is None
    assert saturated_trainer.fit_calls == []  # never spent

    failing_trainer = StubTrainer(ScriptedModel(WRONG, tag="fail"), [ScriptedModel(RIGHT, tag="t1")])
    failing = ImprovementLoop(_env(), trainer=failing_trainer, k=2, workdir=tmp_path / "fail")
    failing_report = failing.step()

    assert failing_report.converged is True
    assert failing_report.converged_reason == "all_failing"
    assert failing_report.baseline_pass_rate == 0.0
    assert failing_report.tuned_pass_rate is None
    assert failing_trainer.fit_calls == []


def test_improvement_loop_refuses_degraded_fingerprint_before_fit(tmp_path):
    # A sourceless scorer degrades env_fingerprint to None, which makes the round
    # unmeasurable. Fail before the fine-tune, not after paying for one.
    sourceless = eval("lambda run, expected: run.content == expected")  # noqa: S307 -- no retrievable source
    trainer = StubTrainer(_partial_base(), [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(
        _env(scorer=CodeScorer(sourceless)),
        trainer=trainer,
        k=2,
        workdir=tmp_path,
    )

    with pytest.raises(FingerprintError) as excinfo:
        loop.step()

    assert "env_fingerprint is None" in str(excinfo.value)
    assert trainer.fit_calls == []  # the point: no spend


def test_loop_noops_on_tool_bearing_export(tmp_path, monkeypatch):
    # The 2.8.0 SFT format has no tool representation, so a run that RECORDS a tool
    # execution is not exportable: a tool-using agent trains on nothing, and the report
    # has to say that rather than look like a saturated environment.
    import agno.environments.improvement as improvement_module

    real_arun = improvement_module.arun_rollouts

    async def arun_with_tools(env_arg, **kwargs):
        result = await real_arun(env_arg, **kwargs)
        for task_result in result.task_results:
            for attempt in task_result.attempts:
                if isinstance(attempt.run, RunOutput):
                    # A recorded execution -- an emitted-but-unexecuted call would not
                    # trip the exporter's skip.
                    attempt.run.tools = [ToolExecution(tool_call_id="c1", tool_name="lookup")]
        return result

    monkeypatch.setattr(improvement_module, "arun_rollouts", arun_with_tools)

    base = _partial_base()
    trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    report = loop.step()

    assert report.converged is True
    assert report.converged_reason == "not_exportable"
    assert report.export_report.n_skipped_tool_runs >= 1
    assert report.tuned_pass_rate is None
    assert trainer.fit_calls == []  # never spent


def test_improvement_loop_cumulative_dataset_and_base_retrain(tmp_path):
    # The correctness core of multi-round training. `fit` retrains the pristine base
    # every round and the learning zone drops tasks the last round mastered, so
    # without cumulative data round 2 would forget round 1.
    # Round 1's zone is {the sea}; round 2's is {autumn}, because round 1 mastered
    # "the sea" and the zone drops it. Training round 2 on its own export alone would
    # forget it.
    base = ScriptedModel({"the sea": [RIGHT, WRONG], "autumn": WRONG, "a train": WRONG}, tag="base", default=WRONG)
    tuned_1 = ScriptedModel({"the sea": RIGHT, "autumn": [RIGHT, WRONG], "a train": WRONG}, tag="tuned-1")
    tuned_2 = ScriptedModel(RIGHT, tag="tuned-2")
    trainer = StubTrainer(base, [tuned_1, tuned_2])
    env = _env(
        base,
        tasks=(
            Task(input="the sea", expected=RIGHT),
            Task(input="autumn", expected=RIGHT),
            Task(input="a train", expected=RIGHT),
        ),
    )
    loop = ImprovementLoop(env, trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=2)

    assert len(reports) == 2
    assert len(trainer.fit_calls) == 2

    round_1_rows = _rows(trainer.fit_calls[0])
    round_2_rows = _rows(trainer.fit_calls[1])
    # Round 2 trains on round 1's rows as well as its own.
    for row in round_1_rows:
        assert row in round_2_rows
    assert len(round_2_rows) > len(round_1_rows)

    # Pristine base every round: the checkpoint's base_model never moves.
    assert reports[0].checkpoint is not None and reports[1].checkpoint is not None
    assert reports[1].checkpoint.base_model == reports[0].checkpoint.base_model

    # Round 2's baseline is round 1's tuned RESULT, reused rather than re-rolled.
    assert reports[1].baseline_pass_rate == reports[0].tuned_pass_rate
    assert reports[1].baseline_policy_fingerprint == reports[0].tuned_policy_fingerprint


def _rows(path):
    return [line for line in path.read_text(encoding="utf-8").split("\n") if line.strip()]


def test_improvement_loop_report_provenance_bytestable(tmp_path):
    # Two identical stub runs must serialize identically: a report carrying a timing,
    # a uuid or an object address is not provenance.
    def run_once(workdir):
        base = _partial_base()
        trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
        loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=workdir)
        return loop.step()

    shared = tmp_path / "shared"
    first = json.dumps(run_once(shared).to_dict(), sort_keys=True)
    second = json.dumps(run_once(shared).to_dict(), sort_keys=True)

    assert first == second

    payload = json.loads(first)
    assert payload["env_fingerprint"]
    assert payload["baseline_policy_fingerprint"]
    assert payload["dataset_digest"]
    assert payload["dataset_path"]
    assert payload["train_result"]["step_metrics"]
    assert payload["export_report"]["n_written"] >= 1


def test_improvement_loop_run_rounds_feeds_tuned_as_policy(tmp_path):
    # Round 2 samples round 1's tuned checkpoint. Once it saturates, the loop stops
    # instead of training on an empty export.
    base = _partial_base()
    tuned_1 = ScriptedModel(RIGHT, tag="tuned-1")  # saturates the env
    trainer = StubTrainer(base, [tuned_1, ScriptedModel(RIGHT, tag="tuned-2")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert len(reports) == 2  # stopped early: round 2 had nothing left to learn
    assert reports[0].tuned_pass_rate == 1.0
    assert reports[1].converged is True
    assert reports[1].converged_reason == "saturated"
    assert reports[1].baseline_policy_fingerprint == reports[0].tuned_policy_fingerprint
    assert len(trainer.fit_calls) == 1


def test_improvement_loop_warns_on_output_schema(tmp_path, monkeypatch):
    # Under an output_schema the exported target is raw JSON text, which is almost
    # never what you meant to fine-tune on.
    from pydantic import BaseModel

    import agno.environments.improvement as improvement_module

    class Answer(BaseModel):
        value: str

    warnings: list = []
    monkeypatch.setattr(improvement_module, "log_warning", warnings.append)

    base = _partial_base()
    agent = Agent(model=base, output_schema=Answer)
    trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(agent=agent), trainer=trainer, k=1, workdir=tmp_path)

    loop.step()

    assert any("output_schema" in str(message) for message in warnings)


def test_iteration_report_carries_audit_digest(tmp_path):
    # The audit verdict is attributable to a specific verifier, or it is not a verdict.
    audit = CodeScorer(exact_match)
    loop = _loop(tmp_path, audit_scorer=audit)

    report = loop.step()

    assert report.audit_scorer_digest == audit.digest()
    assert isinstance(report.reward_hack, RewardHackReport)
    assert report.reward_hack.train_pass_rate == report.tuned_pass_rate
    assert report.reward_hack.audit_pass_rate is not None
    assert report.reward_hack.gap is not None

    # A sourceless audit scorer degrades the digest with a warning; nothing raises,
    # because no comparison API exists -- consumers compare digests themselves.
    sourceless = CodeScorer(eval("lambda run, expected: True"))  # noqa: S307
    degraded = _loop(tmp_path / "degraded", audit_scorer=sourceless)
    degraded_report = degraded.step()
    assert degraded_report.audit_scorer_digest is None
    assert degraded_report.reward_hack is not None


# ---------------------------------------------------------------------------
# Async twins
# ---------------------------------------------------------------------------


def test_astep_matches_step(tmp_path):
    def sync_report():
        base = _partial_base()
        trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
        return ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path / "twin").step()

    async def async_report():
        base = _partial_base()
        trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
        loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path / "twin")
        return await loop.astep()

    assert json.dumps(sync_report().to_dict(), sort_keys=True) == json.dumps(
        asyncio.run(async_report()).to_dict(), sort_keys=True
    )


def test_arun_matches_run(tmp_path):
    def build(workdir):
        base = ScriptedModel({"the sea": RIGHT, "autumn": WRONG, "a train": WRONG}, tag="base", default=WRONG)
        tuned = [
            ScriptedModel({"the sea": RIGHT, "autumn": RIGHT, "a train": WRONG}, tag="tuned-1", default=WRONG),
            ScriptedModel(RIGHT, tag="tuned-2"),
        ]
        env = _env(
            base,
            tasks=(
                Task(input="the sea", expected=RIGHT),
                Task(input="autumn", expected=RIGHT),
                Task(input="a train", expected=RIGHT),
            ),
        )
        return ImprovementLoop(env, trainer=StubTrainer(base, tuned), k=2, workdir=workdir)

    sync_reports = build(tmp_path / "rt").run(rounds=2)
    async_reports = asyncio.run(build(tmp_path / "rt").arun(rounds=2))

    assert [json.dumps(r.to_dict(), sort_keys=True) for r in sync_reports] == [
        json.dumps(r.to_dict(), sort_keys=True) for r in async_reports
    ]


def test_sync_doors_refuse_running_loop(tmp_path):
    # The guard names the method the caller actually called.
    async def call_sync():
        loop = _loop(tmp_path / "guard")
        with pytest.raises(RuntimeError) as excinfo:
            loop.step()
        assert "loop.astep()" in str(excinfo.value)
        with pytest.raises(RuntimeError) as run_exc:
            loop.run(rounds=1)
        assert "loop.arun()" in str(run_exc.value)

    asyncio.run(call_sync())


def test_failed_fit_stops_run_with_no_tuned_numbers(tmp_path):
    base = _partial_base()
    trainer = StubTrainer(
        base,
        [ScriptedModel(RIGHT, tag="tuned-1")],
        fail_on_round=1,
        recoverable=False,
    )
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert len(reports) == 1
    assert reports[0].train_result is not None
    assert reports[0].checkpoint is None
    assert reports[0].tuned_pass_rate is None
    assert reports[0].converged is False  # a failed fit is not convergence


def test_failed_fit_does_not_retain_rows_for_the_next_step(tmp_path):
    # A failed fit leaves no tuned policy, so a second bare step() re-rolls the same
    # base and re-exports the same learning zone. Keeping the first round's rows would
    # train the next attempt on exact duplicates.
    base = _partial_base()
    trainer = StubTrainer(
        base,
        [ScriptedModel(RIGHT, tag="tuned-1")],
        fail_on_round=1,
        recoverable=False,
    )
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    loop.step()
    loop.step()

    first_rows = _rows(trainer.fit_calls[0])
    second_rows = _rows(trainer.fit_calls[1])
    assert len(second_rows) == len(first_rows)
    assert len(second_rows) == len(set(second_rows))  # no duplicated conversations


def test_improvement_loop_warns_on_output_schema_from_factory(tmp_path, monkeypatch):
    # The factory form is the recommended isolation shape; it must not be the one
    # shape that silently skips the scope warning.
    from pydantic import BaseModel

    import agno.environments.improvement as improvement_module

    class Answer(BaseModel):
        value: str

    warnings: list = []
    monkeypatch.setattr(improvement_module, "log_warning", warnings.append)

    base = _partial_base()
    trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(
        _env(agent=lambda: Agent(model=base, output_schema=Answer)),
        trainer=trainer,
        k=1,
        workdir=tmp_path,
    )

    loop.step()

    assert any("output_schema" in str(message) for message in warnings)


def test_improvement_loop_refuses_none_policy_fingerprint(tmp_path):
    # The other half of the pre-flight: without a policy fingerprint, baseline and
    # tuned cannot be told apart, so `diff.policy_changed` comes back True for free
    # and the round is unmeasurable before it is paid for.
    #
    # Driven through _preflight directly rather than through a rollout: a real run
    # resolves a default model when the agent declares none, so the degraded-policy
    # case is not reachable from ordinary wiring. The guard is what is pinned here.
    from dataclasses import replace as dataclass_replace

    base = _partial_base()
    trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    measured = run_rollouts(_env(base), k=2)
    degraded = dataclass_replace(measured, policy_fingerprint=None)

    with pytest.raises(FingerprintError) as excinfo:
        loop._preflight(degraded, 1)

    assert "policy_fingerprint is None" in str(excinfo.value)
    assert trainer.fit_calls == []


def test_partial_fit_is_measured(tmp_path):
    # PARTIAL carries a paid recovery checkpoint: measure what was paid for.
    base = _partial_base()
    trainer = StubTrainer(
        base,
        [ScriptedModel(RIGHT, tag="tuned-1")],
        fail_on_round=1,
        recoverable=True,
    )
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    report = loop.step()

    assert report.checkpoint is not None
    assert "recovery" in report.checkpoint.ref
    assert report.tuned_pass_rate == 1.0
    assert report.diff is not None
