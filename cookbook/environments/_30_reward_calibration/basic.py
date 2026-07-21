"""
Reward Calibration - Basic
==========================

Check the verifier before you trust what it verified. A pass rate is only as
good as the scorer producing it, so this measures the scorer itself against
hand-labelled traces: how often it agrees, and which way it is wrong.

Fully offline and deterministic. The traces are constructed directly; no model
is called.
"""

from agno.environments import calibrate
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.scorer import CodeScorer


def mentions_the_number(run, expected):
    """A tempting shortcut of a scorer: does the answer contain the right number?

    It is lenient in a way that is easy to miss -- "not 42" contains "42", and so
    does "42000". Those are the false positives calibration is meant to surface.
    """
    if run.content is None:
        return False
    return str(expected) in run.content


def _trace(content):
    return RunOutput(content=content, status=RunStatus.completed)


# (run, expected, gold) -- gold is the human verdict: True means "should pass".
labeled_traces = [
    (_trace("42"), 42, True),
    (_trace("The answer is 42."), 42, True),
    (_trace("42"), 42, True),
    (_trace("It is not 42."), 42, False),  # contains "42", but says the opposite
    (_trace("42000"), 42, False),  # contains "42", wrong number
    (
        _trace("The answer is forty-two."),
        42,
        True,
    ),  # correct, but the scorer cannot see it
    (_trace("I do not know."), 42, False),
    (_trace("7"), 42, False),
]


if __name__ == "__main__":
    report = calibrate(CodeScorer(mentions_the_number), labeled_traces)

    print(
        f"traces: {report.n_traces}   scored: {report.n_scored}   scorer errors: {report.n_errors}"
    )
    print(f"agreement:           {report.agreement:.2f}")
    print(f"false positive rate: {report.false_positive_rate:.2f}")
    print(f"false negative rate: {report.false_negative_rate:.2f}")
    print()

    print("where the scorer and the labels disagree:")
    for row in report.disagreements:
        direction = (
            "passed what should fail"
            if row["scorer_passed"]
            else "failed what should pass"
        )
        print(f"  trace {row['index']}: {direction}")

    print()
    print("A false positive is the expensive one: fine-tuning on it teaches the model")
    print("the mistake. Fix the scorer before spending a training run on its output.")
