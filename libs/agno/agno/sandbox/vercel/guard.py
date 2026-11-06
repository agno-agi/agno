"""Guest side of the Vercel sandbox, run as root inside the box: ``python -I -m agno.sandbox.vercel.guard COMMAND``.

Standard library at module level; capture, restore and the digest import the shared package, which the
guest's own interpreter has installed. The host stages every request as a file the guard reads and
removes, and the guard answers with one JSON line.

``exec NAME`` hands a staged command request to the shared runner as the unprivileged agent user.
``capture NAME`` and ``restore NAME`` move a checkpoint archive out of or into the agent's two roots,
and ``remove NAME`` deletes an export. ``digest``, ``finish NAME`` and ``ready`` belong to the bootstrap
(``archive`` is the capture's own child). Only ``digest``, ``finish`` and ``ready`` act without the
bootstrap's root-owned marker.

A command holds a shared lock while it runs; capture and restore hold the exclusive one, so neither can
start while a command runs and no command starts during either. Capture stops the agent user's
processes after journaling each one, so an interrupted capture is undone by the next operation.
"""

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import pwd
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Sequence, Set, Tuple

PYTHON = "/opt/agno/venv/bin/python"
READY = "/opt/agno/READY"
INBOX = "/opt/agno/inbox"
EXPORT = "/opt/agno/export"
WORKSPACE = "/workspace"
HOME = "/runtime"
# The unprivileged identity every command runs as; the guest bootstrap creates it.
AGENT_UID = AGENT_GID = 2001
# The user Vercel's file API writes as, which is who may stage a request.
STAGED_UID = 1000
# A staged runner request: up to 8 MiB of command stdin, which grows by a third as base64, plus argv.
MAX_STAGED = 12 * 1024 * 1024
# Largest bootstrap marker the guard will print.
MAX_MARKER = 64 * 1024
# Largest checkpoint archive the guard will move, whatever limit a request names.
MAX_ARCHIVE = 2 * 1024 * 1024 * 1024
# Largest environment file the bootstrap may install.
MAX_ENV = 256 * 1024
# Exit status of a guard that refused before launching anything, so the host knows nothing ran.
REFUSED = 75
CONTENT_REJECTED = 65  # Archive child rejected the files (sysexits EX_DATAERR).
REFUSAL_PREFIX = "Vercel computer refusing to run: "
_NAME = re.compile(r"[0-9a-f]{32}")
# Variables the computer sets itself; the environment a user supplies cannot replace them.
MANAGED_ENVIRONMENT = ("PATH", "HOME")
_PASSED_ENVIRONMENT = ("LANG", "LC_ALL", "TZ")


@dataclass(frozen=True)
class Layout:
    """Where the guard keeps its state; the defaults are the guest's, a test points them at a temporary tree."""

    control: Path = Path("/opt/agno/control")
    inbox: Path = Path(INBOX)
    export: Path = Path(EXPORT)
    stage: Path = Path("/opt/agno/stage")
    ready: Path = Path(READY)
    env_file: Path = Path("/opt/agno/ENV")
    workspace: Path = Path(WORKSPACE)
    runtime: Path = Path(HOME)
    agent_uid: int = AGENT_UID
    agent_gid: int = AGENT_GID
    staged_uid: int = STAGED_UID
    trusted_uid: int = 0

    @property
    def native(self) -> Path:
        return self.runtime / "native"

    @property
    def roots(self) -> Dict[str, Path]:
        return {"workspace": self.workspace, "native": self.native}


class Refused(Exception):
    """The guard declined before changing what the request asked it to change."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


class Unsupported(RuntimeError):
    """The kernel cannot signal a process by a stable handle: refuse rather than signal by pid alone."""


def _refuse(reason: str) -> int:
    sys.stderr.write(REFUSAL_PREFIX + reason + "\n")
    return REFUSED


def source_digest(package: Path) -> str:
    """One digest of the Python source of an installed ``agno`` package, the same on host and guest."""
    digest = hashlib.sha256()
    for path in sorted(package.rglob("*.py")):
        relative = path.relative_to(package)
        if "__pycache__" in relative.parts or not path.is_file():
            continue
        digest.update(relative.as_posix().encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


# Reading what the host or the bootstrap left


def _read_root_file(path: Path, trusted_uid: int, limit: int, refusal: str) -> bytes:
    """One regular file only ``trusted_uid`` can have written."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise Refused("not-ready", refusal) from error
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_uid != trusted_uid or status.st_mode & 0o022:
            raise Refused("not-ready", refusal)
        return os.read(descriptor, limit)
    finally:
        os.close(descriptor)


def _read_marker(ready: Path, trusted_uid: int) -> bytes:
    """The bootstrap's marker, if it is one regular file only ``trusted_uid`` can have written."""
    return _read_root_file(ready, trusted_uid, MAX_MARKER, "guest is not ready")


def _read_environment(layout: Layout) -> Dict[str, str]:
    """The environment the bootstrap installed for the agent's processes; no file means none."""
    if not os.path.lexists(layout.env_file):
        return {}
    raw = _read_root_file(layout.env_file, layout.trusted_uid, MAX_ENV + 1, "environment file is not trustworthy")
    try:
        values = json.loads(raw) if len(raw) <= MAX_ENV else None
    except ValueError:
        values = None
    if not isinstance(values, dict) or not all(
        isinstance(k, str) and k and "=" not in k and "\0" not in k and isinstance(v, str) and "\0" not in v
        for k, v in values.items()
    ):
        raise Refused("not-ready", "environment file is malformed")
    return {k: v for k, v in values.items() if k not in MANAGED_ENVIRONMENT}


def _open_staged(path: Path, staged_uid: int, limit: int, what: str) -> int:
    """A file the host staged: one regular, private file of the staging user, never the agent's."""
    try:
        # O_NONBLOCK so that a FIFO planted at the path cannot hold the guard; it is refused below.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise Refused("not-staged", f"staged {what} is missing or unreadable") from error
    try:
        status = os.fstat(descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_nlink != 1 or status.st_size > limit:
            raise Refused("not-staged", f"staged {what} is not one regular file within the size limit")
        # The agent uid is refused outright, whatever staged_uid says: it must never stage anything.
        if status.st_uid != staged_uid or status.st_uid == AGENT_UID or status.st_mode & 0o077:
            raise Refused("not-staged", f"staged {what} is not private to the staging user")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _take_json(layout: Layout, name: str, what: str) -> Dict[str, Any]:
    """Read and remove a staged JSON request, removed whatever the outcome: a request not run now is never run later."""
    path = layout.inbox / (name + ".json")
    try:
        descriptor = _open_staged(path, layout.staged_uid, MAX_STAGED, what)
    finally:
        with suppress(OSError):
            os.unlink(path)
    try:
        value = json.loads(os.read(descriptor, MAX_STAGED))
    except ValueError as error:
        raise Refused("not-staged", f"staged {what} is not JSON") from error
    finally:
        os.close(descriptor)
    if not isinstance(value, dict):
        raise Refused("not-staged", f"staged {what} is not an object")
    return value


# Processes


def parse_stat(text: str) -> Optional[Dict[str, Any]]:
    """Split a ``/proc/PID/stat`` line after its last ``)``: the command name may hold spaces and parentheses."""
    try:
        head, tail = text.rsplit(")", 1)
        fields = tail.split()
        state, ppid, start = fields[0], int(fields[1]), fields[19]
    except (IndexError, ValueError):
        return None
    return None if state == "Z" else {"state": state, "ppid": ppid, "start": start}


class LinuxOps:
    """Process identity and signalling on Linux.

    A process is identified by the boot id and its start time in ticks and signalled through a pidfd;
    where one is unavailable the operation is refused, never done by pid alone.
    """

    def __init__(self, proc: str = "/proc") -> None:
        self.proc = Path(proc)
        self.boot_id = (self.proc / "sys/kernel/random/boot_id").read_text().strip()

    def _stat(self, pid: int) -> Optional[Dict[str, Any]]:
        try:
            return parse_stat((self.proc / str(pid) / "stat").read_text())
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            return None

    def identity(self, pid: int) -> Optional[str]:
        status = self._stat(pid)
        return None if status is None else f"{self.boot_id}:{status['start']}"

    def state(self, pid: int) -> str:
        status = self._stat(pid)
        return "" if status is None else str(status["state"])

    def ancestors(self, pid: int) -> List[int]:
        chain = [pid]
        while chain[-1] > 1:
            status = self._stat(chain[-1])
            if status is None or status["ppid"] in chain:
                break
            chain.append(status["ppid"])
        return chain

    def uid_of(self, pid: int) -> Optional[int]:
        try:
            for line in (self.proc / str(pid) / "status").read_text().splitlines():
                if line.startswith("Uid:"):
                    return int(line.split()[1])
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            return None
        return None

    def select(self, uid: int, exclude: Set[int]) -> List[int]:
        """Processes whose real uid is ``uid``, less the excluded, zombies and kernel threads."""
        found = []
        for entry in self.proc.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            if pid in exclude or self.uid_of(pid) != uid:
                continue
            status = self._stat(pid)
            if status is None or status["ppid"] == 2:
                continue
            found.append(pid)
        return sorted(found)

    def signal(self, pid: int, ident: str, sig: int) -> bool:
        if not hasattr(os, "pidfd_open") or not hasattr(signal, "pidfd_send_signal"):
            raise Unsupported("pidfd is not available in this Python or kernel")
        try:
            descriptor = os.pidfd_open(pid)
        except ProcessLookupError:
            return False
        except OSError as error:
            raise Unsupported(f"pidfd_open failed: {error}") from error
        try:
            # The descriptor now names whatever owns this pid; signal only the process that was recorded.
            if self.identity(pid) != ident:
                return False
            try:
                signal.pidfd_send_signal(descriptor, sig)
            except ProcessLookupError:
                return False
            except PermissionError as error:
                raise Unsupported("pidfd_send_signal denied") from error
            return True
        finally:
            os.close(descriptor)


# The checkpoint window


def _fingerprint(roots: Mapping[str, Path]) -> Tuple[str, int]:
    """A digest of the trees' metadata, and the newest change time in them. Change time, not modification
    time, bounds "recent": only the kernel sets it, where the agent can date a file into the future."""
    digest = hashlib.sha256()
    newest = 0

    def walk(path: Path, name: str) -> None:
        nonlocal newest
        status = path.lstat()
        newest = max(newest, status.st_ctime_ns)
        link = os.readlink(path) if stat.S_ISLNK(status.st_mode) else ""
        digest.update(
            repr(
                (
                    name,
                    status.st_mode,
                    status.st_ino,
                    status.st_dev,
                    status.st_size,
                    status.st_mtime_ns,
                    status.st_ctime_ns,
                    status.st_nlink,
                    status.st_uid,
                    status.st_gid,
                    link,
                )
            ).encode()
        )
        if stat.S_ISDIR(status.st_mode):
            for child in sorted(path.iterdir()):
                walk(child, name + "/" + child.name)

    for name in sorted(roots):
        walk(Path(roots[name]), name)
    return digest.hexdigest(), newest


# The runtime reports a dispatch it never saw start as lost after this long.
_DISPATCH_GRACE = 30.0


def _in_flight(job: str, worker_alive: Callable[[int, str], bool]) -> bool:
    """Whether a job with a request and no result may still be running, by the runtime's own rules for calling it lost."""
    try:
        descriptor = os.open(os.path.join(job, "status.json"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            status = json.loads(os.read(descriptor, 64 * 1024))
        finally:
            os.close(descriptor)
        if status["phase"] == "running":
            return worker_alive(int(status["pid"]), str(status["start"]))
        if status["phase"] == "starting":
            return time.time() - float(status["created_at"]) <= _DISPATCH_GRACE
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return True  # state that cannot be read is not evidence that nothing runs


def runtime_idle(runtime: Path, worker_alive: Callable[[int, str], bool]) -> None:
    """Refuse unless the runtime has no turn in flight: the execution lock is free and every job has a result or a lost worker."""
    try:
        jobs = list(os.scandir(runtime / "jobs"))
    except FileNotFoundError:
        jobs = []
    for job in jobs:
        if job.is_symlink() or not job.is_dir(follow_symlinks=False):
            raise Refused("active-execution", "the runtime's jobs directory holds something unexpected")
        if (
            os.path.lexists(os.path.join(job.path, "request.json"))
            and not os.path.lexists(os.path.join(job.path, "result.json"))
            and _in_flight(job.path, worker_alive)
        ):
            raise Refused("active-execution", f"runtime job {job.name[:8]} has no result yet")
    try:
        descriptor = os.open(runtime / "execution.lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return
    except OSError as error:
        raise Refused("active-execution", "the runtime's execution lock is not a plain file") from error
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise Refused("active-execution", "the runtime's execution lock is held") from error
        fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


class Guard:
    """One computer's admission and quiescence.

    Locks (``flock``, so the kernel drops them when the holder dies): ``admission.lock`` is exclusive and
    held only for short critical sections, the only lock anyone waits for. ``command.lock`` is shared for
    the life of an admitted command and exclusive for a capture or restore, and is only ever tried.
    Admission is always taken first. State lives in ``state.json`` (absent is ``fresh``, then ``used``,
    ``restoring``, ``failed``), replaced atomically under admission. The freeze journal is appended and
    synced before each signal it announces, so recovery knows everything that may have been stopped.
    """

    def __init__(
        self,
        layout: Layout = Layout(),
        *,
        ops: Any = None,
        hook: Optional[Callable[[str], None]] = None,
        admission_wait: float = 5.0,
        idle_wait: float = 3.0,
    ) -> None:
        self.layout, self._ops, self.hook, self.admission_wait = layout, ops, hook, admission_wait
        self.idle_wait = idle_wait  # how long capture waits for a turn that is winding down
        self._unsent: Set[Tuple[int, str]] = set()  # intents whose SIGSTOP was refused before it could be sent
        self.freeze_deadline = 5.0  # whole-freeze bound
        self.stop_wait = 2.0  # how long a signalled process may take to reach a stopped state
        self.settle_ns = 30_000_000  # how old the newest change must be before the archive is taken
        self.settle_limit = 2.0  # how long to wait for the roots to settle
        layout.control.mkdir(mode=0o700, parents=True, exist_ok=True)

    @property
    def ops(self) -> Any:
        if self._ops is None:
            self._ops = LinuxOps()
        return self._ops

    def _hit(self, point: str) -> None:
        if self.hook:
            self.hook(point)

    # State

    @property
    def _state_path(self) -> Path:
        return self.layout.control / "state.json"

    @property
    def _journal(self) -> Path:
        return self.layout.control / "freeze.journal"

    def _fsync_directory(self) -> None:
        descriptor = os.open(self.layout.control, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def state(self) -> str:
        try:
            return str(json.loads(self._state_path.read_text())["state"])
        except FileNotFoundError:
            return "fresh"

    def _write_state(self, value: str) -> None:
        for orphan in self.layout.control.glob("state.json.*.tmp"):
            orphan.unlink()  # a writer that died; admission serializes writers
        descriptor, temporary = tempfile.mkstemp(dir=self.layout.control, prefix="state.json.", suffix=".tmp")
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json.dumps({"state": value}).encode())
            stream.flush()
            os.fsync(stream.fileno())
        self._hit("state_before_replace")
        os.replace(temporary, self._state_path)
        self._fsync_directory()

    # Locks

    @contextmanager
    def _admission(self) -> Iterator[None]:
        descriptor = os.open(self.layout.control / "admission.lock", os.O_RDWR | os.O_CREAT, 0o600)
        deadline = time.monotonic() + self.admission_wait
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    os.close(descriptor)
                    raise Refused("busy", "the admission lock is not available") from None
                time.sleep(0.002)
        try:
            yield
        finally:
            os.close(descriptor)

    def _try_command(self, exclusive: bool) -> int:
        descriptor = os.open(self.layout.control / "command.lock", os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(descriptor)
            raise Refused("busy", "a command or a checkpoint window holds the computer") from None
        return descriptor

    # Freeze journal

    def _append(self, record: Dict[str, Any]) -> None:
        line = (json.dumps(record) + "\n").encode()
        new = not self._journal.exists()
        descriptor = os.open(self._journal, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            # A write may be accepted in part; the record must be whole and synced before its process is signalled.
            pending = memoryview(line)
            while pending:
                written = os.write(descriptor, pending)
                if written <= 0:
                    raise OSError(errno.EIO, "the freeze journal accepted no bytes")
                pending = pending[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if new:
            self._fsync_directory()

    def _entries(self) -> List[Dict[str, Any]]:
        try:
            raw = self._journal.read_text()
        except FileNotFoundError:
            return []
        records = []
        for line in raw.split("\n"):
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except ValueError:
                pass  # a torn tail: its signal was never sent, because the append had not finished
        return records

    def _worker_alive(self, pid: int, start: str) -> bool:
        identity = self.ops.identity(pid)
        return identity is not None and identity.rpartition(":")[2] == start

    def _stopped(self, pid: int) -> bool:
        return self.ops.state(pid).startswith(("T", "t"))

    def _thaw(self, entries: Sequence[Dict[str, Any]]) -> None:
        """Resume what the journal says may have been stopped, if it is still the same process.

        Not only the processes seen stopped: an accepted SIGSTOP can still be pending, and generating SIGCONT
        discards a pending stop signal, which nothing else will once the journal is gone.
        """
        for record in entries:
            if record.get("op") != "intent":
                continue
            pid, ident = record["pid"], record["id"]
            if self.ops.identity(pid) != ident or (pid, ident) in self._unsent:
                continue
            self.ops.signal(pid, ident, signal.SIGCONT)

    def _drop_journal(self) -> None:
        self._journal.unlink(missing_ok=True)
        self._fsync_directory()

    def _recover_locked(self) -> None:
        """Undo an interrupted capture or restore. The caller holds admission and a try-lock on the command lock."""
        if self._journal.exists():
            entries = self._entries()
            for record in entries:  # an export from a capture that never finished is unverified
                if record.get("op") == "export":
                    Path(record["path"]).unlink(missing_ok=True)
            self._thaw(entries)
            self._drop_journal()
        if self.state() in ("restoring", "failed") and self.layout.stage.exists():
            shutil.rmtree(self.layout.stage, ignore_errors=True)

    # Freezing

    def _select(self, exclude: Set[int]) -> List[int]:
        return list(self.ops.select(self.layout.agent_uid, exclude))

    def _freeze(self) -> None:
        """Stop every agent process, then prove the window: all that were signalled are stopped and one more pass finds nothing new."""
        mine = set(self.ops.ancestors(os.getpid()))
        deadline = time.monotonic() + self.freeze_deadline
        handled: Set[Tuple[int, str]] = set()
        ours: Dict[int, str] = {}
        while True:
            if time.monotonic() > deadline:
                raise Refused("unstable-freeze", "the agent's processes did not settle in time")
            found = []
            for pid in self._select(mine):
                ident = self.ops.identity(pid)
                # Keyed by identity, not pid: a pid the kernel reuses is a new process and is stopped too.
                if ident is not None and (pid, ident) not in handled:
                    handled.add((pid, ident))
                    found.append((pid, ident))
            for pid, ident in found:
                if self._stopped(pid):
                    continue  # stopped by somebody else: not ours to resume, so not journaled
                self._append({"op": "intent", "pid": pid, "id": ident})  # durable before the signal
                try:
                    sent = self.ops.signal(pid, ident, signal.SIGSTOP)
                except Unsupported as error:
                    self._unsent.add((pid, ident))  # nothing was sent, so the cleanup has nothing to cancel
                    raise Refused("unsupported", str(error)) from error
                if sent:
                    ours[pid] = ident
            # SIGSTOP is asynchronous: a process in uninterruptible sleep stops once it is back in user space.
            wait_until = min(deadline, time.monotonic() + self.stop_wait)
            while any(self.ops.identity(p) == i and not self._stopped(p) for p, i in ours.items()):
                if time.monotonic() > wait_until:
                    raise Refused("unstable-freeze", "a signalled process did not stop")
                time.sleep(0.002)
            if not found:
                return

    def _settled_fingerprint(self) -> str:
        """A first scan taken once every change time it records is at least ``settle_ns`` old, so a later change must carry a newer one."""
        end = time.monotonic() + self.settle_limit
        while True:
            start = time.time_ns()
            digest, newest = _fingerprint(self.layout.roots)
            if newest + self.settle_ns <= start:
                return digest
            remaining = end - time.monotonic()
            if remaining <= 0:
                raise Refused("unstable", "the roots keep changing")
            time.sleep(min(max((newest + self.settle_ns - time.time_ns()) / 1e9, 0.002), remaining))

    # Operations

    @contextmanager
    def admit(self) -> Iterator[None]:
        """Hold the computer for one command: shared, for as long as the command runs."""
        with self._admission():
            descriptor = self._try_command(False)
            try:
                self._recover_locked()
                current = self.state()
                if current in ("restoring", "failed"):
                    raise Refused(current, f"the computer is {current} and must be replaced")
                if current == "fresh":
                    self._write_state("used")
            except BaseException:
                os.close(descriptor)
                raise
        try:
            yield
        finally:
            os.close(descriptor)

    def _hold_idle_computer(self) -> int:
        """Take the exclusive command lock once the runtime is idle, waiting a moment for a turn that is finishing."""
        deadline = time.monotonic() + self.idle_wait
        while True:
            with self._admission():
                exclusive = self._try_command(True)
                try:
                    self._recover_locked()
                    if self.state() in ("restoring", "failed"):
                        raise Refused(self.state(), "the computer is not usable")
                    # While no command can be admitted, so a new turn cannot start between the check and the freeze.
                    runtime_idle(self.layout.runtime, self._worker_alive)
                    return exclusive
                except Refused as refusal:
                    os.close(exclusive)
                    if refusal.code != "active-execution" or time.monotonic() >= deadline:
                        raise
                except BaseException:
                    os.close(exclusive)
                    raise
            time.sleep(0.05)  # not under any lock: the runtime's worker needs none to finish

    def capture(
        self,
        name: str,
        job: Mapping[str, Any],
        *,
        run_archive: Callable[[int, Mapping[str, Any]], None],
    ) -> int:
        """Archive the roots into ``<export>/<name>.tar`` while the agent's processes are stopped; return its size."""
        target = self.layout.export / (name + ".tar")
        exclusive = self._hold_idle_computer()
        try:
            try:
                self._append({"op": "export", "path": str(target)})  # recovery removes an unfinished export
                self._freeze()
                before = self._settled_fingerprint()
                descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                try:
                    run_archive(descriptor, job)
                finally:
                    os.close(descriptor)
                if _fingerprint(self.layout.roots)[0] != before:
                    raise Refused("unstable", "the roots changed during capture")
                os.chown(target, self.layout.staged_uid, -1)  # the host reads it back as the file API user
                return target.stat().st_size
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            finally:
                self._thaw(self._entries())
                self._drop_journal()  # before the lock is released
        finally:
            os.close(exclusive)

    def restore(
        self, name: str, job: Mapping[str, Any], *, extract: Callable[[Path, Path], Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Fill the empty roots of an unused computer from the archive staged as ``<inbox>/<name>.tar``.

        Root extracts the archive inside a directory no agent process can reach, then the two roots are
        given to the agent user with no-follow changes and renamed into place. A failure after the first
        change leaves the computer ``failed``, so it can never run another turn.
        """
        limit = min(int(job.get("max_bytes", MAX_ARCHIVE)), MAX_ARCHIVE)
        staged = self.layout.inbox / (name + ".tar")
        with self._admission():
            exclusive = self._try_command(True)
            try:
                self._recover_locked()
                if self.state() != "fresh":
                    raise Refused("not-fresh", "restore needs an unused computer")
                for root in self.layout.roots.values():
                    if root.is_symlink() or not root.is_dir() or any(root.iterdir()):
                        raise Refused("not-empty", "restore needs empty roots")
                if self._select({os.getpid()}):
                    raise Refused("agent-processes", "restore needs a computer with no agent processes")
                # Checked before the first change, and held open: what is read is what was checked.
                source = _open_staged(staged, self.layout.staged_uid, limit, "archive")
            except BaseException:
                os.close(exclusive)
                raise
            try:
                self._write_state("restoring")
            except BaseException:
                os.close(source)
                os.close(exclusive)
                raise
        stage = self.layout.stage / name
        try:
            self._hit("restore_begin")
            self.layout.stage.mkdir(mode=0o700, exist_ok=True)
            stage.mkdir(mode=0o700)
            archive = stage / "in.tar"
            with suppress(OSError):
                os.unlink(staged)
            self._copy(source, archive, limit)
            result = extract(archive, stage / "out")
            self._hit("restore_extracted")
            self._publish(stage / "out")
            with self._admission():
                self._write_state("used")
            return result
        except BaseException:
            with suppress(Exception), self._admission():
                self._write_state("failed")
            raise
        finally:
            os.close(source)
            shutil.rmtree(stage, ignore_errors=True)
            os.close(exclusive)

    @staticmethod
    def _copy(source: int, destination: Path, limit: int) -> None:
        """Copy the staged archive into root-owned space, never more than ``limit`` bytes."""
        copied = 0
        with open(os.dup(source), "rb") as stream, destination.open("xb") as output:
            while chunk := stream.read(1024 * 1024):
                copied += len(chunk)
                if copied > limit:
                    raise Refused("not-staged", "staged archive grew past its size limit")
                output.write(chunk)

    def _publish(self, extracted: Path) -> None:
        """Check what extraction produced, hand it to the agent user, and rename the two roots into place."""
        names = sorted(entry.name for entry in os.scandir(extracted))
        if names != sorted(self.layout.roots) or any(not stat.S_ISDIR((extracted / n).lstat().st_mode) for n in names):
            raise Refused("bad-restore", "extraction did not produce exactly the two roots")
        if self._select({os.getpid()}):
            raise Refused("agent-processes", "an agent process appeared during restore")
        for root_name in names:
            _hand_over(extracted / root_name, self.layout.agent_uid, self.layout.agent_gid)
        for root_name, root in self.layout.roots.items():
            os.rmdir(root)
            os.rename(extracted / root_name, root)
            self._hit("restore_moved_one")


def _hand_over(root: Path, uid: int, gid: int) -> None:
    """Give a directory tree to ``uid`` without following any link, then make its root private."""
    for parent, directories, files in os.walk(root, followlinks=False):
        for entry in directories + files:
            os.chown(os.path.join(parent, entry), uid, gid, follow_symlinks=False)
    os.chown(root, uid, gid, follow_symlinks=False)
    os.chmod(root, 0o700)


# The commands


def _child_environment(environ: Mapping[str, str], extra: Optional[Mapping[str, str]] = None) -> Dict[str, str]:
    """What the agent's processes see: the user's variables over a small base. The sudo environment is not forwarded."""
    environment = {key: environ[key] for key in _PASSED_ENVIRONMENT if key in environ}
    environment.update(extra or {})
    environment["HOME"] = HOME
    environment["PATH"] = os.path.dirname(PYTHON) + ":/usr/local/bin:/usr/bin:/bin"
    return environment


def _no_new_privileges() -> None:
    # PR_SET_NO_NEW_PRIVS: setuid binaries cannot take a process back to root.
    if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "Could not disable privilege elevation")


def _as_agent(argv: List[str], uid: int, gid: int, **kwargs: Any) -> "subprocess.CompletedProcess[bytes]":
    """Run ``argv`` as the agent user: no supplementary groups, and no way back to root."""
    _no_new_privileges()
    return subprocess.run(argv, user=uid, group=gid, extra_groups=[], **kwargs)


def _spawn(descriptor: int, environment: Dict[str, str]) -> int:
    return _as_agent(
        [PYTHON, "-I", "-m", "agno.sandbox._exec"],
        AGENT_UID,
        AGENT_GID,
        stdin=descriptor,
        env=environment,
        cwd=WORKSPACE,
    ).returncode


def _exit_status(code: int) -> int:
    if code < 0:
        return 128 - code
    # Only this guard refuses; a runner that happened to exit 75 must not read as "nothing ran".
    return 1 if code == REFUSED else code


def run_exec(
    name: str,
    *,
    inbox: Path = Path(INBOX),
    ready: Path = Path(READY),
    trusted_uid: int = 0,
    staged_uid: int = STAGED_UID,
    spawn: Callable[[int, Dict[str, str]], int] = _spawn,
    guard: Optional[Guard] = None,
) -> int:
    """Run the request staged as ``<inbox>/<name>.json`` as the agent user and return its exit status."""
    if _NAME.fullmatch(name) is None:
        return _refuse("invalid staged request name")
    path = inbox / (name + ".json")
    try:
        _read_marker(ready, trusted_uid)
        descriptor = _open_staged(path, staged_uid, MAX_STAGED, "request")
    except Refused as refusal:
        return _refuse(str(refusal))
    finally:
        # Removed before anything runs, refused or not: a request not run now is never run later.
        with suppress(OSError):
            os.unlink(path)
    try:
        extra = _read_environment(guard.layout) if guard is not None else {}
        environment = _child_environment(os.environ, extra)
        if guard is None:
            return _exit_status(spawn(descriptor, environment))
        with guard.admit():
            return _exit_status(spawn(descriptor, environment))
    except Refused as refusal:
        return _refuse(f"{refusal.code}: {refusal}")
    finally:
        os.close(descriptor)


def run_ready(*, ready: Path = Path(READY), trusted_uid: int = 0) -> int:
    """Print the bootstrap's marker if it is trustworthy; the host decides what it means."""
    try:
        marker = _read_marker(ready, trusted_uid)
    except Refused as refusal:
        return _refuse(str(refusal))
    sys.stdout.write(marker.decode("utf-8", errors="replace"))
    return 0


def run_digest() -> int:
    import agno

    sys.stdout.write(json.dumps({"source_digest": source_digest(Path(agno.__file__).parent)}))
    return 0


_CHECK = """
import importlib.metadata as metadata, json, shutil, sys, tempfile
import agno.sandbox.runtime, claude_agent_sdk, openai_codex
from agno.db.sqlite import SqliteDb
with tempfile.TemporaryDirectory() as directory:
    SqliteDb(db_file=directory + "/check.db")
print(json.dumps({
    "python": sys.version.split()[0],
    "agno": metadata.version("agno"),
    "claude-agent-sdk": metadata.version("claude-agent-sdk"),
    "openai-codex": metadata.version("openai-codex"),
    "sqlalchemy": metadata.version("sqlalchemy"),
    "git": shutil.which("git") is not None,
}))
"""


def run_check(layout: Layout = Layout()) -> Dict[str, Any]:
    """Import the runtime, both native SDKs and the lazy SQLite adapter as the agent user; report what is installed."""
    result = _as_agent(
        [PYTHON, "-I", "-c", _CHECK],
        layout.agent_uid,
        layout.agent_gid,
        env=_child_environment(os.environ),
        cwd="/",
        capture_output=True,
        timeout=300,
    )
    if result.returncode:
        raise RuntimeError("readiness check failed: " + result.stderr.decode(errors="replace")[-1500:])
    return dict(json.loads(result.stdout))


def _ensure_agent(layout: Layout) -> None:
    try:
        entry = pwd.getpwuid(layout.agent_uid)
    except KeyError:
        subprocess.run(
            [
                "useradd",
                "--uid",
                str(layout.agent_uid),
                "--user-group",
                "--no-create-home",
                "--home-dir",
                str(layout.runtime),
                "--shell",
                "/usr/sbin/nologin",
                "agent",
            ],
            check=True,
            capture_output=True,
        )
        return
    if entry.pw_gid != layout.agent_gid:
        raise RuntimeError("the agent uid exists with an unexpected group")


def _private_directory(path: Path, uid: int, gid: int = -1) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, 0o700)


def _write_root_file(path: Path, data: bytes, mode: int) -> None:
    temporary = path.with_name(path.name + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, mode)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def run_finish(name: str, layout: Layout = Layout(), *, check: Callable[[Layout], Dict[str, Any]] = run_check) -> int:
    """Finish the bootstrap: users and directories, the agent's environment, and last of all the marker."""
    spec = _take_json(layout, name, "bootstrap request")
    environment, marker = spec.get("env"), spec.get("marker")
    if not isinstance(marker, dict) or not isinstance(environment, dict):
        return _refuse("bootstrap request is malformed")
    if layout.ready.exists():
        return _refuse("the computer is already bootstrapped")
    _ensure_agent(layout)
    layout.ready.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chmod(layout.ready.parent, 0o755)
    root = layout.trusted_uid
    _private_directory(layout.control, root)
    _private_directory(layout.stage, root)
    _private_directory(layout.inbox, layout.staged_uid)
    _private_directory(layout.export, layout.staged_uid)
    for directory in (layout.workspace, layout.runtime, layout.native):
        _private_directory(directory, layout.agent_uid, layout.agent_gid)
    _write_root_file(layout.env_file, json.dumps(environment).encode(), 0o600)
    marker = {**marker, "installed": check(layout)}
    # Last of all: a computer that did not get this far is never reported ready.
    _write_root_file(layout.ready, json.dumps(marker).encode(), 0o644)
    return 0


def _archive_child() -> int:
    """Run as the agent user: write one checkpoint archive of the two roots to stdout."""
    from agno.sandbox.checkpoint import CheckpointArchive, CheckpointContentError, CheckpointLimits

    job = json.loads(sys.stdin.buffer.read())
    roots = {name: Path(path) for name, path in job["roots"].items()}
    archive = CheckpointArchive(CheckpointLimits(**job["limits"]))
    with tempfile.TemporaryDirectory(prefix="agno-capture-") as directory:
        output = Path(directory) / "checkpoint.tar"
        try:
            archive.capture(roots, output, state=job["state"], exclude=job["exclude"])
        except CheckpointContentError as error:
            # Classify by status, never by text derived from the agent's files.
            sys.stderr.write(str(error)[:1500] + "\n")
            return CONTENT_REJECTED
        with output.open("rb") as stream:
            shutil.copyfileobj(stream, sys.stdout.buffer)
        sys.stdout.buffer.flush()
    return 0


def _run_archive(layout: Layout) -> Callable[[int, Mapping[str, Any]], None]:
    def run(descriptor: int, job: Mapping[str, Any]) -> None:
        request = json.dumps(
            {
                "roots": {name: str(path) for name, path in layout.roots.items()},
                "state": job["state"],
                "exclude": job["exclude"],
                "limits": job["limits"],
            }
        ).encode()
        child = _as_agent(
            [PYTHON, "-I", "-m", "agno.sandbox.vercel.guard", "archive"],
            layout.agent_uid,
            layout.agent_gid,
            input=request,
            stdout=descriptor,
            stderr=subprocess.PIPE,
            cwd="/",
            env=_child_environment(os.environ),
            timeout=1800,
        )
        if child.returncode == CONTENT_REJECTED:
            raise Refused("content", child.stderr.decode(errors="replace")[:1500].strip())
        if child.returncode:
            raise RuntimeError("checkpoint capture failed: " + child.stderr.decode(errors="replace")[-1500:])

    return run


def _extract(limits: Mapping[str, Any]) -> Callable[[Path, Path], Dict[str, Any]]:
    def extract(archive: Path, destination: Path) -> Dict[str, Any]:
        from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits

        # Absolute targets belong to this computer; host-side restores retain the shared safe default.
        return CheckpointArchive(CheckpointLimits(**limits)).restore(archive, destination, absolute_links=True)

    return extract


def _check_job(job: Mapping[str, Any], keys: Sequence[str]) -> None:
    if not all(key in job for key in keys) or not isinstance(job.get("limits"), dict):
        raise Refused("not-staged", "staged checkpoint request is incomplete")


def run_capture(name: str, layout: Layout = Layout()) -> int:
    job = _take_json(layout, name, "capture request")
    _check_job(job, ("state", "exclude", "limits"))
    size = Guard(layout).capture(name, job, run_archive=_run_archive(layout))
    sys.stdout.write(json.dumps({"size": size}))
    return 0


def run_restore(name: str, layout: Layout = Layout()) -> int:
    job = _take_json(layout, name, "restore request")
    _check_job(job, ("limits",))
    job = {**job, "max_bytes": job["limits"].get("max_bytes", MAX_ARCHIVE)}
    state = Guard(layout).restore(name, job, extract=_extract(job["limits"]))
    sys.stdout.write(json.dumps({"state": state}))
    return 0


def run_remove(name: str, layout: Layout = Layout()) -> int:
    (layout.export / (name + ".tar")).unlink(missing_ok=True)
    return 0


def _guarded(command: Callable[[], int]) -> int:
    try:
        return command()
    except Refused as refusal:
        return _refuse(f"{refusal.code}: {refusal}")
    except Exception as error:
        sys.stderr.write(f"{type(error).__name__}: {error}\n")
        return 1


def main(argv: List[str]) -> int:
    layout = Layout()
    if len(argv) == 3 and argv[1] == "exec":
        return run_exec(argv[2], guard=Guard(layout))
    if len(argv) == 2 and argv[1] == "ready":
        return run_ready()
    if len(argv) == 2 and argv[1] == "digest":
        return _guarded(run_digest)
    if len(argv) == 2 and argv[1] == "archive":
        return _guarded(_archive_child)
    if len(argv) == 3 and argv[1] == "finish" and _NAME.fullmatch(argv[2]):
        return _guarded(lambda: run_finish(argv[2], layout))
    if len(argv) == 3 and argv[1] in ("capture", "restore", "remove") and _NAME.fullmatch(argv[2]):
        # Marker first: nothing here runs on a computer whose bootstrap did not finish.
        try:
            _read_marker(layout.ready, layout.trusted_uid)
        except Refused as refusal:
            return _refuse(str(refusal))
        commands = {"capture": run_capture, "restore": run_restore, "remove": run_remove}
        return _guarded(lambda: commands[argv[1]](argv[2], layout))
    sys.stderr.write(
        "usage: python -I -m agno.sandbox.vercel.guard exec|capture|restore|remove|finish NAME | ready | digest\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
