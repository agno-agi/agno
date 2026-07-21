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


def test_converged_reason_counters_decide_the_label():
    # "no_learning_zone" must mean the zone was EMPTY. A zone row that existed but
    # could not be carried -- skipped as tool-bearing/limit-hit/textless, or dropped
    # over the dataset caps -- is "not_exportable"; only all-zero counters at an
    # intermediate rate mean there was nothing to express in the first place.
    from agno.environments.exporters import ExportReport
    from agno.environments.improvement import _converged_reason_for

    assert _converged_reason_for(1.0, ExportReport()) == "saturated"
    assert _converged_reason_for(0.0, ExportReport()) == "all_failing"
    assert _converged_reason_for(0.5, ExportReport()) == "no_learning_zone"
    assert _converged_reason_for(0.5, ExportReport(n_skipped_tool_runs=1)) == "not_exportable"
    assert _converged_reason_for(0.5, ExportReport(n_skipped_limit_hit=1)) == "not_exportable"
    assert _converged_reason_for(0.5, ExportReport(n_skipped_no_text=1)) == "not_exportable"
    assert _converged_reason_for(0.5, ExportReport(n_dropped_over_cap=1)) == "not_exportable"


def test_empty_zone_at_intermediate_rate_converges_as_no_learning_zone(tmp_path):
    # One task always passes and one always fails: pass rate 0.5, but every task is
    # unanimous, so the learning zone -- and therefore the export -- is empty with
    # every skip counter at zero. Nothing was inexpressible ("not_exportable" would
    # blame the SFT format); there was simply nothing to express.
    base = ScriptedModel({"the sea": RIGHT, "autumn": WRONG}, tag="unanimous", default=WRONG)
    trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    report = loop.step()

    assert report.converged is True
    assert report.baseline_pass_rate == 0.5
    assert report.converged_reason == "no_learning_zone"
    assert report.export_report.n_written == 0
    assert report.export_report.n_skipped_tool_runs == 0
    assert report.export_report.n_skipped_limit_hit == 0
    assert report.export_report.n_skipped_no_text == 0
    assert trainer.fit_calls == []  # never spent


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


class _ErroringModel(ScriptedModel):
    """Every attempt errors: a rollout through this model scores nothing."""

    def _respond(self, args, kwargs):
        raise RuntimeError("serving outage")

    async def ainvoke_stream(self, *args, **kwargs):
        raise RuntimeError("serving outage")
        yield  # pragma: no cover -- makes this an async generator


def test_unmeasured_round_is_terminal_for_run(tmp_path):
    # A paid checkpoint whose measurement failed must stop run(): the tuned policy
    # never became the next baseline, so a second round would re-fit the pristine
    # base -- paying for the same fine-tune again -- while the outage persists.
    class ServingDownTrainer(StubTrainer):
        async def aas_model(self, checkpoint):
            raise RuntimeError("sampler auth is down")

    base = _partial_base()
    trainer = ServingDownTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert len(trainer.fit_calls) == 1  # exactly one paid fit, then stop
    assert len(reports) == 1
    report = reports[0]
    assert report.checkpoint is not None  # the paid artifact is preserved
    assert report.tuned_pass_rate is None
    assert report.diff is None
    assert report.converged is False  # training happened; this is not convergence
    assert report.unmeasured_reason == "measurement_failed"


def test_unscored_tuned_rollout_is_not_presented_as_measured(tmp_path):
    # A tuned rollout with zero scored attempts is an outage, not a measurement.
    # It must not carry a diff, must not become the next round's baseline, and must
    # stop run() like any other paid-but-unmeasured round.
    base = _partial_base()
    trainer = StubTrainer(base, [_ErroringModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert len(trainer.fit_calls) == 1
    assert len(reports) == 1
    report = reports[0]
    assert report.checkpoint is not None
    assert report.tuned_pass_rate is None
    assert report.diff is None
    assert report.tuned_policy_fingerprint is None
    assert report.unmeasured_reason == "tuned_unscored"
    assert loop._last_tuned_result is None  # the outage never becomes a baseline


def test_prompt_bearing_tuned_model_is_unmeasured(tmp_path):
    # A trainer that bakes a serving prompt into the tuned model would move the ENV
    # fingerprint and make diff() raise after a paid rollout. The loop refuses before
    # that rollout, reports the checkpoint as unmeasured, and run() stops.
    class PromptBakingTrainer(StubTrainer):
        def as_model(self, checkpoint):
            model = super().as_model(checkpoint)
            model.system_prompt = "always answer in haiku"
            return model

    base = _partial_base()
    trainer = PromptBakingTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert len(trainer.fit_calls) == 1
    assert len(reports) == 1
    assert reports[0].checkpoint is not None
    assert reports[0].tuned_pass_rate is None
    assert reports[0].unmeasured_reason == "serving_prompt_mismatch"


def test_round_one_total_failure_raises_instead_of_empty_list(tmp_path):
    # Before any round has been paid for there is no record to protect: an empty
    # list would read as "ran zero rounds cleanly" when the first round blew up.
    class DeadTrainer(StubTrainer):
        async def abase_as_model(self):
            raise RuntimeError("no baseline model")

    base = _partial_base()
    trainer = DeadTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    with pytest.raises(RuntimeError, match="no baseline model"):
        loop.run(rounds=2)

    assert trainer.fit_calls == []


def test_later_round_failure_still_returns_completed_rounds(tmp_path, monkeypatch):
    # The counterpart: once round 1 is paid for, a round-2 explosion must not raise
    # away its record -- run() returns the completed rounds and logs the failure.
    import agno.environments.improvement as improvement_module

    real_export = improvement_module.ato_sft_jsonl
    calls = {"n": 0}

    async def export_fails_second_time(result, path):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("disk gone")
        return await real_export(result, path)

    monkeypatch.setattr(improvement_module, "ato_sft_jsonl", export_fails_second_time)

    base = ScriptedModel({"the sea": [RIGHT, WRONG], "autumn": WRONG}, tag="base", default=WRONG)
    tuned_1 = ScriptedModel({"the sea": RIGHT, "autumn": [RIGHT, WRONG]}, tag="tuned-1", default=WRONG)
    trainer = StubTrainer(base, [tuned_1, ScriptedModel(RIGHT, tag="tuned-2")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert len(reports) == 1  # round 1's record survives round 2's failure
    assert reports[0].checkpoint is not None
    assert len(trainer.fit_calls) == 1


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


# ---------------------------------------------------------------------------
# Coverage, single-flight, audit bounding, provenance, drift
# ---------------------------------------------------------------------------


def test_coverage_collapse_is_not_an_improvement(tmp_path, monkeypatch):
    # pass_rate = n_passed / n_scored excludes unscored attempts, so a tuned rollout
    # of 1 pass + 3 truncated is 1/1 = 1.0 -- and SFT can genuinely regress a model
    # into over-generating until it truncates. That round must not diff "improved",
    # must not audit a clean gap over the survivors, and must not become the baseline
    # a follow-up round calls "saturated".
    import agno.environments.improvement as improvement_module
    from agno.environments._engine import StopReason

    real_arun = improvement_module.arun_rollouts
    calls = {"n": 0}

    async def truncating_tuned_rollout(env_arg, **kwargs):
        calls["n"] += 1
        result = await real_arun(env_arg, **kwargs)
        if calls["n"] == 1:
            return result  # the baseline: 2/4 scored-and-split, coverage 1.0
        kept_one_pass = False
        for task_result in result.task_results:
            for attempt in task_result.attempts:
                if not kept_one_pass and attempt.score is not None and attempt.score.passed:
                    kept_one_pass = True
                    continue
                attempt.score = None
                attempt.stop_reason = StopReason.truncated
        return result

    monkeypatch.setattr(improvement_module, "arun_rollouts", truncating_tuned_rollout)

    base = _partial_base()
    trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, audit_scorer=CodeScorer(exact_match), workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert len(reports) == 1  # terminal: there is no "saturated" round 2
    assert len(trainer.fit_calls) == 1
    report = reports[0]
    assert report.unmeasured_reason == "coverage_regressed"
    assert report.converged is False
    assert report.tuned_pass_rate is None  # 1/1 over survivors is not presented as measured
    assert report.diff is None
    assert report.reward_hack is None  # a survivors-only audit would print a clean gap
    assert report.checkpoint is not None  # the paid artifact is preserved
    assert report.baseline_coverage == 1.0
    assert report.tuned_coverage == 0.25
    assert report.tuned_unscored_breakdown == {"truncated": 3}
    assert loop._last_tuned_result is None  # never becomes the next baseline


async def test_concurrent_astep_is_rejected_single_flight(tmp_path):
    # Two concurrent rounds on one loop would each advance _round and pay for a fit,
    # with last-writer-wins on the baseline. The second entry is REJECTED, not queued:
    # a queued round would still double-fit against a stale baseline.
    base = _partial_base()
    trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    results = await asyncio.gather(loop.astep(), loop.astep(), return_exceptions=True)

    reports = [r for r in results if not isinstance(r, BaseException)]
    rejections = [r for r in results if isinstance(r, RuntimeError)]
    assert len(reports) == 1 and len(rejections) == 1
    assert "already running" in str(rejections[0])
    assert len(trainer.fit_calls) == 1  # exactly one paid fit
    assert loop._round == 1
    assert not loop._step_guard.locked()  # released for the next sequential round


def test_audit_failure_does_not_lose_the_measured_round(tmp_path, monkeypatch):
    # The audit runs AFTER measurement succeeded: an audit-level failure must not take
    # the measured round -- and its paid checkpoint -- down with it.
    async def audit_explodes(self, tuned, round_number):
        raise RuntimeError("judge model is down")

    monkeypatch.setattr(ImprovementLoop, "_audit", audit_explodes)

    loop = _loop(tmp_path, audit_scorer=CodeScorer(exact_match))
    report = loop.step()

    assert report.checkpoint is not None
    assert report.tuned_pass_rate == 1.0  # the measured numbers stand
    assert report.reward_hack is not None
    assert report.reward_hack.audit_pass_rate is None  # no fabricated clean gap
    assert report.reward_hack.gap is None


def test_audit_hang_is_bounded(tmp_path, monkeypatch):
    # A hung judge model must not hold the round's record hostage: the audit is
    # bounded by a timeout and degrades to the same no-audit-rate shape as a failure.
    import time

    import agno.environments.improvement as improvement_module

    async def audit_hangs(self, tuned, round_number):
        await asyncio.sleep(8)
        return RewardHackReport(round=round_number, train_pass_rate=1.0, audit_pass_rate=1.0, gap=0.0)

    monkeypatch.setattr(ImprovementLoop, "_audit", audit_hangs)
    monkeypatch.setattr(improvement_module, "_AUDIT_TIMEOUT_SECONDS", 0.05, raising=False)

    loop = _loop(tmp_path, audit_scorer=CodeScorer(exact_match))
    start = time.monotonic()
    report = loop.step()

    assert time.monotonic() - start < 5  # bounded
    assert report.checkpoint is not None
    assert report.tuned_pass_rate == 1.0
    assert report.reward_hack is not None
    assert report.reward_hack.audit_pass_rate is None


async def test_cancellation_during_measurement_preserves_the_checkpoint(tmp_path):
    # CancelledError is BaseException: pre-fix it sailed past `except Exception` and
    # the paid checkpoint vanished with the coroutine -- a retry would re-fit. The
    # cancellation still propagates; the unreturnable report is recorded on the loop.
    class HangingServeTrainer(StubTrainer):
        async def aas_model(self, checkpoint):
            await asyncio.Event().wait()  # a serve that never completes

    base = _partial_base()
    trainer = HangingServeTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    task = asyncio.ensure_future(loop.astep())
    while not trainer.fit_calls:  # wait until the fit has been paid for
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)  # let astep reach the hanging serve
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    recorded = loop.last_unmeasured_report
    assert recorded is not None
    assert recorded.checkpoint is not None
    assert recorded.unmeasured_reason == "measurement_cancelled"
    assert not loop._step_guard.locked()


def test_env_drift_between_rounds_refuses_before_fitting(tmp_path):
    # A reused baseline was measured in a PAST round. Mutating the env between rounds
    # was only caught by diff() -- after this round's fit and tuned rollout were paid
    # for. The pre-flight now re-fingerprints the environment and refuses first.
    base = ScriptedModel({"the sea": [RIGHT, WRONG], "autumn": WRONG}, tag="base", default=WRONG)
    tuned_1 = ScriptedModel({"the sea": RIGHT, "autumn": [RIGHT, WRONG]}, tag="tuned-1", default=WRONG)
    trainer = StubTrainer(base, [tuned_1, ScriptedModel(RIGHT, tag="tuned-2")])
    env = _env(base)
    loop = ImprovementLoop(env, trainer=trainer, k=2, workdir=tmp_path)

    first = loop.step()
    assert first.checkpoint is not None and first.tuned_pass_rate is not None

    env.agent.instructions = "answer in exactly three words"  # drift after round 1

    with pytest.raises(FingerprintError, match="drifted"):
        loop.step()

    assert len(trainer.fit_calls) == 1  # the drifted round never paid for a fit


def test_wrong_provenance_checkpoint_is_never_served(tmp_path):
    # A trainer whose checkpoint claims a different dataset_digest than the file the
    # loop trained on would be served and measured normally, while the report carries
    # provenance the trainer contradicts. It is preserved but never served.
    from agno.trainers.base import Checkpoint, TrainOn, TrainResult

    class WrongDigestTrainer(StubTrainer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.served = []

        def fit(self, dataset, *, train_on=TrainOn.LAST_ASSISTANT):
            result = super().fit(dataset, train_on=train_on)
            forged = Checkpoint(
                ref=result.checkpoint.ref,
                base_model=result.checkpoint.base_model,
                dataset_digest="0" * 64,
                hyperparams=result.checkpoint.hyperparams,
            )
            return TrainResult(checkpoint=forged, step_metrics=result.step_metrics, status=result.status)

        async def aas_model(self, checkpoint):
            self.served.append(checkpoint)
            return await super().aas_model(checkpoint)

    base = _partial_base()
    trainer = WrongDigestTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert trainer.served == []  # never served
    assert len(reports) == 1
    report = reports[0]
    assert report.unmeasured_reason == "checkpoint_provenance_mismatch"
    assert report.checkpoint is not None  # preserved for the caller to inspect
    assert report.tuned_pass_rate is None


def test_audit_digest_never_degrades_to_the_string_none(tmp_path):
    # str(digest()) would turn a None digest into the STRING "None" -- one shared
    # false identity across every sourceless audit scorer.
    from agno.scorer import Score

    class DigestlessAuditScorer:
        async def ascore(self, run, expected):
            return Score(value=1.0, passed=True)

        def digest(self):
            return None

    loop = _loop(tmp_path, audit_scorer=DigestlessAuditScorer())
    report = loop.step()

    assert report.audit_scorer_digest is None
    assert report.reward_hack is not None


def test_round_one_baseline_outage_is_unmeasured_not_converged(tmp_path):
    # The identical event on the tuned side reports unmeasured; pre-fix the baseline
    # side reported converged=True, so automation keying on `converged` read a
    # transient scorer/serving outage as a finished run. run() still stops --
    # repeating would re-pay a rollout to measure nothing.
    base = _ErroringModel(RIGHT, tag="outage-base")
    trainer = StubTrainer(base, [ScriptedModel(RIGHT, tag="tuned-1")])
    loop = ImprovementLoop(_env(base), trainer=trainer, k=2, workdir=tmp_path)

    reports = loop.run(rounds=3)

    assert len(reports) == 1
    report = reports[0]
    assert report.converged is False
    assert report.converged_reason is None
    assert report.unmeasured_reason == "baseline_unscored"
    assert report.baseline_pass_rate is None
    assert report.checkpoint is None
    assert trainer.fit_calls == []
