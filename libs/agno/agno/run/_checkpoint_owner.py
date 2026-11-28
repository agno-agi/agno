"""Identify the process holding a foreground checkpoint without a heartbeat or a timeout.

Each worker holds an exclusive advisory lock on one file for its lifetime. A replacement
can reuse that file after the kernel releases the lock, writing its own generation first.
A reader must see the original file to prove that its owner exited. Workers with separate
temporary filesystems, or without POSIX locks, leave each other's checkpoints alone.
"""

import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import BinaryIO, Optional
from uuid import UUID, uuid4

_guard = Lock()
_file: Optional[BinaryIO] = None
_owner: Optional[str] = None


def _after_fork() -> None:
    global _file, _owner, _guard
    if _file is not None:
        _file.close()  # Drop only the child's reference to the parent's lock.
    _file, _owner, _guard = None, None, Lock()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(
        before=lambda: _guard.acquire(), after_in_parent=lambda: _guard.release(), after_in_child=_after_fork
    )


def _directory() -> Path:
    directory = Path(tempfile.gettempdir()) / f"agno-checkpoint-owners-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    info = directory.lstat()
    if directory.is_symlink() or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise OSError("Checkpoint owner directory must be private to the current user")
    return directory


def checkpoint_owner() -> Optional[str]:
    global _file, _owner
    if _owner is not None:
        return _owner
    try:
        import fcntl

        with _guard:
            if _owner is not None:
                return _owner
            directory = _directory()
            # Reuse unlocked files so only concurrent workers need separate slots.
            for path in directory.glob("*.lock"):
                handle = path.open("r+b")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    handle.close()
                    continue
                break
            else:
                path = directory / f"{uuid4().hex}.lock"
                handle = path.open("x+b")
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    handle.close()
                    raise
            generation = uuid4().hex
            try:
                handle.write(generation.encode("ascii"))
                handle.flush()
            except BaseException:
                handle.close()
                raise
            _file = handle
            _owner = f"{path.stem}.{generation}"
            return _owner
    except (ImportError, OSError):
        return None


def checkpoint_owner_exited(owner: Optional[str]) -> bool:
    if not isinstance(owner, str) or owner == _owner:
        return False
    try:
        import fcntl

        slot, generation = owner.split(".")
        if slot != UUID(slot).hex or generation != UUID(generation).hex:
            return False
        with (_directory() / f"{slot}.lock").open("rb") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                # Only a worker that acquired the exclusive lock can replace a generation.
                current = handle.read(32).decode("ascii")
                return current == UUID(current).hex and current != generation
            return True
    except (ImportError, OSError, ValueError):
        return False
