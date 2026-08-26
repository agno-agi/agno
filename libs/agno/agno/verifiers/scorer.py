"""ScorerVerifier: reuse an agno.scorer.Scorer as an in-loop verification gate."""

from typing import Any, Optional

from agno.verifiers.base import exception_verdict, run_sync
from agno.verifiers.types import Verdict


class ScorerVerifier:
    """Bridge an `agno.scorer.Scorer` into a Verifier.

    Passes iff `score.passed`; the scorer owns its pass rule, there is no second threshold
    here. The report on failure carries the value and reason. `ascore` is the only scorer
    method used, on both paths: the sync path drives it through the bridge loop, so it works
    inside a running event loop and does not depend on a scorer having a sync `score()`.
    The scorer judges the attempt's run output; `run_context` is accepted and ignored.
    Give the scorer its own Model instance when using the sync path from an application
    that already drives that model on another loop.
    """

    def __init__(self, scorer: Any, *, expected: Any = None, name: Optional[str] = None) -> None:
        if not callable(getattr(scorer, "ascore", None)):
            raise TypeError(f"ScorerVerifier needs a Scorer with ascore(); got {type(scorer).__name__}")
        self.scorer = scorer
        self.expected = expected
        self.name = name or type(scorer).__name__

    def _to_verdict(self, score: Any) -> Verdict:
        if score is None:
            # "score None" reads like a legitimate low score; say what actually happened.
            return Verdict(
                passed=False,
                report=f"{self.name} scorer returned no Score object; treating it as a failure",
                name=self.name,
                data={"value": None, "reason": "scorer returned None", "detail": None},
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
            data={"value": value, "reason": reason, "detail": getattr(score, "detail", None)},
        )

    def verify(self, run_output: Any, run_context: Any = None) -> Verdict:
        try:
            score = run_sync(self.scorer.ascore(run_output, self.expected))
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return self._to_verdict(score)

    async def averify(self, run_output: Any, run_context: Any = None) -> Verdict:
        try:
            score = await self.scorer.ascore(run_output, self.expected)
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return self._to_verdict(score)


__all__ = ["ScorerVerifier"]
