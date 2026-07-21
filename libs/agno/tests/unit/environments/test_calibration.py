"""Reward quality: calibrate a scorer against labels, and read the audit gap."""

import asyncio

import pytest

from agno.agent import Agent
from agno.environments import (
    CalibrationReport,
    Environment,
    ImprovementLoop,
    Task,
    acalibrate,
    calibrate,
    calibrate_result,
    run_rollouts,
)
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.scorer import CodeScorer, Score

from .stubs import ScriptedModel, StubTrainer

RIGHT = "right"
WRONG = "wrong"


def exact_match(run, expected):
    return run.content == expected


def _run(content):
    return RunOutput(content=content, status=RunStatus.completed)


# ---------------------------------------------------------------------------
# Static calibration
# ---------------------------------------------------------------------------


def test_calibrate_fp_fn_agreement():
    # Six labelled traces with known disagreements, reproducing the exact denominators:
    # agreement = matches / n_scored, FPR = FP / gold-negatives, FNR = FN / gold-positives.
    traces = [
        (_run(RIGHT), RIGHT, True),  # scorer passes, gold pass  -> match
        (_run(RIGHT), RIGHT, True),  # match
        (_run(WRONG), RIGHT, False),  # scorer fails, gold fail   -> match
        (_run(WRONG), RIGHT, True),  # scorer fails, gold PASS   -> false negative
        (_run(RIGHT), RIGHT, False),  # scorer passes, gold FAIL  -> false positive
        (_run(RIGHT), RIGHT, False),  # false positive
    ]

    report = calibrate(CodeScorer(exact_match), traces)

    assert isinstance(report, CalibrationReport)
    assert report.n_traces == 6
    assert report.n_scored == 6
    assert report.n_errors == 0
    # 3 gold-positives (2 matched, 1 FN), 3 gold-negatives (1 matched, 2 FP).
    assert report.agreement == 3 / 6
    assert report.false_positive_rate == 2 / 3
    assert report.false_negative_rate == 1 / 3

    assert len(report.disagreements) == 3
    first = report.disagreements[0]
    assert set(first) == {"index", "expected", "gold", "scorer_passed", "scorer_reason"}
    assert first["index"] == 3
    assert first["gold"] is True
    assert first["scorer_passed"] is False


def test_calibrate_rates_are_none_without_that_gold_class():
    all_positive = calibrate(CodeScorer(exact_match), [(_run(RIGHT), RIGHT, True)])
    assert all_positive.false_positive_rate is None  # no gold-negatives to divide by
    assert all_positive.false_negative_rate == 0.0
    assert all_positive.agreement == 1.0


def test_calibrate_needs_expected():
    # A 2-tuple would score every trace against expected=None, which under a
    # None-tolerant scorer greens everything.
    with pytest.raises(ValueError) as excinfo:
        calibrate(CodeScorer(exact_match), [(_run(RIGHT), True)])

    message = str(excinfo.value)
    assert "3-tuple" in message
    assert "expected" in message


def test_calibrate_scorer_errors_excluded_from_every_rate():
    def explodes_on_wrong(run, expected):
        if run.content == WRONG:
            raise RuntimeError("scorer blew up")
        return run.content == expected

    traces = [
        (_run(RIGHT), RIGHT, True),
        (_run(WRONG), RIGHT, False),  # scorer raises
        (_run(RIGHT), RIGHT, False),  # false positive
    ]

    report = calibrate(CodeScorer(explodes_on_wrong), traces)

    assert report.n_traces == 3
    assert report.n_errors == 1
    assert report.n_scored == 2
    assert report.agreement == 1 / 2
    # The errored trace was a gold-negative but is excluded from the denominator.
    assert report.false_positive_rate == 1 / 1


def _labeled_env_result():
    model = ScriptedModel({"the sea": [RIGHT, WRONG], "autumn": [RIGHT, WRONG]}, tag="cal")
    env = Environment(
        name="cal",
        agent=Agent(model=model),
        tasks=(Task(input="the sea", expected=RIGHT), Task(input="autumn", expected=RIGHT)),
        scorer=CodeScorer(exact_match),
    )
    return run_rollouts(env, k=2)


def test_calibrate_result_pairs_expected():
    # The convenience form pairs each labelled attempt's run with its own task's
    # expected, and skips attempts nobody labelled.
    result = _labeled_env_result()
    passing = {}
    for task_result in result.task_results:
        for index, attempt in enumerate(task_result.attempts):
            passing[(str(task_result.task.id), index)] = bool(attempt.score and attempt.score.passed)

    # Label only two of the four attempts, one of each verdict.
    labelled_pass = next(key for key, was_pass in passing.items() if was_pass)
    labelled_fail = next(key for key, was_pass in passing.items() if not was_pass)
    gold = {labelled_pass: True, labelled_fail: False}

    report = calibrate_result(CodeScorer(exact_match), result, gold)

    assert report.n_traces == 2  # unlabelled attempts skipped
    assert report.n_scored == 2
    assert report.agreement == 1.0
    assert report.disagreements == []

    # Disagreements in the convenience form carry the task they came from.
    disagreeing = calibrate_result(
        CodeScorer(lambda run, expected: False),
        result,
        {labelled_pass: True},
    )
    assert len(disagreeing.disagreements) == 1
    assert disagreeing.disagreements[0]["task_id"] == labelled_pass[0]

    # A label naming an attempt that does not exist matches nothing rather than
    # silently shifting the labels.
    stray = calibrate_result(CodeScorer(exact_match), result, {("nope", 0): True})
    assert stray.n_traces == 0
    assert stray.agreement is None


def test_calibrate_rejects_non_bool_gold_labels():
    # "False" is a truthy string: silently coerced, it would count as gold-pass and
    # corrupt every rate. Both doors validate, since acalibrate_result builds its
    # traces from the same labels.
    with pytest.raises(ValueError, match="gold label must be a bool"):
        calibrate(CodeScorer(exact_match), [(_run(RIGHT), RIGHT, "False")])
    with pytest.raises(ValueError, match="gold label must be a bool"):
        calibrate(CodeScorer(exact_match), [(_run(RIGHT), RIGHT, 1)])


def test_calibrate_result_rejects_inexact_gold_keys():
    # bool is an int subclass: ("t1", True) hashes and compares equal to ("t1", 1), so
    # a bool index would silently label attempt 1 instead of failing to match.
    result = _labeled_env_result()

    with pytest.raises(ValueError, match="attempt_index must be an int"):
        calibrate_result(CodeScorer(exact_match), result, {("t1", True): True})
    with pytest.raises(ValueError, match="2-tuple"):
        calibrate_result(CodeScorer(exact_match), result, {"t1": True})
    # A bool LABEL arriving through the result door is caught too.
    with pytest.raises(ValueError, match="gold label must be a bool"):
        calibrate_result(CodeScorer(exact_match), result, {("t1", 0): "False"})


def test_acalibrate_matches_calibrate():
    traces = [
        (_run(RIGHT), RIGHT, True),
        (_run(WRONG), RIGHT, True),
        (_run(RIGHT), RIGHT, False),
    ]
    scorer = CodeScorer(exact_match)

    sync_report = calibrate(scorer, traces)
    async_report = asyncio.run(acalibrate(scorer, traces))

    assert sync_report == async_report


def test_calibrate_sync_door_refuses_running_loop():
    async def call_sync():
        with pytest.raises(RuntimeError) as excinfo:
            calibrate(CodeScorer(exact_match), [(_run(RIGHT), RIGHT, True)])
        assert "acalibrate" in str(excinfo.value)

    asyncio.run(call_sync())


def test_calibrate_accepts_score_returning_scorer():
    # A scorer returning a Score with a reason surfaces that reason on disagreement.
    scorer = CodeScorer(lambda run, expected: Score(value=1.0, passed=True, reason="looks fine to me"))
    report = calibrate(scorer, [(_run(WRONG), RIGHT, False)])
    assert report.disagreements[0]["scorer_reason"] == "looks fine to me"


# ---------------------------------------------------------------------------
# The reward-hacking audit
# ---------------------------------------------------------------------------


def _env(model, *, tasks, scorer):
    return Environment(name="hack", agent=Agent(model=model), tasks=tasks, scorer=scorer)


def test_reward_hack_widening_gap_flags(tmp_path):
    # The signal is the TREND, computed here -- RewardHackReport has no verdict field
    # and no trend helper exists, by design. The audit re-scores the tuned MEASUREMENT
    # rollout, never the exported rows: those all passed the train scorer by
    # construction, which would pin train_pass_rate at 1.0 and destroy the signal.
    def audit_demands_right(run, expected):
        return run.content == RIGHT

    # -- hacking: the train scorer accepts a shortcut the audit rejects. Round 1
    # measures tuned-1 (train 3/6, audit 2/6); round 2 measures tuned-2, which answers
    # shortcut nearly everywhere (train 6/6, audit 2/6). The gap widens.
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
    hacking_reports = hacking_loop.run(rounds=3)
    hacking_gaps = [r.reward_hack.gap for r in hacking_reports if r.reward_hack is not None]

    assert len(hacking_gaps) >= 2
    assert hacking_gaps[-1] > hacking_gaps[0]  # widening: the diagnostic signal

    # The audit read the measurement rollout, not the export: a train rate pinned at
    # 1.0 in every round would mean it had been handed the exported rows.
    assert hacking_reports[0].reward_hack.train_pass_rate < 1.0

    # -- honest: an audit that is uniformly stricter. "style" is always accepted by the
    # train scorer and never by the audit, so the model improving on the real tasks
    # moves both rates by the same amount and the gap stays put.
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
