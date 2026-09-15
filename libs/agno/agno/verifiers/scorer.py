"""ScorerVerifier: reuse an agno.scorer.Scorer as an in-loop verification gate."""

import inspect
from typing import Any, Callable, Optional

from agno.verifiers.base import (
    async_verifier_error,
    exception_verdict,
    validate_policy,
    validate_required_stop_on_failure,
)
from agno.verifiers.types import Verdict


def _accepts_run_metrics(fn: Any) -> bool:
    # A judge that calls a model takes run_metrics and charges its spend there; a plain
    # scorer keeps score(run, expected) and must not receive an unexpected keyword.
    try:
        return "run_metrics" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


class ScorerVerifier:
    """Bridge an `agno.scorer.Scorer` into a Verifier.

    Passes iff `score.passed`; the scorer owns its pass rule, there is no second threshold
    here. The report on failure carries the value and reason. `run()` calls the scorer's
    `score()` and refuses a scorer without one; `arun()` awaits `ascore()`. The scorer judges
    the attempt's run output; `run_context` is accepted and ignored.
    """

    def __init__(
        self,
        scorer: Any,
        *,
        expected: Any = None,
        name: Optional[str] = None,
        required: bool = True,
        max_retries: int = 0,
        run_condition: Optional[Callable[..., Any]] = None,
        stop_on_failure: bool = False,
    ) -> None:
        if not callable(getattr(scorer, "ascore", None)):
            raise TypeError(f"ScorerVerifier needs a Scorer with ascore(); got {type(scorer).__name__}")
        self.scorer = scorer
        self.expected = expected
        self.name = name or type(scorer).__name__
        validate_policy(max_retries, run_condition, label=f"ScorerVerifier {self.name!r}")
        self.required = bool(required)
        self.max_retries = int(max_retries)
        self.run_condition = run_condition
        self.stop_on_failure = bool(stop_on_failure)
        validate_required_stop_on_failure(self.required, self.stop_on_failure, label=f"ScorerVerifier {self.name!r}")

    def _to_verdict(self, score: Any) -> Verdict:
        if score is None:
            # "score None" reads like a legitimate low score; say what actually happened.
            return Verdict(
                passed=False,
                report=f"{self.name} scorer returned no Score object; treating it as a failure",
                name=self.name,
                detail={"value": None, "reason": "scorer returned None", "detail": None},
            )
        if not hasattr(score, "passed"):
            # A bare float, dict or bool is not a Score; "score None" would read as a low score.
            return Verdict(
                passed=False,
                report=f"{self.name} scorer returned {type(score).__name__} ({score!r}), not a Score; treating it as a failure",
                name=self.name,
                detail={"value": None, "reason": f"scorer returned {type(score).__name__}", "detail": None},
            )
        value = getattr(score, "value", None)
        reason = getattr(score, "reason", None) or ""
        raw_passed = getattr(score, "passed", False)
        passed = raw_passed is True
        shown = f"{float(value):.2f}" if isinstance(value, (int, float)) else str(value)
        report = "" if passed else (f"score {shown}: {reason}" if reason else f"score {shown}")
        if not isinstance(raw_passed, bool):
            note = (
                f"{self.name} returned Score.passed of type {type(raw_passed).__name__} "
                f"({raw_passed!r}); only a real bool decides a run, treating it as a failure"
            )
            report = f"{note}\n{report}" if report else note
        return Verdict(
            passed=passed,
            report=report,
            name=self.name,
            detail={"value": value, "reason": reason, "detail": getattr(score, "detail", None)},
        )

    def require_sync(self) -> None:
        """Raise when `run()` cannot score: the scorer has no sync `score()`."""
        if not callable(getattr(self.scorer, "score", None)):
            raise async_verifier_error(self.name)

    def verify(self, run_output: Any, run_context: Any = None) -> Verdict:
        self.require_sync()
        try:
            if _accepts_run_metrics(self.scorer.score):
                score = self.scorer.score(run_output, self.expected, run_metrics=getattr(run_output, "metrics", None))
            else:
                score = self.scorer.score(run_output, self.expected)
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return self._to_verdict(score)

    async def averify(self, run_output: Any, run_context: Any = None) -> Verdict:
        try:
            if _accepts_run_metrics(self.scorer.ascore):
                score = await self.scorer.ascore(
                    run_output, self.expected, run_metrics=getattr(run_output, "metrics", None)
                )
            else:
                score = await self.scorer.ascore(run_output, self.expected)
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return self._to_verdict(score)
