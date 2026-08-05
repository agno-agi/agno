"""Core scoring types: `Score`, the `Scorer` protocol, and the fingerprint errors.

`agno.scorer` must not import `agno.eval` or `agno.environments` -- both import it.
The fingerprint errors live here (not in `agno.environments`) because `CodeScorer.digest`
raises `FingerprintError` before `agno.environments` exists in the dependency order.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, Protocol, Union, runtime_checkable

from agno.run.agent import RunOutput
from agno.run.team import TeamRunOutput

# The union scorers accept. Not named "Run": agno.run is an existing package and the
# collision would read badly in imports.
AnyRunOutput = Union[RunOutput, TeamRunOutput]


class FingerprintError(Exception):
    """A fingerprint component cannot be computed (unserializable value, sourceless callable)."""


class MismatchError(Exception):
    """Two results whose environment fingerprints do not match were compared."""


@dataclass
class Score:
    """The result of scoring one run. `value` is always in [0, 1]."""

    value: float
    passed: bool
    reason: Optional[str] = None
    detail: Optional[Dict[str, Any]] = None

    def __post_init__(self) -> None:
        # An out-of-range value fails loudly: a scorer written against a 1-10 mental
        # model must not silently green every attempt.
        if not 0.0 <= self.value <= 1.0:
            raise ValueError(f"Score.value must be in [0, 1], got {self.value}")


@runtime_checkable
class Scorer(Protocol):
    """Anything that can turn a run into a Score.

    `expected` is the task's expected value when the caller has one (`Task.expected`,
    `Case.expected`); callers with neither pass a bare run. Implementing only `ascore`
    is valid for third-party scorers; the shipped scorers also provide a sync `score()`.
    """

    async def ascore(self, run: AnyRunOutput, expected: Any = None) -> Score: ...
