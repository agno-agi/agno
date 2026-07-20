"""Measure the verifier before you trust what it verifies.

A rising pass rate only means something if the scorer is right about what passing is.
`calibrate` checks a scorer against human-labelled traces and reports where it
disagrees -- which is the difference between "my agent improved" and "my agent learned
what my scorer mistakes for improvement".

This is a harness over the shipped scorer surface, not a new engine: it calls
`scorer.ascore` exactly as a rollout would, and reports the disagreements.
"""

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from agno.environments.runner import EnvironmentRunResult
from agno.scorer import AnyRunOutput, Scorer
from agno.utils.log import log_warning

# (run, expected, gold_verdict) -- gold True means "this run should pass".
LabeledTrace = Tuple[AnyRunOutput, Any, bool]


@dataclass
class CalibrationReport:
    """How well a scorer agrees with the labels, and exactly where it does not.

    Every rate excludes traces the scorer raised on: a scorer that crashes is neither
    a false positive nor a false negative, and folding its failures into a rate would
    quietly make a broken scorer look merely inaccurate.
    """

    n_traces: int  # labelled traces submitted
    n_scored: int  # traces the scorer scored without error
    n_errors: int  # scorer exceptions -- excluded from every rate below
    agreement: Optional[float]  # matches / n_scored
    false_positive_rate: Optional[float]  # FP / gold-negatives (the scorer passed what should fail)
    false_negative_rate: Optional[float]  # FN / gold-positives (the scorer failed what should pass)
    disagreements: List[Dict[str, Any]] = field(default_factory=list)


def _require_triples(labeled_traces: Sequence[Any]) -> None:
    """`expected` is part of the unit, not an optional extra.

    `scorer.ascore(run, expected)` consults it, and a bare `RunOutput` does not carry
    the task's expected value -- it lives on `Task`. A 2-tuple would silently score
    every trace against `expected=None`, which under a None-tolerant scorer greens
    everything.
    """
    for index, trace in enumerate(labeled_traces):
        if not isinstance(trace, (tuple, list)) or len(trace) != 3:
            size = len(trace) if isinstance(trace, (tuple, list)) else "not a tuple"
            raise ValueError(
                f"labeled_traces[{index}] must be a 3-tuple (run, expected, gold), got {size}. "
                "The scorer needs the task's expected value; a bare (run, gold) pair would score "
                "every trace against expected=None."
            )


async def acalibrate(scorer: Scorer, labeled_traces: Sequence[LabeledTrace]) -> CalibrationReport:
    """Score every labelled trace and report agreement, FP/FN rates, and disagreements."""
    _require_triples(labeled_traces)

    n_errors = 0
    n_matches = 0
    gold_positives = 0
    gold_negatives = 0
    false_positives = 0
    false_negatives = 0
    disagreements: List[Dict[str, Any]] = []

    for index, (run, expected, gold) in enumerate(labeled_traces):
        try:
            score = await scorer.ascore(run, expected)
        except Exception as exc:
            n_errors += 1
            log_warning(f"calibrate: scorer raised on trace {index}: {type(exc).__name__}: {exc}")
            continue

        if gold:
            gold_positives += 1
        else:
            gold_negatives += 1

        if score.passed == gold:
            n_matches += 1
            continue

        if score.passed and not gold:
            false_positives += 1
        else:
            false_negatives += 1
        disagreements.append(
            {
                "index": index,
                "expected": expected,
                "gold": gold,
                "scorer_passed": score.passed,
                "scorer_reason": score.reason,
            }
        )

    n_scored = len(labeled_traces) - n_errors
    return CalibrationReport(
        n_traces=len(labeled_traces),
        n_scored=n_scored,
        n_errors=n_errors,
        agreement=(n_matches / n_scored) if n_scored else None,
        false_positive_rate=(false_positives / gold_negatives) if gold_negatives else None,
        false_negative_rate=(false_negatives / gold_positives) if gold_positives else None,
        disagreements=disagreements,
    )


def calibrate(scorer: Scorer, labeled_traces: Sequence[LabeledTrace]) -> CalibrationReport:
    """Sync door over `acalibrate`."""
    _refuse_running_loop("calibrate", "acalibrate")
    return asyncio.run(acalibrate(scorer, labeled_traces))


async def acalibrate_result(
    scorer: Scorer,
    result: EnvironmentRunResult,
    gold: Dict[Tuple[str, int], bool],
) -> CalibrationReport:
    """Calibrate against a rollout you already have.

    `gold` is keyed by `(task_id, attempt_index)`, with `attempt_index` 0-based to match
    the per-line provenance `to_sft_jsonl` writes into its `.meta.json` sidecar (the
    printed report numbers attempts from 1). Each labelled attempt is paired with its
    own task's `expected` automatically; attempts with no label are skipped, and so are
    labels naming an attempt that does not exist -- with a warning, since that is a
    labelling bug rather than a scorer result.
    """
    traces: List[LabeledTrace] = []
    task_ids: List[str] = []
    matched: set = set()

    for task_result in result.task_results:
        task_id = str(task_result.task.id)
        for attempt_index, attempt in enumerate(task_result.attempts):
            key = (task_id, attempt_index)
            if key not in gold:
                continue
            matched.add(key)
            if attempt.run is None:
                # Nothing was captured, so there is nothing for the scorer to read.
                log_warning(f"calibrate_result: {key} is labelled but captured no run; skipping")
                continue
            traces.append((attempt.run, task_result.task.expected, gold[key]))
            task_ids.append(task_id)

    unmatched = sorted(str(key) for key in gold if key not in matched)
    if unmatched:
        log_warning(f"calibrate_result: {len(unmatched)} gold label(s) matched no attempt: {', '.join(unmatched)}")

    report = await acalibrate(scorer, traces)
    # The convenience form knows which task each trace came from; the plain form does not.
    for disagreement in report.disagreements:
        disagreement["task_id"] = task_ids[disagreement["index"]]
    return report


def calibrate_result(
    scorer: Scorer,
    result: EnvironmentRunResult,
    gold: Dict[Tuple[str, int], bool],
) -> CalibrationReport:
    """Sync door over `acalibrate_result`."""
    _refuse_running_loop("calibrate_result", "acalibrate_result")
    return asyncio.run(acalibrate_result(scorer, result, gold))


def _refuse_running_loop(sync_name: str, async_name: str) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(f"{sync_name} cannot be called from a running event loop; await {async_name} instead")
