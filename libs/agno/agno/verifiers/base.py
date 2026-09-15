"""The Verifier protocol, the callable adapter, the guard, and entry coercion."""

import asyncio
import copy
import inspect
import traceback
from typing import Any, Callable, Dict, Optional, Protocol, Tuple, Union, runtime_checkable

from agno.verifiers.types import Verdict


def is_async_callable(fn: Any) -> bool:
    # iscoroutinefunction is False for an instance whose __call__ is async.
    return inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(getattr(fn, "__call__", None))


def async_verifier_error(name: str) -> ValueError:
    # The same refusal `run()` gives an async hook: there is no loop on the sync path to await it.
    return ValueError(f"Cannot use {name} (an async verifier) with `run()`. Use `arun()` instead.")


def _require_sync_run_condition(v: Any) -> None:
    if v.run_condition is not None and is_async_callable(v.run_condition):
        raise ValueError(
            f"Cannot use {getattr(v.run_condition, '__name__', type(v.run_condition).__name__)} (an async run_condition) with `run()`. Use `arun()` instead."
        )


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Verifier(Protocol):
    """Anything that can judge one attempt: an object with a ``name`` and a ``verify`` method,
    an ``averify`` method, or both. Either may declare any of ``run_output``, ``run_context``,
    ``agent``, ``team``, ``workflow`` and ``session`` by name and returns a Verdict. ``run()``
    calls ``verify``; ``arun()`` calls ``averify``, or ``verify`` on a worker thread."""

    name: str


# ---------------------------------------------------------------------------
# Failure rendering and return mapping
# ---------------------------------------------------------------------------


# What the guards turn into a failing Verdict. SystemExit is included: argparse, click and
# pytest.main all exit through it, and a check that does must not unwind the whole run.
# KeyboardInterrupt and CancelledError keep propagating.
_GUARDED = (Exception, SystemExit)


def exception_verdict(name: str, exc: BaseException) -> Verdict:
    """A failing Verdict carrying the exception and the tail of its traceback. Used wherever a
    broken verifier must not crash or silently pass a run."""
    tail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__, limit=-5)).rstrip()
    report = f"{type(exc).__name__}: {exc}\n{tail}"
    return Verdict(passed=False, report=report, name=name, detail={"exception": type(exc).__name__})


def _map_return(result: Any, name: str) -> Verdict:
    """The adapter's return mapping. Only True and a passing Verdict pass; everything else,
    including None from a forgotten return, fails loudly."""
    if isinstance(result, Verdict):
        return result.named(name)
    if result is True:
        return Verdict(passed=True, name=name)
    if result is False:
        return Verdict(passed=False, report=f"{name} failed", name=name)
    if isinstance(result, str):
        return Verdict(passed=False, report=result or f"{name} failed", name=name)
    if result is None:
        return Verdict(
            passed=False,
            report=f"{name} returned None; return True, False, a str, or a Verdict",
            name=name,
        )
    return Verdict(
        passed=False,
        report=f"{name} returned {type(result).__name__}; return True, False, a str, or a Verdict",
        name=name,
    )


# ---------------------------------------------------------------------------
# By-name argument routing
# ---------------------------------------------------------------------------

_ALLOWED_PARAMS = ("run_output", "run_context", "agent", "team", "workflow", "session")


def _owner_key(owner: Any) -> str:
    # Which catch-all key carries the owner. A name check instead of an import: this module
    # must not import agno.team or agno.workflow, and the adapter only needs to tell the
    # owner kinds apart.
    for cls in type(owner).__mro__:
        if cls.__name__ == "Team":
            return "team"
        if cls.__name__ == "Workflow":
            return "workflow"
    return "agent"


def validate_verifier_params(fn: Callable[..., Any], label: str, extra_allowed: Tuple[str, ...] = ()) -> None:
    """Raise TypeError when `fn` declares a parameter without a default that it is never called with.
    An uninspectable callable is not validated."""
    allowed = _ALLOWED_PARAMS + extra_allowed
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return
    for param in parameters.values():
        if param.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL):
            continue
        if param.name not in allowed and param.default is inspect.Parameter.empty:
            raise TypeError(
                f"{label} declares parameter {param.name!r}, which it is never called with; "
                f"allowed parameter names are: {', '.join(allowed)}"
            )


def verifier_args(
    fn: Callable[..., Any], run_output: Any, run_context: Any, owner: Any, session: Any, **extras: Any
) -> Dict[str, Any]:
    """The keyword arguments `fn` declares, out of run_output, run_context, session, `extras` and the
    owner under the name matching its kind. An owner name `fn` declares for another kind gets None."""
    from agno.utils.hooks import filter_hook_args

    all_args: Dict[str, Any] = {
        "run_output": run_output,
        "run_context": run_context,
        **({_owner_key(owner): owner} if owner is not None else {}),
        "session": session,
        **extras,
    }
    kwargs = filter_hook_args(fn, all_args)
    try:
        parameters = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return kwargs
    for name in ("agent", "team", "workflow"):
        if name in parameters and name not in kwargs:
            kwargs[name] = None
    return kwargs


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


def validate_required_stop_on_failure(required: bool, stop_on_failure: bool, label: str) -> None:
    # An advisory check cannot stop the run: advisory means "never gates the outcome" and
    # stop_on_failure means "a failure ends the run" - honoring both at once is impossible, and
    # picking one silently stamps a run unverified while its events say it passed.
    if stop_on_failure and not required:
        raise ValueError(
            f"{label}: stop_on_failure=True contradicts required=False; an advisory check cannot end the run"
        )


def _adopt_policy(target: "CoercedVerifier", source: Any) -> None:
    """Carry the per-check policy attributes onto a wrapper, defaulting where the source
    declares none. The loop reads policy off the coerced wrapper only."""
    target.required = bool(getattr(source, "required", True))
    target.max_retries = int(getattr(source, "max_retries", 0) or 0)
    target.run_condition = getattr(source, "run_condition", None)
    target.stop_on_failure = bool(getattr(source, "stop_on_failure", False))
    validate_required_stop_on_failure(
        target.required, target.stop_on_failure, label=f"verifier {getattr(source, 'name', source)!r}"
    )


def validate_policy(max_retries: int, run_condition: Any, label: str) -> None:
    """The per-check policy checks shared by `check()` and the shipped verifiers. Raises at
    construction: a bad policy must not surface as a mid-run surprise."""
    if max_retries < 0:
        raise ValueError(f"{label}: max_retries must be a non-negative int, got {max_retries!r}")
    if run_condition is not None:
        # Validate the predicate's signature now, with `verdicts` in the allowed set.
        validate_verifier_params(run_condition, label=f"{label} run_condition", extra_allowed=("verdicts",))


class CallableVerifier:
    """`check()` output: a plain callable adapted to the Verifier protocol.

    The callable's parameters are routed by name (run_output, run_context, agent, team,
    workflow, session); its signature is validated at construction. `verify` and `averify` accept the
    loop's uniform call shape and only forward what the callable declared.
    """

    required: bool
    max_retries: int
    run_condition: Optional[Callable[..., Any]]
    stop_on_failure: bool

    def __init__(self, fn: Callable[..., Any], name: Optional[str] = None) -> None:
        self.fn = fn
        self.name: str = name or str(getattr(fn, "__name__", type(fn).__name__))
        self._async = is_async_callable(fn)
        validate_verifier_params(fn, label=f"verifier {self.name!r}")
        _adopt_policy(self, fn)

    def _invoke(self, run_output: Any, run_context: Any, owner: Any, session: Any) -> Any:
        return self.fn(**verifier_args(self.fn, run_output, run_context, owner, session))

    def require_sync(self) -> None:
        """Raise when `run()` cannot call this check."""
        if self._async:
            raise async_verifier_error(self.name)
        _require_sync_run_condition(self)

    def verify(self, run_output: Any, run_context: Any = None, owner: Any = None, session: Any = None) -> Verdict:
        self.require_sync()
        try:
            result = self._invoke(run_output, run_context, owner, session)
        except _GUARDED as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)

    async def averify(
        self, run_output: Any, run_context: Any = None, owner: Any = None, session: Any = None
    ) -> Verdict:
        try:
            if self._async:
                result = await self._invoke(run_output, run_context, owner, session)
            else:
                result = await asyncio.to_thread(self._invoke, run_output, run_context, owner, session)
        except _GUARDED as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)


class GuardedVerifier:
    """The guard every user-supplied Verifier runs behind.

    ``run()`` calls the object's own ``verify`` and refuses an object without a sync one;
    ``arun()`` awaits ``averify``, or runs ``verify`` on a worker thread when that is all the
    object has. A non-Verdict return is mapped through the adapter's rules and an exception
    becomes a failing Verdict, so a broken verifier can never crash a run. Methods are called
    with by-name filtering over run_output, run_context, agent, team, workflow, session, so an
    object may declare any subset; an unknown required parameter raises TypeError at wrap time.
    """

    required: bool
    max_retries: int
    run_condition: Optional[Callable[..., Any]]
    stop_on_failure: bool

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name: str = str(getattr(inner, "name", None) or type(inner).__name__)
        _adopt_policy(self, inner)
        for method in ("verify", "averify"):
            fn = getattr(inner, method, None)
            if callable(fn):
                validate_verifier_params(fn, label=f"verifier {self.name!r} method {method!r}")

    def require_sync(self) -> None:
        """Raise when `run()` cannot call this check."""
        verify = getattr(self.inner, "verify", None)
        if not callable(verify) or is_async_callable(verify):
            raise async_verifier_error(self.name)
        inner_require = getattr(self.inner, "require_sync", None)
        if callable(inner_require):
            inner_require()
        _require_sync_run_condition(self)

    def verify(self, run_output: Any, run_context: Any = None, owner: Any = None, session: Any = None) -> Verdict:
        self.require_sync()
        try:
            result = self.inner.verify(**verifier_args(self.inner.verify, run_output, run_context, owner, session))
        except _GUARDED as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)

    async def averify(
        self, run_output: Any, run_context: Any = None, owner: Any = None, session: Any = None
    ) -> Verdict:
        averify = getattr(self.inner, "averify", None)
        fn = averify if callable(averify) else self.inner.verify
        try:
            kwargs = verifier_args(fn, run_output, run_context, owner, session)
            if is_async_callable(fn):
                result = await fn(**kwargs)
            else:
                result = await asyncio.to_thread(fn, **kwargs)
        except _GUARDED as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)


# What coerce_verifier hands the loop: a wrapper that declares the per-check policy fields
CoercedVerifier = Union[CallableVerifier, GuardedVerifier]


def coerce_verifier(obj: Any) -> "CoercedVerifier":
    """Classify one entry of `verifiers`.

    An object with `verify` and/or `averify` is used through `GuardedVerifier`, which calls
    its own methods and guards against exceptions. A callable with
    neither is adapted via `check()`. Anything else is a programmer error. The result
    always exposes the `verify` and `averify` the run loop calls; a bare user object is never called
    directly. Idempotent: an already-coerced wrapper (a `check()` result) passes through —
    re-wrapping one would route the loop's owner/session past the inner adapter.
    """
    if isinstance(obj, (CallableVerifier, GuardedVerifier)):
        return obj
    if callable(getattr(obj, "verify", None)) or callable(getattr(obj, "averify", None)):
        return GuardedVerifier(obj)
    if callable(obj):
        return CallableVerifier(obj)
    raise ValueError(f"Pass a Verifier, a callable, or a Scorer wrapped in ScorerVerifier, got {type(obj).__name__}")


def check(
    target: Any,
    *,
    name: Optional[str] = None,
    required: Optional[bool] = None,
    max_retries: Optional[int] = None,
    run_condition: Optional[Callable[..., Any]] = None,
    stop_on_failure: Optional[bool] = None,
) -> "CoercedVerifier":
    """Adapt a callable (or any Verifier) into a check with its per-check policy.

    A callable may declare any of `run_output`, `run_context`, `agent`, `team`, `workflow`,
    `session` (or a `**kwargs` catch-all) and receives only what it declared; any other
    parameter without a default raises TypeError here, at adaptation. Return mapping: True
    passes. False fails with a generic report; a str fails with that str as the report; a
    Verdict is used as-is. None and any other type fail with a report naming the problem, so a
    forgotten return never greens a run. Coroutine functions are awaited on the async path and
    refused by `run()`; sync callables run in a thread on the async path. An exception inside
    the callable becomes a failing Verdict.

    ``required=False`` makes the check advisory (reports, never gates); ``max_retries=N``
    re-runs the check up to N extra times before trusting a failure; ``run_condition`` is a
    predicate over the same by-name arguments plus ``verdicts`` (this attempt's so far)
    deciding whether the check runs; ``stop_on_failure=True`` ends the run on a failure that
    retrying cannot fix. A knob left as None keeps whatever policy the target already declares.
    Returns a fresh wrapper.
    """
    label = name or str(getattr(target, "name", None) or getattr(target, "__name__", type(target).__name__))
    validate_policy(
        max_retries if max_retries is not None else 0,
        run_condition,
        label=f"check {label!r}",
    )
    coerced = coerce_verifier(target)
    if coerced is target:
        # An already-coerced target passes through coercion by identity; stamping it in
        # place would bleed this mount's policy into every other mount sharing it.
        coerced = copy.copy(coerced)
    if name:
        coerced.name = name
    if required is not None:
        coerced.required = bool(required)
    if max_retries is not None:
        coerced.max_retries = int(max_retries)
    if run_condition is not None:
        coerced.run_condition = run_condition
    if stop_on_failure is not None:
        coerced.stop_on_failure = bool(stop_on_failure)
    # On the merged policy, not just the passed knobs: stop_on_failure=True over a target
    # declared advisory is as contradictory as passing both at once.
    validate_required_stop_on_failure(coerced.required, coerced.stop_on_failure, label=f"check {label!r}")
    return coerced


def verifier_names(entries: Any) -> list:
    """The display names of a mount's checks, coerced fresh so a mutated verifiers list
    never yields stale names (the verification context in the system message reads these before the gate runs)."""
    names = []
    for index, entry in enumerate(entries or []):
        try:
            names.append(getattr(coerce_verifier(entry), "name", "") or f"verifier {index}")
        except Exception:
            names.append(str(getattr(entry, "name", "") or getattr(entry, "__name__", "check")))
    return names
