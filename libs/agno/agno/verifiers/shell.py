"""ShellVerifier: run a shell command as the executable definition of done."""

import asyncio
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
from collections import deque
from io import BufferedReader
from typing import Any, Callable, Deque, Dict, Optional, cast

from agno.verifiers.base import validate_policy, validate_required_stop_on_failure
from agno.verifiers.types import Verdict

# Head and tail kept from a shell command's output, each side. Well above MAX_REPORT_BYTES,
# so the capped Verdict.report is byte-identical to what full buffering would produce; the
# middle of a very large output is dropped instead of held in memory.
_SHELL_KEEP_BYTES = 65536


class _BoundedOutput:
    """Bounded head-and-tail store for a stream: absorb() keeps the first and last
    _SHELL_KEEP_BYTES and drops the middle.

    Locked: the reader thread fills it and the caller reads it once the grace period is up,
    which may be while the reader is still going.
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

# Credentials in a command line; the derived name lands in the system message. Values are
# masked by their key name (password, secret, token, api key), a bearer header, or URL userinfo.
_URL_CREDENTIALS = re.compile(r"(://)[^/\s:@]+:[^/\s@]+@")
_SECRET_VALUE = r"(?:'[^']*(?:'|$)|\"[^\"]*(?:\"|$)|[^\s'\"]+)"
_ASSIGNED_SECRETS = re.compile(r"(?i)(\w*(?:password|passwd|secret|token|api[_-]?key)\w*=)" + _SECRET_VALUE)
_BEARER_TOKENS = re.compile(r"(?i)(bearer\s+)" + _SECRET_VALUE)


def _default_shell_name(command: str) -> str:
    """A name from the informative end of a command, not its first 40 characters.

    The form the cookbooks and tests use is `f"{sys.executable} -m pytest ..."`, and an absolute
    interpreter path eats the whole budget: two different checks both end up called
    "/Users/me/project/.venv/bin/python -m " and the model cannot tell which one failed.
    """
    text = _URL_CREDENTIALS.sub(r"\1***@", " ".join(command.split()))
    text = _BEARER_TOKENS.sub(r"\1***", _ASSIGNED_SECRETS.sub(r"\1***", text))
    try:
        tokens = shlex.split(text)
    except ValueError:
        tokens = text.split()
    if tokens and ("/" in tokens[0] or "\\" in tokens[0]):
        tokens[0] = os.path.basename(tokens[0])
    return (" ".join(tokens) if tokens else text)[:_SHELL_NAME_BYTES] or "shell"


def _command_tokens(command: Any) -> list:
    if not isinstance(command, str):
        raise TypeError(f"ShellVerifier command must be a str, got {type(command).__name__}")
    try:
        tokens = shlex.split(command, comments=True)
    except ValueError:
        tokens = command.split()
    return tokens


# How long to wait for the killed group to be reaped, and for the reader to hand over what it
# already has. Both are teardown budgets, not part of the command's own deadline.
_REAP_GRACE_SECONDS = 5.0
_DRAIN_GRACE_SECONDS = 5.0


class ShellVerifier:
    """Run a shell command; exit code 0 passes and the merged output is the evidence.

    .. warning::
        The command runs on the host with no sandboxing: anything the agent can write (a test
        file, a ``conftest.py``) can pass the check, so run it from a directory the agent cannot write.

    The command's process group is killed and reaped on every exit path. Exit codes 126 and 127
    are harness errors that end the run for a required check. ``env`` is merged over the current
    environment unless ``inherit_env=False``. The default name is the command's tail with
    credentials masked.
    """

    def __init__(
        self,
        command: str,
        *,
        cwd: Optional[str] = None,
        timeout: float = 120.0,
        env: Optional[Dict[str, str]] = None,
        inherit_env: bool = True,
        name: Optional[str] = None,
        required: bool = True,
        max_retries: int = 0,
        run_condition: Optional[Callable[..., Any]] = None,
        stop_on_failure: bool = False,
    ) -> None:
        if not _command_tokens(command):
            raise ValueError(f"ShellVerifier command must not be empty, got {command!r}")
        if not timeout > 0:
            raise ValueError(f"ShellVerifier timeout must be positive, got {timeout!r}")
        self.command = command
        self.cwd = cwd
        self.timeout = timeout
        self.env = env
        self.inherit_env = bool(inherit_env)
        self.name = name or _default_shell_name(command)
        validate_policy(max_retries, run_condition, label=f"ShellVerifier {self.name!r}")
        self.required = bool(required)
        self.max_retries = int(max_retries)
        self.run_condition = run_condition
        self.stop_on_failure = bool(stop_on_failure)
        validate_required_stop_on_failure(self.required, self.stop_on_failure, label=f"ShellVerifier {self.name!r}")

    def _env(self) -> Dict[str, str]:
        merged = dict(os.environ) if self.inherit_env else {}
        if self.env:
            merged.update(self.env)
        return merged

    def _report(self, returncode: Optional[int], output: str, timed_out: bool) -> Verdict:
        harness_error = (not timed_out) and returncode in _HARNESS_EXIT_CODES
        if timed_out:
            first = f"timed out after {self.timeout:g}s"
        elif harness_error:
            first = f"harness error: exit {returncode} (command not found or not executable)"
        else:
            first = f"exit {returncode}"
        passed = (not timed_out) and returncode == 0
        report = "" if passed else f"{first}\n{output}".rstrip()
        return Verdict(
            passed=passed,
            report=report,
            name=self.name,
            detail={"returncode": returncode, "timed_out": timed_out},
            fatal=harness_error,
        )

    def _launch_failure(self, exc: BaseException) -> Verdict:
        # The command never started (missing cwd, unusable shell): the model's next attempt
        # cannot fix that, so it ends the run like exit 126/127 instead of spending attempts.
        return Verdict(
            passed=False,
            report=f"harness error: {type(exc).__name__}: {exc}",
            name=self.name,
            detail={"returncode": None, "timed_out": False},
            fatal=True,
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
        return self._run({})

    async def averify(self, run_output: Any, run_context: Any = None) -> Verdict:
        started: Dict[str, Any] = {}
        try:
            return await asyncio.to_thread(self._run, started)
        except asyncio.CancelledError:
            # The worker thread cannot be cancelled; killing the group ends its wait at once.
            started["cancelled"] = True
            if "proc" in started:
                self._kill_group(started["proc"].pid)
            raise

    def _run(self, started: Dict[str, Any]) -> Verdict:
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
            return self._launch_failure(exc)
        started["proc"] = proc
        if started.get("cancelled"):
            self._kill_group(proc.pid)
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
                # The deadline measures the leader's exit, not pipe close: a background child
                # holding stdout must not turn a finished command into a timeout.
                proc.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
        finally:
            # Always, on every exit path including Ctrl-C: the group never outlives the
            # verifier. This also closes the write end of the pipe, which is what lets the
            # reader thread finish when a descendant was holding it open.
            self._kill_group(proc.pid)
            try:
                proc.wait(timeout=_REAP_GRACE_SECONDS)
            except Exception:
                pass
        reader.join(timeout=_DRAIN_GRACE_SECONDS)
        if not reader.is_alive():
            # Only once the drain finished: close() takes the buffer lock read1() holds, so a
            # descendant keeping the pipe would block here for its whole life.
            try:
                if proc.stdout is not None:
                    proc.stdout.close()
            except Exception:
                pass
        return self._report(proc.returncode, buffer.text(), timed_out)
