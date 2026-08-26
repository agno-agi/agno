"""The Verifier protocol, the callable adapter, the guard, entry coercion, and the sync bridge."""

import asyncio
import contextvars
import inspect
import threading
import traceback
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol, Tuple, runtime_checkable

from agno.verifiers.types import Verdict

# ---------------------------------------------------------------------------
# Sync bridge
# ---------------------------------------------------------------------------

_bridge_lock = threading.Lock()
_bridge_loop: Optional[asyncio.AbstractEventLoop] = None
_bridge_thread: Optional[threading.Thread] = None


def _get_bridge_loop() -> asyncio.AbstractEventLoop:
    """One long-lived event loop on a daemon thread, started on first use.

    Sync callers submit coroutines here instead of calling `asyncio.run` per call: inside a
    running loop (notebooks, request handlers) `asyncio.run` raises, and a fresh loop per
    call leaves model clients cached on a closed loop by the next attempt. The loop is
    rebuilt if its thread has died.
    """
    global _bridge_loop, _bridge_thread
    with _bridge_lock:
        alive = _bridge_thread is not None and _bridge_thread.is_alive()
        if _bridge_loop is None or _bridge_loop.is_closed() or not alive:
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="agno-verifiers-bridge", daemon=True)
            thread.start()
            _bridge_loop, _bridge_thread = loop, thread
        return _bridge_loop


async def _shield_base_exceptions(coro: Awaitable[Any]) -> tuple:
    # A KeyboardInterrupt or SystemExit raised inside a task tears run_forever off the bridge
    # thread before the result is handed back, which would block the caller forever. Carry it
    # across as a value and re-raise it in the calling thread instead.
    try:
        return True, await coro
    except BaseException as exc:  # noqa: BLE001
        return False, exc


# A ContextVar, not a threading.local: `asyncio.to_thread` copies the calling context into its
# worker thread, but a thread-local does not follow. Without this, a sync-only verifier reached
# through a derived async half loses the marker, submits back to the shared bridge loop — which
# is parked in the join() below — and the process hangs with no message.
_detached: "contextvars.ContextVar[bool]" = contextvars.ContextVar("agno_verifiers_detached", default=False)


def _run_on_private_loop(coro: Awaitable[Any]) -> Any:
    # This thread is the bridge (or a thread the bridge is blocked on); submitting to the
    # shared loop would deadlock, because the loop cannot service the submission while it
    # waits for our result. Run the coroutine on its own short-lived loop instead, on a
    # thread that is itself marked so deeper nesting escapes the same way.
    box: Dict[str, Any] = {}

    def target() -> None:
        # A new thread starts with an empty context, so this marks this subtree only.
        _detached.set(True)
        try:
            box["result"] = asyncio.run(_shield_base_exceptions(coro))
        except BaseException as exc:  # noqa: BLE001 - carried across the thread boundary
            box["result"] = (False, exc)

    thread = threading.Thread(target=target, name="agno-verifiers-bridge-nested", daemon=True)
    thread.start()
    thread.join()
    ok, value = box["result"]
    if ok:
        return value
    raise value


def run_sync(coro: Awaitable[Any]) -> Any:
    """Run `coro` on the bridge loop and block for its result. Safe with or without a running
    loop in the calling thread; exceptions, including BaseException, propagate to the caller.
    Re-entrant calls (a verifier composed inside another verifier's sync path) detect that
    they are already on the bridge and escape to a private loop instead of deadlocking."""
    if threading.current_thread() is _bridge_thread or _detached.get():
        return _run_on_private_loop(coro)
    loop = _get_bridge_loop()
    ok, value = asyncio.run_coroutine_threadsafe(_shield_base_exceptions(coro), loop).result()
    if ok:
        return value
    raise value


def _is_async_callable(fn: Any) -> bool:
    # iscoroutinefunction is False for an instance whose __call__ is async.
    return inspect.iscoroutinefunction(fn) or inspect.iscoroutinefunction(getattr(fn, "__call__", None))


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Verifier(Protocol):
    """Anything that can judge one attempt: it sees the attempt's run output and the run
    context and returns a Verdict."""

    name: str

    def verify(self, run_output: Any, run_context: Any) -> Verdict: ...

    async def averify(self, run_output: Any, run_context: Any) -> Verdict: ...


# ---------------------------------------------------------------------------
# Failure rendering and return mapping
# ---------------------------------------------------------------------------


def _traceback_tail(exc: BaseException, lines: int = 12) -> str:
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip().splitlines()
    return "\n".join(tb[-lines:])


def exception_verdict(name: str, exc: BaseException) -> Verdict:
    """A failing Verdict carrying the exception and the tail of its traceback. Used wherever a
    broken verifier must not crash or silently pass a run."""
    report = f"{type(exc).__name__}: {exc}\n{_traceback_tail(exc)}"
    return Verdict(passed=False, report=report, name=name, data={"exception": type(exc).__name__})


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

_ALLOWED_PARAMS = ("run_output", "run_context", "agent", "team", "session")


def _owner_key(owner: Any) -> str:
    # Which catch-all key carries the owner. A name check instead of an import: this module
    # must not import agno.team, and the adapter only needs to tell a Team apart.
    if any(cls.__name__ == "Team" for cls in type(owner).__mro__):
        return "team"
    return "agent"


class _ArgMap:
    """By-name argument routing for one verifier callable, resolved once at construction.

    Allowed parameter names: run_output, run_context, agent, team, session. `agent` and
    `team` both receive the owning Agent or Team. A parameter outside the set with no
    default raises TypeError here, at construction: a typo in a verifier signature must
    surface immediately, not silently starve the check on every attempt. A parameter
    outside the set that has a default is simply never filled. A `**kwargs` catch-all
    receives run_output, run_context, session, and the owner under exactly one key —
    `team` when the owner is a Team, else `agent`. A callable whose signature cannot be
    inspected (some builtins) is handed the run output alone, positionally.
    """

    def __init__(self, fn: Callable[..., Any], label: str) -> None:
        self._uninspectable = False
        self._positional: List[str] = []
        self._by_name: List[str] = []
        self._has_kwargs = False
        try:
            parameters = inspect.signature(fn).parameters
        except (TypeError, ValueError):
            self._uninspectable = True
            return
        for param in parameters.values():
            if param.kind is inspect.Parameter.VAR_KEYWORD:
                self._has_kwargs = True
            elif param.kind is inspect.Parameter.VAR_POSITIONAL:
                continue
            elif param.name in _ALLOWED_PARAMS:
                if param.kind is inspect.Parameter.POSITIONAL_ONLY:
                    self._positional.append(param.name)
                else:
                    self._by_name.append(param.name)
            elif param.default is inspect.Parameter.empty:
                raise TypeError(
                    f"{label} declares parameter {param.name!r}, which a verifier is never called with; "
                    f"allowed parameter names are: {', '.join(_ALLOWED_PARAMS)}"
                )

    def build(self, run_output: Any, run_context: Any, owner: Any, session: Any) -> Tuple[tuple, Dict[str, Any]]:
        """The (args, kwargs) for one call."""
        if self._uninspectable:
            return (run_output,), {}
        values = {
            "run_output": run_output,
            "run_context": run_context,
            "agent": owner,
            "team": owner,
            "session": session,
        }
        args = tuple(values[name] for name in self._positional)
        kwargs = {name: values[name] for name in self._by_name}
        if self._has_kwargs:
            kwargs.setdefault("run_output", run_output)
            kwargs.setdefault("run_context", run_context)
            kwargs.setdefault("session", session)
            routed = set(kwargs) | set(self._positional)
            if "agent" not in routed and "team" not in routed:
                kwargs[_owner_key(owner)] = owner
        return args, kwargs


# ---------------------------------------------------------------------------
# Adapters
# ---------------------------------------------------------------------------


class CallableVerifier:
    """`verifier()` output: a plain callable adapted to the Verifier protocol.

    The callable's parameters are routed by name (run_output, run_context, agent, team,
    session); its signature is validated at construction. Both twins accept the loop's
    uniform call shape and only forward what the callable declared.
    """

    def __init__(self, fn: Callable[..., Any], name: Optional[str] = None) -> None:
        self.fn = fn
        self.name: str = name or str(getattr(fn, "__name__", type(fn).__name__))
        self._async = _is_async_callable(fn)
        self._argmap = _ArgMap(fn, label=f"verifier {self.name!r}")

    def _invoke(self, run_output: Any, run_context: Any, owner: Any, session: Any) -> Any:
        args, kwargs = self._argmap.build(run_output, run_context, owner, session)
        return self.fn(*args, **kwargs)

    def verify(self, run_output: Any, run_context: Any = None, owner: Any = None, session: Any = None) -> Verdict:
        try:
            if self._async:
                result = run_sync(self._invoke(run_output, run_context, owner, session))
            else:
                result = self._invoke(run_output, run_context, owner, session)
        except Exception as exc:
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
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)


def verifier(fn: Callable[..., Any], name: Optional[str] = None) -> Verifier:
    """Adapt a callable into a Verifier.

    The callable may declare any of `run_output`, `run_context`, `agent`, `team`, `session`
    (or a `**kwargs` catch-all) and receives only what it declared; any other parameter
    without a default raises TypeError here, at adaptation. Return mapping: True passes.
    False fails with a generic report; a str fails with that str as the report; a Verdict
    is used as-is. None and any other type fail with a report naming the problem, so a
    forgotten return never greens a run. Coroutine functions are awaited on the async path
    and driven through the sync bridge on the sync path; sync callables run in a thread on
    the async path. An exception inside the callable becomes a failing Verdict.
    """
    return CallableVerifier(fn, name=name)


class GuardedVerifier:
    """The guard every user-supplied Verifier runs behind.

    Delegates to the object's own `verify` / `averify`, derives a missing half (sync from
    async through the bridge, async from sync through a thread), maps a non-Verdict return
    through the adapter's rules, and turns an exception into a failing Verdict. A broken
    verifier can never crash a run, whichever shape it was written in. The wrapped methods
    are called with by-name filtering over run_output, run_context, agent, team, session,
    so a protocol object may declare any subset; an unknown required parameter raises
    TypeError at wrap time.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name: str = str(getattr(inner, "name", None) or type(inner).__name__)
        sync_half = getattr(inner, "verify", None)
        async_half = getattr(inner, "averify", None)
        # Classify by what each half IS, not by what it is called: an `async def verify` is an
        # async half under the wrong name, and a plain `def averify` is a sync one. Trusting
        # the names left a verifier written with only a sync `averify` with neither half wired,
        # so every attempt failed on a confusing NoneType error instead of running the check.
        self._sync: Optional[Callable[..., Any]] = None
        self._async: Optional[Callable[..., Awaitable[Any]]] = None
        if callable(sync_half):
            if _is_async_callable(sync_half):
                self._async = sync_half
            else:
                self._sync = sync_half
        if callable(async_half):
            if _is_async_callable(async_half):
                self._async = async_half  # a real averify outranks an `async def verify`
            elif self._sync is None:
                self._sync = async_half  # a plain `def averify` is the sync half when verify is absent
        self._sync_args: Optional[_ArgMap] = None
        self._async_args: Optional[_ArgMap] = None
        if self._sync is not None:
            method = getattr(self._sync, "__name__", "verify")
            self._sync_args = _ArgMap(self._sync, label=f"verifier {self.name!r} method {method!r}")
        if self._async is not None:
            method = getattr(self._async, "__name__", "averify")
            self._async_args = _ArgMap(self._async, label=f"verifier {self.name!r} method {method!r}")

    def verify(self, run_output: Any, run_context: Any = None, owner: Any = None, session: Any = None) -> Verdict:
        try:
            if self._sync is not None and self._sync_args is not None:
                args, kwargs = self._sync_args.build(run_output, run_context, owner, session)
                result = self._sync(*args, **kwargs)
            else:
                args, kwargs = self._async_args.build(run_output, run_context, owner, session)  # type: ignore[union-attr]
                result = run_sync(self._async(*args, **kwargs))  # type: ignore[misc]
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)

    async def averify(
        self, run_output: Any, run_context: Any = None, owner: Any = None, session: Any = None
    ) -> Verdict:
        try:
            if self._async is not None and self._async_args is not None:
                args, kwargs = self._async_args.build(run_output, run_context, owner, session)
                result = await self._async(*args, **kwargs)
            else:
                args, kwargs = self._sync_args.build(run_output, run_context, owner, session)  # type: ignore[union-attr]
                result = await asyncio.to_thread(self._sync, *args, **kwargs)  # type: ignore[arg-type]
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)


def coerce_verifier(obj: Any) -> Verifier:
    """Classify one entry of `verifiers`.

    An object with `verify` and/or `averify` is used through `GuardedVerifier`, which calls
    its own methods, derives a missing half, and guards against exceptions. A callable with
    neither is adapted via `verifier()`. Anything else is a programmer error. The result
    always exposes the uniform twins the run loop calls; a bare user object is never called
    directly.
    """
    has_sync = callable(getattr(obj, "verify", None))
    has_async = callable(getattr(obj, "averify", None))
    if has_sync or has_async:
        return GuardedVerifier(obj)
    if callable(obj):
        return verifier(obj)
    raise ValueError(f"pass a Verifier, a callable, or wrap a Scorer in ScorerVerifier; got {type(obj).__name__}")


__all__ = [
    "CallableVerifier",
    "GuardedVerifier",
    "Verifier",
    "coerce_verifier",
    "exception_verdict",
    "run_sync",
    "verifier",
]
