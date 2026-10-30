"""Checkpoint jobs inside an E2B computer.

The host runs ``capture`` and ``restore`` as root. Root stops the agent user's
processes so files hold still, and only a child dropped to that user reads or
writes the managed roots, so root never touches a path the agent controls.
Archives live in a root-only directory the agent cannot reach.
"""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

_USER = "user"
_ROOTS = {"workspace": "/workspace", "native": "/runtime/native"}
# A POSIX path string, so the host can import it on any platform.
_TRANSFER_DIR = "/var/lib/agno-sandbox"
_CHILD_TIMEOUT = 840


def _transfer_file(path: str) -> Path:
    target, directory = Path(path), Path(_TRANSFER_DIR)
    if target.parent != directory or not target.name.endswith(".tar") or "/" in target.name:
        raise SystemExit("Checkpoint files must live directly in " + _TRANSFER_DIR)
    status = directory.lstat()
    if not directory.is_dir() or directory.is_symlink() or status.st_uid != 0 or status.st_mode & 0o077:
        raise SystemExit(_TRANSFER_DIR + " must be a root-only directory")
    return target


def _agent_pids(uid: int) -> List[int]:
    pids = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit() or int(entry.name) == os.getpid():
            continue
        try:
            if entry.stat().st_uid == uid:
                pids.append(int(entry.name))
        except FileNotFoundError:
            continue
    return pids


def _freeze(uid: int) -> List[int]:
    """Stop every process of the agent user, again until none is left running; on failure resume them."""
    stopped: List[int] = []
    try:
        for _ in range(20):
            fresh = [pid for pid in _agent_pids(uid) if pid not in stopped]
            if not fresh:
                return stopped
            for pid in fresh:
                try:
                    os.kill(pid, signal.SIGSTOP)
                    stopped.append(pid)
                except ProcessLookupError:
                    pass
        raise SystemExit("Agent processes kept starting while the checkpoint stopped them")
    except BaseException:
        _thaw(stopped)
        raise


def _thaw(stopped: List[int]) -> None:
    for pid in stopped:
        try:
            os.kill(pid, signal.SIGCONT)
        except ProcessLookupError:
            pass


def _as_agent(argv: List[str], account: Any, **kwargs: Any) -> "subprocess.Popen[bytes]":
    environment = {"HOME": account.pw_dir, "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin")}
    return subprocess.Popen(
        argv, user=account.pw_uid, group=account.pw_gid, extra_groups=[], env=environment, cwd="/", **kwargs
    )


def _finish(child: "subprocess.Popen[bytes]", job: Optional[bytes]) -> bytes:
    try:
        output, error = child.communicate(job, timeout=_CHILD_TIMEOUT)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate()
        raise SystemExit("Checkpoint job did not finish within its time limit") from None
    if child.returncode:
        raise SystemExit("Checkpoint job failed: " + error.decode(errors="replace")[-1500:])
    return output


def _capture(target_path: str, job: str) -> Dict[str, Any]:
    import pwd

    target = _transfer_file(target_path)
    account = pwd.getpwnam(_USER)
    stopped: List[int] = []
    try:
        stopped = _freeze(account.pw_uid)
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            child = _as_agent(
                [sys.executable, "-I", "-m", "agno.sandbox.e2b._archive", "capture-as-agent"],
                account,
                stdin=subprocess.PIPE,
                stdout=descriptor,
                stderr=subprocess.PIPE,
            )
            _finish(child, job.encode())
        finally:
            os.close(descriptor)
        return {"size": target.stat().st_size}
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        _thaw(stopped)


def _restore(source_path: str, job: str) -> Dict[str, Any]:
    import pwd

    source = _transfer_file(source_path)
    account = pwd.getpwnam(_USER)
    stopped: List[int] = []
    try:
        stopped = _freeze(account.pw_uid)
        descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            child = _as_agent(
                [sys.executable, "-I", "-m", "agno.sandbox.e2b._archive", "restore-as-agent", job],
                account,
                stdin=descriptor,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output = _finish(child, None)
        finally:
            os.close(descriptor)
        return {"state": json.loads(output)}
    finally:
        _thaw(stopped)
        source.unlink(missing_ok=True)


def _capture_as_agent() -> None:
    """Run as the agent user: write one checkpoint archive of the managed roots to stdout."""
    from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits

    job = json.loads(sys.stdin.buffer.read())
    roots = {name: Path(path) for name, path in _ROOTS.items()}
    roots["native"].mkdir(mode=0o700, exist_ok=True)
    archive = CheckpointArchive(CheckpointLimits(**job["limits"]))
    with tempfile.TemporaryDirectory(prefix="agno-capture-") as directory:
        output = Path(directory) / "checkpoint.tar"
        archive.capture(roots, output, state=job["state"], exclude=job["exclude"])
        with output.open("rb") as stream:
            shutil.copyfileobj(stream, sys.stdout.buffer)
        sys.stdout.buffer.flush()


def _restore_as_agent(arguments: str) -> None:
    """Run as the agent user: restore the archive on stdin into the empty managed roots."""
    from agno.sandbox.checkpoint import CheckpointArchive, CheckpointLimits

    job = json.loads(arguments)
    roots = {name: Path(path) for name, path in _ROOTS.items()}
    archive = CheckpointArchive(CheckpointLimits(**job["limits"]))
    with tempfile.TemporaryDirectory(prefix="agno-restore-") as directory:
        source, staging = Path(directory) / "checkpoint", Path(directory) / "restored"
        with source.open("xb") as stream:
            shutil.copyfileobj(sys.stdin.buffer, stream)
        state = archive.restore(source, staging)
        for target in roots.values():
            target.mkdir(mode=0o700, exist_ok=True)
            if target.is_symlink() or not target.is_dir() or any(target.iterdir()):
                raise SystemExit("Restore requires an empty, unused generation")
        for name, target in roots.items():
            # An archive may record a read-only root; its entries must still move out.
            (staging / name).chmod(0o700)
            for entry in (staging / name).iterdir():
                shutil.move(str(entry), str(target / entry.name))
            # The managed roots stay private whatever mode the archive recorded.
            target.chmod(0o700)
    sys.stdout.write(json.dumps(state))


def main() -> None:
    command = sys.argv[1:2]
    if command == ["capture"] and len(sys.argv) == 4:
        print(json.dumps(_capture(sys.argv[2], sys.argv[3])))
    elif command == ["restore"] and len(sys.argv) == 4:
        print(json.dumps(_restore(sys.argv[2], sys.argv[3])))
    elif command == ["capture-as-agent"]:
        _capture_as_agent()
    elif command == ["restore-as-agent"] and len(sys.argv) == 3:
        _restore_as_agent(sys.argv[2])
    else:
        sys.exit("usage: python -I -m agno.sandbox.e2b._archive capture|restore PATH JOB")


if __name__ == "__main__":
    main()
