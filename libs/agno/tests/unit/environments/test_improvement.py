"""The improvement loop, end to end and offline.

Everything here runs with no GPU, no network and no trainer SDK: a `StubTrainer`
hands back scripted models, and a `CodeScorer` over plain `Task`s decides pass/fail.
"""

import asyncio
import json

import pytest

from agno.agent import Agent
from agno.environments import Environment, ImprovementLoop, Task
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


def test_reward_hack_widening_gap_flags(tmp_path):
    # The signal is the TREND, computed here -- RewardHackReport has no verdict field
    # and no trend helper exists. A rising train rate against a stalling audit widens
    # the gap; a uniformly stricter audit holds it constant.
    def audit_demands_right(run, expected):
        return run.content == RIGHT

    # -- the hacking case: the train scorer accepts a shortcut the audit rejects.
    # Round 1 measures tuned-1 (train 3/6, audit 2/6, gap 0.167); round 2 measures
    # tuned-2, which answers shortcut everywhere (train 6/6, audit 2/6, gap 0.667).
    hacking_tasks = (
        Task(input="the sea", expected=RIGHT),
        Task(input="autumn", expected=RIGHT),
        Task(input="a train", expected=RIGHT),
    )
    hacking_base = ScriptedModel({"the sea": [RIGHT, WRONG], "autumn": WRONG, "a train": WRONG}, tag="hbase")
    hacking_tuned = [
        ScriptedModel({"the sea": RIGHT, "autumn": ["shortcut", WRONG], "a train": WRONG}, tag="hack-1"),
        ScriptedModel({"the sea": RIGHT, "autumn": "shortcut", "a train": "shortcut"}, tag="hack-2"),
    ]
    hacking_loop = ImprovementLoop(
        _env(
            hacking_base,
            tasks=hacking_tasks,
            scorer=CodeScorer(lambda run, expected: run.content in (RIGHT, "shortcut")),
        ),
        trainer=StubTrainer(hacking_base, hacking_tuned),
        k=2,
        audit_scorer=CodeScorer(audit_demands_right),
        workdir=tmp_path / "hacking",
    )
    hacking_gaps = [r.reward_hack.gap for r in hacking_loop.run(rounds=3) if r.reward_hack is not None]

    assert len(hacking_gaps) >= 2
    assert hacking_gaps[-1] > hacking_gaps[0]  # widening: the diagnostic signal

    # -- the honest case: an audit that is uniformly stricter. The model improves on
    # both scorers by the same amount each round, so the gap is an offset, not a trend.
    # "t-style" is always accepted by the train scorer and never by the audit, which is
    # what holds the offset constant while the real tasks improve.
    honest_tasks = (
        Task(input="style", expected=RIGHT),
        Task(input="the sea", expected=RIGHT),
        Task(input="autumn", expected=RIGHT),
        Task(input="a train", expected=RIGHT),
    )
    honest_base = ScriptedModel(
        {"style": "ok", "the sea": [RIGHT, WRONG], "autumn": WRONG, "a train": WRONG}, tag="obase"
    )
    honest_tuned = [
        ScriptedModel({"style": "ok", "the sea": RIGHT, "autumn": [RIGHT, WRONG], "a train": WRONG}, tag="honest-1"),
        ScriptedModel({"style": "ok", "the sea": RIGHT, "autumn": RIGHT, "a train": WRONG}, tag="honest-2"),
    ]
    honest_loop = ImprovementLoop(
        _env(
            honest_base,
            tasks=honest_tasks,
            scorer=CodeScorer(lambda run, expected: run.content in (RIGHT, "ok")),
        ),
        trainer=StubTrainer(honest_base, honest_tuned),
        k=2,
        audit_scorer=CodeScorer(audit_demands_right),
        workdir=tmp_path / "honest",
    )
    honest_gaps = [r.reward_hack.gap for r in honest_loop.run(rounds=3) if r.reward_hack is not None]

    assert len(honest_gaps) >= 2
    assert all(gap == pytest.approx(honest_gaps[0]) for gap in honest_gaps)
    assert honest_gaps[0] > 0  # stricter from round one -- an offset, not a trend


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
