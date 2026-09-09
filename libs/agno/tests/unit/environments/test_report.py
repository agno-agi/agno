"""Unit tests for the per-attempt report: build_report, print_report, print_attempt.

The report is presentation, not contract -- these tests pin behavior (what is shown,
hidden, and refused), not exact formatting.
"""

import pytest

from agno.environments import EnvironmentRunResult, StopReason, Task, TaskResult
from agno.environments._engine import AttemptResult
from agno.environments._render import build_report
from agno.models.response import ToolExecution
from agno.run.agent import RunOutput
from agno.run.base import RunStatus
from agno.scorer import Score


def _attempt(
    *,
    passed=None,
    value=None,
    stop_reason=StopReason.completed,
    error=None,
    content="the answer",
    tools=None,
    run_present=True,
):
    score = None
    if passed is not None:
        score = Score(value=(1.0 if passed else 0.0) if value is None else value, passed=passed)
    run = None
    if run_present:
        run = RunOutput(content=content, tools=tools, status=RunStatus.completed)
    return AttemptResult(
        run=run,
        score=score,
        stop_reason=stop_reason,
        duration_seconds=1.5,
        error=error,
    )


def _task_result(task_id, attempts):
    return TaskResult(task=Task(input=f"input for {task_id}", id=task_id), attempts=tuple(attempts))


def _result(task_results):
    return EnvironmentRunResult(
        env_name="report-env",
        k=max((len(tr.attempts) for tr in task_results), default=0),
        env_fingerprint="e" * 8,
        policy_fingerprint="p" * 8,
        task_results=tuple(task_results),
        duration_seconds=3.0,
    )


def test_report_failed_only_keeps_fails_and_unscored():
    task = _task_result(
        "t-mixed",
        [
            _attempt(passed=True),
            _attempt(passed=False),
            _attempt(stop_reason=StopReason.error, error="boom", run_present=False),
        ],
    )
    text = build_report([task])
    assert "attempt 2: FAIL" in text
    assert "attempt 3: unscored" in text
    assert "attempt 1" not in text
    assert "boom" in text
    assert "(no run captured)" in text


def test_report_all_shows_every_attempt_with_evidence():
    execution = ToolExecution(tool_name="lookup", tool_args={"q": 1}, result="ok", tool_call_error=False)
    task = _task_result("t-all", [_attempt(passed=True, tools=[execution])])
    text = build_report([task], only="all")
    assert "attempt 1: PASS" in text
    assert "lookup({'q': 1}) -> ok" in text
    assert "the answer" in text


def test_report_all_green_returns_all_clear_message():
    task = _task_result("t-green", [_attempt(passed=True), _attempt(passed=True)])
    text = build_report([task])
    assert "all 2 attempts passed" in text
    assert 'only="all"' in text


def test_report_attempts_cap_names_hidden_count():
    task = _task_result("t-cap", [_attempt(passed=False) for _ in range(5)])
    text = build_report([task], attempts=2)
    assert "attempt 1: FAIL" in text
    assert "attempt 2: FAIL" in text
    assert "attempt 3" not in text
    assert "3 more" in text


def test_report_rejects_unknown_only():
    with pytest.raises(ValueError):
        build_report([], only="everything")


def test_print_report_prints_to_stdout(capsys):
    result = _result([_task_result("t1", [_attempt(passed=False)])])
    result.print_report()
    out = capsys.readouterr().out
    assert "t1" in out
    assert "FAIL" in out


def test_print_attempt_full_detail(capsys):
    score = Score(value=0.0, passed=False, reason="wrong label", detail={"raw_score": 3})
    attempt = AttemptResult(
        run=RunOutput(content="nope", status=RunStatus.completed),
        score=score,
        stop_reason=StopReason.completed,
        duration_seconds=2.0,
    )
    result = _result([_task_result("t1", [attempt])])
    result.print_attempt("t1", 1)
    out = capsys.readouterr().out
    assert "wrong label" in out
    assert "raw_score" in out
    assert "FAIL" in out


def test_print_attempt_unknown_task_names_known_ids():
    result = _result([_task_result("t1", [_attempt(passed=True)])])
    with pytest.raises(KeyError, match="t1"):
        result.print_attempt("nope")


def test_print_attempt_index_is_one_based_and_bounded():
    result = _result([_task_result("t1", [_attempt(passed=True)])])
    with pytest.raises(IndexError):
        result.print_attempt("t1", 0)
    with pytest.raises(IndexError):
        result.print_attempt("t1", 2)
