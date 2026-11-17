"""Runs as root inside an Agent 37 instance; its source is sent whole with every exec command.

Standard library only, so it works on any image with python3. The exec API takes
one shell command with no stdin and returns at most 512 KB of each stream, so
anything larger is staged as a file in a root-only directory and moved in chunks.
Commands and checkpoint work run as UID/GID 1000 in /workspace with HOME=/runtime,
the same user and directories the Docker and AgentCore sandboxes use.
"""

import base64
import ctypes
import hashlib
import json
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, BinaryIO, Dict, List

_CONTROL = Path("/var/lib/agno-agent37")
_WORKSPACE, _RUNTIME = Path("/workspace"), Path("/runtime")
_USER = 1000
_GROUP = 1000
# The interpreter command line for processes this script starts.
_PYTHON = [sys.executable, "-I"]
# A reply this small travels with the command's own response; a larger one is read back in chunks.
_INLINE = 256 * 1024
_MAX_CHUNK = 256 * 1024
# Capture and restore must finish inside one exec call, which Agent 37 holds for 15 minutes.
_CHILD_TIMEOUT = 780
# Staged files this old belong to an operation the host abandoned.
_STALE_SECONDS = 3600


def _file(name: str, suffix: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", name):
        raise ValueError("Invalid staged object name")
    return _CONTROL / (name + suffix)


def _root() -> bool:
    return os.geteuid() == 0


def _prepare() -> None:
    """Create the root-only staging directory and hand the agent its two directories."""
    root = _root()
    _CONTROL.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = _CONTROL.lstat()
    if not stat.S_ISDIR(info.st_mode) or (root and (info.st_uid != 0 or info.st_mode & 0o077)):
        raise PermissionError("The staging directory must belong to root alone")
    _sweep()
    for path in (_WORKSPACE, _RUNTIME):
        path.mkdir(exist_ok=True)
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise PermissionError(f"{path} must be a directory")
        if root and (info.st_uid, info.st_gid) != (_USER, _GROUP):
            os.chown(path, _USER, _GROUP, follow_symlinks=False)


def _sweep() -> None:
    """Remove staged files of abandoned operations, so they can never fill the disk."""
    cutoff = time.time() - _STALE_SECONDS
    for entry in _CONTROL.iterdir():
        try:
            if entry.lstat().st_mtime < cutoff:
                entry.unlink()
        except OSError:
            continue


def _spawn(argv: List[str], **kwargs: Any) -> "subprocess.Popen[bytes]":
    """Start a process as the agent's user in a session of its own."""
    if _root():
        # PR_SET_NO_NEW_PRIVS: setuid binaries cannot take the agent back to root.
        if ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Could not disable privilege elevation")
        kwargs.update(user=_USER, group=_GROUP, extra_groups=[])
    environment = dict(os.environ, HOME=str(_RUNTIME))
    return subprocess.Popen(argv, env=environment, start_new_session=True, **kwargs)


def _input(name: str, expected: List[str], stdin: BinaryIO) -> int:
    """Open a command's input: staged earlier and checked against its digest, or sent with the command."""
    path = _file(name, ".in")
    if not expected:
        data = base64.b64decode(stdin.read().strip(), validate=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    if expected:
        check, size = hashlib.sha256(), 0
        while chunk := os.read(descriptor, 1024 * 1024):
            check.update(chunk)
            size += len(chunk)
        os.lseek(descriptor, 0, os.SEEK_SET)
        if [str(size), check.hexdigest()] != expected:
            os.close(descriptor)
            raise ValueError("Staged input is not what was sent")
    return descriptor


def _output(name: str) -> Dict[str, Any]:
    """Describe a finished command's output, carrying it along when it is small."""
    path = _file(name, ".out")
    check, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            check.update(chunk)
            size += len(chunk)
    reply: Dict[str, Any] = {"size": size, "sha256": check.hexdigest(), "data": None}
    if size <= _INLINE:
        reply["data"] = base64.b64encode(path.read_bytes()).decode("ascii")
        path.unlink()
    return reply


def _put(name: str, offset: str, stdin: BinaryIO) -> Dict[str, Any]:
    data = base64.b64decode(stdin.read().strip(), validate=True)
    if not offset.isdigit():
        raise ValueError("Staged chunks need a nonnegative offset")
    # Chunks land by offset, so they may arrive in any order and a repeated one changes nothing.
    descriptor = os.open(_file(name, ".in"), os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.pwrite(descriptor, data, int(offset))
    finally:
        os.close(descriptor)
    return {}


def _get(name: str, offset: str, length: str) -> Dict[str, Any]:
    if not offset.isdigit() or not length.isdigit() or not 0 < int(length) <= _MAX_CHUNK:
        raise ValueError("Staged reads need a nonnegative offset and a length of at most 256 KiB")
    descriptor = os.open(_file(name, ".out"), os.O_RDONLY | os.O_NOFOLLOW)
    try:
        data = os.pread(descriptor, int(length), int(offset))
    finally:
        os.close(descriptor)
    return {"data": base64.b64encode(data).decode("ascii")}


def _remove(name: str) -> Dict[str, Any]:
    for suffix in (".in", ".out", ".err"):
        _file(name, suffix).unlink(missing_ok=True)
    return {}


def _run(name: str, runner: str, expected: List[str], stdin: BinaryIO) -> Dict[str, Any]:
    """Run the command runner as the agent's user on the request, keeping its result for the host."""
    source = _input(name, expected, stdin)
    try:
        # Every stream is a file: a process the command leaves behind can then never hold this call open.
        with _file(name, ".out").open("xb") as target, _file(name, ".err").open("xb") as errors:
            child = _spawn([*_PYTHON, "-c", runner], stdin=source, stdout=target, stderr=errors, cwd=str(_WORKSPACE))
            child.wait()
        if child.returncode:
            raise RuntimeError("Command runner failed: " + _file(name, ".err").read_text(errors="replace")[-1500:])
        return _output(name)
    except BaseException:
        _file(name, ".out").unlink(missing_ok=True)
        raise
    finally:
        os.close(source)
        _file(name, ".in").unlink(missing_ok=True)
        _file(name, ".err").unlink(missing_ok=True)


def _agent_pids() -> List[int]:
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid == _USER:
                pids.append(int(entry.name))
        except FileNotFoundError:
            continue
    return pids


def _process_state(pid: int) -> str:
    try:
        # The state follows the command name, which may itself contain spaces and ")".
        return Path(f"/proc/{pid}/stat").read_text().rpartition(")")[2].split()[0]
    except (OSError, IndexError):
        return ""


def _freeze() -> List[int]:
    """Stop every process of the agent's user until a full pass finds no new one.

    Stands in for Docker's cgroup freeze so files hold still while they are archived.
    The archive work itself runs as that user, so a process that escapes the freeze
    can at most disturb its own checkpoint.
    """
    stopped: List[int] = []
    seen: set = set()
    for _ in range(20):
        found = [pid for pid in _agent_pids() if pid not in seen]
        if not found:
            break
        for pid in found:
            seen.add(pid)
            if _process_state(pid) in ("T", "t"):
                # Already stopped by the agent itself; thaw must not resume it.
                continue
            try:
                os.kill(pid, signal.SIGSTOP)
                stopped.append(pid)
            except ProcessLookupError:
                pass
    return stopped


def _thaw(stopped: List[int]) -> None:
    for pid in stopped:
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass


def _roots() -> Dict[str, str]:
    return {"workspace": str(_WORKSPACE), "native": str(_RUNTIME / "native")}


def _finish(child: "subprocess.Popen[bytes]", job: Any) -> Any:
    try:
        return child.communicate(job, timeout=_CHILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise RuntimeError("Checkpoint transfer did not finish within its time limit") from None


def _capture(name: str, expected: List[str], stdin: BinaryIO) -> Dict[str, Any]:
    """Archive the agent's roots while its processes are stopped, keeping the archive for the host."""
    source = _input(name, expected, stdin)
    try:
        with os.fdopen(os.dup(source), "rb") as stream:
            job = json.load(stream)
    finally:
        os.close(source)
        _file(name, ".in").unlink(missing_ok=True)
    job["roots"] = _roots()
    # Only root may stop another user's processes; unprivileged, this user's own would include this script.
    stopped = _freeze() if _root() else []
    try:
        with _file(name, ".out").open("xb") as target:
            child = _spawn(
                [*_PYTHON, "-m", "agno.sandbox._roots", "capture"],
                stdin=subprocess.PIPE,
                stdout=target,
                stderr=subprocess.PIPE,
                cwd="/",
            )
            _, error = _finish(child, json.dumps(job).encode())
        if child.returncode:
            raise RuntimeError("Checkpoint capture failed: " + error.decode(errors="replace")[-1500:])
        return _output(name)
    except BaseException:
        _file(name, ".out").unlink(missing_ok=True)
        raise
    finally:
        _thaw(stopped)


def _restore(name: str, limits: str, expected: List[str], stdin: BinaryIO) -> Dict[str, Any]:
    """Restore the staged archive into the agent's roots, which must be empty."""
    if not expected:
        raise ValueError("A checkpoint is staged before it is restored")
    source = _input(name, expected, stdin)
    try:
        job = json.dumps({"roots": _roots(), "limits": json.loads(limits)})
        child = _spawn(
            [*_PYTHON, "-m", "agno.sandbox._roots", "restore", job],
            stdin=source,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            cwd="/",
        )
        _, error = _finish(child, None)
    finally:
        os.close(source)
        _file(name, ".in").unlink(missing_ok=True)
    if child.returncode:
        raise RuntimeError("Checkpoint restore failed: " + error.decode(errors="replace")[-1500:])
    return {}


def main(arguments: List[str], stdin: BinaryIO) -> Dict[str, Any]:
    operation, rest = arguments[0], arguments[1:]
    _prepare()
    if operation == "put" and len(rest) == 2:
        return _put(rest[0], rest[1], stdin)
    if operation == "get" and len(rest) == 3:
        return _get(rest[0], rest[1], rest[2])
    if operation == "remove" and len(rest) == 1:
        return _remove(rest[0])
    if operation == "run" and len(rest) in (2, 4):
        return _run(rest[0], rest[1], rest[2:], stdin)
    if operation == "capture" and len(rest) in (1, 3):
        return _capture(rest[0], rest[1:], stdin)
    if operation == "restore" and len(rest) == 4:
        return _restore(rest[0], rest[1], rest[2:], stdin)
    raise ValueError("Unknown sandbox operation")


if __name__ == "__main__":
    try:
        reply = main(sys.argv[1:], sys.stdin.buffer)
    except Exception as error:
        sys.stderr.write(f"{type(error).__name__}: {error}\n")
        sys.exit(1)
    sys.stdout.write(json.dumps(reply))
