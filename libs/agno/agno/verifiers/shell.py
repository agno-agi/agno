"""ShellVerifier: run a shell command as the executable definition of done."""

import asyncio
import os
import shlex
import signal
import subprocess
import sys
import threading
from collections import deque
from io import BufferedReader
from time import monotonic
from typing import Any, Callable, Deque, Dict, Optional, cast

from agno.verifiers.base import exception_verdict, validate_policy
from agno.verifiers.types import Verdict

# Head and tail kept from a shell command's output, each side. Well above REPORT_CAP_BYTES,
# so the capped Verdict.report is byte-identical to what full buffering would produce; the
# middle of a very large output is dropped instead of held in memory.
_SHELL_KEEP_BYTES = 65536


class _BoundedOutput:
    """Bounded head-and-tail store for a stream: absorb() keeps the first and last
    _SHELL_KEEP_BYTES and drops the middle.

    Locked: the sync path fills this from a reader thread and reads it from the caller once
    the grace period is up, which may be while the reader is still going.
    """

    def __init__(self, keep: int = _SHELL_KEEP_BYTES) -> None:
        self.keep = keep
        self.head = bytearray()
        self.tail: Deque[bytes] = deque()
        self.tail_bytes = 0
        self._lock = threading.Lock()

    def absorb(self, chunk: bytes) -> None:
        with self._lock:
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
        with self._lock:
            return (bytes(self.head) + b"".join(self.tail)).decode("utf-8", errors="replace")


_HARNESS_EXIT_CODES = {126, 127}

# Budget for the default verifier name. It is one line of the report block and the model reads
# it to tell one failing check from another.
_SHELL_NAME_BYTES = 40


def _default_shell_name(command: str) -> str:
    """A name from the informative end of a command, not its first 40 characters.

    The form the cookbooks and tests use is `f"{sys.executable} -m pytest ..."`, and an absolute
    interpreter path eats the whole budget: two different checks both end up called
    "/Users/me/project/.venv/bin/python -m " and the model cannot tell which one failed.
    """
    text = " ".join(command.split())
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    if tokens and ("/" in tokens[0] or "\\" in tokens[0]):
        tokens[0] = os.path.basename(tokens[0])
    return (" ".join(tokens) if tokens else text)[:_SHELL_NAME_BYTES] or "shell"


# How long to wait for the killed group to be reaped, and for the reader to hand over what it
# already has. Both are teardown budgets, not part of the command's own deadline.
_REAP_GRACE_S = 5.0
_DRAIN_GRACE_S = 5.0

# How often the async path checks whether the command leader has exited.
_EXIT_POLL_S = 0.05


class ShellVerifier:
    """Run a shell command; exit code 0 passes.

    `env` is merged over the current environment. `cwd=None` is the process's cwd at verify
    time. Stdout and stderr are merged. Exit codes 126 and 127 (not executable, not found) are
    marked as harness errors rather than handed to the model as work to do.

    The command is the whole check: both twins ignore `run_output` and `run_context`.

    The contract, identical on both twins:

    - The verdict follows the command leader's exit code. `timeout_s` bounds how long that
      leader may run; a descendant that outlives it never turns a successful command into a
      failure, and never turns a failing one into a pass.
    - The command runs in its own process group, and the whole group is killed and reaped
      before this returns — on success, on timeout, and while unwinding from Ctrl-C or task
      cancellation. Nothing the command started outlives the verifier.
    - Output is drained as it arrives and collected best effort under a short grace period
      once the group is gone. The report starts with the exit line, then the merged output;
      Verdict applies the head+tail cap so a runner summary at the end survives.
    """

    def __init__(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        timeout_s: float = 120.0,
        env: Optional[Dict[str, str]] = None,
        name: Optional[str] = None,
        required: bool = True,
        rerun: int = 0,
        run_when: Optional[Callable[..., Any]] = None,
        fatal: bool = False,
    ) -> None:
        self.command = command
        self.cwd = cwd
        self.timeout_s = timeout_s
        self.env = env
        self.name = name or _default_shell_name(command)
        validate_policy(rerun, run_when, label=f"ShellVerifier {self.name!r}")
        self.required = bool(required)
        self.rerun = int(rerun)
        self.run_when = run_when
        self.fatal = bool(fatal)

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

    def verify(self, run_output: Any, run_context: Any = None) -> Verdict:
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
            assert proc.stdout is not None
            # A binary Popen pipe is a BufferedReader; the stubs only promise IO[Any].
            stream = cast(BufferedReader, proc.stdout)
            try:
                while True:
                    # read1, not read: read() on a BufferedReader blocks until it has a full
                    # buffer or EOF, and a command that backgrounds anything holding stdout
                    # never reaches EOF - so every byte the command did write would be lost.
                    chunk = stream.read1(65536)
                    if not chunk:
                        break
                    buffer.absorb(chunk)
            except (ValueError, OSError):
                pass  # the pipe was closed under us during teardown

        reader = threading.Thread(target=drain, name="agno-verifiers-shell-drain", daemon=True)
        reader.start()
        timed_out = False
        try:
            try:
                proc.wait(timeout=self.timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            # Always, on every exit path including Ctrl-C: the group never outlives the
            # verifier. This also closes the write end of the pipe, which is what lets the
            # reader thread finish when a descendant was holding it open.
            self._kill_group(proc.pid)
            try:
                proc.wait(timeout=_REAP_GRACE_S)
            except Exception:
                pass
        reader.join(timeout=_DRAIN_GRACE_S)
        if not reader.is_alive():
            # Only when the drain has finished. BufferedReader.close() takes the same buffer
            # lock the reader holds inside read1(), so closing while it is still parked on a
            # descendant that kept the pipe would block for that descendant's whole life and
            # make timeout_s bound nothing at all. Left open, the fd goes with the Popen.
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
        return self._report(proc.returncode, buffer.text(), timed_out)

    async def averify(self, run_output: Any, run_context: Any = None) -> Verdict:
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
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                **popen_kwargs,
            )
        except Exception as exc:
            return exception_verdict(self.name, exc)
        buffer = _BoundedOutput()

        async def pump() -> None:
            assert proc.stdout is not None
            try:
                while True:
                    chunk = await proc.stdout.read(65536)
                    if not chunk:
                        break
                    buffer.absorb(chunk)
            except (asyncio.CancelledError, ValueError, OSError):
                pass

        pump_task = asyncio.ensure_future(pump())
        timed_out = False
        try:
            # NOT `await proc.wait()`: asyncio resolves that only once every pipe is closed as
            # well, so a command that exited cleanly while a descendant still held stdout is
            # reported as a timeout - while the sync twin, judging on the exit code, passes the
            # very same command. The leader's exit shows up on `returncode` as soon as SIGCHLD
            # lands, whatever the pipe is doing, so the deadline is measured against that.
            deadline = monotonic() + self.timeout_s
            while proc.returncode is None:
                if monotonic() >= deadline:
                    timed_out = True
                    break
                await asyncio.sleep(_EXIT_POLL_S)
        finally:
            # Runs on cancellation and KeyboardInterrupt too: kill the group and reap it
            # before the exception propagates, so no child and no transport is left behind.
            self._kill_group(proc.pid)
            # A cancel delivered while parked in either grace wait below must still cancel
            # the task: swallowing it would return a Verdict from a cancelled task. The
            # teardown completes first (kill, reap, drain, transport close all still run),
            # then the cancellation is re-raised after the transport is closed. The grace
            # waits' own expiry raises TimeoutError, which stays quiet as before.
            cancelled_in_teardown = False
            try:
                await asyncio.wait_for(asyncio.shield(proc.wait()), timeout=_REAP_GRACE_S)
            except asyncio.CancelledError:
                cancelled_in_teardown = True
            except BaseException:  # noqa: BLE001 - teardown must not mask the original exit
                pass
            if not pump_task.done():
                pump_task.cancel()
            try:
                await asyncio.wait_for(asyncio.shield(pump_task), timeout=_DRAIN_GRACE_S)
            except asyncio.CancelledError:
                cancelled_in_teardown = True
            except BaseException:  # noqa: BLE001 - the drain is best effort
                pass
            # Close the transport while the loop is still running. A descendant that escaped
            # the group kill can hold the pipe open, and the read fd would then leak on every
            # call; on the long-lived bridge loop that accumulates, and each surviving
            # transport later raises "Event loop is closed" from __del__ after the loop goes.
            transport = getattr(proc, "_transport", None)
            if transport is not None:
                try:
                    transport.close()
                except Exception:
                    pass
            if cancelled_in_teardown:
                raise asyncio.CancelledError()
        return self._report(proc.returncode, buffer.text(), timed_out)


__all__ = ["ShellVerifier"]
