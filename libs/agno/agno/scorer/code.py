"""CodeScorer: wrap a callable as a scorer."""

import asyncio
import hashlib
import inspect
import textwrap
from typing import Any, Callable, Union

from agno.scorer.base import AnyRunOutput, FingerprintError, Score


class CodeScorer:
    """Score runs with any callable `(run, expected) -> bool | float | Score`.

    A `bool` becomes `Score(1.0, True)` / `Score(0.0, False)` -- `pass_threshold` is not
    consulted. A `float` is passed through with `passed = value >= pass_threshold`; an
    `int` is accepted and treated as a float; a value outside [0, 1] raises. A `Score`
    is used verbatim. Sync callables run via `asyncio.to_thread`;
    coroutine functions, and callable objects whose `__call__` is async, are awaited.

    `run.content` is `Any`, not `str`: under `output_schema` it is a pydantic model, and
    comparing a typed field against the expected value is the recommended shape.
    `run.get_content_as_string()` exists but is lossy.
    """

    def __init__(self, fn: Callable[[AnyRunOutput, Any], Any], *, pass_threshold: float = 0.5) -> None:
        self.fn = fn
        self.pass_threshold = pass_threshold

    def _is_async(self) -> bool:
        # iscoroutinefunction is False for an instance whose __call__ is async.
        return inspect.iscoroutinefunction(self.fn) or inspect.iscoroutinefunction(getattr(self.fn, "__call__", None))

    def _to_score(self, result: Union[bool, float, Score]) -> Score:
        if isinstance(result, Score):
            return result
        # bool before float: bool subclasses int and must bypass the threshold.
        if isinstance(result, bool):
            return Score(value=1.0 if result else 0.0, passed=result)
        if isinstance(result, (int, float)):
            value = float(result)
            return Score(value=value, passed=value >= self.pass_threshold)
        raise TypeError(
            f"CodeScorer function must return bool, float, or Score, got {type(result).__name__}: {result!r}"
        )

    def score(self, run: AnyRunOutput, expected: Any = None) -> Score:
        if self._is_async():
            result = asyncio.run(self.fn(run, expected))
        else:
            result = self.fn(run, expected)
        return self._to_score(result)

    async def ascore(self, run: AnyRunOutput, expected: Any = None) -> Score:
        if self._is_async():
            result = await self.fn(run, expected)
        else:
            result = await asyncio.to_thread(self.fn, run, expected)
        return self._to_score(result)

    def digest(self) -> str:
        """sha256 hex of the function's dedented source AND pass_threshold, for
        `env_fingerprint`.

        pass_threshold is part of the identity: the same function with a different
        threshold grades differently, so it must change the digest -- otherwise two
        environments that pass and fail the same score hash identically.

        Source hashing has two documented residuals: editing an unrelated part of the
        same statement flips the hash (over-invalidation, safe), and closure-captured
        values are invisible to it (under-invalidation, accepted). `__code__.co_code`
        is not used: it varies across Python versions and misses co_consts and closures.
        """
        try:
            source = inspect.getsource(self.fn)
        except (OSError, TypeError) as exc:
            raise FingerprintError(
                f"CodeScorer cannot digest {self.fn!r}: source is not retrievable "
                "(REPL-defined, builtin, or C callable)"
            ) from exc
        payload = f"{textwrap.dedent(source)}\npass_threshold={self.pass_threshold!r}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
