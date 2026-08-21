"""Verifiers: the protocol, the callable adapter, ShellVerifier, ScorerVerifier, and the sync bridge."""

import asyncio
import inspect
import os
import signal
import subprocess
import sys
import threading
import traceback
from collections import deque
from typing import Any, Awaitable, Callable, Deque, Dict, Optional, Protocol, runtime_checkable

from agno.verify.types import Verdict

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
            thread = threading.Thread(target=loop.run_forever, name="agno-verify-bridge", daemon=True)
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


_detached = threading.local()


def _run_on_private_loop(coro: Awaitable[Any]) -> Any:
    # This thread is the bridge (or a thread the bridge is blocked on); submitting to the
    # shared loop would deadlock, because the loop cannot service the submission while it
    # waits for our result. Run the coroutine on its own short-lived loop instead, on a
    # thread that is itself marked so deeper nesting escapes the same way.
    box: Dict[str, Any] = {}

    def target() -> None:
        _detached.flag = True
        try:
            box["result"] = asyncio.run(_shield_base_exceptions(coro))
        except BaseException as exc:  # noqa: BLE001 - carried across the thread boundary
            box["result"] = (False, exc)

    thread = threading.Thread(target=target, name="agno-verify-bridge-nested", daemon=True)
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
    if threading.current_thread() is _bridge_thread or getattr(_detached, "flag", False):
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
# Protocol and adapters
# ---------------------------------------------------------------------------


@runtime_checkable
class Verifier(Protocol):
    """Anything that can judge one attempt's RunOutput."""

    name: str

    def verify(self, run: Any) -> Verdict: ...

    async def averify(self, run: Any) -> Verdict: ...


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
            report=f"{name} returned None; return True to pass, a str or False to fail",
            name=name,
        )
    return Verdict(
        passed=False,
        report=f"{name} returned {type(result).__name__}; return True, False, a str, or a Verdict",
        name=name,
    )


class CallableVerifier:
    """`verifier()` output: a plain callable adapted to the Verifier protocol."""

    def __init__(self, fn: Callable[[Any], Any], name: Optional[str] = None) -> None:
        self.fn = fn
        self.name: str = name or str(getattr(fn, "__name__", type(fn).__name__))
        self._async = _is_async_callable(fn)

    def verify(self, run: Any) -> Verdict:
        try:
            result = run_sync(self.fn(run)) if self._async else self.fn(run)
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)

    async def averify(self, run: Any) -> Verdict:
        try:
            result = await self.fn(run) if self._async else await asyncio.to_thread(self.fn, run)
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)


def verifier(fn: Callable[[Any], Any], name: Optional[str] = None) -> Verifier:
    """Adapt a callable `(run) -> Verdict | True | False | str` into a Verifier.

    True passes. False fails with a generic report; a str fails with that str as the report;
    a Verdict is used as-is. None and any other type fail with a report naming the problem,
    so a forgotten return never greens a run. Coroutine functions are awaited on the async
    path and driven through the sync bridge on the sync path; sync callables run in a thread
    on the async path. An exception inside the callable becomes a failing Verdict.
    """
    return CallableVerifier(fn, name=name)


class GuardedVerifier:
    """The guard every user-supplied Verifier runs behind.

    Delegates to the object's own `verify` / `averify`, derives a missing half (sync from
    async through the bridge, async from sync through a thread), maps a non-Verdict return
    through the adapter's rules, and turns an exception into a failing Verdict. A broken
    verifier can never crash a run, whichever shape it was written in.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.name: str = str(getattr(inner, "name", None) or type(inner).__name__)
        sync_half = getattr(inner, "verify", None)
        async_half = getattr(inner, "averify", None)
        # An `async def verify` is an async half under the wrong name; honour what it is.
        self._sync: Optional[Callable[[Any], Any]] = (
            sync_half if callable(sync_half) and not _is_async_callable(sync_half) else None
        )
        self._async: Optional[Callable[[Any], Awaitable[Any]]] = None
        if callable(async_half) and _is_async_callable(async_half):
            self._async = async_half
        elif callable(sync_half) and _is_async_callable(sync_half):
            self._async = sync_half

    def verify(self, run: Any) -> Verdict:
        try:
            if self._sync is not None:
                result = self._sync(run)
            else:
                result = run_sync(self._async(run))  # type: ignore[misc]
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)

    async def averify(self, run: Any) -> Verdict:
        try:
            if self._async is not None:
                result = await self._async(run)
            else:
                result = await asyncio.to_thread(self._sync, run)  # type: ignore[arg-type]
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return _map_return(result, self.name)


def coerce_verifier(obj: Any) -> Verifier:
    """Classify one entry of `verifiers`.

    An object with `verify` and/or `averify` is used through `GuardedVerifier`, which calls
    its own methods, derives a missing half, and guards against exceptions. A callable with
    neither is adapted via `verifier()`. Anything else is a programmer error.
    """
    has_sync = callable(getattr(obj, "verify", None))
    has_async = callable(getattr(obj, "averify", None))
    if has_sync or has_async:
        return GuardedVerifier(obj)
    if callable(obj):
        return verifier(obj)
    raise ValueError(
        f"verifiers entries must be a Verifier, a callable, or a ScorerVerifier; got {type(obj).__name__}. "
        "Wrap a Scorer in ScorerVerifier."
    )


# ---------------------------------------------------------------------------
# ShellVerifier
# ---------------------------------------------------------------------------

# Head and tail kept from a shell command's output, each side. Well above REPORT_CAP_BYTES,
# so the capped Verdict.report is byte-identical to what full buffering would produce; the
# middle of a very large output is dropped instead of held in memory.
_SHELL_KEEP_BYTES = 65536


class _BoundedOutput:
    """Bounded head-and-tail store for a stream: absorb() keeps the first and last
    _SHELL_KEEP_BYTES and drops the middle."""

    def __init__(self, keep: int = _SHELL_KEEP_BYTES) -> None:
        self.keep = keep
        self.head = bytearray()
        self.tail: Deque[bytes] = deque()
        self.tail_bytes = 0

    def absorb(self, chunk: bytes) -> None:
        if len(self.head) < self.keep:
            take = self.keep - len(self.head)
            self.head += chunk[:take]
            chunk = chunk[take:]
        if not chunk:
            return
        self.tail.append(chunk)
        self.tail_bytes += len(chunk)
        while self.tail and self.tail_bytes - len(self.tail[0]) >= self.keep:
            self.tail_bytes -= len(self.tail.popleft())

    def text(self) -> str:
        return (bytes(self.head) + b"".join(self.tail)).decode("utf-8", errors="replace")


_HARNESS_EXIT_CODES = {126, 127}


class ShellVerifier:
    """Run a shell command; exit code 0 passes.

    `env` is merged over the current environment. `cwd=None` is the process's cwd at verify
    time. Stdout and stderr are merged. The command runs in its own process group and the
    whole group is killed on timeout, so a hung test run does not outlive the attempt. The
    report starts with the exit line, then the full merged output; Verdict applies the
    head+tail cap so the runner summary at the end survives. Exit codes 126 and 127 (not
    executable, not found) are marked as harness errors rather than handed to the model as
    work to do.
    """

    def __init__(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        timeout_s: float = 120.0,
        env: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.timeout_s = timeout_s
        self.env = env
        self.name = name or command[:40]

    def _env(self) -> Dict[str, str]:
        merged = dict(os.environ)
        if self.env:
            merged.update(self.env)
        return merged

    def _report(self, returncode: Optional[int], output: str, timed_out: bool) -> Verdict:
        if timed_out:
            first = f"timed out after {self.timeout_s:g}s"
        elif returncode in _HARNESS_EXIT_CODES:
            first = f"harness error: exit {returncode} (command not found or not executable)"
        else:
            first = f"exit {returncode}"
        passed = (not timed_out) and returncode == 0
        report = "" if passed else f"{first}\n{output}".rstrip()
        return Verdict(
            passed=passed, report=report, name=self.name, data={"returncode": returncode, "timed_out": timed_out}
        )

    @staticmethod
    def _kill_group(pid: int) -> None:
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True, check=False)
            else:
                os.killpg(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    def verify(self, run: Any) -> Verdict:
        popen_kwargs: Dict[str, Any] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True
        try:
            proc = subprocess.Popen(
                self.command,
                shell=True,
                cwd=self.cwd,
                env=self._env(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
            )
        except Exception as exc:
            return exception_verdict(self.name, exc)
        buffer = _BoundedOutput()

        def drain() -> None:
            stream = proc.stdout
            assert stream is not None
            while True:
                chunk = stream.read(65536)
                if not chunk:
                    break
                buffer.absorb(chunk)

        reader = threading.Thread(target=drain, name="agno-verify-shell-drain", daemon=True)
        reader.start()
        timed_out = False
        finished = False
        try:
            try:
                proc.wait(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_group(proc.pid)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
            finished = True
        finally:
            if not finished:
                # Ctrl-C or any other exceptional exit: the command and its whole process
                # group must not outlive the verifier.
                self._kill_group(proc.pid)
                try:
                    proc.wait(timeout=5)
                except Exception:
                    pass
        reader.join(timeout=5)
        return self._report(proc.returncode, buffer.text(), timed_out)

    async def averify(self, run: Any) -> Verdict:
        popen_kwargs: Dict[str, Any] = {}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True
        try:
            proc = await asyncio.create_subprocess_shell(
                self.command,
                cwd=self.cwd,
                env=self._env(),
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **popen_kwargs,
            )
        except Exception as exc:
            return exception_verdict(self.name, exc)
        buffer = _BoundedOutput()

        async def pump_and_wait() -> None:
            # Both the read and the exit are under the deadline: a child that closes its
            # pipes and keeps running must not outlive the timeout either.
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                buffer.absorb(chunk)
            await proc.wait()

        timed_out = False
        finished = False
        try:
            try:
                await asyncio.wait_for(pump_and_wait(), timeout=self.timeout_s)
            except asyncio.TimeoutError:
                timed_out = True
                self._kill_group(proc.pid)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            finished = True
        finally:
            if not finished:
                # Cancellation, KeyboardInterrupt, or any other exceptional exit: kill the
                # whole group before the exception propagates.
                self._kill_group(proc.pid)
        return self._report(proc.returncode, buffer.text(), timed_out)


# ---------------------------------------------------------------------------
# ScorerVerifier
# ---------------------------------------------------------------------------


class ScorerVerifier:
    """Bridge an `agno.scorer.Scorer` into a Verifier.

    Passes iff `score.passed`; the scorer owns its pass rule, there is no second threshold
    here. The report on failure carries the value and reason. `ascore` is the only scorer
    method used, on both paths: the sync path drives it through the bridge loop, so it works
    inside a running event loop and does not depend on a scorer having a sync `score()`.
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

    def verify(self, run: Any) -> Verdict:
        try:
            score = run_sync(self.scorer.ascore(run, self.expected))
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return self._to_verdict(score)

    async def averify(self, run: Any) -> Verdict:
        try:
            score = await self.scorer.ascore(run, self.expected)
        except Exception as exc:
            return exception_verdict(self.name, exc)
        return self._to_verdict(score)


__all__ = [
    "CallableVerifier",
    "GuardedVerifier",
    "ScorerVerifier",
    "ShellVerifier",
    "Verifier",
    "coerce_verifier",
    "exception_verdict",
    "run_sync",
    "verifier",
]
